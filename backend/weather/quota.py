"""Rate-limit awareness and the upstream circuit breaker.

WHY THIS DOES NOT USE X-RateLimit-* HEADERS
-------------------------------------------
Weather-AI's documentation states that every response carries:

    X-RateLimit-Limit / X-RateLimit-Remaining / X-RateLimit-Reset

Verified against the live API, those headers DO NOT EXIST. Every header of
several real 200 responses was inspected and none of them is present. Parsing
is still attempted below - costless, and it means we pick them up automatically
if the provider starts sending them - but nothing depends on it.

The quota is instead tracked two ways, combined:

1. `GET /v1/usage` returns {plan, used, limit, remaining, unlimited}. It is the
   authoritative reading - but it costs a request itself, so polling it often
   would consume the very budget it reports on. Hourly polling would be
   720 requests/month against a 1,000/month free tier: absurd. It is therefore
   synced at most once per WEATHER_USAGE_TTL (default 24h, ~30/month, 3%).

   That interval is enforced by a SHARED ATOMIC CLAIM, not just a timestamp
   check - see claim_usage_sync(). A bare "is it due?" read is a check-then-act
   race, and the per-location coalescing lock does not cover it, so without the
   claim every concurrent worker on a cold cache would spend a request on the
   same reading.

2. Between syncs we count our own upstream calls locally and subtract. We are
   the only consumer of this key, so `remaining_at_sync - calls_since_sync` is
   an accurate running estimate for free.

The estimate is deliberately conservative: local counting can only ever make
remaining look LOWER than it is (we count a call even if it failed), so the
reserve triggers early rather than late.

THE MONTHLY-QUOTA CONSEQUENCE
-----------------------------
The limit is monthly, so a 429 is not a momentary backoff - it is a lockout
lasting until the quota rolls over. Being rate limited is a sustained outage we
inflicted on ourselves, so the design is built to avoid reaching it and to stay
useful once there.
"""

import logging
import time

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

USAGE_KEY = "upstream:usage"
USAGE_LOCK_KEY = "lock:upstream:usage"
CALLS_KEY = "upstream:calls_since_sync"
BREAKER_KEY = "upstream:breaker"

REASON_RATE_LIMITED = "rate_limited"
REASON_QUOTA_RESERVE = "quota_reserve"
REASON_UPSTREAM_FAILURE = "upstream_failure"


def _to_int(value):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Rate-limit headers (forward compatibility only - absent on the live API)
# ---------------------------------------------------------------------------

def parse_rate_limit_headers(headers) -> dict:
    """Extract X-RateLimit-* if present. Returns {} on the live API today."""
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
    """Fold header-reported quota into stored state, if the provider sends any."""
    parsed = parse_rate_limit_headers(headers)
    if not parsed:
        return {}

    logger.info("upstream_rate_limit_headers_present %s", parsed)
    usage = get_usage()
    usage.update(
        {
            "limit": parsed.get("limit", usage.get("limit")),
            "remaining": parsed.get("remaining", usage.get("remaining")),
            "reset_at": parsed.get("reset_at", usage.get("reset_at")),
            "synced_at": time.time(),
            "source": "headers",
        }
    )
    _store_usage(usage)
    _reset_call_counter()
    return parsed


# ---------------------------------------------------------------------------
# /v1/usage - the authoritative reading
# ---------------------------------------------------------------------------

# Minimum retention for a quota reading, independent of the sync interval.
# Guards a real footgun: Django treats timeout=0 as "expire immediately", so a
# WEATHER_USAGE_TTL of 0 (a plausible way to force frequent syncing) would
# silently discard every reading and make the estimate permanently unavailable.
MIN_USAGE_RETENTION = 86400


def _store_usage(usage: dict) -> None:
    try:
        # Retained far longer than the sync interval so the figure survives idle
        # periods and we do not re-sync just because nobody visited.
        retention = max(settings.WEATHER_USAGE_TTL * 7, MIN_USAGE_RETENTION)
        cache.set(USAGE_KEY, usage, timeout=retention)
    except Exception:  # pragma: no cover - cache backend down
        logger.debug("quota: could not persist usage")


def get_usage() -> dict:
    try:
        return dict(cache.get(USAGE_KEY) or {})
    except Exception:  # pragma: no cover
        return {}


def record_usage(payload: dict) -> dict:
    """Store a /v1/usage response and reset the local call counter.

    Expected shape (verified live):
        {"plan": "free", "used": 3, "limit": 1000,
         "remaining": 997, "unlimited": false}
    """
    if not isinstance(payload, dict):
        return {}

    usage = {
        "plan": payload.get("plan"),
        "used": _to_int(payload.get("used")),
        "limit": _to_int(payload.get("limit")),
        "remaining": _to_int(payload.get("remaining")),
        "unlimited": bool(payload.get("unlimited")),
        "synced_at": time.time(),
        "source": "usage_endpoint",
    }
    _store_usage(usage)
    # The reading already accounts for everything spent up to now.
    _reset_call_counter()

    logger.info(
        "quota_synced plan=%s used=%s limit=%s remaining=%s",
        usage["plan"], usage["used"], usage["limit"], usage["remaining"],
    )
    return usage


def usage_sync_due() -> bool:
    """True when the stored reading is missing or older than the sync interval.

    This is only the "should we?" half. It is a plain read, so several workers
    can answer True simultaneously - see claim_usage_sync for the "may I?" half.
    """
    usage = get_usage()
    if not usage or usage.get("synced_at") is None:
        return True
    return (time.time() - usage["synced_at"]) > settings.WEATHER_USAGE_TTL


