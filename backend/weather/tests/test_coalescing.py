"""Scenario C: many simultaneous users, one upstream request.

This is the headline behaviour of the project, so it is tested with real
threads rather than a simulation. The assertion that matters is the call count
on the fake upstream client.
"""

import threading
import time
from unittest import mock

from django.db import connection
from django.test import override_settings

from weather import cache as weather_cache
from weather.exceptions import UpstreamUnavailable
from weather.service import STATUS_LIVE, get_weather
from weather.tests.base import FakeClient, WeatherTransactionTestCase

CONCURRENT_USERS = 25


def _call_in_thread(results, errors, index, location="Nairobi"):
    """Run one get_weather call, recording the outcome.

    Each thread gets its own DB connection, closed afterwards so the test
    database can be torn down cleanly.
    """
    try:
        results[index] = get_weather(location)
    except Exception as exc:  # noqa: BLE001 - recorded and asserted on
        errors[index] = exc
    finally:
        connection.close()


class RequestCoalescingTests(WeatherTransactionTestCase):
    @override_settings(WEATHER_COALESCE_WAIT=10, WEATHER_LOCK_TTL=15)
    def test_concurrent_cache_misses_produce_exactly_one_upstream_call(self):
        # The delay widens the window in which followers pile up behind the
        # leader; without it the leader can finish before the others start.
        fake = FakeClient(delay=0.4)

        results = [None] * CONCURRENT_USERS
        errors = [None] * CONCURRENT_USERS
        barrier = threading.Barrier(CONCURRENT_USERS)

        def worker(index):
            # Release all threads at once, so this is a genuine thundering herd.
            barrier.wait()
            _call_in_thread(results, errors, index)

        with mock.patch("weather.service.get_client", return_value=fake):
            threads = [
                threading.Thread(target=worker, args=(i,))
                for i in range(CONCURRENT_USERS)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

        self.assertEqual(
            [e for e in errors if e], [], "no request should fail during coalescing"
        )
        self.assertEqual(
            fake.calls,
            1,
            f"{CONCURRENT_USERS} simultaneous users must produce 1 upstream call, "
            f"got {fake.calls}",
        )
        self.assertTrue(all(r is not None for r in results))

        # Exactly one caller is the leader and sees a live fetch; the rest are
        # served the leader's cached result.
        live = [r for r in results if r.status == STATUS_LIVE]
        self.assertEqual(len(live), 1)
        self.assertTrue(all(not r.is_stale for r in results))

    @override_settings(WEATHER_COALESCE_WAIT=10)
    def test_different_locations_are_not_coalesced_together(self):
        """The lock is per-location: Nairobi must not block Mombasa."""
        fake = FakeClient(delay=0.3)
        results = [None] * 2
        errors = [None] * 2

        with mock.patch("weather.service.get_client", return_value=fake):
            threads = [
                threading.Thread(target=_call_in_thread, args=(results, errors, 0, "Nairobi")),
                threading.Thread(target=_call_in_thread, args=(results, errors, 1, "Mombasa")),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

        self.assertEqual([e for e in errors if e], [])
        self.assertEqual(fake.calls, 2, "distinct locations need distinct fetches")

    @override_settings(WEATHER_COALESCE_WAIT=6, WEATHER_CACHE_TTL=60, WEATHER_STALE_TTL=86400)
    def test_followers_degrade_to_stale_when_the_leader_fails(self):
        """A failing leader must not turn N followers into N retries."""
        weather_cache.write(
            "nairobi", "metric", {"temperature": 19.0}, fetched_at=time.time() - 600
        )
        fake = FakeClient(error=UpstreamUnavailable("http_503"), delay=0.3)

        results = [None] * 8
        errors = [None] * 8
        barrier = threading.Barrier(8)

        def worker(index):
            barrier.wait()
            _call_in_thread(results, errors, index)

        with mock.patch("weather.service.get_client", return_value=fake):
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=40)

        self.assertEqual([e for e in errors if e], [])
        self.assertEqual(
            fake.calls, 1, "a failed leader must not cause followers to retry upstream"
        )
        self.assertTrue(
            all(r.is_stale for r in results), "every caller should get stale data"
        )
        self.assertEqual(results[0].payload["temperature"], 19.0)
