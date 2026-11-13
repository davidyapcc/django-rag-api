import base64
import hashlib
import json
import time
from decimal import Decimal
from types import SimpleNamespace

import jwt
import pytest
from django.tasks import task
from django.tasks.base import TaskResultStatus
from django.tasks.exceptions import InvalidTask
from django.utils import timezone

from apps.core.models import DailySpend, OwnerDailySpend
from apps.documents import tasks as doc_tasks
from apps.documents.models import Chunk, Document
from apps.documents.services import Upload, ingest
from apps.documents.tasks import QStashBackend, verify_qstash_signature
from rag import providers
from rag.providers import ProviderError

pytestmark = pytest.mark.django_db

SIGNING_KEY = "sig_current_secret_key_for_tests_01"
NEXT_SIGNING_KEY = "sig_next_secret_key_for_tests_0002"


def sign_qstash_body(body: bytes, key: str, *, exp_seconds: int = 300) -> str:
    now = int(time.time())
    digest = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode("ascii")
    payload = {"iss": "Upstash", "iat": now, "nbf": now, "exp": now + exp_seconds, "body": digest}
    return jwt.encode(payload, key, algorithm="HS256")


@task
def _sample_task(document_id: int) -> None:
    pass


def test_qstash_signature_accepts_current_and_next_keys(settings):
    settings.QSTASH_CURRENT_SIGNING_KEY = "sig_current_secret_key_for_tests_01"
    settings.QSTASH_NEXT_SIGNING_KEY = "sig_next_secret_key_for_tests_0002"
    body = b'{"document_id": 42}'

    sig_current = sign_qstash_body(body, settings.QSTASH_CURRENT_SIGNING_KEY)
    sig_next = sign_qstash_body(body, settings.QSTASH_NEXT_SIGNING_KEY)

    assert verify_qstash_signature(body, sig_current) is True
    assert verify_qstash_signature(body, sig_next) is True


def test_qstash_signature_rejects_invalid_expired_or_tampered(settings):
    settings.QSTASH_CURRENT_SIGNING_KEY = "sig_current_secret_key_for_tests_01"
    settings.QSTASH_NEXT_SIGNING_KEY = ""
    body = b'{"document_id": 42}'

    valid = sign_qstash_body(body, settings.QSTASH_CURRENT_SIGNING_KEY)
    expired = sign_qstash_body(body, settings.QSTASH_CURRENT_SIGNING_KEY, exp_seconds=-10)
    wrong_key = sign_qstash_body(body, "wrong_secret_key_for_tests_0000000")

    assert verify_qstash_signature(body, "") is False
    assert verify_qstash_signature(body, "not-a-jwt") is False
    assert verify_qstash_signature(body, expired) is False
    assert verify_qstash_signature(body, wrong_key) is False
    assert verify_qstash_signature(b'{"document_id": 99}', valid) is False


def test_qstash_signature_rejects_when_no_signing_keys_configured(settings):
    settings.QSTASH_CURRENT_SIGNING_KEY = ""
    settings.QSTASH_NEXT_SIGNING_KEY = ""
    sig = sign_qstash_body(b"{}", "some_secret_key_for_tests_00000000")
    assert verify_qstash_signature(b"{}", sig) is False


def test_qstash_backend_enqueue_publishes_with_failure_callback(settings, monkeypatch):
    settings.QSTASH_URL = "https://qstash.example.test"
    settings.QSTASH_TOKEN = "tok-test"
    settings.QSTASH_CALLBACK_BASE_URL = "https://app.example.test/"

    calls = []

    def fake_post(url: str, headers: dict[str, str], body: bytes) -> dict:
        calls.append(SimpleNamespace(url=url, headers=headers, body=body))
        return {"messageId": "msg_123"}

    monkeypatch.setattr(doc_tasks, "_post", fake_post)

    backend = QStashBackend("default", {})
    result = backend.enqueue(_sample_task, (42,), {})

    assert result.id == "msg_123"
    assert result.status == TaskResultStatus.READY
    assert len(calls) == 1
    call = calls[0]
    assert call.url == "https://qstash.example.test/v2/publish/https://app.example.test/api/v1/tasks/ingest/"
    assert call.headers["Authorization"] == "Bearer tok-test"
    assert call.headers["Content-Type"] == "application/json"
    assert call.headers["Upstash-Failure-Callback"] == "https://app.example.test/api/v1/tasks/ingest/failed/"
    assert json.loads(call.body) == {"document_id": 42}


