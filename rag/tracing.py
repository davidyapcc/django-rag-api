"""Pipeline spans. Provider-agnostic: without a configured tracer provider these are no-ops.

Traces leave the tenant boundary, so span names and attributes carry ids, counts, tokens,
cost and distances only: never question, answer, document or chunk text, or document titles.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.util.types import AttributeValue

_tracer = trace.get_tracer("ragapi")


@contextmanager
def stage(name: str, **attributes: AttributeValue | None) -> Iterator[Span]:
    """A span for one pipeline stage. Exceptions are recorded by type only: their messages can
    quote content (an extraction error, a provider error echoing the request)."""
    with _tracer.start_as_current_span(name, record_exception=False, set_status_on_exception=False) as span:
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
