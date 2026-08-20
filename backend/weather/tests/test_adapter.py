"""Adapter tests, asserted against the REAL captured Weather-AI response.

tests/fixtures/live_weather_response.json is a verbatim authenticated
`GET /v1/weather?days=7&ai=true` response. Testing against it means an upstream
shape change breaks the suite instead of silently producing null fields.
"""

from django.test import SimpleTestCase

from weather.adapter import (
    GROUP_CLEAR,
    GROUP_CLOUDY,
    GROUP_DRIZZLE,
    GROUP_FOG,
    GROUP_PARTLY_CLOUDY,
    GROUP_RAIN,
    GROUP_THUNDERSTORM,
    GROUP_UNKNOWN,
    HOURLY_WINDOW,
    INTENSITY_HEAVY,
    INTENSITY_LIGHT,
    INTENSITY_MODERATE,
    INTENSITY_NONE,
    describe_code,
    normalize_upstream,
    refine_intensity,
)
from weather.tests.base import SAMPLE_UPSTREAM, load_live_fixture


class LiveResponseShapeTests(SimpleTestCase):
    """Guards the assumptions the whole app is built on."""

    def test_fixture_has_the_documented_top_level_keys(self):
        raw = load_live_fixture()
        for key in ("lat", "lon", "units", "days", "current", "hourly", "daily", "ai_summary"):
            self.assertIn(key, raw)

    def test_current_contains_only_the_fields_we_rely_on(self):
        """If upstream adds humidity or feels-like, this test tells us."""
        current = load_live_fixture()["current"]
        self.assertEqual(
            set(current),
            {"time", "interval", "temperature", "windspeed",
             "winddirection", "is_day", "weathercode"},
        )

    def test_humidity_pressure_and_visibility_are_genuinely_absent(self):
        """The reason the UI does not show those cards."""
        current = load_live_fixture()["current"]
        for absent in ("humidity", "feels_like", "pressure", "visibility", "uv_index"):
            self.assertNotIn(absent, current)

    def test_forecast_series_shapes(self):
        raw = load_live_fixture()
        self.assertEqual(len(raw["daily"]), 7)
        self.assertEqual(set(raw["daily"][0]),
                         {"date", "temp_max", "temp_min", "precipitation", "weathercode"})
        self.assertEqual(set(raw["hourly"][0]),
                         {"time", "temp", "precipitation", "weathercode"})

    def test_ai_summary_is_null_on_the_free_plan(self):
        self.assertIsNone(load_live_fixture()["ai_summary"])


class WmoCodeTests(SimpleTestCase):
    def test_codes_present_in_the_live_response_all_map(self):
        # 0, 1, 2, 3, 51, 53 and 95 appeared in the captured response.
        for code, group in [
            (0, GROUP_CLEAR), (1, GROUP_CLEAR), (2, GROUP_PARTLY_CLOUDY),
            (3, GROUP_CLOUDY), (51, GROUP_DRIZZLE), (53, GROUP_DRIZZLE),
            (95, GROUP_THUNDERSTORM),
        ]:
            label, resolved, _ = describe_code(code)
            self.assertEqual(resolved, group, f"code {code}")
            self.assertTrue(label, f"code {code} must have a human label")

    def test_rain_and_fog_codes(self):
        self.assertEqual(describe_code(61)[1], GROUP_RAIN)
        self.assertEqual(describe_code(82)[1], GROUP_RAIN)
        self.assertEqual(describe_code(45)[1], GROUP_FOG)

    def test_code_intensities(self):
        self.assertEqual(describe_code(51)[2], INTENSITY_LIGHT)
        self.assertEqual(describe_code(53)[2], INTENSITY_MODERATE)
        self.assertEqual(describe_code(65)[2], INTENSITY_HEAVY)
        self.assertEqual(describe_code(0)[2], INTENSITY_NONE)

    def test_unknown_code_degrades_rather_than_raising(self):
        label, group, intensity = describe_code(1234)
        self.assertIsNone(label)
        self.assertEqual(group, GROUP_UNKNOWN)
        self.assertEqual(intensity, INTENSITY_NONE)

    def test_missing_code_is_unknown(self):
        self.assertEqual(describe_code(None)[1], GROUP_UNKNOWN)


class IntensityRefinementTests(SimpleTestCase):
    """Measured rainfall drives the animation, so the bands matter."""

    def test_rainfall_promotes_intensity(self):
        self.assertEqual(refine_intensity(INTENSITY_LIGHT, 12.0), INTENSITY_HEAVY)
        self.assertEqual(refine_intensity(INTENSITY_LIGHT, 4.0), INTENSITY_MODERATE)

    def test_rainfall_never_demotes_the_code(self):
        # Code says heavy rain but only a trace has fallen this hour: trust the
        # code, which describes the conditions, not the single-hour total.
        self.assertEqual(refine_intensity(INTENSITY_HEAVY, 0.1), INTENSITY_HEAVY)

    def test_no_rainfall_leaves_intensity_untouched(self):
        self.assertEqual(refine_intensity(INTENSITY_NONE, 0), INTENSITY_NONE)
        self.assertEqual(refine_intensity(INTENSITY_NONE, None), INTENSITY_NONE)


