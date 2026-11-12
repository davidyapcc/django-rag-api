"""Turns tracing on when an OTLP endpoint is configured; otherwise it stays a no-op.

Uses the standard OpenTelemetry env vars (OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_HEADERS,
OTEL_SERVICE_NAME, ...), so pointing it at a backend is configuration only.
"""

import os

from opentelemetry import trace
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanProcessor


def configure(processor: SpanProcessor | None = None) -> bool:
    """Install a tracer provider plus Django (request) and psycopg (database) instrumentation.
    Returns whether tracing is on.

    Database spans carry the SQL with its placeholders, never the bound parameters
    (`capture_parameters` stays off), so question and document text stay out of traces."""
    if processor is None:
        if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            return False
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        processor = BatchSpanProcessor(OTLPSpanExporter())
    resource = Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "django-rag-api")})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    DjangoInstrumentor().instrument()
    PsycopgInstrumentor().instrument(capture_parameters=False, enable_commenter=False)
    return True
