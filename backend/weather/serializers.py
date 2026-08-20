"""Application-level response shapes.

The frontend never sees Weather-AI's raw JSON. It sees this contract, which is
stable regardless of upstream changes and always carries honest freshness
metadata alongside the data.

Sections are split by what they are, so a dashboard can render each
independently: where, now, the next hours, the next days, any prose, and how
much to trust the freshness.
"""

from datetime import datetime, timezone

from django.conf import settings
from rest_framework import serializers

from locations.serializers import LocationSerializer


def _iso(epoch: float | None) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


# Keys of the payload that belong to "current conditions" rather than forecast.
_CURRENT_FIELDS = (
    "temperature",
    "wind_speed",
    "wind_direction",
    "wind_direction_degrees",
    "precipitation_this_hour",
    "weather_code",
    "condition",
    "condition_group",
    "condition_intensity",
    "is_day",
    "observed_at",
    "units",
)


class WeatherResponseSerializer(serializers.Serializer):
    """Serialises a service.WeatherResult."""

    def to_representation(self, result):
        payload = result.payload or {}

        return {
            "location": LocationSerializer(result.location).data,
            # Present-moment conditions.
            "current": {key: payload.get(key) for key in _CURRENT_FIELDS},
            # Forecast, which arrived in the same cached upstream response and
            # therefore cost no additional quota.
            "hourly": payload.get("hourly") or [],
            "daily": payload.get("daily") or [],
            # Passed through from upstream untouched. Null on the free plan, in
            # which case the UI renders no insight section at all.
            "ai_summary": payload.get("ai_summary"),
            "meta": {
                # "live" | "cached" | "stale"
                "status": result.status,
                "is_cached": result.is_cached,
                "is_stale": result.is_stale,
                # When Weather-AI actually returned this data.
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
