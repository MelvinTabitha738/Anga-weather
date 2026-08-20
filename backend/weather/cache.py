"""Weather cache keys and the fresh/stale envelope.

Design note - one key, two lifetimes:

A naive implementation keeps a "fresh" key on a short TTL and a separate
"stale" copy on a long one, then has to keep the two in sync. Instead we store
a single entry with the LONG retention (WEATHER_STALE_TTL) and stamp it with
`fetched_at`. Freshness is then derived from the age of that timestamp:

    age < WEATHER_CACHE_TTL                     -> FRESH  (serve as-is)
    WEATHER_CACHE_TTL <= age < WEATHER_STALE_TTL -> STALE  (fallback only)
    age >= WEATHER_STALE_TTL                     -> gone   (cache expired it)

One key means one write, no divergence between the two copies, and the exact
data age is always available to report honestly to the client.

Cache key format:

    anga:weather:v1:{units}:{slug}      (KEY_PREFIX "anga:" added by Django)

* `v1` is a payload schema version. Changing the response shape means bumping
  it, which retires every old entry without a manual flush.
* `units` is part of the key because the upstream response differs by unit.
* `slug` is the canonical, validated output of normalize_location() - never raw
  user input, so arbitrary strings can never reach the cache backend.
"""

import time
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

CACHE_VERSION = "v1"


def weather_cache_key(slug: str, units: str) -> str:
    return f"weather:{CACHE_VERSION}:{units}:{slug}"


def lock_key(slug: str, units: str) -> str:
    """Key for the single-flight lock guarding one location's upstream fetch."""
    return f"lock:weather:{CACHE_VERSION}:{units}:{slug}"


@dataclass(frozen=True)
class CachedWeather:
    """A cached upstream payload plus the age metadata we report to clients."""

    payload: dict
    fetched_at: float

    @property
    def age_seconds(self) -> int:
        return max(0, int(time.time() - self.fetched_at))

    @property
    def is_fresh(self) -> bool:
        return self.age_seconds < settings.WEATHER_CACHE_TTL

    @property
    def is_stale(self) -> bool:
        return not self.is_fresh

    @property
    def expires_at(self) -> float:
        """When this entry stops being fresh."""
        return self.fetched_at + settings.WEATHER_CACHE_TTL


def read(slug: str, units: str) -> CachedWeather | None:
    """Return the cached entry for a location, fresh or stale, or None."""
    entry = cache.get(weather_cache_key(slug, units))
    if not entry or "payload" not in entry:
        return None
    return CachedWeather(
        payload=entry["payload"],
        fetched_at=float(entry.get("fetched_at", 0)),
    )


def write(slug: str, units: str, payload: dict, fetched_at: float | None = None) -> CachedWeather:
    """Store a successful upstream payload for the full stale retention window."""
    fetched_at = time.time() if fetched_at is None else fetched_at
    entry = {"payload": payload, "fetched_at": fetched_at}

    # Retention is the STALE ttl: the entry must outlive its freshness so it
    # remains available as a fallback when upstream fails.
    cache.set(
        weather_cache_key(slug, units),
        entry,
        timeout=settings.WEATHER_STALE_TTL,
    )
    return CachedWeather(payload=payload, fetched_at=fetched_at)


def invalidate(slug: str, units: str) -> None:
    """Drop a cached location. Used by tests; no public endpoint exposes this."""
    cache.delete(weather_cache_key(slug, units))
