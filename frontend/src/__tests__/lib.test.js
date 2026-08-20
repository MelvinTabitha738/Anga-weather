import { describe, expect, it } from 'vitest'

import {
  buildMetrics,
  formatDayName,
  formatHour,
  formatPrecipitation,
  formatTemperature,
  formatWind,
  rainfallCell,
  rainfallUnit,
  temperatureBar,
  weekRange,
} from '../lib/format'
import { formatAge, messageForError, stalenessNotice } from '../lib/messages'
import { IDLE_THEME, RAIN_DENSITY, resolveTheme } from '../lib/weatherTheme'

describe('formatting', () => {
  it('rounds temperature to whole degrees', () => {
    expect(formatTemperature(24.4)).toBe('24°')
    expect(formatTemperature(-3.6)).toBe('-4°')
    // Math.round(-0.4) is -0; it must display as "0°", never "-0°".
    expect(formatTemperature(-0.4)).toBe('0°')
  })

  it('returns null for missing values so the UI can omit the field', () => {
    for (const missing of [null, undefined, NaN, 'abc']) {
      expect(formatTemperature(missing)).toBeNull()
      expect(formatWind(missing)).toBeNull()
    }
  })

  it('labels wind by unit system', () => {
    expect(formatWind(11.4, 'metric')).toBe('11 km/h')
    expect(formatWind(11.4, 'imperial')).toBe('11 mph')
  })

  it('keeps light rain visible instead of rounding it to zero', () => {
    expect(formatPrecipitation(0.4)).toBe('0.4 mm')
    expect(formatPrecipitation(12.2)).toBe('12 mm')
  })

  it('builds metrics only from fields Weather-AI actually returns', () => {
    const metrics = buildMetrics(
      { wind_speed: 5.2, wind_direction: 'WNW', precipitation_this_hour: 0.1, units: 'metric' },
      [{ temp_max: 26.3, temp_min: 15, precipitation: 2.2 }],
    )
    const keys = metrics.map((m) => m.key)
    expect(keys).toContain('wind')
    expect(keys).toContain('rain-today')
    expect(keys).toContain('range')
    // Never derivable from this provider.
    expect(keys).not.toContain('humidity')
    expect(keys).not.toContain('pressure')
    expect(keys).not.toContain('visibility')
  })

  it('drops metrics whose underlying value is missing', () => {
    const metrics = buildMetrics({ wind_speed: null, units: 'metric' }, [])
    expect(metrics.map((m) => m.key)).not.toContain('wind')
  })

  it('returns nothing at all for an absent payload', () => {
    expect(buildMetrics(null, null)).toEqual([])
  })
})

describe('rainfall cells', () => {
  it('states the unit for the column legend', () => {
    expect(rainfallUnit('metric')).toBe('mm')
    expect(rainfallUnit('imperial')).toBe('in')
  })

  it('shows a bare figure, leaving the unit to the legend', () => {
    const cell = rainfallCell(1.9, 'metric')
    expect(cell.text).toBe('1.9')
    expect(cell.dry).toBe(false)
    // ...but assistive tech still gets the whole phrase.
    expect(cell.label).toBe('1.9 millimetres of rain')
  })

  it('marks a dry day explicitly instead of rendering nothing', () => {
    // Weather-AI returns 0.0 for dry days - a known value, not missing data.
    const cell = rainfallCell(0, 'metric')
    expect(cell.text).toBe('—')
    expect(cell.dry).toBe(true)
    expect(cell.label).toBe('No rain expected')
  })

  it('distinguishes genuinely missing data from a dry day', () => {
    expect(rainfallCell(null).label).toBe('Rainfall not available')
    expect(rainfallCell(undefined).label).toBe('Rainfall not available')
  })

  it('keeps a trace visible rather than rounding it to zero', () => {
    expect(rainfallCell(0.1).text).toBe('0.1')
    expect(rainfallCell(0.1).dry).toBe(false)
  })

  it('rounds larger totals and speaks the right unit', () => {
    expect(rainfallCell(12.6).text).toBe('13')
    expect(rainfallCell(2.5, 'imperial').label).toBe('2.5 inches of rain')
  })
})

describe('forecast time formatting', () => {
  it('renders naive local timestamps without shifting them', () => {
    // Upstream sends East Africa wall-clock with no offset; 15:00 must stay 3 PM.
    expect(formatHour('2026-08-20T15:00')).toBe('3 PM')
    expect(formatHour('2026-08-20T00:00')).toBe('12 AM')
    expect(formatHour('2026-08-20T12:00')).toBe('12 PM')
  })

  it('rejects malformed timestamps rather than printing NaN', () => {
    expect(formatHour('not-a-time')).toBeNull()
    expect(formatHour(null)).toBeNull()
  })

  it('names the first two days relatively', () => {
    expect(formatDayName('2026-08-20', 0)).toBe('Today')
    expect(formatDayName('2026-08-21', 1)).toBe('Tomorrow')
    expect(formatDayName('2026-08-22', 2)).toBe('Saturday')
  })
})

