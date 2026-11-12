import json

import pytest
import sentry_sdk
from django.core.files.uploadedfile import SimpleUploadedFile
from sentry_sdk.transport import Transport

import apps.core.errors as errors
from rag import providers

SECRET = "zanzibar-glockenspiel"  # stands in for question, chunk and title text


class CapturingTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict] = []

    def capture_envelope(self, envelope) -> None:
        for item in envelope.items:
            if item.type == "event":
                self.events.append(item.payload.json)


@pytest.fixture
def sentry(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.invalid/1")
    transport = CapturingTransport()
    assert errors.configure(transport) is True
    yield transport
    sentry_sdk.get_client().close()
    monkeypatch.delenv("SENTRY_DSN")  # init() would otherwise read it back from the environment
    sentry_sdk.init()  # back to a disabled client


def test_sentry_is_off_without_a_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert errors.configure() is False


def test_unhandled_error_reaches_sentry_without_content(spans, sentry, auth_api, uploaded, monkeypatch):
    def boom(self, texts):
        raise RuntimeError(f"upstream echoed {texts[0]}")

    monkeypatch.setattr(providers.FakeProvider, "embed", boom)
    with pytest.raises(RuntimeError):
        auth_api.post("/api/v1/ask/?q=" + SECRET, {"question": f"Where is {SECRET}?"}, format="json")
    sentry_sdk.flush()
    (event,) = sentry.events
    (exc,) = event["exception"]["values"]
    assert exc["type"] == "RuntimeError"
    assert exc["value"] == errors.SCRUBBED
    assert exc["stacktrace"]["frames"], "stack trace is kept"
    assert event["transaction"] == "/api/v1/ask/"
    assert len(event["tags"]["otel.trace_id"]) == 32
    assert SECRET not in json.dumps(event)


def test_logged_error_keeps_template_not_arguments(sentry, user, monkeypatch):
    from apps.documents.services import Upload, ingest

    def fail(self, texts):
        raise providers.ProviderError(f"upstream echoed {texts[0]}")

    monkeypatch.setattr(providers.FakeProvider, "embed", fail)
    with pytest.raises(providers.ProviderError):
        ingest(user, Upload(f"{SECRET}.txt", "text/plain", f"All about {SECRET}.".encode()))
    sentry_sdk.flush()
    (event,) = sentry.events
    assert event["logentry"] == {"message": "embedding failed for %s"}
    assert SECRET not in json.dumps(event)


def test_breadcrumbs_drop_arguments(sentry, auth_api):
    auth_api.post(
        "/api/v1/documents/",
        {"file": SimpleUploadedFile(f"{SECRET}.md", f"# {SECRET}\n\nAll about {SECRET}.".encode())},
        format="multipart",
    )
    sentry_sdk.capture_exception(RuntimeError(SECRET))
    sentry_sdk.capture_message(SECRET)
    sentry_sdk.flush()
    exc_event, msg_event = sentry.events
    assert exc_event["breadcrumbs"]["values"], "breadcrumbs are kept"
    assert msg_event["message"] == errors.SCRUBBED
    assert SECRET not in json.dumps(sentry.events)
