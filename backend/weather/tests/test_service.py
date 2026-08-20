"""The core behavioural contract: cache, fallback, and honest freshness.

These map one-to-one onto the request-flow scenarios in the README.
"""

import time
from unittest import mock

from django.test import override_settings

from locations.normalize import InvalidLocation
from locations.selectors import LocationNotFound
from weather import cache as weather_cache
from weather import quota
from weather.exceptions import UpstreamRateLimited, UpstreamUnavailable
from weather.service import (
    STATUS_CACHED,
    STATUS_LIVE,
    STATUS_STALE,
    NoDataAvailable,
    get_weather,
)
from weather.tests.base import FakeClient, WeatherTestCase


class LocationResolutionTests(WeatherTestCase):
    def test_rejects_malformed_input_before_touching_upstream(self):
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            for bad in ["", "   ", "x" * 100, "DROP TABLE locations;"]:
                with self.assertRaises(InvalidLocation):
                    get_weather(bad)
        self.assertEqual(fake.calls, 0, "invalid input must never reach Weather-AI")

    def test_unknown_but_well_formed_location_is_not_found(self):
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            with self.assertRaises(LocationNotFound):
                get_weather("Kampala")
        self.assertEqual(fake.calls, 0)

    def test_case_and_whitespace_variants_share_one_cache_entry(self):
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            for variant in ["Nairobi", "nairobi", "  NAIROBI  ", "NaIrObI"]:
                get_weather(variant)
        self.assertEqual(
            fake.calls, 1, "normalisation must collapse variants onto one cache key"
        )

    def test_alias_resolves_to_the_same_cache_entry(self):
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            get_weather("Nairobi")
            result = get_weather("Nairobi City")
        self.assertEqual(fake.calls, 1)
        self.assertEqual(result.location.slug, "nairobi")


class CacheBehaviourTests(WeatherTestCase):
    """Scenarios A, B and D from the README."""

    def test_scenario_b_cache_miss_calls_upstream_once_and_stores(self):
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            result = get_weather("Nairobi")

        self.assertEqual(result.status, STATUS_LIVE)
        self.assertFalse(result.is_cached)
        self.assertFalse(result.is_stale)
        self.assertEqual(result.age_seconds, 0)
        self.assertEqual(fake.calls, 1)
        self.assertIsNotNone(weather_cache.read("nairobi", "metric"))

    def test_scenario_a_fresh_cache_hit_does_not_call_upstream(self):
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            get_weather("Nairobi")
            second = get_weather("Nairobi")
            third = get_weather("Nairobi")

        self.assertEqual(fake.calls, 1, "three requests, one upstream call")
        self.assertEqual(second.status, STATUS_CACHED)
        self.assertTrue(third.is_cached)
        self.assertFalse(third.is_stale)

    @override_settings(WEATHER_CACHE_TTL=60)
    def test_scenario_d_expired_cache_refetches_and_replaces(self):
        # Seed an entry that aged past the fresh TTL.
        weather_cache.write(
            "nairobi", "metric", {"temperature": 10.0}, fetched_at=time.time() - 600
        )
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            result = get_weather("Nairobi")

        self.assertEqual(fake.calls, 1)
        self.assertEqual(result.status, STATUS_LIVE)
        self.assertEqual(result.payload["temperature"], 24.5, "cache must be replaced")

    @override_settings(WEATHER_CACHE_TTL=60)
    def test_units_are_cached_separately(self):
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            get_weather("Nairobi", units="metric")
            get_weather("Nairobi", units="imperial")
        self.assertEqual(fake.calls, 2, "metric and imperial are different responses")


