import { useMemo } from 'react'

import {
  EFFECT_CLOUDS,
  EFFECT_FOG,
  EFFECT_RAIN,
  EFFECT_STARS,
  EFFECT_STORM,
  EFFECT_SUN,
  themeToCssVars,
} from '../../lib/weatherTheme'
import RainCanvas from './RainCanvas'

/**
 * The atmosphere behind everything.
 *
 * Two modes:
 *
 * PHOTO - the landing page. A photograph of Mount Kenya at dusk, drifting
 *   slowly so the sky is alive rather than a still. There is no weather to
 *   react to before a location is chosen, so this is where the brand lives.
 *
 * REACTIVE - once a location is loaded. Layers, back to front: the sky
 *   gradient from the theme's three stops, a glow for sun/moon/storm light, the
 *   effect layer (clouds / stars / rain / fog), and the scrim.
 *
 * The scrim is the constant. Its alphas are solved per sky in weatherTheme.js;
 * the photograph gets its own, measured against the brightest pixel that falls
 * under text (a sunlit cloud at luminance 0.84, which needs 0.66 to carry
 * --ink-muted past 4.5:1).
 *
 * All decorative, so the whole thing is aria-hidden. The weather is conveyed
 * in text by the components above it, not by these visuals alone.
 */
export default function Backdrop({ theme, photo = false }) {
  const style = useMemo(() => themeToCssVars(theme), [theme])

  const showClouds = theme.effect === EFFECT_CLOUDS || theme.effect === EFFECT_STORM
  const showRain = theme.effect === EFFECT_RAIN || theme.effect === EFFECT_STORM
  const isStorm = theme.effect === EFFECT_STORM

  if (photo) {
    return (
      <div
        className="backdrop backdrop--photo"
        aria-hidden="true"
        data-testid="backdrop"
        data-effect="photo"
        data-intensity="none"
      >
        <div className="backdrop__photo" />
        <div className="backdrop__photo-scrim" />
        {/* Above the scrim, deliberately. Underneath it these were being
            washed out by a veil reaching 0.748 over the text column - about
            4% of their opacity survived, which is invisible. A mask fades
            them out across that column instead, so they read clearly over the
            sky without touching the contrast behind the words. */}
        <div className="backdrop__wisps">
          <span className="wisp wisp--a" />
          <span className="wisp wisp--b" />
          <span className="wisp wisp--c" />
          <span className="wisp wisp--d" />
        </div>
      </div>
    )
  }

  return (
    <div
      className={`backdrop backdrop--${theme.group} ${theme.isDay ? 'is-day' : 'is-night'}`}
      style={style}
      aria-hidden="true"
      data-testid="backdrop"
      data-effect={theme.effect}
      data-intensity={theme.intensity}
    >
      <div className="backdrop__sky" />
      <div className="backdrop__glow" />

      {theme.effect === EFFECT_SUN && <div className="backdrop__sun" />}
      {theme.effect === EFFECT_STARS && <Stars />}
      {theme.effect === EFFECT_FOG && <div className="backdrop__fog" />}

      {showClouds && (
        <div className="backdrop__clouds">
          <span className="cloud cloud--a" />
          <span className="cloud cloud--b" />
          <span className="cloud cloud--c" />
        </div>
      )}

      {showRain && <RainCanvas dropCount={theme.rainDrops} stormy={isStorm} />}
      {isStorm && <div className="backdrop__lightning" />}

      <div className="backdrop__scrim" />
    </div>
  )
}

/**
 * A fixed star field. Positions are deterministic rather than random so the
 * sky does not reshuffle on every re-render, which reads as flicker.
 */
const STAR_SEEDS = [
  [8, 14, 1.6, 0], [17, 32, 1.1, 1.4], [24, 9, 1.9, 0.7], [31, 41, 1.2, 2.1],
  [39, 18, 1.5, 0.3], [46, 6, 1.0, 1.8], [52, 28, 1.7, 1.1], [58, 47, 1.2, 2.6],
  [63, 12, 1.4, 0.5], [69, 35, 1.8, 1.6], [74, 21, 1.1, 2.3], [81, 8, 1.6, 0.9],
  [86, 39, 1.3, 1.9], [91, 17, 1.5, 0.2], [95, 30, 1.1, 2.8], [12, 45, 1.3, 1.2],
  [35, 52, 1.0, 0.6], [55, 15, 1.2, 2.4], [78, 50, 1.4, 1.5], [4, 27, 1.2, 2.0],
]

function Stars() {
  return (
    <div className="backdrop__stars">
      <span className="moon" />
      {STAR_SEEDS.map(([left, top, size, delay], index) => (
        <span
          key={index}
          className="star"
          style={{
            left: `${left}%`,
            top: `${top}%`,
            width: `${size}px`,
            height: `${size}px`,
            animationDelay: `${delay}s`,
          }}
        />
      ))}
    </div>
  )
}
