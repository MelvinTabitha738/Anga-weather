"""The /v1/usage sync must not multiply across workers.

GET /v1/usage costs a request from the same monthly budget it reports on, so
syncing it is only worth doing if the sync itself is strictly rate limited. The
danger is a check-then-act race: several workers each see "a sync is due" and
each spend a request.

The per-location coalescing lock does NOT protect this. That lock is keyed by
location, so simultaneous leaders for Nairobi, Mombasa and Kisumu are three
different leaders - all of which reach the usage gate at once.
"""

import threading
import time
from unittest import mock

from django.conf import settings
from django.db import connection
from django.test import override_settings

from weather import quota
from weather.service import get_weather
from weather.tests.base import FakeClient, WeatherTransactionTestCase
from locations.models import Location


def _seed(slug, name, lat, lon):
    Location.objects.create(
        slug=slug, name=name, county=name, kind="county",
        latitude=lat, longitude=lon, prominence=50,
    )


class UsageSyncSingleFlightTests(WeatherTransactionTestCase):
    """Concurrent workers, distinct locations, cold quota cache."""

    def setUp(self):
        super().setUp()
        for slug, name, lat, lon in [
            ("kisumu", "Kisumu", "-0.09170", "34.76800"),
            ("nakuru", "Nakuru", "-0.30310", "36.08000"),
            ("eldoret", "Eldoret", "0.51430", "35.26980"),
            ("garissa", "Garissa", "-0.45360", "39.64610"),
        ]:
            _seed(slug, name, lat, lon)

    @override_settings(WEATHER_COALESCE_WAIT=10)
    def test_concurrent_workers_sync_usage_only_once(self):
        """The regression this guards: N simultaneous cache misses on N
        DIFFERENT locations must still produce exactly ONE /v1/usage call."""
        locations = ["Nairobi", "Mombasa", "Kisumu", "Nakuru", "Eldoret", "Garissa"]

        # usage_delay widens the race window so the check-then-act gap is real
        # rather than something the GIL happens to hide.
        fake = FakeClient(delay=0.25, usage_delay=0.25)

        errors = []
        barrier = threading.Barrier(len(locations))

        def worker(name):
            try:
                barrier.wait()
                get_weather(name)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connection.close()

        with mock.patch("weather.service.get_client", return_value=fake):
            threads = [threading.Thread(target=worker, args=(n,)) for n in locations]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

        self.assertEqual(errors, [], "no request should fail")
        # Each distinct location legitimately needs its own weather call...
        self.assertEqual(fake.calls, len(locations))
        # ...but the quota reading is global and must be fetched once.
        self.assertEqual(
            fake.usage_calls,
            1,
            f"expected 1 /v1/usage call across {len(locations)} concurrent "
            f"workers, got {fake.usage_calls}",
        )

    def test_a_second_sync_is_not_due_after_a_successful_one(self):
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            get_weather("Nairobi")
            get_weather("Mombasa")
            get_weather("Kisumu")

        self.assertEqual(fake.calls, 3)
        self.assertEqual(fake.usage_calls, 1, "sync is due once, not per location")

    def test_sync_becomes_due_again_once_the_interval_lapses(self):
        """Age the stored reading rather than shrinking the TTL, so the test
        does not sit on the `now - synced_at > TTL` boundary."""
        fake = FakeClient()
        with mock.patch("weather.service.get_client", return_value=fake):
            get_weather("Nairobi")
            self.assertEqual(fake.usage_calls, 1)

            aged = quota.get_usage()
            aged["synced_at"] = time.time() - (settings.WEATHER_USAGE_TTL + 60)
            quota._store_usage(aged)
            quota.clear_usage_sync_lock()

            get_weather("Mombasa")

        self.assertEqual(fake.usage_calls, 2, "an expired reading must resync")

    def test_a_failed_sync_does_not_retry_immediately(self):
        """If /v1/usage fails, the next worker must not immediately try again -
        that would spend the budget on repeated failures."""
        fake = FakeClient()
        fake.fetch_usage = lambda: {}  # simulate a failed/empty usage response

        with mock.patch("weather.service.get_client", return_value=fake):
            get_weather("Nairobi")
            get_weather("Mombasa")
            get_weather("Kisumu")

        # The claim is held for the retry backoff, so only the first attempt ran.
        self.assertIsNotNone(quota.get_usage_sync_lock_state())


class ClaimPrimitiveTests(WeatherTransactionTestCase):
    """Direct pressure on the claim itself, independent of the service."""

    def test_only_one_of_many_threads_wins_the_claim(self):
        winners = []
        lock = threading.Lock()
        barrier = threading.Barrier(50)

        def contend():
            barrier.wait()
            if quota.claim_usage_sync():
                with lock:
                    winners.append(threading.get_ident())

        threads = [threading.Thread(target=contend) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        self.assertEqual(len(winners), 1, f"50 threads produced {len(winners)} winners")

    def test_claim_is_refused_while_a_fresh_reading_exists(self):
        quota.record_usage({"plan": "free", "used": 5, "limit": 1000, "remaining": 995})
        quota.clear_usage_sync_lock()
        self.assertFalse(
            quota.claim_usage_sync(),
            "a fresh reading means no sync is due, claim or not",
        )

    def test_claim_is_refused_a_second_time_even_when_due(self):
        self.assertTrue(quota.claim_usage_sync())
        self.assertFalse(quota.claim_usage_sync(), "the claim must not be reentrant")

    def test_successful_sync_closes_the_gate_even_after_the_claim_expires(self):
        """The claim is only the mutex; synced_at is what enforces the interval."""
        self.assertTrue(quota.claim_usage_sync())
        quota.record_usage({"plan": "free", "used": 5, "limit": 1000, "remaining": 995})

        # Even with the mutex released, a fresh reading keeps the gate shut.
        quota.clear_usage_sync_lock()
        self.assertFalse(quota.claim_usage_sync())

    def test_a_zero_sync_interval_does_not_discard_the_reading(self):
        """Regression: Django treats timeout=0 as expire-immediately, so a
        WEATHER_USAGE_TTL of 0 used to wipe every stored reading."""
        with override_settings(WEATHER_USAGE_TTL=0):
            quota.record_usage(
                {"plan": "free", "used": 5, "limit": 1000, "remaining": 995}
            )
            self.assertEqual(quota.get_usage().get("remaining"), 995)
            self.assertEqual(quota.estimated_remaining(), 995)
