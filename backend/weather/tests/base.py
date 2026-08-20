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

# A minimal upstream body in one of the shapes weather/adapter.py accepts.
SAMPLE_UPSTREAM = {
    "current": {
        "temperature": 24.5,
        "feels_like": 25.1,
        "humidity": 62,
        "wind_speed": 11.2,
        "wind_deg": 130,
        "precipitation": 0.0,
        "condition": {"text": "Partly cloudy"},
        "weather_code": 2,
        "is_day": 1,
        "time": "2026-08-20T09:00:00Z",
    }
}


class FakeClient:
    """Stand-in for WeatherAIClient that counts calls and can be made to fail.

    Counting is the whole point of the coalescing tests: the assertion is not
    "did it work" but "how many times did we touch upstream".
    """

    def __init__(self, payload=None, error=None, delay=0.0):
        self.payload = payload if payload is not None else SAMPLE_UPSTREAM
        self.error = error
        self.delay = delay
        self.calls = 0
        self._lock = threading.Lock()

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
    "WeatherTestCase",
    "WeatherTransactionTestCase",
    "seed_minimal_gazetteer",
    "UpstreamRateLimited",
    "UpstreamUnavailable",
]
