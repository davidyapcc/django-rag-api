from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Guest
from apps.core.models import DailySpend
from apps.documents.models import Document
from apps.qa.models import Query
from rag import providers
from rag.providers import ProviderError

pytestmark = pytest.mark.django_db


@pytest.fixture
def guest_client():
    client = Client()
    resp = client.post("/guest/")
    assert resp.status_code == 302 and resp.url == "/app/"
    return client


def test_landing_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Try it as a guest" in resp.content


def test_guest_flow_end_to_end(guest_client):
    page = guest_client.get("/app/")
    assert b"a guest" in page.content

    resp = guest_client.post("/app/documents/samples/")
    assert b"Loaded 3 sample document" in resp.content

    resp = guest_client.post("/app/ask/", {"question": "What grind size does a French press need?"})
    assert b"coarse" in resp.content
    assert b"coffee-brewing.md" in resp.content
    assert resp["HX-Trigger"] == "query-created"

    history = guest_client.get("/app/history/")
    assert b"French press" in history.content


def test_app_requires_login(client):
    resp = client.get("/app/")
    assert resp.status_code == 302 and "/login/" in resp.url


def test_signup_and_login(client):
    resp = client.post(
        "/signup/", {"username": "erin", "password1": "Long-enough-pass1", "password2": "Long-enough-pass1"}
    )
    assert resp.status_code == 302
    assert client.get("/app/").status_code == 200
    client.post("/logout/")
    resp = client.post("/login/", {"username": "erin", "password": "Long-enough-pass1"})
    assert resp.status_code == 302 and resp.url == "/app/"


def test_signup_form_errors_rerender(client):
    resp = client.post("/signup/", {"username": "x", "password1": "a", "password2": "b"})
    assert resp.status_code == 200
    assert client.get("/signup/").status_code == 200


def test_upload_and_delete(guest_client):
    resp = guest_client.post("/app/documents/upload/", {"file": SimpleUploadedFile("t.txt", b"Tea is nice.")})
    assert b"Added t.txt" in resp.content
    doc = Document.objects.get()
    resp = guest_client.post(f"/app/documents/{doc.pk}/delete/")
    assert resp.status_code == 200
    assert not Document.objects.exists()


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({}, b"Choose a file"),
        ({"file": SimpleUploadedFile("x.exe", b"MZ")}, b"Unsupported file type"),
        ({"file": SimpleUploadedFile("e.txt", b"   ")}, b"no extractable text"),
    ],
)
def test_upload_errors(guest_client, data, message):
    assert message in guest_client.post("/app/documents/upload/", data).content


def test_duplicate_upload(guest_client):
    guest_client.post("/app/documents/upload/", {"file": SimpleUploadedFile("t.txt", b"Same.")})
    resp = guest_client.post("/app/documents/upload/", {"file": SimpleUploadedFile("u.txt", b"Same.")})
    assert b"already uploaded" in resp.content


def test_guest_limit_shown(guest_client, settings):
    settings.GUEST_MAX_DOCUMENTS = 1
    guest_client.post("/app/documents/upload/", {"file": SimpleUploadedFile("a.txt", b"One.")})
    resp = guest_client.post("/app/documents/upload/", {"file": SimpleUploadedFile("b.txt", b"Two.")})
    assert b"up to 1 documents" in resp.content


def test_cannot_delete_someone_elses_document(guest_client, user):
    from apps.documents.services import Upload, ingest

    doc = ingest(user, Upload("mine.txt", "text/plain", b"private"))
    assert guest_client.post(f"/app/documents/{doc.pk}/delete/").status_code == 404
    assert Document.objects.filter(pk=doc.pk).exists()


def test_guests_are_isolated(guest_client):
    guest_client.post("/app/documents/samples/")
    other = Client()
    other.post("/guest/")
    page = other.get("/app/")
    assert b"coffee-brewing.md" not in page.content
    resp = other.post("/app/ask/", {"question": "What grind size does a French press need?"})
    assert b"No sources" in resp.content


def test_empty_question(guest_client):
    assert b"Type a question" in guest_client.post("/app/ask/", {"question": ""}).content


def test_provider_errors_are_friendly(guest_client, monkeypatch):
    def boom(self, *a):
        raise ProviderError("down")

    monkeypatch.setattr(providers.FakeProvider, "embed", boom)
    assert b"unavailable" in guest_client.post("/app/ask/", {"question": "q"}).content
    resp = guest_client.post("/app/documents/upload/", {"file": SimpleUploadedFile("t.txt", b"Hi.")})
    assert b"unavailable" in resp.content
    assert b"unavailable" in guest_client.post("/app/documents/samples/").content


def test_samples_twice(guest_client):
    guest_client.post("/app/documents/samples/")
    assert b"already loaded" in guest_client.post("/app/documents/samples/").content


def test_budget_message(guest_client, settings, monkeypatch):
    settings.DEMO_DAILY_BUDGET_USD = 0.01
    monkeypatch.setattr(providers.FakeProvider, "name", "paid-fake")
    DailySpend.objects.create(day=timezone.now().date(), cost_usd=Decimal("1"))
    assert b"daily budget" in guest_client.post("/app/ask/", {"question": "q"}).content
    assert b"daily budget" in guest_client.post("/app/documents/samples/").content


def test_rate_limits(guest_client, monkeypatch):
    from rest_framework.throttling import ScopedRateThrottle

    monkeypatch.setattr(
        ScopedRateThrottle, "THROTTLE_RATES", {"ask": "1/hour", "upload": "1/day", "guest": "1/hour"}
    )
    guest_client.post("/app/ask/", {"question": "q"})
    assert b"bit fast" in guest_client.post("/app/ask/", {"question": "q"}).content
    guest_client.post("/app/documents/upload/", {"file": SimpleUploadedFile("a.txt", b"One.")})
    resp = guest_client.post("/app/documents/upload/", {"file": SimpleUploadedFile("b.txt", b"Two.")})
    assert b"bit fast" in resp.content

    # Same IP as the fixture's guest, which used up the 1/hour allowance.
    resp = Client().post("/guest/", follow=True)
    assert b"bit fast" in resp.content
    assert Guest.objects.count() == 1


def test_history_counts_only_own_queries(guest_client, user):
    Query.objects.create(owner=user, question="secret", answer="a", provider="fake", model="m")
    assert b"secret" not in guest_client.get("/app/history/").content
