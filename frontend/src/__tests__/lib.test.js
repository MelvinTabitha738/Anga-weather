import { describe, expect, it } from 'vitest'

import { buildDetails, formatPrecipitation, formatTemperature, formatWind } from '../lib/format'
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

  it('builds details only from fields the API returned', () => {
    const details = buildDetails({
      temperature: 20,
      humidity: 55,
      wind_speed: null,
      uv_index: null,
      units: 'metric',
    })
    const keys = details.map((detail) => detail.key)
    expect(keys).toContain('humidity')
    expect(keys).not.toContain('wind')
    expect(keys).not.toContain('uv_index')
  })

  it('returns nothing at all for an absent payload', () => {
    expect(buildDetails(null)).toEqual([])
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
