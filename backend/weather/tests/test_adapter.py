"""Adapter tests: upstream shape -> application payload, and condition mapping.

The condition vocabulary drives the frontend's background, so misclassification
is a visible product bug, not just a data one.
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
    INTENSITY_HEAVY,
    INTENSITY_LIGHT,
    INTENSITY_MODERATE,
    INTENSITY_NONE,
    classify_condition,
    normalize_upstream,
)


class ConditionClassificationTests(SimpleTestCase):
    def test_wmo_codes_map_to_groups(self):
        cases = [
            (0, GROUP_CLEAR), (1, GROUP_CLEAR), (2, GROUP_PARTLY_CLOUDY),
            (3, GROUP_CLOUDY), (45, GROUP_FOG), (53, GROUP_DRIZZLE),
            (63, GROUP_RAIN), (95, GROUP_THUNDERSTORM),
        ]
        for code, expected in cases:
            group, _ = classify_condition(code, None, None)
            self.assertEqual(group, expected, f"WMO code {code}")

    def test_wmo_intensity_bands(self):
        self.assertEqual(classify_condition(65, None, None)[1], INTENSITY_HEAVY)
        self.assertEqual(classify_condition(63, None, None)[1], INTENSITY_MODERATE)
        self.assertEqual(classify_condition(61, None, None)[1], INTENSITY_LIGHT)

    def test_text_fallback_when_no_code(self):
        self.assertEqual(classify_condition(None, "Sunny", None)[0], GROUP_CLEAR)
        self.assertEqual(classify_condition(None, "Partly cloudy", None)[0], GROUP_PARTLY_CLOUDY)
        self.assertEqual(classify_condition(None, "Light rain shower", None)[0], GROUP_RAIN)
        self.assertEqual(classify_condition(None, "Mist", None)[0], GROUP_FOG)

    def test_thunderstorm_beats_rain_in_text_matching(self):
        group, _ = classify_condition(None, "Thunderstorm with heavy rain", None)
        self.assertEqual(group, GROUP_THUNDERSTORM)

    def test_text_intensity_words(self):
        self.assertEqual(classify_condition(None, "Heavy rain", None)[1], INTENSITY_HEAVY)
        self.assertEqual(classify_condition(None, "Light drizzle", None)[1], INTENSITY_LIGHT)

    def test_precipitation_refines_intensity(self):
        """Rainfall bands: <2.5 light, 2.5-7.6 moderate, >=7.6 heavy (mm/h)."""
        self.assertEqual(classify_condition(None, "Rain", 0.4)[1], INTENSITY_LIGHT)
        self.assertEqual(classify_condition(None, "Rain", 4.0)[1], INTENSITY_MODERATE)
        self.assertEqual(classify_condition(None, "Rain", 12.0)[1], INTENSITY_HEAVY)

    def test_precipitation_promotes_an_unknown_condition_to_rain(self):
        group, intensity = classify_condition(None, None, 3.0)
        self.assertEqual(group, GROUP_RAIN)
        self.assertEqual(intensity, INTENSITY_MODERATE)

    def test_dry_conditions_have_no_intensity(self):
        self.assertEqual(classify_condition(0, "Clear", 0)[1], INTENSITY_NONE)
        self.assertEqual(classify_condition(3, "Cloudy", None)[1], INTENSITY_NONE)

    def test_completely_unknown_input_is_unknown_not_a_crash(self):
        group, intensity = classify_condition(None, None, None)
        self.assertEqual(group, GROUP_UNKNOWN)
        self.assertEqual(intensity, INTENSITY_NONE)


class NormalizeUpstreamTests(SimpleTestCase):
    def test_maps_a_nested_current_block(self):
        raw = {
            "current": {
                "temperature": 26.0, "feels_like": 27.5, "humidity": 70,
                "wind_speed": 14.0, "wind_deg": 90, "precipitation": 1.2,
                "condition": {"text": "Light rain"}, "is_day": 1,
            }
        }
        out = normalize_upstream(raw)
        self.assertEqual(out["temperature"], 26.0)
        self.assertEqual(out["feels_like"], 27.5)
        self.assertEqual(out["humidity"], 70)
        self.assertEqual(out["wind_speed"], 14.0)
        self.assertEqual(out["wind_direction"], "E", "90 degrees is east")
        self.assertEqual(out["condition"], "Light rain")
        self.assertEqual(out["condition_group"], GROUP_RAIN)
        self.assertIs(out["is_day"], True)

    def test_maps_a_flat_response(self):
        out = normalize_upstream({"temp_c": 19.0, "humidity": 55, "condition": "Clear"})
        self.assertEqual(out["temperature"], 19.0)
        self.assertEqual(out["humidity"], 55)
        self.assertEqual(out["condition_group"], GROUP_CLEAR)

    def test_missing_fields_become_null_not_errors(self):
        out = normalize_upstream({})
        self.assertIsNone(out["temperature"])
        self.assertIsNone(out["humidity"])
        self.assertIsNone(out["condition"])
        self.assertEqual(out["condition_group"], GROUP_UNKNOWN)

    def test_epoch_observed_at_is_converted_to_iso(self):
        out = normalize_upstream({"current": {"dt": 1755680400}})
        self.assertIsNotNone(out["observed_at"])
        self.assertIn("T", out["observed_at"])

    def test_garbage_values_do_not_raise(self):
        out = normalize_upstream(
            {"current": {"temperature": "not-a-number", "humidity": None, "wind_deg": []}}
        )
        self.assertIsNone(out["temperature"])
        self.assertIsNone(out["humidity"])
        self.assertIsNone(out["wind_direction"])

    def test_units_are_echoed_for_the_frontend(self):
        self.assertEqual(normalize_upstream({}, units="imperial")["units"], "imperial")
