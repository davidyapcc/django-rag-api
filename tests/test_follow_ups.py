"""Follow-ups: a Query that names an earlier Query of the same Owner as its predecessor."""

from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import DailySpend
from apps.qa.models import Query
from apps.qa.services import PredecessorNotFoundError, ask
from rag import providers
from rag.providers import ProviderError
from rag.types import RewriteResult, Usage

pytestmark = pytest.mark.django_db

FIRST = "What grind does a French press need?"


def post_ask(client, **body):
    return client.post("/api/v1/ask/", body, format="json")


@pytest.fixture
def first(auth_api, uploaded):
    resp = post_ask(auth_api, question=FIRST)
    assert resp.status_code == 201
    return resp.json()


def _stub_rewrite(monkeypatch, question="What grind does a French press need, and why?", usage=None):
    calls = []

    def rewrite(self, q, history):
        calls.append((q, list(history)))
        return RewriteResult(question, "fake", usage or Usage(5, 7))

    monkeypatch.setattr(providers.FakeProvider, "rewrite", rewrite)
    return calls


def test_follow_up_stores_predecessor_original_and_standalone_question(auth_api, first):
    resp = post_ask(auth_api, question="and why?", predecessor=first["id"])
    assert resp.status_code == 201, resp.content
    data = resp.json()
    assert data["predecessor"] == first["id"]
    assert data["question"] == "and why?"
    assert data["standalone_question"] == f"{FIRST} and why?"
    query = Query.objects.get(pk=data["id"])
    assert query.predecessor_id == first["id"]
    assert query.standalone_question == f"{FIRST} and why?"


def test_plain_query_has_no_predecessor_or_standalone_question(first):
    assert first["predecessor"] is None
    assert first["standalone_question"] is None


def test_follow_up_cost_and_tokens_include_the_rewrite(user, uploaded, monkeypatch, settings):
    settings.CHAT_INPUT_PRICE_PER_MTOK = 1_000_000.0  # $1 per token
    settings.CHAT_OUTPUT_PRICE_PER_MTOK = 1_000_000.0
    settings.EMBEDDING_PRICE_PER_MTOK = 0.0
    standalone = "What grind does a French press need?"
    plain = ask(user, standalone)
    _stub_rewrite(monkeypatch, question=standalone, usage=Usage(5, 7))
    follow = ask(user, "and why?", predecessor_id=plain.pk)
    assert follow.input_tokens == plain.input_tokens + 5
    assert follow.output_tokens == plain.output_tokens + 7
    assert follow.cost_usd == plain.cost_usd + Decimal(12)


def test_other_owners_query_as_predecessor_is_404(first, other_user):
    client = APIClient()
    client.force_authenticate(other_user)
    resp = post_ask(client, question="and why?", predecessor=first["id"])
    assert resp.status_code == 404
    assert str(first["id"]) not in resp.content.decode()
    assert not Query.objects.filter(owner=other_user).exists()


def test_missing_predecessor_is_404(auth_api):
    assert post_ask(auth_api, question="and why?", predecessor=999_999).status_code == 404


def test_service_rejects_other_owners_predecessor(first, other_user):
    with pytest.raises(PredecessorNotFoundError):
        ask(other_user, "and why?", predecessor_id=first["id"])


def test_only_the_last_three_queries_reach_the_rewrite(user, uploaded, monkeypatch):
    chain = []
    predecessor = None
    for i in range(5):
        chain.append(
            Query.objects.create(owner=user, question=f"q{i}", answer=f"a{i}", predecessor=predecessor)
        )
        predecessor = chain[-1]
    calls = _stub_rewrite(monkeypatch)
    ask(user, "and then?", predecessor_id=chain[-1].pk)
    ((question, history),) = calls
    assert question == "and then?"
    assert [(t.question, t.answer) for t in history] == [("q2", "a2"), ("q3", "a3"), ("q4", "a4")]


def test_history_uses_the_standalone_question_of_an_earlier_follow_up(user, uploaded, monkeypatch):
    root = Query.objects.create(owner=user, question="q0", answer="a0")
    mid = Query.objects.create(
        owner=user, question="and?", standalone_question="q0 and?", answer="a1", predecessor=root
    )
    calls = _stub_rewrite(monkeypatch)
    ask(user, "then?", predecessor_id=mid.pk)
    assert [t.question for t in calls[0][1]] == ["q0", "q0 and?"]


def test_answering_sees_only_the_standalone_question_and_chunks(user, uploaded, monkeypatch):
    plain = ask(user, FIRST)
    _stub_rewrite(monkeypatch, question="Why a coarse grind for French press?")
    seen = []
    real_answer = providers.FakeProvider.answer

    def spy(self, question, chunks):
        seen.append((question, chunks))
        return real_answer(self, question, chunks)

    monkeypatch.setattr(providers.FakeProvider, "answer", spy)
    follow = ask(user, "and why?", predecessor_id=plain.pk)
    ((question, chunks),) = seen
    assert question == "Why a coarse grind for French press?"
    assert [c.id for c in chunks] == follow.retrieved_chunk_ids
    sent = question + " ".join(c.text for c in chunks)
    assert plain.answer not in sent.replace(chunks[0].text, "")


