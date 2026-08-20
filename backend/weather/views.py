"""HTTP layer for the weather API.

Views stay thin on purpose: validate input, call the service, map domain
exceptions onto status codes. All caching, coalescing and degradation policy
lives in weather.service, which is why it can be tested without HTTP.

This is an application API, not a proxy. Nothing here forwards arbitrary
parameters to Weather-AI, so no client can use us to spend our quota on
locations or options we did not choose to support.
"""

import logging
import time

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from locations.normalize import InvalidLocation
from locations.selectors import LocationNotFound
from weather import metrics, quota
from weather.exceptions import error_response
from weather.serializers import WeatherResponseSerializer
from weather.service import NoDataAvailable, get_weather

logger = logging.getLogger(__name__)

SUPPORTED_UNITS = {"metric", "imperial"}


class WeatherView(APIView):
    """GET /api/weather/?location=nairobi&units=metric

    Returns current conditions for a Kenyan location, served from cache
    wherever possible. Always includes freshness metadata - the response never
    presents stale data as current.
    """

    throttle_scope = "weather"

    def get(self, request):
        raw_location = request.query_params.get("location", "")
        units = (request.query_params.get("units") or "metric").strip().lower()

        if units not in SUPPORTED_UNITS:
            return error_response(
                "invalid_units",
                "Units must be either 'metric' or 'imperial'.",
                status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = get_weather(raw_location, units=units)

        except InvalidLocation as exc:
            metrics.increment("invalid_location")
            # The message here is written for humans and contains only what the
            # user typed, never internal detail.
            return error_response(
                "invalid_location", str(exc), status.HTTP_400_BAD_REQUEST
            )

        except LocationNotFound:
            metrics.increment("unknown_location")
            return error_response(
                "unknown_location",
                "We don't have weather for that place yet. Try a Kenyan county or town.",
                status.HTTP_404_NOT_FOUND,
            )

        except NoDataAvailable as exc:
            # Upstream failed and we have nothing cached. 503, not 429: our own
            # throttle returns 429, and conflating the two would leave the
            # frontend unable to tell "you are too fast" from "upstream is down".
            code = (
                "rate_limited"
                if exc.reason in ("rate_limited", "quota_reserve")
                else "weather_unavailable"
            )
            retry_after = None
            if exc.retry_at:
                retry_after = max(1, int(exc.retry_at - time.time()))

            response = error_response(
                code,
                "Weather information is temporarily unavailable. Please try again shortly.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
                retry_after=retry_after,
            )
            if retry_after:
                response["Retry-After"] = str(retry_after)
            return response

        payload = WeatherResponseSerializer(result).data

        response = Response(payload)
        # Let browsers and any CDN reuse the response for the remaining life of
        # our server-side entry. Client caching is an optimisation on top of the
        # server cache, never a replacement for it.
        remaining_ttl = max(0, settings.WEATHER_CACHE_TTL - result.age_seconds)
        response["Cache-Control"] = f"public, max-age={remaining_ttl}"
        return response


class StatsView(APIView):
    """GET /api/meta/stats/

    Non-sensitive observability: cache counters, the current cache/upstream
    configuration, and the last observed Weather-AI quota. Exposed so the
    caching behaviour can be demonstrated without shell access.

    Contains no secrets - never the API key, and no user data.
    """

    throttle_scope = "meta"

    def get(self, request):
        counters = metrics.snapshot()

        # Exactly one of these three fires per incoming request, so summing
        # them gives the request count without double-counting. (Coalescing
        # counters must NOT be added here: a follower already incremented
        # cache_miss on its way in.)
        served = (
            counters["cache_hit_fresh"] + counters["cache_hit_stale"] + counters["cache_miss"]
        )
        upstream = counters["upstream_request"]
        avoided = max(0, served - upstream)

        # The number that actually matters: the share of user requests that did
        # not become a Weather-AI request.
        hit_rate = round(avoided / served, 4) if served else None

        quota_state = quota.get_quota()
        breaker = quota.breaker_state()

        return Response(
            {
                "counters": counters,
                "derived": {
                    "requests_served": served,
                    "upstream_requests_made": upstream,
                    "upstream_requests_avoided": avoided,
                    "cache_hit_rate": hit_rate,
                },
                "config": {
                    "cache_backend": settings.CACHE_BACKEND_NAME,
                    "fresh_ttl_seconds": settings.WEATHER_CACHE_TTL,
                    "stale_ttl_seconds": settings.WEATHER_STALE_TTL,
                    "coalesce_wait_seconds": settings.WEATHER_COALESCE_WAIT,
                    "quota_reserve": settings.WEATHER_QUOTA_RESERVE,
                },
                "upstream_quota": {
                    "limit": quota_state.get("limit"),
                    "remaining": quota_state.get("remaining"),
                    "reset_at": quota_state.get("reset_at"),
                    "observed_at": quota_state.get("observed_at"),
                },
                "breaker": {
                    "open": breaker is not None,
                    "reason": (breaker or {}).get("reason"),
                    "reset_at": (breaker or {}).get("reset_at"),
                },
            }
        )


class HealthView(APIView):
    """GET /healthz - liveness probe for the platform. Never throttled."""

    throttle_classes = []

    def get(self, request):
        return Response({"status": "ok", "service": "anga"})