def test_qstash_backend_enqueue_requires_int_document_id(settings):
    settings.QSTASH_TOKEN = "tok-test"
    backend = QStashBackend("default", {})
    with pytest.raises(InvalidTask):
        backend.enqueue(_sample_task, (), {})
    with pytest.raises(InvalidTask):
        backend.enqueue(_sample_task, ("not-an-int",), {})
    with pytest.raises(InvalidTask):
        backend.enqueue(_sample_task, (True,), {})


def _signed_post(client, path: str, payload: dict, key: str = SIGNING_KEY):
    body = json.dumps(payload).encode("utf-8")
    sig = sign_qstash_body(body, key)
    return client.post(path, data=body, content_type="application/json", HTTP_UPSTASH_SIGNATURE=sig)


@pytest.fixture
def pending_doc(user, settings):
    settings.TASKS = {"default": {"BACKEND": "django.tasks.backends.dummy.DummyBackend"}}
    settings.QSTASH_CURRENT_SIGNING_KEY = SIGNING_KEY
    settings.QSTASH_NEXT_SIGNING_KEY = NEXT_SIGNING_KEY
    return ingest(user, Upload("coffee.md", "text/markdown", b"French press needs a coarse grind."))


def test_delivery_callback_ingests_pending_document_and_ignores_owner(client, pending_doc, other_user):
    resp = _signed_post(
        client,
        "/api/v1/tasks/ingest/",
        {"document_id": pending_doc.pk, "owner": other_user.pk},
    )
    assert resp.status_code == 200
    pending_doc.refresh_from_db()
    assert pending_doc.status == Document.Status.READY
    assert pending_doc.owner_id != other_user.pk
    assert (
        Chunk.objects.filter(document=pending_doc, owner=pending_doc.owner).count() == pending_doc.chunk_count
    )

    # Second delivery with next signing key is idempotent.
    resp2 = _signed_post(
        client,
        "/api/v1/tasks/ingest/",
        {"document_id": pending_doc.pk},
        key=NEXT_SIGNING_KEY,
    )
    assert resp2.status_code == 200
    assert Chunk.objects.filter(document=pending_doc).count() == pending_doc.chunk_count