class StaleFallbackTests(WeatherTestCase):
    """Scenarios E and F: upstream fails, with and without a fallback."""

    def _seed_stale(self, age_seconds=3600):
        return weather_cache.write(
            "nairobi",
            "metric",
            {"temperature": 21.0, "condition": "Cloudy"},
            fetched_at=time.time() - age_seconds,
        )

    @override_settings(WEATHER_CACHE_TTL=60, WEATHER_STALE_TTL=86400)
    def test_scenario_e_429_serves_stale_and_labels_it(self):
        self._seed_stale(age_seconds=900)
        fake = FakeClient(error=UpstreamRateLimited(reset_at=time.time() + 3600))

        with mock.patch("weather.service.get_client", return_value=fake):
            result = get_weather("Nairobi")

        self.assertEqual(result.status, STATUS_STALE)
        self.assertTrue(result.is_stale)
        self.assertEqual(result.fallback_reason, "rate_limited")
        self.assertGreater(result.age_seconds, 60)
        self.assertEqual(result.payload["temperature"], 21.0)
        self.assertIsNotNone(result.retry_at, "client needs a retry hint")

    @override_settings(WEATHER_CACHE_TTL=60, WEATHER_STALE_TTL=86400)
    def test_scenario_e_5xx_serves_stale(self):
        self._seed_stale()
        fake = FakeClient(error=UpstreamUnavailable("http_503"))

        with mock.patch("weather.service.get_client", return_value=fake):
            result = get_weather("Nairobi")

        self.assertEqual(result.status, STATUS_STALE)
        self.assertEqual(result.fallback_reason, "upstream_unavailable")

    @override_settings(WEATHER_CACHE_TTL=60, WEATHER_STALE_TTL=86400)
    def test_timeout_serves_stale(self):
        self._seed_stale()
        fake = FakeClient(error=UpstreamUnavailable("timeout"))

        with mock.patch("weather.service.get_client", return_value=fake):
            result = get_weather("Nairobi")

        self.assertEqual(result.status, STATUS_STALE)

    def test_scenario_f_no_cache_and_upstream_down_raises_cleanly(self):
        fake = FakeClient(error=UpstreamUnavailable("http_503"))
        with mock.patch("weather.service.get_client", return_value=fake):
            with self.assertRaises(NoDataAvailable) as ctx:
                get_weather("Nairobi")
        self.assertEqual(ctx.exception.reason, "upstream_unavailable")

    @override_settings(WEATHER_STALE_TTL=300)
    def test_data_older_than_stale_window_is_not_served(self):
        # Written with an age beyond the retention window; the cache backend
        # would have evicted it, so simulate that by writing then deleting.
        self._seed_stale(age_seconds=99999)
        weather_cache.invalidate("nairobi", "metric")

        fake = FakeClient(error=UpstreamUnavailable("http_503"))
        with mock.patch("weather.service.get_client", return_value=fake):
            with self.assertRaises(NoDataAvailable):
                get_weather("Nairobi")


class RateLimitBreakerTests(WeatherTestCase):
    """Once upstream says 429, we stop calling it entirely."""

    @override_settings(WEATHER_CACHE_TTL=60, WEATHER_STALE_TTL=86400)
    def test_breaker_prevents_further_upstream_calls(self):
        weather_cache.write(
            "nairobi", "metric", {"temperature": 21.0}, fetched_at=time.time() - 900
        )
        quota.open_breaker(quota.REASON_RATE_LIMITED, seconds=300)

        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            result = get_weather("Nairobi")

        self.assertEqual(fake.calls, 0, "breaker must short-circuit before the network")
        self.assertEqual(result.status, STATUS_STALE)
        self.assertEqual(result.fallback_reason, "rate_limited")

    def test_breaker_open_with_no_cache_raises_rather_than_retrying(self):
        quota.open_breaker(quota.REASON_RATE_LIMITED, seconds=300)
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            with self.assertRaises(NoDataAvailable):
                get_weather("Nairobi")
        self.assertEqual(fake.calls, 0)

    @override_settings(WEATHER_QUOTA_RESERVE=25)
    def test_quota_reserve_suspends_upstream_before_the_budget_is_drained(self):
        quota.record_headers(
            {"X-RateLimit-Limit": "1000", "X-RateLimit-Remaining": "10",
             "X-RateLimit-Reset": str(int(time.time()) + 86400)}
        )
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            with self.assertRaises(NoDataAvailable) as ctx:
                get_weather("Nairobi")

        self.assertEqual(fake.calls, 0)
        self.assertEqual(ctx.exception.reason, "quota_reserve")

    @override_settings(WEATHER_QUOTA_RESERVE=25)
    def test_healthy_remaining_quota_allows_upstream(self):
        quota.record_headers(
            {"X-RateLimit-Limit": "1000", "X-RateLimit-Remaining": "800"}
        )
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            result = get_weather("Nairobi")
        self.assertEqual(fake.calls, 1)
        self.assertEqual(result.status, STATUS_LIVE)