def test_retrieval_runs_on_the_standalone_question(user, uploaded, monkeypatch):
    plain = ask(user, "What is the capital of France?")
    assert plain.retrieved_chunk_ids == []
    _stub_rewrite(monkeypatch, question="What grind does a French press need?")
    follow = ask(user, "hmm?", predecessor_id=plain.pk)
    assert follow.retrieved_chunk_ids


def _must_not_run(*a, **kw):
    raise AssertionError("rewrite should not be called")


@pytest.fixture
def paid_provider(monkeypatch, settings):
    settings.DEMO_DAILY_BUDGET_USD = 0.01
    monkeypatch.setattr(providers.FakeProvider, "name", "paid-fake")


def test_exhausted_budget_declines_follow_up_before_the_rewrite(first, user, paid_provider, monkeypatch):
    DailySpend.objects.update_or_create(day=timezone.now().date(), defaults={"cost_usd": Decimal("1")})

    monkeypatch.setattr(providers.FakeProvider, "rewrite", _must_not_run)
    client = APIClient()
    client.force_authenticate(user)
    assert post_ask(client, question="and why?", predecessor=first["id"]).status_code == 429


def test_exhausted_allowance_declines_follow_up_before_the_rewrite(first, user, monkeypatch, settings):
    from apps.core.budget import AllowanceExceededError
    from apps.core.models import OwnerDailySpend

    monkeypatch.setattr(providers.FakeProvider, "name", "paid-fake")
    settings.DEMO_DAILY_BUDGET_USD = 10
    settings.ALLOWANCE_DAILY_USD = 0.05
    OwnerDailySpend.objects.update_or_create(
        owner=user, day=timezone.now().date(), defaults={"cost_usd": Decimal("1")}
    )

    monkeypatch.setattr(providers.FakeProvider, "rewrite", _must_not_run)
    with pytest.raises(AllowanceExceededError):
        ask(user, "and why?", predecessor_id=first["id"])


def test_rewrite_failure_is_502_and_creates_no_query(auth_api, first, monkeypatch):
    def boom(self, *a):
        raise ProviderError("down")

    monkeypatch.setattr(providers.FakeProvider, "rewrite", boom)
    before = Query.objects.count()
    assert post_ask(auth_api, question="and why?", predecessor=first["id"]).status_code == 502
    assert Query.objects.count() == before


def test_rewrite_has_its_own_span_without_content(spans, auth_api, first):
    resp = post_ask(auth_api, question="and the secret clause?", predecessor=first["id"])
    assert resp.status_code == 201
    finished = spans.get_finished_spans()
    by_name = {s.name: s for s in finished}
    rewrite = by_name["ask.rewrite"]
    assert rewrite.parent.span_id == by_name["ask"].context.span_id
    assert rewrite.attributes["history_count"] == 1
    assert rewrite.attributes["llm.input_tokens"] > 0
    text = " ".join(f"{s.name} {dict(s.attributes or {})}" for s in finished)
    for content in ("secret", "French", "coarse"):
        assert content not in text


def test_plain_ask_has_no_rewrite_span(spans, user):
    ask(user, "What is the capital of Australia?")
    assert "ask.rewrite" not in {s.name for s in spans.get_finished_spans()}


# --- Web UI ---


@pytest.fixture
def guest_client():
    client = Client()
    assert client.post("/guest/").status_code == 302
    client.post("/app/documents/samples/")
    return client


def test_answer_offers_a_follow_up(guest_client):
    resp = guest_client.post("/app/ask/", {"question": "What grind size does a French press need?"})
    query = Query.objects.latest("created_at")
    assert b"Ask a follow-up" in resp.content
    assert f'name="predecessor" value="{query.pk}"'.encode() in resp.content


def test_web_follow_up_shows_the_standalone_question(guest_client):
    guest_client.post("/app/ask/", {"question": "What grind size does a French press need?"})
    first = Query.objects.latest("created_at")
    resp = guest_client.post("/app/ask/", {"question": "and why?", "predecessor": first.pk})
    follow = Query.objects.latest("created_at")
    assert follow.predecessor_id == first.pk
    assert b"Searched for" in resp.content
    assert b"What grind size does a French press need? and why?" in resp.content


def test_web_follow_up_to_another_owners_query_is_404(guest_client, user):
    theirs = Query.objects.create(owner=user, question="private", answer="private answer")
    resp = guest_client.post("/app/ask/", {"question": "and why?", "predecessor": theirs.pk})
    assert resp.status_code == 404
    assert b"private" not in resp.content
    assert Query.objects.filter(predecessor=theirs).count() == 0