class NormalizeLiveResponseTests(SimpleTestCase):
    def setUp(self):
        self.out = normalize_upstream(load_live_fixture(), units="metric")

    def test_current_conditions_map_from_real_data(self):
        self.assertEqual(self.out["temperature"], 26.0)
        self.assertEqual(self.out["wind_speed"], 5.2)
        self.assertEqual(self.out["wind_direction_degrees"], 292.0)
        self.assertEqual(self.out["wind_direction"], "WNW")
        self.assertIs(self.out["is_day"], True)
        self.assertEqual(self.out["weather_code"], 51)
        self.assertEqual(self.out["condition"], "Light drizzle")
        self.assertEqual(self.out["condition_group"], GROUP_DRIZZLE)
        self.assertEqual(self.out["observed_at"], "2026-08-20T15:30")

    def test_fields_upstream_does_not_provide_are_simply_not_there(self):
        for absent in ("humidity", "feels_like", "pressure", "visibility", "uv_index"):
            self.assertNotIn(absent, self.out)

    def test_hourly_starts_at_the_current_hour_and_is_capped(self):
        hourly = self.out["hourly"]
        self.assertTrue(hourly)
        self.assertLessEqual(len(hourly), HOURLY_WINDOW)
        # current.time is 15:30, so the series must begin at 15:00 - the hour
        # in progress, not 16:00.
        self.assertEqual(hourly[0]["time"], "2026-08-20T15:00")
        self.assertTrue(all(h["time"] >= "2026-08-20T15:00" for h in hourly))

    def test_hourly_entries_are_fully_described(self):
        first = self.out["hourly"][0]
        self.assertEqual(
            set(first),
            {"time", "temperature", "precipitation", "weather_code",
             "condition", "condition_group", "condition_intensity"},
        )
        self.assertIsInstance(first["temperature"], float)

    def test_daily_has_seven_days_with_highs_and_lows(self):
        daily = self.out["daily"]
        self.assertEqual(len(daily), 7)
        self.assertEqual(daily[0]["date"], "2026-08-20")
        self.assertEqual(daily[0]["temp_max"], 26.3)
        self.assertEqual(daily[0]["temp_min"], 15.0)
        self.assertEqual(daily[0]["precipitation"], 2.2)
        self.assertEqual(daily[0]["condition_group"], GROUP_DRIZZLE)

    def test_the_stormy_day_is_classified_as_a_thunderstorm(self):
        # 2026-08-25 carries weathercode 95 with 12.6mm.
        stormy = [d for d in self.out["daily"] if d["date"] == "2026-08-25"][0]
        self.assertEqual(stormy["condition_group"], GROUP_THUNDERSTORM)
        self.assertEqual(stormy["condition_intensity"], INTENSITY_HEAVY)

    def test_current_precipitation_comes_from_the_current_hour(self):
        # current carries no precipitation field; it is taken from hourly[0].
        self.assertEqual(
            self.out["precipitation_this_hour"], self.out["hourly"][0]["precipitation"]
        )

    def test_ai_summary_passes_through_as_null(self):
        self.assertIsNone(self.out["ai_summary"])

    def test_units_echoed(self):
        self.assertEqual(self.out["units"], "metric")


class RobustnessTests(SimpleTestCase):
    def test_empty_response_does_not_raise(self):
        out = normalize_upstream({})
        self.assertIsNone(out["temperature"])
        self.assertEqual(out["condition_group"], GROUP_UNKNOWN)
        self.assertEqual(out["hourly"], [])
        self.assertEqual(out["daily"], [])

    def test_garbage_values_become_null(self):
        out = normalize_upstream(
            {"current": {"temperature": "warm", "windspeed": None, "winddirection": []}}
        )
        self.assertIsNone(out["temperature"])
        self.assertIsNone(out["wind_speed"])
        self.assertIsNone(out["wind_direction"])

    def test_malformed_series_entries_are_skipped_not_fatal(self):
        out = normalize_upstream(
            {
                "current": {"time": "2026-08-20T10:00", "weathercode": 0},
                "hourly": ["nonsense", {"time": "2026-08-20T11:00", "temp": 20, "weathercode": 0}],
                "daily": [None, {"date": "2026-08-20", "temp_max": 25, "temp_min": 14}],
            }
        )
        self.assertEqual(len(out["hourly"]), 1)
        self.assertEqual(len(out["daily"]), 1)

    def test_sample_used_by_other_tests_maps_correctly(self):
        out = normalize_upstream(SAMPLE_UPSTREAM)
        self.assertEqual(out["temperature"], 24.5)
        self.assertEqual(out["condition_group"], GROUP_PARTLY_CLOUDY)
        self.assertEqual(len(out["daily"]), 2)
