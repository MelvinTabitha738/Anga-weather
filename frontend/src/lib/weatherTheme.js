/**
 * Weather-state -> visual atmosphere.
 *
 * The backend classifies every upstream response into a small stable
 * vocabulary (condition_group + condition_intensity + is_day). This module is
 * the single place that turns that vocabulary into an atmosphere: sky colours,
 * which animated effect to run, and how strongly to run it.
 *
 * Components never branch on weather conditions themselves - they read a theme
 * from here. Adding a new condition means editing one table, not hunting
 * through JSX.
 *
 * Contrast note: every sky is paired with a dark scrim (see backdrop.css) and
 * text is always near-white. That keeps body text comfortably above 4.5:1 on
 * bright midday skies as well as night ones, instead of leaving contrast to
 * chance per palette.
 */

export const EFFECT_NONE = 'none'
export const EFFECT_SUN = 'sun'
export const EFFECT_CLOUDS = 'clouds'
export const EFFECT_RAIN = 'rain'
export const EFFECT_STORM = 'storm'
export const EFFECT_STARS = 'stars'
export const EFFECT_FOG = 'fog'

/** Rain particle counts per intensity. Deliberately modest - a believable
 *  shower, not a performance problem on a mid-range phone. */
export const RAIN_DENSITY = {
  none: 0,
  light: 70,
  moderate: 160,
  heavy: 320,
}

const DAY_THEMES = {
  clear: {
    sky: ['#2F6FB4', '#5E9BD6', '#A8CBE6'],
    glow: 'rgba(255, 214, 148, 0.55)',
    effect: EFFECT_SUN,
    label: 'Clear',
  },
  partly_cloudy: {
    sky: ['#3A6FA5', '#6E9AC2', '#AFC5D6'],
    glow: 'rgba(255, 226, 178, 0.35)',
    effect: EFFECT_CLOUDS,
    label: 'Partly cloudy',
  },
  cloudy: {
    sky: ['#5A6B7B', '#7E8D9B', '#A9B4BD'],
    glow: 'rgba(255, 255, 255, 0.16)',
    effect: EFFECT_CLOUDS,
    label: 'Cloudy',
  },
  fog: {
    sky: ['#77828A', '#9AA4AB', '#BEC5C9'],
    glow: 'rgba(255, 255, 255, 0.22)',
    effect: EFFECT_FOG,
    label: 'Fog',
  },
  drizzle: {
    sky: ['#4A5A69', '#6B7B8A', '#8E9BA7'],
    glow: 'rgba(255, 255, 255, 0.12)',
    effect: EFFECT_RAIN,
    label: 'Drizzle',
  },
  rain: {
    sky: ['#33404E', '#4E606F', '#71838F'],
    glow: 'rgba(255, 255, 255, 0.10)',
    effect: EFFECT_RAIN,
    label: 'Rain',
  },
  thunderstorm: {
    sky: ['#1E252F', '#333D49', '#4A5561'],
    glow: 'rgba(180, 200, 255, 0.14)',
    effect: EFFECT_STORM,
    label: 'Thunderstorm',
  },
  unknown: {
    sky: ['#3C4A5A', '#5A6A7A', '#818E9B'],
    glow: 'rgba(255, 255, 255, 0.12)',
    effect: EFFECT_NONE,
    label: 'Weather',
  },
}

const NIGHT_THEMES = {
  clear: {
    sky: ['#070D1A', '#12203A', '#243755'],
    glow: 'rgba(150, 180, 235, 0.22)',
    effect: EFFECT_STARS,
    label: 'Clear night',
  },
  partly_cloudy: {
    sky: ['#0B1322', '#1A2739', '#2C3C52'],
    glow: 'rgba(150, 180, 235, 0.18)',
    effect: EFFECT_STARS,
    label: 'Partly cloudy',
  },
  cloudy: {
    sky: ['#121820', '#202934', '#323C48'],
    glow: 'rgba(255, 255, 255, 0.08)',
    effect: EFFECT_CLOUDS,
    label: 'Cloudy',
  },
  fog: {
    sky: ['#161C22', '#262E36', '#3A434C'],
    glow: 'rgba(255, 255, 255, 0.10)',
    effect: EFFECT_FOG,
    label: 'Fog',
  },
  drizzle: {
    sky: ['#0E1620', '#1C2732', '#2C3945'],
    glow: 'rgba(255, 255, 255, 0.07)',
    effect: EFFECT_RAIN,
    label: 'Drizzle',
  },
  rain: {
    sky: ['#0A111A', '#17222E', '#26333F'],
    glow: 'rgba(255, 255, 255, 0.06)',
    effect: EFFECT_RAIN,
    label: 'Rain',
  },
  thunderstorm: {
    sky: ['#05090F', '#101720', '#1D262F'],
    glow: 'rgba(180, 200, 255, 0.12)',
    effect: EFFECT_STORM,
    label: 'Thunderstorm',
  },
  unknown: {
    sky: ['#0D141E', '#1B2531', '#2A3543'],
    glow: 'rgba(255, 255, 255, 0.08)',
    effect: EFFECT_NONE,
    label: 'Weather',
  },
}

/**
 * The sky before any weather has loaded.
 *
 * Deliberately not neutral. This is the first impression, and a flat grey-blue
 * says nothing about where you are. An equatorial dawn - deep indigo overhead
 * falling to amber at the horizon - is the light Kenya actually gets, and it
 * gives the word "Anga" something to mean before a single number arrives.
 */
export const IDLE_THEME = {
  key: 'idle',
  group: 'unknown',
  intensity: 'none',
  isDay: true,
  sky: ['#14294A', '#3A5F87', '#C97F3F'],
  glow: 'rgba(255, 196, 120, 0.34)',
  effect: EFFECT_NONE,
  rainDrops: 0,
  label: 'Anga',
}

/**
 * Build the visual theme for a weather payload.
 *
 * Tolerates a missing or partial payload: an unknown condition falls back to a
 * neutral sky rather than throwing, because a backdrop must always render.
 */
export function resolveTheme(weather) {
  if (!weather) return IDLE_THEME

  const group = weather.condition_group || 'unknown'
  const intensity = weather.condition_intensity || 'none'
  // is_day may legitimately be null when upstream omits it; daytime is the
  // safer default because a wrongly dark UI reads as broken.
  const isDay = weather.is_day !== false

  const table = isDay ? DAY_THEMES : NIGHT_THEMES
  const base = table[group] || table.unknown

  return {
    key: `${group}-${isDay ? 'day' : 'night'}-${intensity}`,
    group,
    intensity,
    isDay,
    sky: base.sky,
    glow: base.glow,
    effect: base.effect,
    rainDrops: RAIN_DENSITY[intensity] ?? RAIN_DENSITY.light,
    label: base.label,
  }
}

/** CSS custom properties consumed by backdrop.css and the layout. */
export function themeToCssVars(theme) {
  return {
    '--sky-top': theme.sky[0],
    '--sky-mid': theme.sky[1],
    '--sky-bottom': theme.sky[2],
    '--sky-glow': theme.glow,
  }
}