describe('temperature bars', () => {
  const week = [
    { temp_min: 15, temp_max: 26 },
    { temp_min: 14, temp_max: 28 },
  ]

  it('spans the week range', () => {
    expect(weekRange(week)).toEqual({ weekMin: 14, weekMax: 28 })
  })

  it('positions a day inside that range', () => {
    const { weekMin, weekMax } = weekRange(week)
    const bar = temperatureBar(week[0], weekMin, weekMax)
    expect(bar.left).toBeCloseTo((1 / 14) * 100, 1)
    expect(bar.width).toBeCloseTo((11 / 14) * 100, 1)
  })

  it('returns null when a day has no temperatures', () => {
    expect(temperatureBar({ temp_min: null, temp_max: null }, 14, 28)).toBeNull()
  })

  it('survives a flat week without dividing by zero', () => {
    const bar = temperatureBar({ temp_min: 20, temp_max: 20 }, 20, 20)
    expect(bar).toEqual({ left: 0, width: 100 })
  })
})

describe('age wording', () => {
  it('rounds down so freshness is never overstated', () => {
    expect(formatAge(0)).toBe('just now')
    expect(formatAge(59)).toBe('just now')
    expect(formatAge(119)).toBe('1 minute ago')
    expect(formatAge(840)).toBe('14 minutes ago')
    expect(formatAge(3600)).toBe('1 hour ago')
    expect(formatAge(7199)).toBe('1 hour ago')
    expect(formatAge(90000)).toBe('1 day ago')
  })

  it('rejects nonsense rather than printing it', () => {
    expect(formatAge(-5)).toBeNull()
    expect(formatAge('soon')).toBeNull()
  })
})

describe('staleness notice', () => {
  it('is absent for fresh data', () => {
    expect(stalenessNotice({ is_stale: false, age_seconds: 10 })).toBeNull()
  })

  it('distinguishes a quota pause from an outage', () => {
    const limited = stalenessNotice({
      is_stale: true,
      age_seconds: 840,
      fallback_reason: 'rate_limited',
    })
    expect(limited).toMatch(/paused/i)
    expect(limited).toMatch(/14 minutes ago/)

    const down = stalenessNotice({
      is_stale: true,
      age_seconds: 300,
      fallback_reason: 'upstream_unavailable',
    })
    expect(down).toMatch(/could not refresh/i)
  })
})

describe('error messages', () => {
  it('maps known codes to specific guidance', () => {
    expect(messageForError({ code: 'unknown_location' }).body).toMatch(/counties and major towns/i)
    expect(messageForError({ code: 'network_error' }).title).toMatch(/no connection/i)
  })

  it('falls back safely for an unrecognised code', () => {
    expect(messageForError({ code: 'something_new' }).title).toBe('Something went wrong')
    expect(messageForError(null).title).toBe('Something went wrong')
  })
})

describe('weather theme', () => {
  it('returns the idle atmosphere with no weather', () => {
    expect(resolveTheme(null)).toBe(IDLE_THEME)
  })

  it('selects effect and density from condition and intensity', () => {
    const heavyRain = resolveTheme({
      condition_group: 'rain',
      condition_intensity: 'heavy',
      is_day: true,
    })
    expect(heavyRain.effect).toBe('rain')
    expect(heavyRain.rainDrops).toBe(RAIN_DENSITY.heavy)

    const lightRain = resolveTheme({
      condition_group: 'rain',
      condition_intensity: 'light',
      is_day: true,
    })
    expect(lightRain.rainDrops).toBeLessThan(heavyRain.rainDrops)
  })

  it('switches to a night sky when the API reports night', () => {
    const night = resolveTheme({ condition_group: 'clear', is_day: false })
    expect(night.isDay).toBe(false)
    expect(night.effect).toBe('stars')

    const day = resolveTheme({ condition_group: 'clear', is_day: true })
    expect(day.effect).toBe('sun')
    expect(day.sky).not.toEqual(night.sky)
  })

  it('assumes day when the API omits is_day, since a wrongly dark UI reads as broken', () => {
    expect(resolveTheme({ condition_group: 'clear' }).isDay).toBe(true)
  })

  it('falls back to a neutral sky for an unrecognised condition', () => {
    const theme = resolveTheme({ condition_group: 'meteor_shower', is_day: true })
    expect(theme.sky).toHaveLength(3)
    expect(theme.effect).toBe('none')
  })

  it('gives storms their own treatment', () => {
    expect(resolveTheme({ condition_group: 'thunderstorm', is_day: true }).effect).toBe('storm')
  })
})
