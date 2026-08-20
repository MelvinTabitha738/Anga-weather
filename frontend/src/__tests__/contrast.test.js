import { describe, expect, it } from 'vitest'

import { IDLE_THEME, resolveTheme, scrimAlphaFor, themeToCssVars } from '../lib/weatherTheme'

/**
 * Legibility must not depend on the weather.
 *
 * This is a real regression guard, not a formality: a fixed scrim produced 20
 * WCAG failures across the daytime palettes, including primary text at 3.63:1
 * over the fog sky. The scrim is now solved per sky, and this test recomputes
 * the actual contrast the browser will render for every theme, every gradient
 * stop, and every step of the text ramp.
 *
 * Any new sky added to weatherTheme.js is covered automatically.
 */

const SCRIM_RGB = [6, 10, 16]

// The text ramp from index.css, with the ratio each must clear.
// --ink-faint is only used at large or secondary sizes, so it targets 3:1.
const INK = [
  { name: '--ink', alpha: 0.97, required: 4.5 },
  { name: '--ink-muted', alpha: 0.72, required: 4.5 },
  { name: '--ink-faint', alpha: 0.52, required: 3.0 },
]

const hexToRgb = (hex) =>
  [0, 2, 4].map((i) => parseInt(String(hex).replace('#', '').slice(i, i + 2), 16))

const toLinear = (v) => {
  const c = v / 255
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

const luminance = ([r, g, b]) =>
  0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b)

const over = (fg, alpha, bg) => fg.map((c, i) => c * alpha + bg[i] * (1 - alpha))

const contrast = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

/** Every condition, day and night, plus the idle sky. */
const GROUPS = [
  'clear', 'partly_cloudy', 'cloudy', 'fog',
  'drizzle', 'rain', 'thunderstorm', 'unknown',
]

function allThemes() {
  const themes = [{ label: 'idle', theme: IDLE_THEME }]
  for (const group of GROUPS) {
    for (const isDay of [true, false]) {
      themes.push({
        label: `${group}-${isDay ? 'day' : 'night'}`,
        theme: resolveTheme({ condition_group: group, is_day: isDay }),
      })
    }
  }
  return themes
}

describe('text stays legible over every sky', () => {
  it.each(allThemes())('$label', ({ theme }) => {
    const vars = themeToCssVars(theme)
    const stops = [
      ['top', vars['--sky-top'], vars['--scrim-top']],
      ['mid', vars['--sky-mid'], vars['--scrim-mid']],
      ['bottom', vars['--sky-bottom'], vars['--scrim-bottom']],
    ]

    for (const [where, skyHex, scrimAlpha] of stops) {
      const background = over(SCRIM_RGB, scrimAlpha, hexToRgb(skyHex))

      for (const { name, alpha, required } of INK) {
        const text = over([255, 255, 255], alpha, background)
        const ratio = contrast(text, background)

        expect(
          ratio,
          `${name} over ${skyHex} (${where}, scrim ${scrimAlpha}) = ${ratio.toFixed(2)}:1`,
        ).toBeGreaterThanOrEqual(required)
      }
    }
  })
})

describe('the scrim adapts rather than smothering', () => {
  it('emits a scrim alpha for every gradient stop', () => {
    const vars = themeToCssVars(resolveTheme({ condition_group: 'clear', is_day: true }))
    for (const key of ['--scrim-top', '--scrim-mid', '--scrim-bottom']) {
      expect(typeof vars[key]).toBe('number')
      expect(vars[key]).toBeGreaterThan(0)
      expect(vars[key]).toBeLessThanOrEqual(0.74)
    }
  })

  it('veils a bright sky more heavily than a dark one', () => {
    // The whole point: a night sky keeps its depth, a noon sky gets what it needs.
    const brightNoon = scrimAlphaFor('#A8CBE6')
    const midnight = scrimAlphaFor('#070D1A')
    expect(brightNoon).toBeGreaterThan(midnight)
  })

  it('never goes fully transparent, even over the darkest sky', () => {
    // Some veil is always needed: the rain canvas and star field sit above the
    // sky and would otherwise compete with the text.
    expect(scrimAlphaFor('#000000')).toBeGreaterThanOrEqual(0.16)
  })

  it('is deterministic and cached', () => {
    expect(scrimAlphaFor('#5E9BD6')).toBe(scrimAlphaFor('#5E9BD6'))
  })
})
