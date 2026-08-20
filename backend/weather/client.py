"""HTTP client for the Weather-AI API.

Scope: this module knows how to make ONE authenticated request and classify the
outcome. It does not cache, coalesce, or decide about fallbacks - that is
weather.service. Keeping transport separate from policy is what lets the whole
caching layer be tested without a network.

Security: the API key is read from settings (env-sourced) and attached as an
Authorization header. It is never logged, never returned to a client and never
included in an exception message. Log lines record the path, coordinates and
status code only.

Retries: there are deliberately NONE. Weather-AI's rate limit is a monthly
quota, so a retry after a 429 cannot succeed and only burns budget; and a retry
after a 5xx multiplies load on an already-struggling upstream. Backoff is
handled once, centrally, by weather.quota's circuit breaker.
"""

import logging

import requests
from django.conf import settings

from weather.exceptions import (
    UpstreamMisconfigured,
    UpstreamRateLimited,
    UpstreamUnavailable,
)
from weather import quota

logger = logging.getLogger(__name__)

WEATHER_PATH = "/v1/weather"


class WeatherAIClient:
    """Thin wrapper over GET /v1/weather."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key if api_key is not None else settings.WEATHER_AI_API_KEY
        self.base_url = (base_url or settings.WEATHER_AI_BASE_URL).rstrip("/")

        self._session = requests.Session()
        # Explicitly disable urllib3's automatic retries. See module docstring.
        adapter = requests.adapters.HTTPAdapter(max_retries=0)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def fetch_weather(self, latitude, longitude, units: str = "metric") -> dict:
        """Fetch current conditions for a coordinate pair.

        Returns the raw decoded JSON body. Raises UpstreamRateLimited,
        UpstreamUnavailable or UpstreamMisconfigured - never a bare exception
        that could carry credentials into a traceback.
        """
        if not self.api_key:
            # Fail as a configuration error rather than sending an unauthorised
            # request that would waste a round trip and log a confusing 401.
            raise UpstreamMisconfigured("WEATHER_AI_API_KEY is not configured.")

        params = {
            "lat": f"{float(latitude):.4f}",
            "lon": f"{float(longitude):.4f}",
            # We only render current conditions. days=1 is the smallest valid
            # value and keeps the response small.
            "days": 1,
            # Documented default is ai=true, which spends the separate (much
            # smaller) AI quota. We do not use the AI summary.
            "ai": "true" if settings.WEATHER_INCLUDE_AI else "false",
            "units": units,
        }

        url = f"{self.base_url}{WEATHER_PATH}"
        try:
            response = self._session.get(
                url,
                params=params,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json",
                    "User-Agent": "Anga/1.0 (+https://github.com/anga-weather)",
                },
                timeout=(settings.WEATHER_CONNECT_TIMEOUT, settings.WEATHER_READ_TIMEOUT),
            )
        except requests.Timeout as exc:
            logger.warning("upstream_timeout path=%s lat=%s lon=%s", WEATHER_PATH, latitude, longitude)
            raise UpstreamUnavailable("timeout") from exc
        except requests.RequestException as exc:
            # Deliberately does not interpolate `exc`, which can contain the
            # full request URL. The class name is enough to triage.
            logger.warning(
                "upstream_connection_error path=%s error=%s",
                WEATHER_PATH,
                type(exc).__name__,
            )
            raise UpstreamUnavailable("connection_error") from exc

        # Record quota state from every response, success or failure - the
        # headers are free information that saves us calling /v1/usage.
        quota.record_headers(response.headers)

        logger.info(
            "upstream_response path=%s lat=%s lon=%s status=%s remaining=%s",
            WEATHER_PATH,
            latitude,
            longitude,
            response.status_code,
            quota.parse_rate_limit_headers(response.headers).get("remaining"),
        )

        return self._handle_response(response)

    def _handle_response(self, response) -> dict:
        status = response.status_code

        if status == 429:
            quota.handle_rate_limited(response.headers)
            parsed = quota.parse_rate_limit_headers(response.headers)
            raise UpstreamRateLimited(
                reset_at=parsed.get("reset_at"), remaining=parsed.get("remaining")
            )

        if status in (401, 403):
            # An operator problem: bad key, revoked key, or a plan that does not
            # include this endpoint. Logged loudly, reported to users as a
            # generic outage so we never hint at credential state.
            logger.error(
                "upstream_auth_failure status=%s - check WEATHER_AI_API_KEY and plan", status
            )
            raise UpstreamMisconfigured(f"upstream rejected credentials ({status})")

        if status >= 500:
            raise UpstreamUnavailable(f"http_{status}")

        if status >= 400:
            # 400 means we sent bad coordinates - a bug on our side, not a
            # transient outage, so it is logged as an error.
            logger.error("upstream_bad_request status=%s", status)
            raise UpstreamUnavailable(f"http_{status}")

        try:
            payload = response.json()
        except ValueError as exc:
            logger.error("upstream_invalid_json status=%s", status)
            raise UpstreamUnavailable("invalid_json") from exc

        if not isinstance(payload, dict):
            logger.error("upstream_unexpected_payload type=%s", type(payload).__name__)
            raise UpstreamUnavailable("unexpected_payload")

        return payload


# Module-level client so the underlying connection pool is reused across
# requests instead of reconnecting to Weather-AI on every cache miss.
_client: WeatherAIClient | None = None


def get_client() -> WeatherAIClient:
    global _client
    if _client is None:
        _client = WeatherAIClient()
    return _client


def reset_client() -> None:
    """Drop the cached client. Used by tests that patch settings."""
    global _client
    _client = None
