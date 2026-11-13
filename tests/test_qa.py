from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.documents.models import Chunk
from apps.qa.models import Query
from rag import providers
from rag.providers import ProviderError
from rag.types import AnswerResult, Usage

pytestmark = pytest.mark.django_db


def ask(client, **body):
    return client.post("/api/v1/ask/", body, format="json")


def test_answer_with_citation(auth_api, uploaded):
    resp = ask(auth_api, question="What grind does a French press need?")
    assert resp.status_code == 201
    data = resp.json()
    assert "coarse" in data["answer"]
    assert data["citations"][0]["document_id"] == uploaded["id"]
    assert data["provider"] == "fake"
    assert Decimal(data["cost_usd"]) >= 0


def test_no_documents_means_abstain_without_chat_call(auth_api, monkeypatch):
    def must_not_run(*a, **kw):
        raise AssertionError("chat model should not be called")

    monkeypatch.setattr(providers.FakeProvider, "answer", must_not_run)
    data = ask(auth_api, question="What is the capital of France?").json()
    assert data["citations"] == []
    assert data["model"] == "none"
    assert "don't know" in data["answer"]


def test_hallucinated_citations_are_dropped(auth_api, uploaded, monkeypatch):
    def fake_answer(self, question, chunks):
        return AnswerResult("x", [chunks[0].id, 999_999, chunks[0].id], "fake", Usage(1, 1))

    monkeypatch.setattr(providers.FakeProvider, "answer", fake_answer)
    data = ask(auth_api, question="French press grind?").json()
    assert [c["chunk_id"] for c in data["citations"]] == [Chunk.objects.first().pk]


def test_other_users_documents_are_never_retrieved(uploaded, other_user):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(other_user)
    data = ask(client, question="What grind does a French press need?").json()
    assert data["citations"] == []


def test_document_filter(auth_api, uploaded):
    other = auth_api.post(
        "/api/v1/documents/",
        {"file": SimpleUploadedFile("tea.txt", b"French press can also brew loose leaf tea nicely.")},
        format="multipart",
    ).json()
    data = ask(auth_api, question="French press?", document_ids=[other["id"]]).json()
    assert {c["document_id"] for c in data["citations"]} == {other["id"]}


def test_provider_failure_returns_502(auth_api, uploaded, monkeypatch):
    def boom(self, *a):
        raise ProviderError("down")

    monkeypatch.setattr(providers.FakeProvider, "answer", boom)
    assert ask(auth_api, question="French press grind?").status_code == 502


def test_validation(auth_api):
    assert ask(auth_api, question="").status_code == 400
    assert ask(auth_api, question="x", top_k=50).status_code == 400


def test_query_history_and_usage(auth_api, uploaded, other_user):
    ask(auth_api, question="French press grind?")
    ask(auth_api, question="Water temperature?")
    Query.objects.create(owner=other_user, question="q", answer="a", provider="fake", model="m", cost_usd=1)

    history = auth_api.get("/api/v1/queries/").json()
    assert history["count"] == 2
    detail = auth_api.get(f"/api/v1/queries/{history['results'][0]['id']}/").json()
    assert "citations" in detail

    usage = auth_api.get("/api/v1/queries/usage/").json()
    assert usage["queries"] == 2
    assert Decimal(usage["cost_usd"]) < 1


def test_usage_with_no_queries(auth_api):
    usage = auth_api.get("/api/v1/queries/usage/").json()
    assert usage["queries"] == 0
    assert Decimal(usage["cost_usd"]) == 0


def test_pending_document_not_retrieved_and_returns_409_when_named(
    auth_api, other_user, coffee_file, dummy_tasks
):
    from rest_framework.test import APIClient

    pending = auth_api.post("/api/v1/documents/", {"file": coffee_file}, format="multipart").json()
    assert pending["status"] == "pending"

    # Without document_ids, pending documents have no chunks and are not retrieved.
    abstain = ask(auth_api, question="What grind does a French press need?")
    assert abstain.status_code == 201
    assert abstain.json()["citations"] == []

    # Naming a pending document of the same Owner returns 409.
    conflict = ask(auth_api, question="What grind?", document_ids=[pending["id"]])
    assert conflict.status_code == 409

    # Naming another Owner's pending document does not leak its state.
    other_client = APIClient()
    other_client.force_authenticate(other_user)
    other_resp = ask(other_client, question="What grind?", document_ids=[pending["id"]])
    assert other_resp.status_code == 201
    assert other_resp.json()["citations"] == []
