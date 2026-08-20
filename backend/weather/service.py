"""Weather orchestration: cache, coalesce, fetch, degrade.

This is the module the whole assignment is really about. It decides, for every
incoming request, whether that request needs to become an upstream request -
and the answer is usually no.

    resolve location
        -> fresh cache?            yes -> serve it, upstream untouched
        -> breaker open?           yes -> serve stale, or a clean error
        -> win the single-flight lock?
               yes -> call Weather-AI once, cache, serve
               no  -> wait for the leader's result, then serve it
        -> upstream failed?        -> serve stale if we have it, else error

REQUEST COALESCING
------------------
The failure mode this prevents: N users request an uncached location at the
same instant, every one of them misses the cache, and all N call Weather-AI.
On a 1,000-request MONTHLY quota, one such burst can cost a meaningful slice of
the month's budget for data that is identical N times over.

The fix is single-flight. `cache.add()` is atomic - on Redis it compiles to
`SET NX EX` - so exactly one concurrent request acquires the lock and becomes
the leader. The rest become followers: they poll briefly for the leader's
result and serve that. One upstream request, N satisfied users.

Followers detect the leader's result by comparing `fetched_at` against the
entry that existed when they started waiting, so a pre-existing stale entry is
never mistaken for a fresh fetch.

Limitation, stated plainly: followers block a worker thread while waiting.
With gunicorn's threaded workers that is fine at this scale, and the wait is
bounded by WEATHER_COALESCE_WAIT. See the README trade-offs section.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field

from django.conf import settings
from django.core.cache import cache as django_cache

from locations.models import Location
from locations.selectors import LocationNotFound, resolve_location
from weather import cache as weather_cache
from weather import metrics, quota
from weather.adapter import normalize_upstream
from weather.client import get_client
from weather.exceptions import (
    UpstreamMisconfigured,
    UpstreamRateLimited,
    UpstreamUnavailable,
)

logger = logging.getLogger(__name__)

# How often a follower checks for the leader's result.
POLL_INTERVAL = 0.15

# Response status vocabulary shared with the frontend.
STATUS_LIVE = "live"      # fetched from Weather-AI during this request
STATUS_CACHED = "cached"  # served from cache, still within the fresh TTL
STATUS_STALE = "stale"    # served from cache past its TTL, as a fallback

# Why we fell back to stale data. Surfaced so the UI can word its notice.
REASON_RATE_LIMITED = "rate_limited"
REASON_UPSTREAM_UNAVAILABLE = "upstream_unavailable"
REASON_QUOTA_RESERVE = "quota_reserve"


class NoDataAvailable(Exception):
    """Upstream failed and there is no cached data to fall back on."""

    def __init__(self, reason: str, retry_at: float | None = None):
        self.reason = reason
        self.retry_at = retry_at
        super().__init__(reason)


@dataclass
class WeatherResult:
    """What the view renders. Freshness metadata is never optional."""

    location: Location
    payload: dict
    status: str
    fetched_at: float
    age_seconds: int
    fallback_reason: str | None = None
    retry_at: float | None = None
    meta: dict = field(default_factory=dict)

    @property
    def is_cached(self) -> bool:
        return self.status != STATUS_LIVE

    @property
    def is_stale(self) -> bool:
        return self.status == STATUS_STALE


def _result_from_cache(location, entry, status, reason=None, retry_at=None):
    return WeatherResult(
        location=location,
        payload=entry.payload,
        status=status,
        fetched_at=entry.fetched_at,
        age_seconds=entry.age_seconds,
        fallback_reason=reason,
        retry_at=retry_at,
    )


def _wait_for_leader(slug, units, baseline_fetched_at, lock):
    """Poll for a result newer than `baseline_fetched_at`.

    Returns the leader's entry, or None if it did not arrive in time or the
    leader failed. Exits early when the lock disappears, so a failed leader
    does not make every follower wait out the full timeout.
    """
    deadline = time.monotonic() + settings.WEATHER_COALESCE_WAIT

    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL)

        entry = weather_cache.read(slug, units)
        if entry is not None and entry.fetched_at > baseline_fetched_at:
            return entry

        # Lock gone means the leader finished. Either it wrote a result (caught
        # above on the next read) or it failed - no point waiting further.
        if django_cache.get(lock) is None:
            entry = weather_cache.read(slug, units)
            if entry is not None and entry.fetched_at > baseline_fetched_at:
                return entry
            return None

    return None


def _degrade(location, cached, reason, retry_at=None):
    """Serve stale data if we have it, otherwise raise a clean failure."""
    if cached is not None:
        metrics.increment("served_stale_fallback")
        logger.info(
            "stale_fallback location=%s reason=%s age=%ss",
            location.slug,
            reason,
            cached.age_seconds,
        )
        return _result_from_cache(
            location, cached, STATUS_STALE, reason=reason, retry_at=retry_at
        )

    metrics.increment("served_error_no_fallback")
    logger.warning(
        "no_data_available location=%s reason=%s", location.slug, reason
    )
    raise NoDataAvailable(reason, retry_at=retry_at)


def _fetch_and_store(location, units, cached):
    """Leader path: one upstream call, then cache and return it."""
    metrics.increment("upstream_request")
    logger.info(
        "upstream_fetch location=%s lat=%s lon=%s",
        location.slug,
        location.latitude,
        location.longitude,
    )

    try:
        raw = get_client().fetch_weather(location.latitude, location.longitude, units)
    except UpstreamRateLimited as exc:
        metrics.increment("upstream_rate_limited")
        logger.warning(
            "upstream_rate_limited location=%s reset_at=%s", location.slug, exc.reset_at
        )
        return _degrade(location, cached, REASON_RATE_LIMITED, retry_at=exc.reset_at)
    except (UpstreamUnavailable, UpstreamMisconfigured) as exc:
        metrics.increment("upstream_unavailable")
        reason = getattr(exc, "reason", "misconfigured")
        quota.handle_upstream_failure(reason)
        logger.warning("upstream_unavailable location=%s reason=%s", location.slug, reason)
        return _degrade(location, cached, REASON_UPSTREAM_UNAVAILABLE)

    payload = normalize_upstream(raw, units=units)
    entry = weather_cache.write(location.slug, units, payload)

    metrics.increment("upstream_success")
    logger.info("upstream_success location=%s cached_for=%ss", location.slug, settings.WEATHER_STALE_TTL)

    return WeatherResult(
        location=location,
        payload=payload,
        status=STATUS_LIVE,
        fetched_at=entry.fetched_at,
        age_seconds=0,
    )


def get_weather(raw_location: str, units: str = "metric") -> WeatherResult:
    """Return weather for a Kenyan location, from cache wherever possible.

    Raises locations.normalize.InvalidLocation for malformed input,
    locations.selectors.LocationNotFound for unknown places, and
    NoDataAvailable when upstream fails with no cached fallback.
    """
    location = resolve_location(raw_location)
    slug = location.slug

    # --- 1. Fresh cache: the common case, and no upstream contact at all ---
    cached = weather_cache.read(slug, units)
    if cached is not None and cached.is_fresh:
        metrics.increment("cache_hit_fresh")
        logger.debug("cache_hit_fresh location=%s age=%ss", slug, cached.age_seconds)
        return _result_from_cache(location, cached, STATUS_CACHED)

    if cached is not None:
        metrics.increment("cache_hit_stale")
        logger.debug("cache_stale location=%s age=%ss", slug, cached.age_seconds)
    else:
        metrics.increment("cache_miss")
        logger.debug("cache_miss location=%s", slug)

    # --- 2. Rate-limit gate: never call an upstream we know is closed -----
    allowed, blocked_reason = quota.upstream_allowed()
    if not allowed:
        metrics.increment("breaker_short_circuit")
        state = quota.breaker_state() or {}
        logger.info("breaker_short_circuit location=%s reason=%s", slug, blocked_reason)
        reason = (
            REASON_RATE_LIMITED
            if blocked_reason == quota.REASON_RATE_LIMITED
            else REASON_QUOTA_RESERVE
            if blocked_reason == quota.REASON_QUOTA_RESERVE
            else REASON_UPSTREAM_UNAVAILABLE
        )
        return _degrade(location, cached, reason, retry_at=state.get("reset_at"))

    # --- 3. Single-flight: one upstream call per location, per window -----
    baseline = cached.fetched_at if cached is not None else 0.0
    lock = weather_cache.lock_key(slug, units)
    token = uuid.uuid4().hex

    # cache.add() is atomic (Redis SET NX EX): exactly one caller wins.
    is_leader = django_cache.add(lock, token, settings.WEATHER_LOCK_TTL)

    if is_leader:
        metrics.increment("coalesce_leader")
        try:
            return _fetch_and_store(location, units, cached)
        finally:
            # Release only our own lock. Without the token check, a leader that
            # overran WEATHER_LOCK_TTL could delete a *successor's* lock and
            # let a second upstream request through.
            if django_cache.get(lock) == token:
                django_cache.delete(lock)

    # Follower: someone else is already fetching this exact location.
    logger.debug("coalesce_follower location=%s waiting", slug)
    entry = _wait_for_leader(slug, units, baseline, lock)

    if entry is not None:
        metrics.increment("coalesce_follower_served")
        logger.info("coalesce_follower_served location=%s", slug)
        return _result_from_cache(location, entry, STATUS_CACHED)

    # The leader failed or was too slow. Degrade rather than launching a
    # second upstream request, which is exactly what coalescing exists to stop.
    metrics.increment("coalesce_follower_timeout")
    logger.info("coalesce_follower_timeout location=%s", slug)
    return _degrade(location, cached, REASON_UPSTREAM_UNAVAILABLE)


__all__ = [
    "get_weather",
    "WeatherResult",
    "NoDataAvailable",
    "LocationNotFound",
    "STATUS_LIVE",
    "STATUS_CACHED",
    "STATUS_STALE",
]
