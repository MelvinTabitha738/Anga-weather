"""Translate Weather-AI's response into Anga's application payload.

VERIFIED AGAINST THE LIVE API
-----------------------------
Weather-AI publishes no response schema, so this mapping was derived by
inspecting a real authenticated `GET /v1/weather?days=7&ai=true` response.
A captured sample lives at tests/fixtures/live_weather_response.json and the
tests assert against it, so a change in the upstream shape fails loudly.

The response contains exactly this and nothing more:

    {
      "lat", "lon", "units", "days",
      "current":  {time, interval, temperature, windspeed,
                   winddirection, is_day, weathercode},
      "hourly":  [{time, temp, precipitation, weathercode}]      x48,
      "daily":   [{date, temp_max, temp_min, precipitation,
                   weathercode}]                                 x7,
      "ai_summary": null
    }

WHAT IS NOT AVAILABLE
---------------------
There is no humidity, feels-like, pressure, visibility, UV index, sunrise or
sunset, and no condition text. Those fields are simply absent, so Anga does not
display them. We surface what the provider actually returns.

`ai_summary` came back null on a free-plan key even with ai=true. It is passed
through as-is: the UI renders that section only when it is non-null, so nothing
is fabricated while the capability still works if the plan ever provides it.

CONDITION TEXT
--------------
`weathercode` is the WMO 4677 present-weather scale. Rendering code 51 as
"Light drizzle" is translating a documented standard, not inventing data, and
it is what drives both the wording and the backdrop.
"""

import logging

logger = logging.getLogger(__name__)

# --- Condition vocabulary shared with the frontend -------------------------
GROUP_CLEAR = "clear"
GROUP_PARTLY_CLOUDY = "partly_cloudy"
GROUP_CLOUDY = "cloudy"
GROUP_FOG = "fog"
GROUP_DRIZZLE = "drizzle"
GROUP_RAIN = "rain"
GROUP_SNOW = "snow"
GROUP_THUNDERSTORM = "thunderstorm"
GROUP_UNKNOWN = "unknown"

INTENSITY_NONE = "none"
INTENSITY_LIGHT = "light"
INTENSITY_MODERATE = "moderate"
INTENSITY_HEAVY = "heavy"

_INTENSITY_RANK = {
    INTENSITY_NONE: 0,
    INTENSITY_LIGHT: 1,
    INTENSITY_MODERATE: 2,
    INTENSITY_HEAVY: 3,
}

# WMO 4677 present-weather codes -> (label, group, intensity).
# Snow codes are included for completeness; at Kenyan altitudes they realistically
# only ever appear on Mount Kenya.
WMO_CODES = {
    0: ("Clear sky", GROUP_CLEAR, INTENSITY_NONE),
    1: ("Mainly clear", GROUP_CLEAR, INTENSITY_NONE),
    2: ("Partly cloudy", GROUP_PARTLY_CLOUDY, INTENSITY_NONE),
    3: ("Overcast", GROUP_CLOUDY, INTENSITY_NONE),
    45: ("Fog", GROUP_FOG, INTENSITY_NONE),
    48: ("Freezing fog", GROUP_FOG, INTENSITY_NONE),
    51: ("Light drizzle", GROUP_DRIZZLE, INTENSITY_LIGHT),
    53: ("Moderate drizzle", GROUP_DRIZZLE, INTENSITY_MODERATE),
    55: ("Heavy drizzle", GROUP_DRIZZLE, INTENSITY_HEAVY),
    56: ("Light freezing drizzle", GROUP_DRIZZLE, INTENSITY_LIGHT),
    57: ("Freezing drizzle", GROUP_DRIZZLE, INTENSITY_HEAVY),
    61: ("Light rain", GROUP_RAIN, INTENSITY_LIGHT),
    63: ("Moderate rain", GROUP_RAIN, INTENSITY_MODERATE),
    65: ("Heavy rain", GROUP_RAIN, INTENSITY_HEAVY),
    66: ("Light freezing rain", GROUP_RAIN, INTENSITY_LIGHT),
    67: ("Freezing rain", GROUP_RAIN, INTENSITY_HEAVY),
    71: ("Light snow", GROUP_SNOW, INTENSITY_LIGHT),
    73: ("Moderate snow", GROUP_SNOW, INTENSITY_MODERATE),
    75: ("Heavy snow", GROUP_SNOW, INTENSITY_HEAVY),
    77: ("Snow grains", GROUP_SNOW, INTENSITY_LIGHT),
    80: ("Light showers", GROUP_RAIN, INTENSITY_LIGHT),
    81: ("Showers", GROUP_RAIN, INTENSITY_MODERATE),
    82: ("Violent showers", GROUP_RAIN, INTENSITY_HEAVY),
    85: ("Light snow showers", GROUP_SNOW, INTENSITY_LIGHT),
    86: ("Snow showers", GROUP_SNOW, INTENSITY_HEAVY),
    95: ("Thunderstorm", GROUP_THUNDERSTORM, INTENSITY_MODERATE),
    96: ("Thunderstorm with hail", GROUP_THUNDERSTORM, INTENSITY_HEAVY),
    99: ("Severe thunderstorm with hail", GROUP_THUNDERSTORM, INTENSITY_HEAVY),
}

# How many hours of the hourly series to expose. The API returns 48 (today and
# tomorrow); a day's outlook is what the UI actually shows.
HOURLY_WINDOW = 24


def _as_float(value):
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value):
    number = _as_float(value)
    return None if number is None else int(round(number))