@pytest.mark.parametrize("path", ["/api/v1/tasks/ingest/", "/api/v1/tasks/ingest/failed/"])
def test_callbacks_reject_missing_or_invalid_signature(client, pending_doc, path):
    body = json.dumps({"document_id": pending_doc.pk}).encode("utf-8")

    missing = client.post(path, data=body, content_type="application/json")
    invalid = client.post(
        path,
        data=body,
        content_type="application/json",
        HTTP_UPSTASH_SIGNATURE="bad.jwt.token",
    )
    tampered = client.post(
        path,
        data=b'{"document_id": 999999}',
        content_type="application/json",
        HTTP_UPSTASH_SIGNATURE=sign_qstash_body(body, SIGNING_KEY),
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert tampered.status_code == 401
    pending_doc.refresh_from_db()
    assert pending_doc.status == Document.Status.PENDING
    assert not Chunk.objects.filter(document=pending_doc).exists()


def test_delivery_callback_transient_error_returns_502_and_keeps_pending(client, pending_doc, monkeypatch):
    def transient_boom(self, texts):
        raise ProviderError("rate limited", transient=True)

    monkeypatch.setattr(providers.FakeProvider, "embed", transient_boom)
    resp = _signed_post(client, "/api/v1/tasks/ingest/", {"document_id": pending_doc.pk})
    assert resp.status_code == 502
    pending_doc.refresh_from_db()
    assert pending_doc.status == Document.Status.PENDING
    assert not Chunk.objects.filter(document=pending_doc).exists()


def test_delivery_callback_permanent_error_marks_failed_and_returns_200(client, pending_doc, monkeypatch):
    def permanent_boom(self, texts):
        raise ProviderError("invalid request", transient=False)

    monkeypatch.setattr(providers.FakeProvider, "embed", permanent_boom)
    resp = _signed_post(client, "/api/v1/tasks/ingest/", {"document_id": pending_doc.pk})
    assert resp.status_code == 200
    pending_doc.refresh_from_db()
    assert pending_doc.status == Document.Status.FAILED
    assert pending_doc.error == "invalid request"
    assert not Chunk.objects.filter(document=pending_doc).exists()


def test_delivery_callback_budget_exhausted_marks_failed_without_provider_call(
    client, pending_doc, settings, monkeypatch
):
    monkeypatch.setattr(providers.FakeProvider, "name", "paid-fake")
    settings.DEMO_DAILY_BUDGET_USD = 0.01
    DailySpend.objects.create(day=timezone.now().date(), cost_usd=Decimal("1"))

    def must_not_run(self, texts):
        raise AssertionError("embed should not be called when budget is exhausted")

    monkeypatch.setattr(providers.FakeProvider, "embed", must_not_run)
    resp = _signed_post(client, "/api/v1/tasks/ingest/", {"document_id": pending_doc.pk})
    assert resp.status_code == 200
    pending_doc.refresh_from_db()
    assert pending_doc.status == Document.Status.FAILED
    assert "daily budget" in pending_doc.error


def test_delivery_callback_allowance_exhausted_marks_failed_without_provider_call(
    client, pending_doc, user, settings, monkeypatch
):
    monkeypatch.setattr(providers.FakeProvider, "name", "paid-fake")
    settings.DEMO_DAILY_BUDGET_USD = 10
    settings.ALLOWANCE_DAILY_USD = 0.05
    OwnerDailySpend.objects.create(owner=user, day=timezone.now().date(), cost_usd=Decimal("1"))

    def must_not_run(self, texts):
        raise AssertionError("embed should not be called when allowance is exhausted")

    monkeypatch.setattr(providers.FakeProvider, "embed", must_not_run)
    resp = _signed_post(client, "/api/v1/tasks/ingest/", {"document_id": pending_doc.pk})
    assert resp.status_code == 200
    pending_doc.refresh_from_db()
    assert pending_doc.status == Document.Status.FAILED
    assert "daily allowance" in pending_doc.error


def test_failure_callback_marks_pending_failed_and_ignores_ready(client, pending_doc):
    source = base64.b64encode(json.dumps({"document_id": pending_doc.pk}).encode()).decode()
    resp = _signed_post(client, "/api/v1/tasks/ingest/failed/", {"sourceBody": source})
    assert resp.status_code == 200
    pending_doc.refresh_from_db()
    assert pending_doc.status == Document.Status.FAILED
    assert pending_doc.error

    # Ready documents are left untouched by the failure callback.
    pending_doc.status = Document.Status.READY
    pending_doc.error = ""
    pending_doc.save(update_fields=["status", "error"])
    resp2 = _signed_post(client, "/api/v1/tasks/ingest/failed/", {"document_id": pending_doc.pk})
    assert resp2.status_code == 200
    pending_doc.refresh_from_db()
    assert pending_doc.status == Document.Status.READY


def test_callbacks_reject_invalid_payload_with_400(client, settings):
    settings.QSTASH_CURRENT_SIGNING_KEY = SIGNING_KEY
    assert _signed_post(client, "/api/v1/tasks/ingest/", {}).status_code == 400
    assert _signed_post(client, "/api/v1/tasks/ingest/", {"document_id": "abc"}).status_code == 400
    assert _signed_post(client, "/api/v1/tasks/ingest/failed/", {"sourceBody": "!!!"}).status_code == 400


def test_callbacks_excluded_from_openapi_schema(client):
    resp = client.get("/api/schema/")
    assert resp.status_code == 200
    assert b"/api/v1/tasks/ingest/" not in resp.content
