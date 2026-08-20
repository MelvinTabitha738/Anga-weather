"""Application-level response shapes.

The frontend never sees Weather-AI's raw JSON. It sees this contract, which is
stable regardless of upstream changes and always carries honest freshness
metadata alongside the data.
"""

from datetime import datetime, timezone

from django.conf import settings
from rest_framework import serializers

from locations.serializers import LocationSerializer


def _iso(epoch: float | None) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


class WeatherResponseSerializer(serializers.Serializer):
    """Serialises a service.WeatherResult.

    Three top-level sections keep concerns separate: what place this is, what
    the weather is, and how much to trust its freshness.
    """

    def to_representation(self, result):
        return {
            "location": LocationSerializer(result.location).data,
            "weather": result.payload,
            "meta": {
                # "live" | "cached" | "stale"
                "status": result.status,
                "is_cached": result.is_cached,
                "is_stale": result.is_stale,
                # When Weather-AI actually observed/returned this data.
                "fetched_at": _iso(result.fetched_at),
                "age_seconds": result.age_seconds,
                # When this entry stops counting as fresh.
                "expires_at": _iso(result.fetched_at + settings.WEATHER_CACHE_TTL),
                "ttl_seconds": settings.WEATHER_CACHE_TTL,
                # Populated only when serving stale data, so the UI can explain
                # itself rather than silently showing old numbers.
                "fallback_reason": result.fallback_reason,
                "retry_at": _iso(result.retry_at),
            },
        }
