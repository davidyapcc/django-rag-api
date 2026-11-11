from typing import Any, cast

from rest_framework.throttling import ScopedRateThrottle


class _Scope:
    def __init__(self, scope: str) -> None:
        self.throttle_scope = scope


def allowed(request, scope: str) -> bool:
    """Apply the API's per-user (or per-IP when anonymous) rate limits to the web pages."""
    # ScopedRateThrottle only reads `throttle_scope` from the view.
    return ScopedRateThrottle().allow_request(request, cast(Any, _Scope(scope)))
