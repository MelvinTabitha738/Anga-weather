import { useId } from 'react'

/**
 * Weather imagery, keyed by the backend's condition vocabulary.
 *
 * These are rendered rather than drawn: every element is built from radial and
 * linear gradients with real light direction, soft shadow under each cloud
 * form, translucent rain, and a glowing sun corona. Line art reads as a
 * diagram; shading reads as weather.
 *
 * Why SVG and not photographs or an icon pack: it stays sharp at any size,
 * inherits the page's light, weighs nothing, needs no network request, and -
 * critically for this app - can be driven by data. A photograph of a sun is
 * the same sun at 12°C and at 34°C.
 *
 * TEMPERATURE DRIVES THE LIGHT
 * ----------------------------
 * The sun's palette and glow are chosen from the actual temperature, so a cool
 * Nyahururu morning renders a pale, thin sun and a hot Garissa afternoon a
 * heavy amber one. Same condition code, different heat.
 *
 * PERFORMANCE
 * -----------
 * Blur filters are the expensive part, and a dashboard renders ~31 of these at
 * once (24 hourly + 7 daily). Filters are therefore only used above `size` 48;
 * small icons get the gradients without them, which is visually almost
 * identical at that scale and far cheaper.
 */

// --- Sun palettes, coldest to hottest -------------------------------------
const SUN_PALETTES = {
  cold: { core: '#FFFDF5', mid: '#FFE9A8', edge: '#F5C86A', glow: '#FFE9A8', glowOpacity: 0.30, rays: 0.35 },
  cool: { core: '#FFFEF6', mid: '#FFE08A', edge: '#F0AE4B', glow: '#FFDD8A', glowOpacity: 0.40, rays: 0.45 },
  mild: { core: '#FFFDF0', mid: '#FFD166', edge: '#EF9B2F', glow: '#FFC85C', glowOpacity: 0.52, rays: 0.58 },
  warm: { core: '#FFF8E4', mid: '#FFBC42', edge: '#E87A1E', glow: '#FFA83C', glowOpacity: 0.64, rays: 0.70 },
  hot:  { core: '#FFF3D8', mid: '#FFA425', edge: '#DE5B14', glow: '#FF8A2B', glowOpacity: 0.78, rays: 0.82 },
}

/** Kenyan range in practice: ~8°C on the highlands to ~38°C in the north. */
export function sunPalette(temperature) {
  // Guard null/undefined/'' explicitly: Number(null) is 0, which would render
  // a missing temperature as a freezing pale sun rather than a neutral one.
  if (temperature === null || temperature === undefined || temperature === '') {
    return SUN_PALETTES.mild
  }
  const t = Number(temperature)
  if (!Number.isFinite(t)) return SUN_PALETTES.mild
  if (t <= 13) return SUN_PALETTES.cold
  if (t <= 19) return SUN_PALETTES.cool
  if (t <= 26) return SUN_PALETTES.mild
  if (t <= 32) return SUN_PALETTES.warm
  return SUN_PALETTES.hot
}

// --- Cloud tones ----------------------------------------------------------
const CLOUD_LIGHT = { top: '#FFFFFF', bottom: '#C9D4E0' }
const CLOUD_GREY = { top: '#E4EAF1', bottom: '#9AA8B8' }
const CLOUD_DARK = { top: '#8E9AAA', bottom: '#5A6675' }
const CLOUD_STORM = { top: '#6C7688', bottom: '#3B4452' }
const CLOUD_NIGHT = { top: '#B9C4D4', bottom: '#77839A' }

