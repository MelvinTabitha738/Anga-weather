"""Translate Weather-AI's raw response into Anga's stable application payload.

WHY THIS MODULE EXISTS
----------------------
Weather-AI publishes its request contract (auth, parameters, status codes,
X-RateLimit-* headers) but does NOT publish a response-body schema - there is
no OpenAPI document and the docs show sample bodies only for /v1/ip-lookup and
the trees endpoints. Rather than let an unverified shape leak through the whole
codebase, every assumption about the upstream body is confined to this file.

Nothing else in the application reads a raw Weather-AI field. If the upstream
shape differs from what we expect, this is the only module that changes.

FIELD_CANDIDATES therefore lists several plausible paths per field and takes
the first that resolves. Run

    python manage.py probe_upstream --lat -1.2864 --lon 36.8172

against a real API key to dump the actual body; the candidate lists can then be
pruned to the one verified path each. `log_unmapped_keys` reports any top-level
key we do not consume, so an unexpected shape is visible in the logs rather
than silently producing nulls.

THE CONDITION VOCABULARY
------------------------
Classification happens here, server-side, and produces a small stable
vocabulary (group + intensity + is_day). The frontend switches on that vocabulary
to pick a background, so the visual logic is driven by one shared contract
rather than each component re-interpreting upstream condition strings.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# --- Condition vocabulary shared with the frontend -------------------------
GROUP_CLEAR = "clear"
GROUP_PARTLY_CLOUDY = "partly_cloudy"
GROUP_CLOUDY = "cloudy"
GROUP_FOG = "fog"
GROUP_DRIZZLE = "drizzle"
GROUP_RAIN = "rain"
GROUP_THUNDERSTORM = "thunderstorm"
GROUP_UNKNOWN = "unknown"

INTENSITY_NONE = "none"
INTENSITY_LIGHT = "light"
INTENSITY_MODERATE = "moderate"
INTENSITY_HEAVY = "heavy"


def _dig(data, *paths):
    """Return the first non-null value found at any of the dotted paths."""
    for path in paths:
        cursor = data
        for part in path.split("."):
            if isinstance(cursor, dict) and part in cursor:
                cursor = cursor[part]
            else:
                cursor = None
                break
        if cursor is not None:
            return cursor
    return None


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


# Candidate paths per field, most likely first. Prune to the verified path once
# a live response has been captured with `manage.py probe_upstream`.
FIELD_CANDIDATES = {
    "temperature": (
        "current.temperature", "current.temp_c", "current.temp",
        "current.temperature_2m", "temperature", "temp_c", "temp",
    ),
    "feels_like": (
        "current.feels_like", "current.feelslike_c", "current.apparent_temperature",
        "current.apparentTemperature", "feels_like", "feelslike_c",
    ),
    "humidity": (
        "current.humidity", "current.relative_humidity", "current.relative_humidity_2m",
        "current.humidity_pct", "humidity",
    ),
    "wind_speed": (
        "current.wind_speed", "current.wind_kph", "current.windspeed",
        "current.wind_speed_10m", "wind_speed", "wind_kph",
    ),
    "wind_direction_deg": (
        "current.wind_deg", "current.wind_degree", "current.wind_direction",
        "current.winddirection", "wind_deg",
    ),
    "wind_direction_text": (
        "current.wind_dir", "current.wind_cardinal", "wind_dir",
    ),
    "precipitation": (
        "current.precipitation", "current.precip_mm", "current.rain",
        "current.precipitation_mm", "precipitation", "precip_mm",
    ),
    "precipitation_chance": (
        "current.precipitation_probability", "current.chance_of_rain",
        "current.pop", "daily.0.precipitation_probability",
    ),
    "condition_text": (
        "current.condition.text", "current.condition", "current.weather",
        "current.summary", "current.description", "condition", "summary",
    ),
    "condition_code": (
        "current.weather_code", "current.condition.code", "current.weathercode",
        "current.code", "weather_code",
    ),
    "is_day": ("current.is_day", "current.isDay", "is_day"),
    "observed_at": (
        "current.time", "current.observed_at", "current.last_updated",
        "current.dt", "observed_at", "timestamp",
    ),
    "pressure": ("current.pressure", "current.pressure_mb", "pressure"),
    "uv_index": ("current.uv", "current.uv_index", "current.uvi", "uv_index"),
    "location_name": ("location.name", "location.city", "city", "timezone"),
}

# WMO 4677/4680 present-weather codes, used by many weather APIs. Applied only
# when the upstream code is numeric and inside the WMO range.
_WMO_GROUPS = {
    GROUP_CLEAR: {0, 1},
    GROUP_PARTLY_CLOUDY: {2},
    GROUP_CLOUDY: {3},
    GROUP_FOG: {45, 48},
    GROUP_DRIZZLE: {51, 53, 55, 56, 57},
    GROUP_RAIN: {61, 63, 65, 66, 67, 80, 81, 82},
    GROUP_THUNDERSTORM: {95, 96, 99},
}
_WMO_HEAVY = {65, 67, 82, 99}
_WMO_MODERATE = {53, 63, 81, 96}

# Keyword fallback for text conditions, checked in order - "thunderstorm" must
# be tested before "storm"/"rain" so it is not misclassified.
_TEXT_GROUPS = (
    (GROUP_THUNDERSTORM, ("thunder", "storm", "lightning")),
    (GROUP_DRIZZLE, ("drizzle",)),
    (GROUP_RAIN, ("rain", "shower", "downpour")),
    (GROUP_FOG, ("fog", "mist", "haze")),
    (GROUP_PARTLY_CLOUDY, ("partly", "partial", "few clouds", "scattered")),
    (GROUP_CLOUDY, ("cloud", "overcast")),
    (GROUP_CLEAR, ("clear", "sun", "fair")),
)


def classify_condition(code, text, precipitation_mm):
    """Map upstream condition signals onto (group, intensity).

    Three signals in priority order: a numeric WMO-range code, then the
    condition text, then - to refine intensity - the precipitation amount.
    """
    group = GROUP_UNKNOWN
    intensity = INTENSITY_NONE

    numeric_code = _as_int(code)
    if numeric_code is not None and 0 <= numeric_code <= 99:
        for candidate_group, codes in _WMO_GROUPS.items():
            if numeric_code in codes:
                group = candidate_group
                break
        if numeric_code in _WMO_HEAVY:
            intensity = INTENSITY_HEAVY
        elif numeric_code in _WMO_MODERATE:
            intensity = INTENSITY_MODERATE
        elif group in (GROUP_DRIZZLE, GROUP_RAIN, GROUP_THUNDERSTORM):
            intensity = INTENSITY_LIGHT

    if group == GROUP_UNKNOWN and text:
        lowered = str(text).lower()
        for candidate_group, keywords in _TEXT_GROUPS:
            if any(keyword in lowered for keyword in keywords):
                group = candidate_group
                break
        if "heavy" in lowered or "torrential" in lowered:
            intensity = INTENSITY_HEAVY
        elif "moderate" in lowered:
            intensity = INTENSITY_MODERATE
        elif "light" in lowered or "slight" in lowered:
            intensity = INTENSITY_LIGHT

    # Precipitation amount refines intensity when the code/text did not, and
    # can promote an unknown condition to rain. Thresholds follow the common
    # meteorological bands for hourly rainfall (mm/h).
    millimetres = _as_float(precipitation_mm)
    if millimetres is not None and millimetres > 0:
        if group in (GROUP_UNKNOWN, GROUP_CLEAR, GROUP_PARTLY_CLOUDY, GROUP_CLOUDY):
            group = GROUP_RAIN
        if millimetres >= 7.6:
            intensity = INTENSITY_HEAVY
        elif millimetres >= 2.5:
            intensity = max(intensity, INTENSITY_MODERATE, key=_intensity_rank)
        else:
            intensity = max(intensity, INTENSITY_LIGHT, key=_intensity_rank)

    if group in (GROUP_CLEAR, GROUP_PARTLY_CLOUDY, GROUP_CLOUDY, GROUP_FOG):
        if not millimetres:
            intensity = INTENSITY_NONE

    return group, intensity


def _intensity_rank(value):
    return {
        INTENSITY_NONE: 0,
        INTENSITY_LIGHT: 1,
        INTENSITY_MODERATE: 2,
        INTENSITY_HEAVY: 3,
    }.get(value, 0)


_CARDINALS = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)


def _cardinal(degrees):
    value = _as_float(degrees)
    if value is None:
        return None
    return _CARDINALS[int((value % 360) / 22.5 + 0.5) % 16]


def _iso(value):
    """Best-effort ISO-8601 string from an epoch int or an existing string."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return str(value)


