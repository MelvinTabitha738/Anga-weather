"""Shared test scaffolding.

Every weather test needs the same three things: a clean cache (entries and the
circuit breaker leak between tests otherwise), a seeded gazetteer, and a fake
upstream. This module provides all three.
"""

import threading
import time

from django.core.cache import cache
from django.test import TestCase, TransactionTestCase

from locations.models import Location, LocationAlias
from weather import client as client_module
from weather import metrics
from weather.exceptions import UpstreamRateLimited, UpstreamUnavailable

# A minimal upstream body in the VERIFIED live Weather-AI shape. The full
# captured response lives at tests/fixtures/live_weather_response.json.
SAMPLE_UPSTREAM = {
    "lat": -1.2864,
    "lon": 36.8172,
    "units": "metric",
    "days": 7,
    "current": {
        "time": "2026-08-20T15:30",
        "interval": 900,
        "temperature": 24.5,
        "windspeed": 11.2,
        "winddirection": 130,
        "is_day": 1,
        "weathercode": 2,
    },
    "hourly": [
        {"time": "2026-08-20T15:00", "temp": 24.5, "precipitation": 0.0, "weathercode": 2},
        {"time": "2026-08-20T16:00", "temp": 24.1, "precipitation": 0.2, "weathercode": 51},
        {"time": "2026-08-20T17:00", "temp": 23.4, "precipitation": 1.1, "weathercode": 61},
    ],
    "daily": [
        {"date": "2026-08-20", "temp_max": 26.3, "temp_min": 15.0,
         "precipitation": 2.2, "weathercode": 51},
        {"date": "2026-08-21", "temp_max": 28.4, "temp_min": 14.1,
         "precipitation": 0.4, "weathercode": 2},
    ],
    "ai_summary": None,
}


def load_live_fixture():
    """The real captured response, for tests that assert against reality."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent / "fixtures" / "live_weather_response.json"
    return json.loads(path.read_text(encoding="utf-8"))


class FakeClient:
    """Stand-in for WeatherAIClient that counts calls and can be made to fail.

    Counting is the whole point of the coalescing tests: the assertion is not
    "did it work" but "how many times did we touch upstream".
    """

    def __init__(self, payload=None, error=None, delay=0.0, usage_delay=0.0):
        self.payload = payload if payload is not None else SAMPLE_UPSTREAM
        self.error = error
        self.delay = delay
        self.usage_delay = usage_delay
        self.calls = 0
        # /v1/usage costs a request of its own, so tests count it separately.
        self.usage_calls = 0
        self._lock = threading.Lock()

    def fetch_usage(self):
        with self._lock:
            self.usage_calls += 1
        if self.usage_delay:
            time.sleep(self.usage_delay)
        return {"plan": "free", "used": 12, "limit": 1000,
                "remaining": 988, "unlimited": False}

    def fetch_weather(self, latitude, longitude, units="metric"):
        with self._lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.payload


def seed_minimal_gazetteer():
    """Two locations and one alias - enough for every behavioural test."""
    nairobi = Location.objects.create(
        slug="nairobi", name="Nairobi", county="Nairobi", kind="county",
        latitude="-1.28640", longitude="36.81720", prominence=100,
    )
    Location.objects.create(
        slug="mombasa", name="Mombasa", county="Mombasa", kind="county",
        latitude="-4.04350", longitude="39.66820", prominence=95,
    )
    LocationAlias.objects.create(alias="nairobi-city", location=nairobi)
    return nairobi


class CacheIsolationMixin:
    """Clears cache state around each test so runs cannot contaminate each other."""

    def setUp(self):
        super().setUp()
        cache.clear()
        metrics.reset()
        client_module.reset_client()
        self.addCleanup(cache.clear)
        self.addCleanup(client_module.reset_client)


class WeatherTestCase(CacheIsolationMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.nairobi = seed_minimal_gazetteer()


class WeatherTransactionTestCase(CacheIsolationMixin, TransactionTestCase):
    """For tests using real threads, which need committed rows to be visible."""

    def setUp(self):
        super().setUp()
        self.nairobi = seed_minimal_gazetteer()


__all__ = [
    "FakeClient",
    "SAMPLE_UPSTREAM",
    "load_live_fixture",
    "WeatherTestCase",
    "WeatherTransactionTestCase",
    "seed_minimal_gazetteer",
    "UpstreamRateLimited",
    "UpstreamUnavailable",
]
