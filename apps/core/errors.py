"""Turns Sentry error tracking on when SENTRY_DSN is set; otherwise it stays a no-op.

Error events leave the tenant boundary just like traces, so they follow the same rule: no question,
answer, document or chunk text, and no document titles. Sentry gets the exception type, the stack
trace (code, no local variables), the URL path, ids, and the OpenTelemetry trace id, which is enough
to find the matching trace. Exception messages and log arguments are dropped because they can
quote content (an extraction error, a provider error echoing the request, a log line with a title).
Sentry's own performance tracing stays off: OpenTelemetry owns traces (see `tracing.py`).
"""

import os
from typing import Any

import sentry_sdk
from opentelemetry import trace
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.transport import Transport

SCRUBBED = "[scrubbed]"


def configure(transport: Transport | None = None) -> bool:
    """Initialise the Sentry SDK. Returns whether error tracking is on."""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        transport=transport,
        integrations=[DjangoIntegration()],
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        # Render sets RENDER_GIT_COMMIT, so each deploy is its own release with no extra config.
        release=os.environ.get("SENTRY_RELEASE") or os.environ.get("RENDER_GIT_COMMIT"),
        # Collect nothing that can hold content or identify a person; before_send scrubs the rest.
        data_collection={
            "user_info": False,
            "cookies": {"mode": "off"},
            "http_bodies": [],
            "url_query_params": {"mode": "off"},
            "gen_ai": {"inputs": False, "outputs": False},
            "database_query_data": False,
            "stack_frame_variables": False,
        },
        traces_sample_rate=None,
        before_send=scrub_event,
        before_breadcrumb=scrub_breadcrumb,
    )
    return True


def scrub_event(event: Any, hint: Any) -> Any:
    for exc in (event.get("exception") or {}).get("values") or []:
        if exc.get("value"):
            exc["value"] = SCRUBBED
    logentry = event.get("logentry")
    if logentry:
        # Keep the template ("embedding failed for %s"), drop the arguments and the formatted line.
        event["logentry"] = {"message": logentry.get("message", SCRUBBED)}
    if event.get("message"):
        event["message"] = SCRUBBED
    request = event.get("request")
    if request:
        for key in ("data", "query_string", "cookies"):
            request.pop(key, None)
    event.pop("extra", None)
    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        event.setdefault("tags", {})["otel.trace_id"] = format(ctx.trace_id, "032x")
    return event


def scrub_breadcrumb(crumb: Any, hint: Any) -> Any:
    record = (hint or {}).get("log_record")
    if record is not None:
        crumb["message"] = str(record.msg)  # the template, not the formatted line
    elif crumb.get("category") != "query" and crumb.get("message"):
        crumb["message"] = SCRUBBED
    crumb.pop("data", None)  # SQL parameters, log arguments
    return crumb
