"""Domain exceptions and the DRF exception handler.

Two rules govern everything in this module:

1. The client never sees an internal detail - no stack traces, no upstream
   response bodies, no hint that an API key exists.
2. Every error carries a machine-readable `code` so the frontend can render a
   specific human message instead of echoing backend prose.
"""

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class UpstreamError(Exception):
    """Base class for failures talking to Weather-AI."""


class UpstreamRateLimited(UpstreamError):
    """Weather-AI returned 429 - the monthly quota is exhausted."""

    def __init__(self, reset_at: float | None = None, remaining: int | None = None):
        self.reset_at = reset_at
        self.remaining = remaining
        super().__init__("Weather-AI rate limit reached.")


class UpstreamUnavailable(UpstreamError):
    """Weather-AI failed transiently: 5xx, timeout, connection or parse error."""

    def __init__(self, reason: str = "unavailable"):
        self.reason = reason
        super().__init__(f"Weather-AI unavailable: {reason}")


class UpstreamMisconfigured(UpstreamError):
    """Our credentials or plan are wrong (401/403), or no key is configured.

    This is an operator problem, not a user problem. It is logged loudly and
    reported to the client as a generic unavailability.
    """


def error_response(code: str, message: str, http_status: int, **extra) -> Response:
    """Build the single error shape every endpoint returns."""
    body = {"error": {"code": code, "message": message}}
    if extra:
        body["error"].update(extra)
    return Response(body, status=http_status)


def api_exception_handler(exc, context):
    """DRF exception handler that normalises errors and hides internals."""
    response = drf_exception_handler(exc, context)

    if response is not None:
        # Throttling is the one DRF-native error we reshape by hand so the
        # frontend can tell "you are going too fast" from "upstream is busy".
        if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            return error_response(
                "too_many_requests",
                "You are making requests too quickly. Please slow down.",
                status.HTTP_429_TOO_MANY_REQUESTS,
                retry_after=getattr(exc, "wait", None),
            )

        detail = response.data.get("detail") if isinstance(response.data, dict) else None
        return error_response(
            "request_error",
            str(detail) if detail else "The request could not be processed.",
            response.status_code,
        )

    # Anything reaching here is an unhandled bug. Log the traceback server-side
    # and return an opaque message.
    logger.exception("Unhandled exception in %s", context.get("view"))
    return error_response(
        "internal_error",
        "Something went wrong on our side. Please try again shortly.",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