def log_unmapped_keys(raw: dict) -> None:
    """Warn about top-level upstream keys the adapter does not consume.

    Cheap early warning that the upstream shape has changed or that we are
    ignoring data worth surfacing.
    """
    if not isinstance(raw, dict):
        logger.warning("upstream_shape_unexpected type=%s", type(raw).__name__)
        return

    consumed = {path.split(".")[0] for paths in FIELD_CANDIDATES.values() for path in paths}
    unmapped = sorted(set(raw.keys()) - consumed)
    if unmapped:
        logger.info("upstream_unmapped_keys keys=%s", ",".join(unmapped))


def normalize_upstream(raw: dict, units: str = "metric") -> dict:
    """Build Anga's application-level weather payload from a raw response.

    Every field is nullable: the frontend renders only what is present, so a
    missing upstream field produces an omitted card rather than a blank one.
    """
    log_unmapped_keys(raw)

    def field(name):
        return _dig(raw, *FIELD_CANDIDATES[name])

    precipitation = _as_float(field("precipitation"))
    condition_text = field("condition_text")
    if isinstance(condition_text, dict):
        condition_text = condition_text.get("text") or condition_text.get("description")

    group, intensity = classify_condition(
        field("condition_code"), condition_text, precipitation
    )

    is_day = field("is_day")
    if is_day is not None:
        is_day = bool(_as_int(is_day)) if not isinstance(is_day, bool) else is_day

    wind_degrees = _as_float(field("wind_direction_deg"))
    wind_text = field("wind_direction_text") or _cardinal(wind_degrees)

    return {
        "temperature": _as_float(field("temperature")),
        "feels_like": _as_float(field("feels_like")),
        "humidity": _as_int(field("humidity")),
        "wind_speed": _as_float(field("wind_speed")),
        "wind_direction": wind_text,
        "wind_direction_degrees": wind_degrees,
        "precipitation": precipitation,
        "precipitation_chance": _as_int(field("precipitation_chance")),
        "pressure": _as_float(field("pressure")),
        "uv_index": _as_float(field("uv_index")),
        "condition": str(condition_text) if condition_text else None,
        "condition_group": group,
        "condition_intensity": intensity,
        "is_day": is_day,
        "observed_at": _iso(field("observed_at")),
        "units": units,
    }
