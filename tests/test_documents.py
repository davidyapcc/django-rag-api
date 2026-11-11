import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.documents.models import Chunk, Document
from rag import providers
from rag.providers import ProviderError
from tests.conftest import COFFEE

pytestmark = pytest.mark.django_db


def test_upload_creates_document_and_chunks(uploaded, user):
    assert uploaded["status"] == "ready"
    assert uploaded["chunk_count"] >= 1
    assert uploaded["content_type"] == "text/markdown"
    doc = Document.objects.get(pk=uploaded["id"])
    assert doc.owner == user
    assert Chunk.objects.filter(document=doc, owner=user).count() == uploaded["chunk_count"]


def test_custom_title(auth_api, coffee_file):
    resp = auth_api.post("/api/v1/documents/", {"file": coffee_file, "title": "Brewing"}, format="multipart")
    assert resp.json()["title"] == "Brewing"


def test_duplicate_upload_returns_conflict(auth_api, uploaded):
    resp = auth_api.post(
        "/api/v1/documents/", {"file": SimpleUploadedFile("copy.md", COFFEE)}, format="multipart"
    )
    assert resp.status_code == 409
    assert resp.json()["document"]["id"] == uploaded["id"]


def test_unsupported_extension_rejected(auth_api):
    resp = auth_api.post(
        "/api/v1/documents/", {"file": SimpleUploadedFile("x.exe", b"MZ")}, format="multipart"
    )
    assert resp.status_code == 400


def test_too_large_rejected(auth_api, settings):
    settings.MAX_UPLOAD_BYTES = 10
    resp = auth_api.post(
        "/api/v1/documents/", {"file": SimpleUploadedFile("big.txt", b"x" * 11)}, format="multipart"
    )
    assert resp.status_code == 400


def test_empty_document_is_unprocessable(auth_api):
    resp = auth_api.post(
        "/api/v1/documents/", {"file": SimpleUploadedFile("empty.txt", b"   ")}, format="multipart"
    )
    assert resp.status_code == 422


def test_bad_encoding_is_unprocessable(auth_api):
    resp = auth_api.post(
        "/api/v1/documents/", {"file": SimpleUploadedFile("bad.txt", b"\xff\xfe\xfa")}, format="multipart"
    )
    assert resp.status_code == 422


def test_embedding_failure_returns_502_and_stores_nothing(auth_api, coffee_file, monkeypatch):
    def boom(self, texts):
        raise ProviderError("down")

    monkeypatch.setattr(providers.FakeProvider, "embed", boom)
    resp = auth_api.post("/api/v1/documents/", {"file": coffee_file}, format="multipart")
    assert resp.status_code == 502
    assert not Document.objects.exists()


def test_list_retrieve_chunks_delete(auth_api, uploaded):
    assert auth_api.get("/api/v1/documents/").json()["count"] == 1
    assert auth_api.get(f"/api/v1/documents/{uploaded['id']}/").status_code == 200
    chunks = auth_api.get(f"/api/v1/documents/{uploaded['id']}/chunks/").json()
    assert chunks["results"][0]["index"] == 0
    assert auth_api.delete(f"/api/v1/documents/{uploaded['id']}/").status_code == 204
    assert not Chunk.objects.exists()


def test_users_cannot_see_each_others_documents(uploaded, other_user):
    client = APIClient()
    client.force_authenticate(other_user)
    assert client.get("/api/v1/documents/").json()["count"] == 0
    assert client.get(f"/api/v1/documents/{uploaded['id']}/").status_code == 404
    assert client.delete(f"/api/v1/documents/{uploaded['id']}/").status_code == 404


def test_upload_is_throttled(auth_api, monkeypatch):
    from rest_framework.throttling import ScopedRateThrottle

    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"upload": "1/day"})
    first = auth_api.post(
        "/api/v1/documents/", {"file": SimpleUploadedFile("a.txt", b"one")}, format="multipart"
    )
    second = auth_api.post(
        "/api/v1/documents/", {"file": SimpleUploadedFile("b.txt", b"two")}, format="multipart"
    )
    assert first.status_code == 201
    assert second.status_code == 429


def test_chunk_owner_must_match_its_document_owner(uploaded, other_user):
    doc = Document.objects.get(pk=uploaded["id"])
    with pytest.raises(IntegrityError), transaction.atomic():
        Chunk.objects.create(
            document=doc, owner=other_user, index=999, text="x", embedding=[0.0] * settings.EMBEDDING_DIM
        )


def test_moving_a_document_moves_its_chunks(uploaded, other_user):
    doc = Document.objects.get(pk=uploaded["id"])
    Document.objects.filter(pk=doc.pk).update(owner=other_user)
    assert set(Chunk.objects.filter(document=doc).values_list("owner", flat=True)) == {other_user.pk}
