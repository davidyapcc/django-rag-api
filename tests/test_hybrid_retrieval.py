"""Hybrid retrieval (ADR 0004): a Chunk is a candidate if it passes the vector gate or the
full-text gate; reciprocal rank fusion orders the candidates."""

import pytest

from apps.documents.models import Chunk
from apps.documents.services import Upload, ingest
from apps.qa import services
from apps.qa.services import retrieve
from rag import providers

pytestmark = pytest.mark.django_db

NETWORK = b"Use WPA3 encryption where devices support it, and WPA2 otherwise. Turn off WPS."
COFFEE = b"Use water between 90 and 96 degrees Celsius. A French press needs a coarse grind."
FAR_AWAY = 0.0  # a max_distance nothing passes, so only the full-text gate can retrieve


def _vector(owner, question):
    return providers.get_provider().embed([question]).vectors[0]


def test_exact_term_outside_max_distance_is_retrieved_by_text(user):
    doc = ingest(user, Upload("net.txt", "text/plain", NETWORK))
    q = "Should I use WPA3?"
    hits = retrieve(user, q, _vector(user, q), top_k=5, max_distance=FAR_AWAY)
    assert [h.chunk.document_id for h in hits] == [doc.pk]
    assert hits[0].distance is None
    assert hits[0].text_coverage == 1.0


def test_shared_common_word_below_the_floor_is_not_retrieved(user):
    ingest(user, Upload("coffee.txt", "text/plain", COFFEE))
    q = "What was the hottest water temperature ever recorded on the surface of Venus?"
    assert retrieve(user, q, _vector(user, q), top_k=5, max_distance=FAR_AWAY) == []


def test_floor_is_a_setting(user, settings):
    ingest(user, Upload("coffee.txt", "text/plain", COFFEE))
    q = "What was the hottest water temperature ever recorded on the surface of Venus?"
    settings.RAG_MIN_TEXT_COVERAGE = 0.1
    assert retrieve(user, q, _vector(user, q), top_k=5, max_distance=FAR_AWAY)


def test_off_topic_question_abstains_without_a_model_call(auth_api, user, monkeypatch):
    ingest(user, Upload("coffee.txt", "text/plain", COFFEE))
    monkeypatch.setattr(providers.FakeProvider, "max_distance", FAR_AWAY)

    def must_not_run(*a, **kw):
        raise AssertionError("chat model should not be called")

    monkeypatch.setattr(providers.FakeProvider, "answer", must_not_run)
    resp = auth_api.post(
        "/api/v1/ask/", {"question": "How hot is the surface of Venus in degrees?"}, format="json"
    )
    assert resp.status_code == 201
    assert resp.json()["citations"] == []


def test_text_gate_never_crosses_owners(user, other_user):
    ingest(other_user, Upload("net.txt", "text/plain", NETWORK))
    q = "Should I use WPA3?"
    assert retrieve(user, q, _vector(user, q), top_k=5, max_distance=FAR_AWAY) == []


def test_loading_fused_chunks_is_scoped_by_owner(user, other_user, monkeypatch):
    # Defence in depth: even if a gate returned another Owner's Chunk id, retrieve drops it.
    foreign = ingest(other_user, Upload("net.txt", "text/plain", NETWORK))
    foreign_chunk = Chunk.objects.get(document=foreign)
    monkeypatch.setattr(services, "_vector_gate", lambda *a: [(foreign_chunk.pk, 0.1)])
    q = "Should I use WPA3?"
    assert retrieve(user, q, [0.0], top_k=5, max_distance=1.0) == []


def test_document_filter_applies_to_the_text_gate(user):
    net = ingest(user, Upload("net.txt", "text/plain", NETWORK))
    coffee = ingest(user, Upload("coffee.txt", "text/plain", COFFEE))
    q = "Should I use WPA3?"
    v = _vector(user, q)
    assert retrieve(user, q, v, top_k=5, max_distance=FAR_AWAY, document_ids=[coffee.pk]) == []
    hits = retrieve(user, q, v, top_k=5, max_distance=FAR_AWAY, document_ids=[net.pk])
    assert [h.chunk.document_id for h in hits] == [net.pk]


def test_question_of_only_stopwords_has_no_text_candidates(user):
    ingest(user, Upload("net.txt", "text/plain", NETWORK))
    q = "What is it?"
    assert retrieve(user, q, _vector(user, q), top_k=5, max_distance=FAR_AWAY) == []


def test_fusion_ranks_chunks_found_by_both_gates_first(user, monkeypatch):
    net = ingest(user, Upload("net.txt", "text/plain", NETWORK))
    coffee = ingest(user, Upload("coffee.txt", "text/plain", COFFEE))
    net_chunk = Chunk.objects.get(document=net)
    coffee_chunk = Chunk.objects.get(document=coffee)
    # Vector gate prefers the coffee chunk, then the network chunk; only the network chunk
    # matches the text, so fusion puts it first.
    monkeypatch.setattr(services, "_vector_gate", lambda *a: [(coffee_chunk.pk, 0.1), (net_chunk.pk, 0.2)])
    q = "Should I use WPA3?"
    hits = retrieve(user, q, [0.0], top_k=5, max_distance=1.0)
    assert [h.chunk.pk for h in hits] == [net_chunk.pk, coffee_chunk.pk]
    assert hits[0].distance == 0.2 and hits[0].text_coverage == 1.0
    assert hits[1].text_coverage is None
    assert hits[0].score > hits[1].score


def test_top_k_caps_the_fused_list(user, monkeypatch):
    net = ingest(user, Upload("net.txt", "text/plain", NETWORK))
    coffee = ingest(user, Upload("coffee.txt", "text/plain", COFFEE))
    ids = [Chunk.objects.get(document=d).pk for d in (coffee, net)]
    monkeypatch.setattr(services, "_vector_gate", lambda *a: [(ids[0], 0.1)])
    q = "Should I use WPA3?"
    assert len(retrieve(user, q, [0.0], top_k=1, max_distance=1.0)) == 1