function Defs({ id, sun, cloud, detail }) {
  return (
    <defs>
      <radialGradient id={`${id}-sun`} cx="42%" cy="38%" r="62%">
        <stop offset="0%" stopColor={sun.core} />
        <stop offset="52%" stopColor={sun.mid} />
        <stop offset="100%" stopColor={sun.edge} />
      </radialGradient>

      <radialGradient id={`${id}-glow`} cx="50%" cy="50%" r="50%">
        <stop offset="0%" stopColor={sun.glow} stopOpacity={sun.glowOpacity} />
        <stop offset="55%" stopColor={sun.glow} stopOpacity={sun.glowOpacity * 0.35} />
        <stop offset="100%" stopColor={sun.glow} stopOpacity="0" />
      </radialGradient>

      <linearGradient id={`${id}-cloud`} x1="30%" y1="0%" x2="60%" y2="100%">
        <stop offset="0%" stopColor={cloud.top} />
        <stop offset="100%" stopColor={cloud.bottom} />
      </linearGradient>

      <linearGradient id={`${id}-cloud-back`} x1="30%" y1="0%" x2="60%" y2="100%">
        <stop offset="0%" stopColor={cloud.top} stopOpacity="0.75" />
        <stop offset="100%" stopColor={cloud.bottom} stopOpacity="0.75" />
      </linearGradient>

      <linearGradient id={`${id}-drop`} x1="50%" y1="0%" x2="50%" y2="100%">
        <stop offset="0%" stopColor="#BFE0FF" stopOpacity="0.35" />
        <stop offset="100%" stopColor="#6FA8E8" stopOpacity="0.95" />
      </linearGradient>

      <radialGradient id={`${id}-moon`} cx="36%" cy="32%" r="70%">
        <stop offset="0%" stopColor="#FFFDF4" />
        <stop offset="60%" stopColor="#EFE7D2" />
        <stop offset="100%" stopColor="#CFC5AC" />
      </radialGradient>

      <linearGradient id={`${id}-bolt`} x1="30%" y1="0%" x2="70%" y2="100%">
        <stop offset="0%" stopColor="#FFF6C9" />
        <stop offset="55%" stopColor="#FFD34A" />
        <stop offset="100%" stopColor="#F5A312" />
      </linearGradient>

      {detail && (
        <filter id={`${id}-soft`} x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="1.1" />
        </filter>
      )}
      {detail && (
        <filter id={`${id}-shadow`} x="-40%" y="-40%" width="180%" height="200%">
          <feDropShadow dx="0" dy="1.1" stdDeviation="1.1" floodColor="#1B2430" floodOpacity="0.28" />
        </filter>
      )}
    </defs>
  )
}

/** The sun: corona glow, rays, then a lit disc. */
function Sun({ id, sun, detail, cx = 24, cy = 22, r = 9.5 }) {
  const rays = []
  for (let i = 0; i < 8; i += 1) {
    const angle = (i * Math.PI) / 4
    const inner = r + 3.2
    const outer = r + 7
    rays.push(
      <line
        key={i}
        x1={cx + Math.cos(angle) * inner}
        y1={cy + Math.sin(angle) * inner}
        x2={cx + Math.cos(angle) * outer}
        y2={cy + Math.sin(angle) * outer}
        stroke={sun.mid}
        strokeOpacity={sun.rays}
        strokeWidth="2.4"
        strokeLinecap="round"
      />,
    )
  }

  return (
    <g>
      <circle cx={cx} cy={cy} r={r + 13} fill={`url(#${id}-glow)`} />
      <g className="wicon__rays">{rays}</g>
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill={`url(#${id}-sun)`}
        filter={detail ? `url(#${id}-shadow)` : undefined}
      />
      {/* Specular highlight: the detail that stops it reading as a flat disc. */}
      <ellipse cx={cx - r * 0.3} cy={cy - r * 0.36} rx={r * 0.34} ry={r * 0.26}
               fill="#FFFFFF" opacity="0.5" />
    </g>
  )
}

function Moon({ id, detail, cx = 24, cy = 21, r = 9 }) {
  return (
    <g>
      <circle cx={cx} cy={cy} r={r + 10} fill={`url(#${id}-glow)`} opacity="0.5" />
      <circle cx={cx} cy={cy} r={r} fill={`url(#${id}-moon)`}
              filter={detail ? `url(#${id}-shadow)` : undefined} />
      {/* Craters give it scale; without them it is just a pale circle. */}
      <circle cx={cx + 2.6} cy={cy - 2.4} r="1.7" fill="#C8BEA6" opacity="0.55" />
      <circle cx={cx - 2.8} cy={cy + 1.6} r="1.2" fill="#C8BEA6" opacity="0.45" />
      <circle cx={cx + 1.2} cy={cy + 3.4} r="0.9" fill="#C8BEA6" opacity="0.4" />
    </g>
  )
}

/** A cloud built from overlapping lobes so the silhouette reads as volume. */
function Cloud({ id, detail, x = 0, y = 0, scale = 1, back = false }) {
  const fill = back ? `url(#${id}-cloud-back)` : `url(#${id}-cloud)`
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`}
       filter={detail && !back ? `url(#${id}-shadow)` : undefined}>
      <ellipse cx="17" cy="30" rx="8.5" ry="7.4" fill={fill} />
      <ellipse cx="26" cy="26.4" rx="10.6" ry="9.4" fill={fill} />
      <ellipse cx="33.5" cy="30.6" rx="7.8" ry="6.6" fill={fill} />
      <rect x="15" y="30" width="22" height="7.6" rx="3.8" fill={fill} />
    </g>
  )
}

