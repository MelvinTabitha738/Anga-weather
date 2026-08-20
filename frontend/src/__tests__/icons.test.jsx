import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import WeatherIcon, { sunPalette } from '../components/WeatherIcon'

/**
 * The icons are data-driven, not decorative: the same condition renders
 * differently depending on how hot it is.
 */

describe('temperature drives the sun', () => {
  it('gets warmer and brighter as the temperature climbs', () => {
    const cold = sunPalette(10)
    const mild = sunPalette(22)
    const hot = sunPalette(35)

    // Glow strength should increase monotonically with heat.
    expect(cold.glowOpacity).toBeLessThan(mild.glowOpacity)
    expect(mild.glowOpacity).toBeLessThan(hot.glowOpacity)

    // And the rays with it.
    expect(cold.rays).toBeLessThan(hot.rays)

    // A cold sun is pale; a hot one is not the same colour.
    expect(cold.mid).not.toBe(hot.mid)
  })

  it('covers the Kenyan range, highlands to the north', () => {
    // ~8C on the Aberdares to ~38C in Turkana.
    for (const t of [8, 14, 20, 27, 33, 38]) {
      const p = sunPalette(t)
      expect(p.glowOpacity).toBeGreaterThan(0)
      expect(p.core).toMatch(/^#/)
    }
  })

  it('falls back to a mid palette when temperature is unknown', () => {
    const fallback = sunPalette(null)
    expect(fallback).toEqual(sunPalette(22))
    expect(sunPalette(undefined)).toEqual(fallback)
    expect(sunPalette('warm')).toEqual(fallback)
  })
})

describe('rendering', () => {
  it('exposes the condition and intensity as data attributes', () => {
    const { container } = render(
      <WeatherIcon group="rain" intensity="heavy" temperature={19} label="Heavy rain" />,
    )
    const svg = container.querySelector('svg.wicon')
    expect(svg).toHaveAttribute('data-group', 'rain')
    expect(svg).toHaveAttribute('data-intensity', 'heavy')
  })

  it('is labelled for assistive tech when given a label, hidden otherwise', () => {
    const { rerender, container } = render(<WeatherIcon group="clear" label="Clear sky" />)
    expect(screen.getByRole('img', { name: 'Clear sky' })).toBeInTheDocument()

    rerender(<WeatherIcon group="clear" />)
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })

  it('gives each instance unique gradient ids', () => {
    // Duplicate ids would make every icon inherit the first one's palette -
    // a real hazard when the dashboard renders ~31 of them.
    const { container } = render(
      <>
        <WeatherIcon group="clear" temperature={10} />
        <WeatherIcon group="clear" temperature={35} />
      </>,
    )
    const ids = [...container.querySelectorAll('linearGradient, radialGradient')].map((n) => n.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('renders every condition group without throwing', () => {
    for (const g of ['clear', 'partly_cloudy', 'cloudy', 'fog', 'drizzle',
                     'rain', 'thunderstorm', 'snow', 'unknown']) {
      for (const isDay of [true, false]) {
        const { container, unmount } = render(
          <WeatherIcon group={g} isDay={isDay} temperature={24} />,
        )
        expect(container.querySelector('svg.wicon')).toBeTruthy()
        unmount()
      }
    }
  })
})
