/**
 * Weather icons, keyed by the backend's condition vocabulary.
 *
 * Drawn as inline SVG rather than emoji: emoji render differently on every
 * platform, cannot inherit colour, and make a product look assembled rather
 * than designed. These use `currentColor` so they take the surrounding text
 * colour and stay legible on every sky.
 *
 * Selection is data-driven - (condition_group, is_day) in, glyph out - so no
 * component ever branches on weather itself.
 */

const STROKE = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
}

function Sun() {
  return (
    <g {...STROKE}>
      <circle cx="12" cy="12" r="4.2" />
      <path d="M12 2.6v2.2M12 19.2v2.2M2.6 12h2.2M19.2 12h2.2M5.4 5.4l1.6 1.6M17 17l1.6 1.6M18.6 5.4L17 7M7 17l-1.6 1.6" />
    </g>
  )
}

function Moon() {
  return (
    <g {...STROKE}>
      <path d="M20 14.2A8.2 8.2 0 0 1 9.8 4a8.4 8.4 0 1 0 10.2 10.2z" />
    </g>
  )
}

/** Shared cloud body, offset so it can sit under a sun or moon. */
function Cloud({ y = 0 }) {
  return (
    <path
      {...STROKE}
      d={`M7.4 ${18.6 + y}h9.4a3.6 3.6 0 0 0 .5-7.2 5.4 5.4 0 0 0-10.3-1.3 3.9 3.9 0 0 0 .4 8.5z`}
    />
  )
}

function PartlyCloudy({ isDay }) {
  return (
    <>
      <g {...STROKE} opacity="0.95">
        {isDay ? (
          <>
            <circle cx="8.6" cy="8.4" r="3.1" />
            <path d="M8.6 2.6v1.6M2.8 8.4h1.6M4.5 4.3l1.1 1.1M12.7 4.3l-1.1 1.1" />
          </>
        ) : (
          <path d="M13.6 9.6A5.6 5.6 0 0 1 7 3.2a5.7 5.7 0 1 0 6.6 6.4z" />
        )}
      </g>
      <Cloud y={-0.6} />
    </>
  )
}

function Overcast() {
  return (
    <>
      <path
        {...STROKE}
        opacity="0.55"
        d="M6.2 12.4a3.4 3.4 0 0 1 1-6.5 4.8 4.8 0 0 1 9 .6"
      />
      <Cloud y={0.4} />
    </>
  )
}

function Fog() {
  return (
    <>
      <Cloud y={-2.2} />
      <g {...STROKE} opacity="0.75">
        <path d="M4.4 19.4h11M6.8 22h10" />
      </g>
    </>
  )
}

/** Rain body; `drops` controls how heavy it reads. */
function RainGlyph({ drops = 3, streak = false }) {
  const positions = [8.4, 12, 15.6].slice(0, drops)
  return (
    <>
      <Cloud y={-3} />
      <g {...STROKE}>
        {positions.map((x, i) => (
          <path
            key={x}
            d={streak ? `M${x} 17.4l-1.2 4.2` : `M${x} 17.6v${i === 1 ? 3.4 : 2.4}`}
          />
        ))}
      </g>
    </>
  )
}

function Thunderstorm() {
  return (
    <>
      <Cloud y={-3.4} />
      <g {...STROKE}>
        <path d="M13.2 16.6l-2.9 4h3.2l-1.4 3.2" />
        <path d="M8.2 17.4l-1 2.6" opacity="0.7" />
      </g>
    </>
  )
}

function Snow() {
  return (
    <>
      <Cloud y={-3} />
      <g {...STROKE}>
        <path d="M8.4 18.4v3M7.2 19.2l2.4 1.4M9.6 19.2l-2.4 1.4" />
        <path d="M15 18.4v3M13.8 19.2l2.4 1.4M16.2 19.2l-2.4 1.4" />
      </g>
    </>
  )
}

function Unknown() {
  return (
    <g {...STROKE}>
      <circle cx="12" cy="12" r="8.4" opacity="0.5" />
      <path d="M9.6 9.8a2.4 2.4 0 1 1 3 2.3v1.4" />
      <circle cx="12" cy="16.8" r="0.7" fill="currentColor" stroke="none" />
    </g>
  )
}

function glyphFor(group, intensity, isDay) {
  switch (group) {
    case 'clear':
      return isDay ? <Sun /> : <Moon />
    case 'partly_cloudy':
      return <PartlyCloudy isDay={isDay} />
    case 'cloudy':
      return <Overcast />
    case 'fog':
      return <Fog />
    case 'drizzle':
      return <RainGlyph drops={2} />
    case 'rain':
      return (
        <RainGlyph
          drops={intensity === 'light' ? 2 : 3}
          streak={intensity === 'heavy'}
        />
      )
    case 'thunderstorm':
      return <Thunderstorm />
    case 'snow':
      return <Snow />
    default:
      return <Unknown />
  }
}

export default function WeatherIcon({
  group = 'unknown',
  intensity = 'none',
  isDay = true,
  size = 24,
  label,
  className = '',
}) {
  // Decorative unless given a label, in which case it carries the meaning.
  const a11y = label
    ? { role: 'img', 'aria-label': label }
    : { 'aria-hidden': 'true', focusable: 'false' }

  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={`wicon ${className}`}
      data-group={group}
      {...a11y}
    >
      {glyphFor(group, intensity, isDay)}
    </svg>
  )
}
