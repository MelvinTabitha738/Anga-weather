"""Rate-limit awareness and the upstream circuit breaker.

Weather-AI's documented rate limit is a MONTHLY quota, not a per-second one:

    X-RateLimit-Limit:     1000        (free tier)
    X-RateLimit-Remaining: 987
    X-RateLimit-Reset:     1717977600  (unix epoch)

Two consequences drive the design here:

* A 429 is not something to retry in a moment. It means the month's quota is
  gone and will not return until X-RateLimit-Reset - potentially days away. So
  a 429 opens the breaker until that timestamp and we serve cache exclusively.

* Because the quota is a finite monthly budget, running it to zero is a real
  failure mode. We reserve a floor (WEATHER_QUOTA_RESERVE) and stop calling
  upstream before the budget is fully drained, keeping a margin for genuinely
  new locations.

The breaker is stored in the shared cache, so with Redis all instances observe
one 429 and back off together instead of each discovering it independently.
"""

import logging
import time

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

QUOTA_KEY = "upstream:quota"
BREAKER_KEY = "upstream:breaker"

# Reasons the breaker can be open, surfaced in logs and /api/meta/stats/.
REASON_RATE_LIMITED = "rate_limited"
REASON_QUOTA_RESERVE = "quota_reserve"
REASON_UPSTREAM_FAILURE = "upstream_failure"


def _to_int(value):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def parse_rate_limit_headers(headers) -> dict:
    """Extract the documented X-RateLimit-* headers, ignoring anything absent.

    Header lookup is case-insensitive via requests' CaseInsensitiveDict, but we
    tolerate a plain dict too so tests can pass literals.
    """
    if headers is None:
        return {}
    get = headers.get

    parsed = {
        "limit": _to_int(get("X-RateLimit-Limit") or get("x-ratelimit-limit")),
        "remaining": _to_int(get("X-RateLimit-Remaining") or get("x-ratelimit-remaining")),
        "reset_at": _to_int(get("X-RateLimit-Reset") or get("x-ratelimit-reset")),
    }
    return {k: v for k, v in parsed.items() if v is not None}


def record_headers(headers) -> dict:
    """Persist the latest observed quota state and return it.

    Called after every upstream response, success or failure, so the quota view
    stays current without spending a request on /v1/usage.
    """
    parsed = parse_rate_limit_headers(headers)
    if not parsed:
        return {}

    parsed["observed_at"] = time.time()
    try:
        # Retained well past a monthly reset so the figure survives idle periods.
        cache.set(QUOTA_KEY, parsed, timeout=settings.WEATHER_MAX_BREAKER_SECONDS * 2)
    except Exception:  # pragma: no cover - cache backend down
        logger.debug("quota: could not persist rate-limit state")

    remaining = parsed.get("remaining")
    if remaining is not None and remaining <= settings.WEATHER_QUOTA_RESERVE:
        logger.warning(
            "quota_low remaining=%s reserve=%s - upstream calls will be suspended",
            remaining,
            settings.WEATHER_QUOTA_RESERVE,
        )
    return parsed


def get_quota() -> dict:
    """Return the last observed quota state, or an empty dict if never seen."""
    try:
        return cache.get(QUOTA_KEY) or {}
    except Exception:  # pragma: no cover - cache backend down
        return {}


def open_breaker(reason: str, until: float | None = None, seconds: int | None = None):
    """Stop upstream calls until `until` (epoch) or for `seconds`.

    The duration is clamped to [1, WEATHER_MAX_BREAKER_SECONDS] so a malformed
    or absurd reset header cannot take the service offline indefinitely.
    """
    now = time.time()
    if until is not None:
        duration = until - now
    elif seconds is not None:
        duration = seconds
    else:
        duration = settings.WEATHER_FAILURE_BACKOFF

    duration = max(1, min(int(duration), settings.WEATHER_MAX_BREAKER_SECONDS))
    reset_at = now + duration

    try:
        cache.set(
            BREAKER_KEY,
            {"reason": reason, "reset_at": reset_at},
            timeout=duration,
        )
    except Exception:  # pragma: no cover - cache backend down
        logger.debug("quota: could not open breaker")
        return

    logger.warning(
        "breaker_open reason=%s duration=%ss until=%s",
        reason,
        duration,
        int(reset_at),
    )


def breaker_state() -> dict | None:
    """Return {reason, reset_at} while the breaker is open, else None."""
    try:
        state = cache.get(BREAKER_KEY)
    except Exception:  # pragma: no cover - cache backend down
        return None

    if not state:
        return None
    # Belt and braces: the cache TTL should already have expired this.
    if state.get("reset_at", 0) <= time.time():
        return None
    return state


def clear_breaker() -> None:
    """Close the breaker early, e.g. after a successful probe or in tests."""
    try:
        cache.delete(BREAKER_KEY)
    except Exception:  # pragma: no cover
        pass


def upstream_allowed() -> tuple[bool, str | None]:
    """Decide whether an upstream call may be made right now.

    Returns (allowed, reason_if_blocked). This is the single gate every
    upstream request passes through, which is what stops retry storms: once one
    request learns we are rate limited, every subsequent request is short-
    circuited without touching the network.
    """
    state = breaker_state()
    if state:
        return False, state.get("reason", REASON_RATE_LIMITED)

    quota = get_quota()
    remaining = quota.get("remaining")
    if remaining is not None and remaining <= settings.WEATHER_QUOTA_RESERVE:
        return False, REASON_QUOTA_RESERVE

    return True, None


def handle_rate_limited(headers) -> None:
    """React to a 429: record state and back off until the documented reset."""
    parsed = record_headers(headers)
    reset_at = parsed.get("reset_at")

    if reset_at and reset_at > time.time():
        open_breaker(REASON_RATE_LIMITED, until=reset_at)
    else:
        # No usable reset header - back off for a fixed window rather than
        # retrying immediately.
        open_breaker(
            REASON_RATE_LIMITED, seconds=settings.WEATHER_DEFAULT_429_BACKOFF
        )


def handle_upstream_failure(reason: str) -> None:
    """React to a 5xx/timeout: brief backoff so we do not hammer a sick API."""
    open_breaker(REASON_UPSTREAM_FAILURE, seconds=settings.WEATHER_FAILURE_BACKOFF)
    logger.info("upstream_failure_backoff reason=%s", reason)