def claim_usage_sync() -> bool:
    """Atomically claim the right to spend a request on /v1/usage.

    Returns True for exactly ONE caller across every worker and instance.

    Why this is needed: usage_sync_due() is a read, so it is a classic
    check-then-act race. The per-location coalescing lock does not help - it is
    keyed by location, so simultaneous leaders for Nairobi, Mombasa and Kisumu
    are three separate leaders that all reach this gate at once. Without a
    claim, a cold cache on a multi-worker deploy spends one request per
    concurrent miss on a reading that is identical for all of them.

    cache.add() is the same atomic primitive the request coalescing uses - on
    Redis it compiles to `SET NX EX` - so the winner is decided by Redis, not by
    timing. The claim is held for WEATHER_USAGE_LOCK_TTL, which doubles as the
    retry backoff: a failed sync is not retried until it expires. On success,
    record_usage() stamps synced_at, so usage_sync_due() stays False for the
    full WEATHER_USAGE_TTL regardless of when the claim lapses.

    Note the ordering: the cheap read runs first so the common case (not due)
    costs no write at all.
    """
    if not usage_sync_due():
        return False
    try:
        return bool(
            cache.add(USAGE_LOCK_KEY, time.time(), timeout=settings.WEATHER_USAGE_LOCK_TTL)
        )
    except Exception:  # pragma: no cover - cache backend down
        # Fail closed: if we cannot coordinate, do not spend the request.
        logger.debug("quota: could not claim usage sync")
        return False


def get_usage_sync_lock_state():
    """When the current claim was taken, or None if unclaimed."""
    try:
        return cache.get(USAGE_LOCK_KEY)
    except Exception:  # pragma: no cover
        return None


def clear_usage_sync_lock() -> None:
    """Release the claim early. Used by tests and manual resyncs."""
    try:
        cache.delete(USAGE_LOCK_KEY)
    except Exception:  # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# Local call counting between syncs
# ---------------------------------------------------------------------------

def record_upstream_call() -> None:
    """Count one upstream request against the running estimate.

    Called for every attempt, including failures: a request that errored may
    still have been metered, so counting it keeps the estimate conservative.
    """
    try:
        cache.incr(CALLS_KEY, 1)
    except ValueError:
        try:
            cache.set(CALLS_KEY, 1, timeout=None)
        except Exception:  # pragma: no cover
            pass
    except Exception:  # pragma: no cover
        logger.debug("quota: could not count upstream call")


def _calls_since_sync() -> int:
    try:
        return int(cache.get(CALLS_KEY) or 0)
    except Exception:  # pragma: no cover
        return 0


def _reset_call_counter() -> None:
    try:
        cache.set(CALLS_KEY, 0, timeout=None)
    except Exception:  # pragma: no cover
        pass


def estimated_remaining():
    """Best estimate of monthly requests left, or None if never synced."""
    usage = get_usage()
    if usage.get("unlimited"):
        return None
    remaining = usage.get("remaining")
    if remaining is None:
        return None
    return max(0, remaining - _calls_since_sync())


def get_quota() -> dict:
    """Quota state for /api/meta/stats/, including the running estimate."""
    usage = get_usage()
    if not usage:
        return {}
    return {
        **usage,
        "calls_since_sync": _calls_since_sync(),
        "estimated_remaining": estimated_remaining(),
    }


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

def open_breaker(reason: str, until: float | None = None, seconds: int | None = None):
    """Stop upstream calls until `until` (epoch) or for `seconds`.

    Clamped to [1, WEATHER_MAX_BREAKER_SECONDS] so a malformed reset value
    cannot take the service offline indefinitely.
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
        cache.set(BREAKER_KEY, {"reason": reason, "reset_at": reset_at}, timeout=duration)
    except Exception:  # pragma: no cover
        logger.debug("quota: could not open breaker")
        return

    logger.warning(
        "breaker_open reason=%s duration=%ss until=%s", reason, duration, int(reset_at)
    )


def breaker_state() -> dict | None:
    try:
        state = cache.get(BREAKER_KEY)
    except Exception:  # pragma: no cover
        return None
    if not state:
        return None
    if state.get("reset_at", 0) <= time.time():
        return None
    return state


def clear_breaker() -> None:
    try:
        cache.delete(BREAKER_KEY)
    except Exception:  # pragma: no cover
        pass


def upstream_allowed() -> tuple[bool, str | None]:
    """The single gate every upstream call passes through.

    Once one request learns we are locked out, every later request is
    short-circuited here without touching the network - which is what prevents
    retry storms.
    """
    state = breaker_state()
    if state:
        return False, state.get("reason", REASON_RATE_LIMITED)

    remaining = estimated_remaining()
    if remaining is not None and remaining <= settings.WEATHER_QUOTA_RESERVE:
        return False, REASON_QUOTA_RESERVE

    return True, None


def handle_rate_limited(headers) -> None:
    """React to a 429: back off until the reset, or for a fixed window."""
    parsed = record_headers(headers)
    reset_at = parsed.get("reset_at")

    if reset_at and reset_at > time.time():
        open_breaker(REASON_RATE_LIMITED, until=reset_at)
    else:
        # No usable reset (the normal case, since the headers are absent).
        open_breaker(REASON_RATE_LIMITED, seconds=settings.WEATHER_DEFAULT_429_BACKOFF)

    # A 429 means the real remaining is zero regardless of our estimate.
    usage = get_usage()
    if usage:
        usage["remaining"] = 0
        usage["synced_at"] = time.time()
        usage["source"] = "429"
        _store_usage(usage)
        _reset_call_counter()


def handle_upstream_failure(reason: str) -> None:
    """React to a 5xx/timeout with a brief backoff."""
    open_breaker(REASON_UPSTREAM_FAILURE, seconds=settings.WEATHER_FAILURE_BACKOFF)
    logger.info("upstream_failure_backoff reason=%s", reason)
