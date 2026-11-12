import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode

import apps.core.tracing as tracing
from apps.documents.services import Upload, ingest
from rag import providers
from rag.providers import ProviderError

from .conftest import COFFEE

QUESTION = "What grind does a French press need?"


def _by_name(exporter) -> dict:
    return {s.name: s for s in exporter.get_finished_spans()}


def _all_span_text(exporter) -> str:
    parts = []
    for s in exporter.get_finished_spans():
        parts.append(s.name)
        parts.extend(f"{k}={v}" for k, v in (s.attributes or {}).items())
        for e in s.events:
            parts.append(e.name)
            parts.extend(f"{k}={v}" for k, v in (e.attributes or {}).items())
        parts.append(s.status.description or "")
    return "\n".join(parts)


def test_tracing_is_off_without_an_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert tracing.configure() is False


def test_endpoint_turns_on_otlp_export(monkeypatch):
    installed = []
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.invalid:4318")
    monkeypatch.setattr(trace, "set_tracer_provider", installed.append)
    monkeypatch.setattr(tracing.DjangoInstrumentor, "instrument", lambda self: None)
    assert tracing.configure() is True
    (provider,) = installed
    assert provider.resource.attributes["service.name"] == "django-rag-api"
    provider.shutdown()  # nothing was exported, so this makes no network call


def test_ask_spans_nest_under_the_request(spans, auth_api, uploaded):
    spans.clear()
    resp = auth_api.post("/api/v1/ask/", {"question": QUESTION}, format="json")
    assert resp.status_code == 201
    by_name = _by_name(spans)
    request = next(s for s in spans.get_finished_spans() if s.kind == SpanKind.SERVER)
    ask = by_name["ask"]
    assert ask.parent.span_id == request.context.span_id
    for stage in ("ask.embed", "ask.retrieve", "ask.answer"):
        assert by_name[stage].parent.span_id == ask.context.span_id
    assert ask.attributes["query.id"] == resp.json()["id"]
    assert ask.attributes["query.abstained"] is False
    assert ask.attributes["cost_usd"] >= 0
    assert by_name["ask.answer"].attributes["llm.input_tokens"] > 0
    assert by_name["ask.retrieve"].attributes["retrieved_count"] >= 1


def test_upload_spans_each_stage(spans, auth_api):
    resp = auth_api.post(
        "/api/v1/documents/", {"file": SimpleUploadedFile("coffee.md", COFFEE)}, format="multipart"
    )
    assert resp.status_code == 201
    by_name = _by_name(spans)
    root = by_name["ingest"]
    for stage in ("ingest.extract", "ingest.chunk", "ingest.embed", "ingest.store"):
        assert by_name[stage].parent.span_id == root.context.span_id
    assert root.attributes["document.id"] == resp.json()["id"]
    assert by_name["ingest.embed"].attributes["llm.embedding_tokens"] > 0


def test_spans_carry_no_content(spans, auth_api, uploaded):
    resp = auth_api.post("/api/v1/ask/", {"question": QUESTION}, format="json")
    text = _all_span_text(spans).lower()
    answer = resp.json()["answer"]
    for content in (QUESTION, answer, "coarse grind", "French press", "coffee.md", uploaded["title"]):
        assert content.lower() not in text, content


def test_abstained_ask_has_no_answer_span(spans, user):
    from apps.qa.services import ask

    ask(user, "What is the capital city of Australia?")
    by_name = _by_name(spans)
    assert "ask.answer" not in by_name
    assert by_name["ask"].attributes["query.abstained"] is True


def test_errors_are_recorded_by_type_only(spans, user, monkeypatch):
    def fail(self, texts):
        raise ProviderError("upstream echoed: French press needs a coarse grind")

    monkeypatch.setattr(providers.FakeProvider, "embed", fail)
    with pytest.raises(ProviderError):
        ingest(user, Upload("c.txt", "text/plain", b"French press needs a coarse grind."))
    embed = _by_name(spans)["ingest.embed"]
    assert embed.status.status_code == StatusCode.ERROR
    assert embed.attributes["error.type"] == "ProviderError"
    assert "coarse" not in _all_span_text(spans)


def test_database_calls_are_spans_without_parameters(spans, auth_api, uploaded):
    spans.clear()
    resp = auth_api.post("/api/v1/ask/", {"question": QUESTION}, format="json")
    assert resp.status_code == 201
    db = [s for s in spans.get_finished_spans() if (s.attributes or {}).get("db.system") == "postgresql"]
    retrieve = _by_name(spans)["ask.retrieve"]
    assert any(s.parent.span_id == retrieve.context.span_id for s in db)
    for s in db:
        assert "db.statement.parameters" not in s.attributes
        assert "%s" in s.attributes["db.statement"] or "%(" in s.attributes["db.statement"]
