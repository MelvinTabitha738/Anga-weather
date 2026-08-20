"""HTTP contract tests: status codes, response shape, and error hygiene."""

import time
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from rest_framework.throttling import ScopedRateThrottle

from weather import cache as weather_cache
from weather import quota
from weather.exceptions import UpstreamRateLimited, UpstreamUnavailable
from weather.tests.base import FakeClient, WeatherTestCase


class WeatherEndpointTests(WeatherTestCase):
    def _get(self, **params):
        return self.client.get(reverse("weather"), params)

    def test_successful_response_shape(self):
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            response = self._get(location="Nairobi")

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(body["location"]["slug"], "nairobi")
        self.assertEqual(body["location"]["label"], "Nairobi")

        current = body["current"]
        self.assertEqual(current["temperature"], 24.5)
        self.assertEqual(current["wind_speed"], 11.2)
        self.assertEqual(current["wind_direction"], "SE")
        self.assertEqual(current["condition"], "Partly cloudy")
        # The shared vocabulary the frontend switches its backdrop on.
        self.assertEqual(current["condition_group"], "partly_cloudy")
        self.assertIn("condition_intensity", current)
        self.assertIs(current["is_day"], True)

        meta = body["meta"]
        self.assertEqual(meta["status"], "live")
        self.assertFalse(meta["is_cached"])
        self.assertFalse(meta["is_stale"])
        self.assertIsNotNone(meta["fetched_at"])
        self.assertIsNone(meta["fallback_reason"])
        self.assertEqual(meta["ttl_seconds"], 1800)

    def test_response_never_contains_fields_upstream_does_not_return(self):
        """Humidity, feels-like, pressure and visibility are simply not in the
        Weather-AI response, so they must not appear in ours."""
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            body = self._get(location="Nairobi").json()

        for absent in ("humidity", "feels_like", "pressure", "visibility", "uv_index"):
            self.assertNotIn(absent, body["current"])

    def test_forecast_is_included_in_the_same_response(self):
        """The forecast rides along in the cached upstream response, so it
        costs no extra quota."""
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            body = self._get(location="Nairobi").json()

        self.assertEqual(fake.calls, 1, "forecast must not need a second call")

        self.assertTrue(body["hourly"])
        first_hour = body["hourly"][0]
        for key in ("time", "temperature", "precipitation", "condition_group"):
            self.assertIn(key, first_hour)

        self.assertTrue(body["daily"])
        first_day = body["daily"][0]
        for key in ("date", "temp_max", "temp_min", "condition_group"):
            self.assertIn(key, first_day)

    def test_ai_summary_is_present_as_a_key_but_null(self):
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            body = self._get(location="Nairobi").json()
        self.assertIn("ai_summary", body)
        self.assertIsNone(body["ai_summary"])

    def test_second_request_is_served_from_cache(self):
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            self._get(location="Nairobi")
            response = self._get(location="Nairobi")

        self.assertEqual(fake.calls, 1)
        meta = response.json()["meta"]
        self.assertEqual(meta["status"], "cached")
        self.assertTrue(meta["is_cached"])
        self.assertFalse(meta["is_stale"])

    def test_cache_control_header_reflects_remaining_ttl(self):
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            response = self._get(location="Nairobi")
        self.assertIn("max-age=", response["Cache-Control"])

    def test_missing_location_is_a_400(self):
        response = self._get()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_location")

    def test_overlong_location_is_rejected(self):
        response = self._get(location="n" * 200)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_location")

    def test_non_kenyan_location_is_a_404(self):
        response = self._get(location="Kampala")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "unknown_location")

    def test_invalid_units_rejected(self):
        response = self._get(location="Nairobi", units="kelvin")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_units")

    @override_settings(WEATHER_CACHE_TTL=60, WEATHER_STALE_TTL=86400)
    def test_stale_fallback_is_labelled_in_the_response(self):
        weather_cache.write(
            "nairobi", "metric", {"temperature": 20.0}, fetched_at=time.time() - 900
        )
        fake = FakeClient(error=UpstreamRateLimited(reset_at=time.time() + 600))

        with mock.patch("weather.service.get_client", return_value=fake):
            response = self._get(location="Nairobi")

        self.assertEqual(response.status_code, 200, "stale data is still a success")
        meta = response.json()["meta"]
        self.assertEqual(meta["status"], "stale")
        self.assertTrue(meta["is_stale"])
        self.assertEqual(meta["fallback_reason"], "rate_limited")
        self.assertGreater(meta["age_seconds"], 60)

    def test_upstream_failure_without_cache_returns_503_not_429(self):
        """Our 429 means the CLIENT is too fast; upstream problems are 503."""
        fake = FakeClient(error=UpstreamRateLimited(reset_at=time.time() + 600))
        with mock.patch("weather.service.get_client", return_value=fake):
            response = self._get(location="Nairobi")

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["error"]["code"], "rate_limited")
        self.assertIn("Retry-After", response)

    def test_error_bodies_never_leak_internals(self):
        fake = FakeClient(error=UpstreamUnavailable("http_503"))
        with mock.patch("weather.service.get_client", return_value=fake):
            response = self._get(location="Nairobi")

        raw = response.content.decode().lower()
        for leak in ["traceback", "weather-ai.co", "bearer", "wai_", "api_key", "authorization"]:
            self.assertNotIn(leak, raw, f"error body leaked {leak!r}")


