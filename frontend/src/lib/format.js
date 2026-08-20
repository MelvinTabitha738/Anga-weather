/**
 * Display formatting for weather values.
 *
 * Every helper returns null for missing data. The UI omits a field entirely
 * when it gets null, rather than rendering an empty card - if Weather-AI does
 * not supply a value, we do not pretend to have one.
 */

const isMissing = (value) => value === null || value === undefined || Number.isNaN(Number(value))

export function formatTemperature(value) {
  if (isMissing(value)) return null
  return `${Math.round(Number(value))}°`
}

export function formatTemperatureWithUnit(value, units = 'metric') {
  if (isMissing(value)) return null
  return `${Math.round(Number(value))}°${units === 'imperial' ? 'F' : 'C'}`
}

export function formatWind(value, units = 'metric') {
  if (isMissing(value)) return null
  const rounded = Math.round(Number(value))
  // ASSUMPTION pending verification: Weather-AI documents a `units` parameter
  // but not the wind unit its response uses, so we label metric as km/h and
  // imperial as mph. Run `manage.py probe_upstream` against a live key to
  // confirm; if it returns m/s, convert here (this is the only place that
  // labels wind).
  return `${rounded} ${units === 'imperial' ? 'mph' : 'km/h'}`
}

export function formatPercent(value) {
  if (isMissing(value)) return null
  return `${Math.round(Number(value))}%`
}

export function formatPrecipitation(value, units = 'metric') {
  if (isMissing(value)) return null
  const number = Number(value)
  const unit = units === 'imperial' ? 'in' : 'mm'
  // Sub-millimetre drizzle rounds to 0, which reads as "no rain"; keep one
  // decimal below 10 so light rain is still visible as a number.
  return `${number < 10 ? number.toFixed(1) : Math.round(number)} ${unit}`
}

export function formatIndex(value) {
  if (isMissing(value)) return null
  return String(Math.round(Number(value)))
}

export function formatPressure(value) {
  if (isMissing(value)) return null
  return `${Math.round(Number(value))} hPa`
}

/**
 * Build the detail row, dropping anything the API did not return.
 * Order is by everyday usefulness, not by what the API happens to provide.
 */
export function buildDetails(weather) {
  if (!weather) return []
  const units = weather.units || 'metric'

  const candidates = [
    { key: 'feels_like', label: 'Feels like', value: formatTemperature(weather.feels_like) },
    { key: 'humidity', label: 'Humidity', value: formatPercent(weather.humidity) },
    {
      key: 'wind',
      label: 'Wind',
      value: formatWind(weather.wind_speed, units),
      hint: weather.wind_direction || null,
    },
    {
      key: 'precipitation',
      label: 'Rain',
      value: formatPrecipitation(weather.precipitation, units),
    },
    {
      key: 'precipitation_chance',
      label: 'Chance of rain',
      value: formatPercent(weather.precipitation_chance),
    },
    { key: 'uv_index', label: 'UV index', value: formatIndex(weather.uv_index) },
    { key: 'pressure', label: 'Pressure', value: formatPressure(weather.pressure) },
  ]

  return candidates.filter((detail) => detail.value !== null)
}