function Drops({ id, count, streak }) {
  const xs = [16.5, 24, 31.5].slice(0, count)
  return (
    <g className="wicon__rain">
      {xs.map((x, i) => (
        <path
          key={x}
          d={
            streak
              ? `M${x} 39.5 L${x - 1.6} 45.5`
              : `M${x} 39.5 c1.5 2.1 2.3 3.3 2.3 4.3 a2.3 2.3 0 0 1-4.6 0 c0-1 .8-2.2 2.3-4.3 z`
          }
          fill={streak ? 'none' : `url(#${id}-drop)`}
          stroke={streak ? `url(#${id}-drop)` : 'none'}
          strokeWidth={streak ? 2 : 0}
          strokeLinecap="round"
          style={{ animationDelay: `${i * 0.22}s` }}
        />
      ))}
    </g>
  )
}

function Bolt({ id, detail }) {
  return (
    <g className="wicon__bolt" filter={detail ? `url(#${id}-shadow)` : undefined}>
      <path d="M25.5 37.5 L20 45.5 h4.2 L22.4 52 L29.5 43 h-4.3 z" fill={`url(#${id}-bolt)`} />
    </g>
  )
}

function Fog({ id }) {
  return (
    <g className="wicon__fog">
      <rect x="12" y="39.5" width="24" height="2.6" rx="1.3" fill="#E1E8F0" opacity="0.85" />
      <rect x="15" y="44.5" width="21" height="2.6" rx="1.3" fill="#E1E8F0" opacity="0.6" />
      <rect x="13" y="49.5" width="17" height="2.6" rx="1.3" fill="#E1E8F0" opacity="0.4" />
    </g>
  )
}

function scene(group, intensity, isDay, id, sun, detail) {
  switch (group) {
    case 'clear':
      return isDay ? <Sun id={id} sun={sun} detail={detail} /> : <Moon id={id} detail={detail} />

    case 'partly_cloudy':
      return (
        <>
          {isDay
            ? <Sun id={id} sun={sun} detail={detail} cx={30} cy={17} r={8} />
            : <Moon id={id} detail={detail} cx={30} cy={16} r={7.5} />}
          <Cloud id={id} detail={detail} y={2} scale={0.92} />
        </>
      )

    case 'cloudy':
      return (
        <>
          <Cloud id={id} detail={detail} x={5} y={-5} scale={0.66} back />
          <Cloud id={id} detail={detail} y={3} />
        </>
      )

    case 'fog':
      return (
        <>
          <Cloud id={id} detail={detail} y={-2} scale={0.95} />
          <Fog id={id} />
        </>
      )

    case 'drizzle':
      return (
        <>
          <Cloud id={id} detail={detail} y={-1} />
          <Drops id={id} count={2} />
        </>
      )

    case 'rain':
      return (
        <>
          <Cloud id={id} detail={detail} y={-1} />
          <Drops id={id} count={intensity === 'light' ? 2 : 3} streak={intensity === 'heavy'} />
        </>
      )

    case 'thunderstorm':
      return (
        <>
          <Cloud id={id} detail={detail} y={-2} />
          <Bolt id={id} detail={detail} />
        </>
      )

    case 'snow':
      return (
        <>
          <Cloud id={id} detail={detail} y={-1} />
          <g className="wicon__rain" fill="#EAF4FF">
            <circle cx="17" cy="42" r="2" />
            <circle cx="24" cy="45" r="2.2" />
            <circle cx="31" cy="42" r="2" />
          </g>
        </>
      )

    default:
      return (
        <>
          <Cloud id={id} detail={detail} y={1} scale={0.95} />
        </>
      )
  }
}

function cloudToneFor(group, isDay) {
  if (group === 'thunderstorm') return CLOUD_STORM
  if (group === 'rain') return CLOUD_DARK
  if (group === 'drizzle' || group === 'cloudy') return CLOUD_GREY
  if (!isDay) return CLOUD_NIGHT
  return CLOUD_LIGHT
}

export default function WeatherIcon({
  group = 'unknown',
  intensity = 'none',
  isDay = true,
  temperature = null,
  size = 24,
  label,
  className = '',
}) {
  // Unique per instance: a dashboard renders ~31 of these and duplicate
  // gradient ids would make every icon inherit the first one's palette.
  const id = useId().replace(/:/g, '')

  const sun = sunPalette(temperature)
  const cloud = cloudToneFor(group, isDay)
  const detail = size >= 48

  const a11y = label
    ? { role: 'img', 'aria-label': label }
    : { 'aria-hidden': 'true', focusable: 'false' }

  return (
    <svg
      viewBox="0 0 48 56"
      width={size}
      height={size * (56 / 48)}
      className={`wicon ${className}`}
      data-group={group}
      data-intensity={intensity}
      {...a11y}
    >
      <Defs id={id} sun={sun} cloud={cloud} detail={detail} />
      {scene(group, intensity, isDay, id, sun, detail)}
    </svg>
  )
}