class ThrottleTests(WeatherTestCase):
    """Our own throttle protects the backend, and therefore the upstream quota.

    DRF binds SimpleRateThrottle.THROTTLE_RATES as a class attribute at import
    time, so override_settings(REST_FRAMEWORK=...) does not reach it. Patching
    the dict in place is the reliable way to exercise throttling.
    """

    def test_our_own_throttle_returns_a_distinct_code(self):
        fake = FakeClient()
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"weather": "3/min"}):
            with mock.patch("weather.service.get_client", return_value=fake):
                for _ in range(3):
                    response = self.client.get(reverse("weather"), {"location": "Nairobi"})
                    self.assertEqual(response.status_code, 200)
                response = self.client.get(reverse("weather"), {"location": "Nairobi"})

        self.assertEqual(response.status_code, 429)
        body = response.json()
        # Distinct from the upstream "rate_limited" code, so the UI can tell
        # "you are going too fast" from "Weather-AI is out of quota".
        self.assertEqual(body["error"]["code"], "too_many_requests")

    def test_throttled_requests_never_reach_upstream(self):
        fake = FakeClient()
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"weather": "2/min"}):
            with mock.patch("weather.service.get_client", return_value=fake):
                for _ in range(6):
                    self.client.get(reverse("weather"), {"location": "Nairobi"})

        # Two requests got through; the first fetched, the second hit cache.
        # The four throttled ones must not have spent any quota.
        self.assertEqual(fake.calls, 1)


class LocationSearchEndpointTests(WeatherTestCase):
    def test_search_returns_ranked_matches(self):
        response = self.client.get(reverse("location-search"), {"q": "nai"})
        self.assertEqual(response.status_code, 200)
        slugs = [r["slug"] for r in response.json()["results"]]
        self.assertIn("nairobi", slugs)

    def test_search_never_calls_upstream(self):
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            self.client.get(reverse("location-search"), {"q": "mom"})
        self.assertEqual(fake.calls, 0, "typing must not spend upstream quota")

    def test_empty_query_returns_prominent_suggestions(self):
        response = self.client.get(reverse("location-search"))
        self.assertGreater(response.json()["count"], 0)

    def test_malformed_query_returns_empty_not_error(self):
        response = self.client.get(reverse("location-search"), {"q": "../../etc/passwd"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 0)


class StatsEndpointTests(WeatherTestCase):
    def test_stats_report_cache_activity_without_secrets(self):
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            self.client.get(reverse("weather"), {"location": "Nairobi"})
            self.client.get(reverse("weather"), {"location": "Nairobi"})

        response = self.client.get(reverse("meta-stats"))
        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(body["counters"]["cache_miss"], 1)
        self.assertEqual(body["counters"]["cache_hit_fresh"], 1)
        self.assertEqual(body["counters"]["upstream_success"], 1)
        self.assertEqual(body["config"]["fresh_ttl_seconds"], 1800)

        raw = response.content.decode().lower()
        self.assertNotIn("wai_", raw)
        self.assertNotIn("secret", raw)

    def test_derived_totals_count_each_request_once(self):
        """Regression: a coalescing follower increments cache_miss AND
        coalesce_follower_served, so summing both inflated the request count
        and reported more upstream calls avoided than requests received."""
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            for _ in range(4):
                self.client.get(reverse("weather"), {"location": "Nairobi"})

        derived = self.client.get(reverse("meta-stats")).json()["derived"]

        self.assertEqual(derived["requests_served"], 4)
        self.assertEqual(derived["upstream_requests_made"], 1)
        self.assertEqual(derived["upstream_requests_avoided"], 3)
        self.assertLessEqual(derived["upstream_requests_avoided"], derived["requests_served"])
        self.assertEqual(derived["cache_hit_rate"], 0.75)

    def test_stats_report_breaker_state(self):
        quota.open_breaker(quota.REASON_RATE_LIMITED, seconds=120)
        body = self.client.get(reverse("meta-stats")).json()
        self.assertTrue(body["breaker"]["open"])
        self.assertEqual(body["breaker"]["reason"], "rate_limited")


class HealthTests(WeatherTestCase):
    def test_health_is_ok(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
