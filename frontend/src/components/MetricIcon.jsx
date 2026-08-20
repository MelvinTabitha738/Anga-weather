/**
 * Small glyphs for the at-a-glance metric cards.
 *
 * Only four exist, because only four metrics are derivable from what
 * Weather-AI returns. There is deliberately no humidity, pressure or
 * visibility icon here - adding one would invite adding the card.
 */

const STROKE = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
}

const GLYPHS = {
  wind: (
    <g {...STROKE}>
      <path d="M3 8.5h9.2a2.6 2.6 0 1 0-2.6-2.6" />
      <path d="M3 12.5h13a2.6 2.6 0 1 1-2.6 2.6" />
      <path d="M3 16.5h6" />
    </g>
  ),
  drop: (
    <g {...STROKE}>
      <path d="M12 3.4s5.2 5.8 5.2 9.2a5.2 5.2 0 0 1-10.4 0C6.8 9.2 12 3.4 12 3.4z" />
    </g>
  ),
  umbrella: (
    <g {...STROKE}>
      <path d="M12 4.2a8 8 0 0 1 8 8H4a8 8 0 0 1 8-8z" />
      <path d="M12 12.2v6a2 2 0 0 1-4 0" />
    </g>
  ),
  range: (
    <g {...STROKE}>
      <path d="M7 16.4V6.8M7 6.8 4.4 9.4M7 6.8l2.6 2.6" />
      <path d="M17 7.6V17.2M17 17.2l2.6-2.6M17 17.2l-2.6-2.6" />
    </g>
  ),
}

/** Standalone droplet, used to label the rainfall columns in the forecasts. */
export function RainDropIcon({ size = 12, className = '' }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <path {...STROKE} d="M12 3.4s5.2 5.8 5.2 9.2a5.2 5.2 0 0 1-10.4 0C6.8 9.2 12 3.4 12 3.4z" />
    </svg>
  )
}

export default function MetricIcon({ name, size = 18 }) {
  const glyph = GLYPHS[name]
  if (!glyph) return null

  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className="metric__icon"
      aria-hidden="true"
      focusable="false"
    >
      {glyph}
    </svg>
  )
}
