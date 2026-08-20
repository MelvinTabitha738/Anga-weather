"""Lightweight counters for the cache/upstream lifecycle.

Deliberately cheap: counters live in the same cache as the weather data, so
they cost no extra infrastructure and are shared across workers when Redis is
configured. They are approximate - increments are not transactional - which is
fine for observability but means they should never drive control flow.

Exposed read-only via /api/meta/stats/ so the caching behaviour is observable
without shell access. Nothing here is sensitive.
"""

import logging
from django.core.cache import cache

logger = logging.getLogger(__name__)

PREFIX = "metrics:"

# Every counter the service can emit, so /api/meta/stats/ always returns a
# stable set of keys rather than only those that happen to have fired.
COUNTERS = (
    "cache_hit_fresh",
    "cache_hit_stale",
    "cache_miss",
    "coalesce_leader",
    "coalesce_follower_served",
    "coalesce_follower_timeout",
    "upstream_request",
    "usage_synced",
    "upstream_success",
    "upstream_rate_limited",
    "upstream_unavailable",
    "breaker_short_circuit",
    "served_stale_fallback",
    "served_error_no_fallback",
    "invalid_location",
    "unknown_location",
)


def increment(name: str, delta: int = 1) -> None:
    """Increment a counter, tolerating a cold cache and cache outages."""
    key = f"{PREFIX}{name}"
    try:
        cache.incr(key, delta)
    except ValueError:
        # Key does not exist yet. A concurrent writer may win this race and
        # lose a count; acceptable for approximate metrics.
        try:
            cache.set(key, delta, timeout=None)
        except Exception:  # pragma: no cover - cache backend down
            logger.debug("metrics: could not initialise counter %s", name)
    except Exception:  # pragma: no cover - cache backend down
        # Metrics must never break a weather response.
        logger.debug("metrics: could not increment %s", name)


def snapshot() -> dict[str, int]:
    """Return all counters, defaulting missing ones to zero."""
    keys = {name: f"{PREFIX}{name}" for name in COUNTERS}
    try:
        found = cache.get_many(list(keys.values()))
    except Exception:  # pragma: no cover - cache backend down
        found = {}
    return {name: int(found.get(key, 0) or 0) for name, key in keys.items()}


def reset() -> None:
    """Clear all counters. Used by tests and local experimentation."""
    try:
        cache.delete_many([f"{PREFIX}{name}" for name in COUNTERS])
    except Exception:  # pragma: no cover
        logger.debug("metrics: could not reset counters")
