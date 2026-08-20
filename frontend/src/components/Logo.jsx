import { useId } from 'react'

/**
 * The Anga mark: a sun low over a horizon, under an open sky.
 *
 * "Anga" is Swahili for sky, so the mark is the sky itself rather than a
 * weather symbol - a thermometer or a cloud would tie the brand to one
 * condition, and this product shows all of them. The horizon band and the low
 * sun read as the equatorial light Kenya actually gets: a fast dawn, a high
 * hard noon, a fast dusk.
 *
 * Built to survive being small. At 20px the sun and horizon still separate,
 * because they differ in value and not only in hue.
 */
export default function Logo({ size = 34, className = '' }) {
  const id = useId().replace(/:/g, '')

  return (
    <svg
      viewBox="0 0 40 40"
      width={size}
      height={size}
      className={`logo ${className}`}
      role="img"
      aria-label="Anga"
    >
      <defs>
        <linearGradient id={`${id}-sky`} x1="50%" y1="0%" x2="50%" y2="100%">
          <stop offset="0%" stopColor="#16325A" />
          <stop offset="48%" stopColor="#3E76A8" />
          <stop offset="82%" stopColor="#E2A254" />
          <stop offset="100%" stopColor="#F0C070" />
        </linearGradient>
        <radialGradient id={`${id}-sun`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#FFF6DC" />
          <stop offset="55%" stopColor="#FFD066" />
          <stop offset="100%" stopColor="#F09A2E" />
        </radialGradient>
        <clipPath id={`${id}-clip`}>
          <rect x="0" y="0" width="40" height="40" rx="11" />
        </clipPath>
      </defs>

      <g clipPath={`url(#${id}-clip)`}>
        <rect x="0" y="0" width="40" height="40" fill={`url(#${id}-sky)`} />

        {/* Sun sitting on the horizon, half-swallowed by it. */}
        <circle cx="20" cy="27.5" r="7.6" fill={`url(#${id}-sun)`} />

        {/* Horizon haze: the band that makes the sun read as *setting*. */}
        <rect x="0" y="28.6" width="40" height="11.4" fill="#B9762E" opacity="0.34" />
        <rect x="0" y="28.2" width="40" height="1.1" fill="#FFE1A8" opacity="0.75" />

        {/* Two thin clouds, high and small, for depth. */}
        <rect x="6.5" y="11" width="12" height="2.1" rx="1.05" fill="#FFFFFF" opacity="0.5" />
        <rect x="21" y="16.4" width="9" height="1.9" rx="0.95" fill="#FFFFFF" opacity="0.34" />
      </g>

      {/* Inner hairline keeps the mark crisp on light and dark alike. */}
      <rect
        x="0.6"
        y="0.6"
        width="38.8"
        height="38.8"
        rx="10.4"
        fill="none"
        stroke="#FFFFFF"
        strokeOpacity="0.18"
      />
    </svg>
  )
}
