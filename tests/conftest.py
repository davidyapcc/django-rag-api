import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from rag import providers

_span_exporter = None


@pytest.fixture(autouse=True)
def _fake_provider(settings):
    settings.LLM_PROVIDER = "fake"
    settings.TASKS = {"default": {"BACKEND": "django.tasks.backends.immediate.ImmediateBackend"}}
    settings.SECURE_SSL_REDIRECT = False
    # The manifest storage needs collectstatic; tests render templates without it.
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    providers._build.cache_clear()
    cache.clear()  # throttling state
    yield
    providers._build.cache_clear()


@pytest.fixture
def dummy_tasks(settings):
    settings.TASKS = {"default": {"BACKEND": "django.tasks.backends.dummy.DummyBackend"}}


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="alice", password="s3cure-Passw0rd!")


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(username="bob", password="s3cure-Passw0rd!")


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def auth_api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


COFFEE = (
    b"# Coffee\n\nUse water between 90 and 96 degrees Celsius for brewing.\n\n"
    b"French press needs a coarse grind so the metal filter can hold it back."
)


@pytest.fixture
def coffee_file():
    return SimpleUploadedFile("coffee.md", COFFEE, content_type="text/markdown")


@pytest.fixture
def uploaded(auth_api, coffee_file):
    resp = auth_api.post("/api/v1/documents/", {"file": coffee_file}, format="multipart")
    assert resp.status_code == 202, resp.content
    return resp.json()


@pytest.fixture
def spans():
    """Finished spans, captured in memory. Tracing is off unless an OTLP endpoint is set, so the
    first use installs an in-memory tracer provider (and Django instrumentation) for the session."""
    global _span_exporter
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from apps.core.tracing import configure

    if _span_exporter is None:
        _span_exporter = InMemorySpanExporter()
        configure(SimpleSpanProcessor(_span_exporter))
    # configure() wraps psycopg.connect, which misses a connection the test run opened earlier.
    from django.db import connection
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor

    if connection.connection is not None:
        PsycopgInstrumentor.instrument_connection(connection.connection)
    _span_exporter.clear()
    yield _span_exporter
    _span_exporter.clear()
