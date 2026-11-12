"""Pipeline spans. Provider-agnostic: without a configured tracer provider these are no-ops.

Traces leave the tenant boundary, so span names and attributes carry ids, counts, tokens,
cost and distances only: never question, answer, document or chunk text, or document titles.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.util.types import AttributeValue

_tracer = trace.get_tracer("ragapi")


@contextmanager
def stage(
    name: str, kind: SpanKind = SpanKind.INTERNAL, **attributes: AttributeValue | None
) -> Iterator[Span]:
    """A span for one pipeline stage. Exceptions are recorded by type only: their messages can
    quote content (an extraction error, a provider error echoing the request)."""
    with _tracer.start_as_current_span(
        name, kind=kind, record_exception=False, set_status_on_exception=False
    ) as span:
        set_attributes(span, **attributes)
        try:
            yield span
        except BaseException as exc:
            span.set_attribute("error.type", type(exc).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise


def set_attributes(span: Span, **attributes: AttributeValue | None) -> None:
    """Keyword names use `__` for `.` (owner__id -> owner.id); None values are skipped."""
    span.set_attributes({key.replace("__", "."): v for key, v in attributes.items() if v is not None})


@contextmanager
def llm_call(operation: str, provider: str, model: str) -> Iterator[Span]:
    """A client span around one call to an LLM vendor, named and attributed per the OpenTelemetry
    GenAI semantic conventions (`chat gpt-6-luna`, `embeddings text-embedding-3-small`), so GenAI-aware
    backends group calls by model. Prompts and completions are never recorded."""
    with stage(
        f"{operation} {model}",
        kind=SpanKind.CLIENT,
        gen_ai__operation__name=operation,
        gen_ai__provider__name=provider,
        gen_ai__request__model=model,
    ) as span:
        yield span
