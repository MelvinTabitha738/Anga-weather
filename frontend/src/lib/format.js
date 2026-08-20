/**
 * Display formatting.
 *
 * Every helper returns null for missing data, and the UI omits anything null.
 * That rule matters more than usual here: Weather-AI returns no humidity,
 * feels-like, pressure, visibility or UV index, so there is no placeholder to
 * fall back on and nothing to invent.
 */

const isMissing = (value) =>
  value === null || value === undefined || Number.isNaN(Number(value))

export function formatTemperature(value) {
  if (isMissing(value)) return null
  // Math.round(-0.4) is -0, which would render as "-0°".
  const rounded = Math.round(Number(value)) || 0
  return `${rounded}°`
}

export function formatTemperatureWithUnit(value, units = 'metric') {
  if (isMissing(value)) return null
  const rounded = Math.round(Number(value)) || 0
  return `${rounded} degrees ${units === 'imperial' ? 'Fahrenheit' : 'Celsius'}`
}

export function formatWind(value, units = 'metric') {
  if (isMissing(value)) return null
  // Weather-AI returns `windspeed` alongside a `units` parameter of
  // metric/imperial; metric responses are km/h.
  return `${Math.round(Number(value))} ${units === 'imperial' ? 'mph' : 'km/h'}`
}

export function formatPrecipitation(value, units = 'metric') {
  if (isMissing(value)) return null
  const number = Number(value)
  const unit = units === 'imperial' ? 'in' : 'mm'
  if (number === 0) return `0 ${unit}`
  // Sub-millimetre drizzle rounds to 0, which reads as "no rain"; keep one
  // decimal below 10 so light rain stays visible as a number.
  return `${number < 10 ? Number(number.toFixed(1)) : Math.round(number)} ${unit}`
}

/** The unit rainfall is reported in, for the column legend. */
export function rainfallUnit(units = 'metric') {
  return units === 'imperial' ? 'in' : 'mm'
}

/**
 * One rainfall cell for the forecast lists.
 *
 * Weather-AI returns a precipitation figure for EVERY day and hour, including
 * 0.0 — so a dry day is a known value, not missing data. Rendering nothing for
 * it made an explicit "no rain" look like "no information", and left the reader
 * guessing why only some rows carried a number.
 *
 * Every cell therefore gets content: a figure when it rains, an em dash when it
 * does not. The unit is carried once by the column legend rather than repeated
 * on every row, and `label` gives assistive tech the full phrase.
 */
export function rainfallCell(value, units = 'metric') {
  const unit = rainfallUnit(units)
  const spoken = unit === 'in' ? 'inches' : 'millimetres'

  if (isMissing(value)) {
    return { text: '—', dry: true, label: 'Rainfall not available' }
  }

  const amount = Number(value)
  if (amount <= 0) {
    return { text: '—', dry: true, label: 'No rain expected' }
  }

  // Keep one decimal below 10 so a 0.2 trace does not round away to zero.
  const shown = amount < 10 ? Number(amount.toFixed(1)) : Math.round(amount)
  return { text: String(shown), dry: false, label: `${shown} ${spoken} of rain` }
}

/**
 * The at-a-glance row.
 *
 * Built ONLY from fields Weather-AI actually returns: wind (current), and
 * today's rainfall and high/low (from the daily series). Humidity, pressure
 * and visibility are not available from this provider and are therefore not
 * shown rather than faked.
 */
export function buildMetrics(current, daily) {
  if (!current) return []
  const units = current.units || 'metric'
  const today = daily?.[0]

  const candidates = [
    {
      key: 'wind',
      label: 'Wind',
      value: formatWind(current.wind_speed, units),
      hint: current.wind_direction || null,
      icon: 'wind',
    },
    {
      key: 'rain-hour',
      label: 'Rain this hour',
      value: formatPrecipitation(current.precipitation_this_hour, units),
      icon: 'drop',
    },
    {
      key: 'rain-today',
      label: 'Rain today',
      value: today ? formatPrecipitation(today.precipitation, units) : null,
      icon: 'umbrella',
    },
    {
      key: 'range',
      label: 'High / Low',
      value:
        today && !isMissing(today.temp_max) && !isMissing(today.temp_min)
          ? `${formatTemperature(today.temp_max)} / ${formatTemperature(today.temp_min)}`
          : null,
      icon: 'range',
    },
  ]

  return candidates.filter((metric) => metric.value !== null)
}

// --- Time helpers ---------------------------------------------------------
// Upstream timestamps are naive local time for the requested coordinates
// ("2026-08-20T15:30"), i.e. already East Africa Time. They are parsed as
// local wall-clock and never shifted, so 15:00 displays as 3 PM.

function parseLocal(value) {
  if (typeof value !== 'string') return null
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/)
  if (!match) return null
  const [, y, m, d, hh = '0', mm = '0'] = match
  const date = new Date(Number(y), Number(m) - 1, Number(d), Number(hh), Number(mm))
  return Number.isNaN(date.getTime()) ? null : date
}

/** "3 PM" — the label under each hourly column. */
export function formatHour(value) {
  const date = parseLocal(value)
  if (!date) return null
  const hour = date.getHours()
  const suffix = hour < 12 ? 'AM' : 'PM'
  const display = hour % 12 === 0 ? 12 : hour % 12
  return `${display} ${suffix}`
}

/** "Thursday, 20 August" — the dateline under the place name.
 *  Assembled from parts rather than one toLocaleDateString call, because
 *  en-GB renders "Thursday 20 August" with no comma and the punctuation
 *  should not vary by runtime. */
export function formatFullDate(value) {
  const date = parseLocal(value) || new Date()
  const weekday = date.toLocaleDateString('en-GB', { weekday: 'long' })
  const month = date.toLocaleDateString('en-GB', { month: 'long' })
  return `${weekday}, ${date.getDate()} ${month}`
}

/** "Today", "Tomorrow", then "Saturday" — the 7-day rows. */
export function formatDayName(value, index) {
  if (index === 0) return 'Today'
  if (index === 1) return 'Tomorrow'
  const date = parseLocal(value)
  if (!date) return null
  return date.toLocaleDateString('en-GB', { weekday: 'long' })
}

/**
 * Where today's high/low sits inside the week's range, as two percentages.
 * Drives the little temperature bars in the 7-day list, which make the week's
 * shape readable at a glance instead of forcing a numbers comparison.
 */
export function temperatureBar(day, weekMin, weekMax) {
  if (isMissing(day?.temp_min) || isMissing(day?.temp_max)) return null
  const span = weekMax - weekMin
  if (!Number.isFinite(span) || span <= 0) return { left: 0, width: 100 }
  const left = ((day.temp_min - weekMin) / span) * 100
  const width = ((day.temp_max - day.temp_min) / span) * 100
  return { left, width: Math.max(width, 4) }
}

export function weekRange(daily) {
  const mins = (daily || []).map((d) => d.temp_min).filter((v) => !isMissing(v))
  const maxes = (daily || []).map((d) => d.temp_max).filter((v) => !isMissing(v))
  if (!mins.length || !maxes.length) return { weekMin: 0, weekMax: 0 }
  return { weekMin: Math.min(...mins), weekMax: Math.max(...maxes) }
}
