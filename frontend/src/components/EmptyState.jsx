import Logo from './Logo'

/**
 * The first thing anyone sees.
 *
 * It has one job: make "Anga" mean something in the two seconds before the
 * visitor decides whether to type. So it leads with the word itself and what it
 * means, sets it in the display face at full size, and puts a warm equatorial
 * sky behind it — rather than opening with a bare input and a generic heading.
 *
 * Deliberately NOT done here: showing live weather for the suggested towns.
 * Six cities on the landing page would be six upstream calls every 30 minutes -
 * roughly 288 a day against a budget of 33. A beautiful landing page that quietly
 * bankrupts the quota would contradict the entire point of the backend. The
 * chips are invitations, not readings.
 */
export default function EmptyState({ suggestions = [], onSelect }) {
  return (
    <section className="welcome">
      <div className="welcome__mark">
        <Logo size={64} />
      </div>

      <h1 className="welcome__title">
        Anga
        <span className="welcome__meaning">
          <span className="welcome__meaning-line" aria-hidden="true" />
          Swahili for <em>sky</em>
        </span>
      </h1>

      <p className="welcome__lede">
        Weather for every Kenyan county and town — the hour ahead, the week ahead,
        and an honest answer about how fresh it is.
      </p>

      {suggestions.length > 0 && (
        <div className="welcome__starters">
          <p className="welcome__starters-label">Start somewhere</p>
          <div className="welcome__chips">
            {suggestions.map((place) => (
              <button
                key={place.slug}
                type="button"
                className="chip"
                onClick={() => onSelect(place.slug, place.label)}
              >
                {place.name}
              </button>
            ))}
          </div>
        </div>
      )}

      <ul className="welcome__points">
        <li>
          <PointIcon name="clock" />
          <span>Hourly outlook and a 7-day forecast</span>
        </li>
        <li>
          <PointIcon name="sky" />
          <span>The sky behind the numbers changes with the weather</span>
        </li>
        <li>
          <PointIcon name="shield" />
          <span>Cached server-side, so it stays fast and never overstates its age</span>
        </li>
      </ul>
    </section>
  )
}

const POINTS = {
  clock: (
    <>
      <circle cx="12" cy="12" r="8.4" />
      <path d="M12 7.6V12l3 1.8" strokeLinecap="round" />
    </>
  ),
  sky: (
    <>
      <circle cx="9" cy="9.4" r="3.2" />
      <path d="M6.6 17.6h9.6a3.3 3.3 0 0 0 .4-6.6 4.9 4.9 0 0 0-9.3-1.1 3.5 3.5 0 0 0-.7 7.7z" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3.6 19 6.4v5.2c0 4.2-2.9 7.4-7 8.8-4.1-1.4-7-4.6-7-8.8V6.4z" />
      <path d="M9.2 12.2 11.3 14.4 15 10.6" strokeLinecap="round" strokeLinejoin="round" />
    </>
  ),
}

function PointIcon({ name }) {
  return (
    <svg
      className="welcome__point-icon"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
    >
      {POINTS[name]}
    </svg>
  )
}
