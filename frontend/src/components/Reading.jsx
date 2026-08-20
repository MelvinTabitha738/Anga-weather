import { buildDetails, formatTemperature, formatTemperatureWithUnit } from '../lib/format'
import { formatAge, stalenessNotice } from '../lib/messages'

/**
 * The weather reading itself.
 *
 * Two commitments here:
 *
 * 1. Nothing is invented. Detail cells are built from what the API actually
 *    returned, so a field Weather-AI omits produces no cell rather than a
 *    placeholder dash.
 * 2. Freshness is never overstated. Cached and stale readings say so in words,
 *    not just colour, and stale data carries an explicit notice above it.
 */
export default function Reading({ data }) {
  const { location, weather, meta } = data
  const details = buildDetails(weather)
  const notice = stalenessNotice(meta)

  const temperature = formatTemperature(weather.temperature)
  const accessibleTemperature = formatTemperatureWithUnit(weather.temperature, weather.units)

  return (
    <section className="reading" aria-labelledby="reading-place">
      {notice && (
        <div className="notice" role="status">
          <InfoIcon />
          <span>{notice}</span>
        </div>
      )}

      <h1 className="reading__place" id="reading-place">
        {location.kind !== 'county' && location.county && (
          <span className="reading__county">{location.county} County</span>
        )}
        {location.name}
      </h1>

      <div className="reading__temperature">
        {temperature ? (
          <p className="reading__degrees">
            <span aria-hidden="true">{temperature}</span>
            <span className="visually-hidden">{accessibleTemperature}</span>
          </p>
        ) : (
          <p className="reading__degrees" aria-label="Temperature unavailable">
            —
          </p>
        )}
        {weather.condition && <p className="reading__condition">{weather.condition}</p>}
      </div>

      {details.length > 0 && (
        <dl className="details">
          {details.map((detail) => (
            <div className="details__item" key={detail.key}>
              <dt className="details__label">{detail.label}</dt>
              <dd className="details__value">
                {detail.value}
                {detail.hint && <span className="details__hint"> {detail.hint}</span>}
              </dd>
            </div>
          ))}
        </dl>
      )}

      <Freshness meta={meta} />
    </section>
  )
}

/**
 * One honest line about where this reading came from and how old it is.
 * `is_cached` is not hidden from the user - a cache hit is a feature, and
 * saying so is what makes the "stale" state credible when it appears.
 */
function Freshness({ meta }) {
  const age = formatAge(meta.age_seconds)

  let dotClass = 'freshness__dot'
  let text

  if (meta.is_stale) {
    dotClass += ' freshness__dot--stale'
    text = `Last updated ${age} · not current`
  } else if (meta.is_cached) {
    dotClass += ' freshness__dot--cached'
    text = age === 'just now' ? 'Updated just now · cached' : `Updated ${age} · cached`
  } else {
    text = 'Updated just now · live from Weather-AI'
  }

  return (
    <p className="freshness">
      <span className={dotClass} aria-hidden="true" />
      <span>{text}</span>
    </p>
  )
}

function InfoIcon() {
  return (
    <svg
      className="notice__icon"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="6.4" />
      <path d="M8 7.4v4" strokeLinecap="round" />
      <circle cx="8" cy="5" r="0.75" fill="currentColor" stroke="none" />
    </svg>
  )
}