def describe_code(code):
    """Map a WMO code to (label, group, intensity), tolerating anything odd."""
    numeric = _as_int(code)
    if numeric is None or numeric not in WMO_CODES:
        if numeric is not None:
            logger.info("upstream_unknown_weathercode code=%s", numeric)
        return None, GROUP_UNKNOWN, INTENSITY_NONE
    return WMO_CODES[numeric]


def refine_intensity(base_intensity, precipitation_mm):
    """Let measured rainfall promote (never demote) the code's intensity.

    The WMO code says what kind of weather it is; the millimetre figure says how
    hard it is actually falling. Thresholds follow the conventional hourly
    rainfall bands. This is what makes the rain animation track real rainfall.
    """
    millimetres = _as_float(precipitation_mm)
    if millimetres is None or millimetres <= 0:
        return base_intensity

    if millimetres >= 7.6:
        measured = INTENSITY_HEAVY
    elif millimetres >= 2.5:
        measured = INTENSITY_MODERATE
    else:
        measured = INTENSITY_LIGHT

    return max(base_intensity, measured, key=lambda i: _INTENSITY_RANK.get(i, 0))


_CARDINALS = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)


def _cardinal(degrees):
    value = _as_float(degrees)
    if value is None:
        return None
    return _CARDINALS[int((value % 360) / 22.5 + 0.5) % 16]


def _warn_unexpected_shape(raw):
    """Log if upstream grows or drops a top-level key we rely on."""
    if not isinstance(raw, dict):
        logger.warning("upstream_shape_unexpected type=%s", type(raw).__name__)
        return
    known = {"lat", "lon", "units", "days", "current", "hourly", "daily", "ai_summary"}
    added = sorted(set(raw) - known)
    missing = sorted(known - set(raw))
    if added:
        logger.info("upstream_new_keys keys=%s", ",".join(added))
    if missing:
        logger.warning("upstream_missing_keys keys=%s", ",".join(missing))


def _build_hourly(raw, current_time):
    """Hourly entries from the current hour onwards, capped to HOURLY_WINDOW.

    Timestamps are naive local time ("2026-08-20T15:30") for the requested
    coordinates, so lexicographic comparison on the shared ISO format correctly
    orders them without needing to guess a timezone.
    """
    entries = raw.get("hourly")
    if not isinstance(entries, list):
        return []

    # Truncate "2026-08-20T15:30" to the hour so the current hour is included
    # rather than skipped.
    cutoff = f"{current_time[:13]}:00" if current_time else None

    hours = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        time_value = entry.get("time")
        if cutoff and isinstance(time_value, str) and time_value < cutoff:
            continue

        label, group, intensity = describe_code(entry.get("weathercode"))
        precipitation = _as_float(entry.get("precipitation"))
        hours.append(
            {
                "time": time_value,
                "temperature": _as_float(entry.get("temp")),
                "precipitation": precipitation,
                "weather_code": _as_int(entry.get("weathercode")),
                "condition": label,
                "condition_group": group,
                "condition_intensity": refine_intensity(intensity, precipitation),
            }
        )

    return hours[:HOURLY_WINDOW]


def _build_daily(raw):
    entries = raw.get("daily")
    if not isinstance(entries, list):
        return []

    days = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        label, group, intensity = describe_code(entry.get("weathercode"))
        precipitation = _as_float(entry.get("precipitation"))
        days.append(
            {
                "date": entry.get("date"),
                "temp_max": _as_float(entry.get("temp_max")),
                "temp_min": _as_float(entry.get("temp_min")),
                "precipitation": precipitation,
                "weather_code": _as_int(entry.get("weathercode")),
                "condition": label,
                "condition_group": group,
                "condition_intensity": refine_intensity(intensity, precipitation),
            }
        )
    return days


def normalize_upstream(raw: dict, units: str = "metric") -> dict:
    """Build Anga's payload from a verified Weather-AI response.

    Every value is nullable. The UI omits anything null rather than showing a
    placeholder, so a field the provider drops disappears from the interface
    instead of rendering as an empty card.
    """
    _warn_unexpected_shape(raw)

    current = raw.get("current") if isinstance(raw.get("current"), dict) else {}

    observed_at = current.get("time")
    label, group, base_intensity = describe_code(current.get("weathercode"))

    hourly = _build_hourly(raw, observed_at if isinstance(observed_at, str) else None)
    daily = _build_daily(raw)

    # `current` carries no precipitation figure, so the rainfall for the current
    # hour comes from the matching hourly entry. It is labelled as exactly that
    # in the UI - "Rain this hour" - never as an instantaneous measurement.
    current_precipitation = hourly[0]["precipitation"] if hourly else None
    intensity = refine_intensity(base_intensity, current_precipitation)

    is_day = current.get("is_day")
    if is_day is not None:
        is_day = bool(_as_int(is_day)) if not isinstance(is_day, bool) else is_day

    wind_degrees = _as_float(current.get("winddirection"))

    return {
        # --- current conditions (all verified present upstream) ---
        "temperature": _as_float(current.get("temperature")),
        "wind_speed": _as_float(current.get("windspeed")),
        "wind_direction": _cardinal(wind_degrees),
        "wind_direction_degrees": wind_degrees,
        "precipitation_this_hour": current_precipitation,
        "weather_code": _as_int(current.get("weathercode")),
        "condition": label,
        "condition_group": group,
        "condition_intensity": intensity,
        "is_day": is_day,
        "observed_at": observed_at,
        "units": units,
        # --- forecast: already in the response we cache, so it costs nothing extra ---
        "hourly": hourly,
        "daily": daily,
        # --- passed through untouched; null on the free plan ---
        "ai_summary": raw.get("ai_summary"),
    }
