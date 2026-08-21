/**
 * The landing page.
 *
 * Laid out to the supplied design: eyebrow, a two-line display headline with
 * the second line in warm amber, a short lede, the search, a row of starting
 * points, and three feature panels above the footer — over a photograph of
 * Mount Kenya at dusk.
 *
 * The design's "right now over Nairobi" card is deliberately absent. Showing a
 * live reading before anyone has searched would mean fetching weather on every
 * landing view, and on a 1,000-request MONTHLY quota that is the single most
 * expensive thing this product could do. The layout gives the space back to the
 * photograph instead.
 *
 * The search here is the primary one — the masthead keeps its own for the rest
 * of the app, but on this page the hero field is what the eye lands on.
 */
export default function EmptyState({ suggestions = [], onSelect, children }) {
  return (
    <div className="home">
      <section className="home__hero">
        <p className="home__eyebrow">Swahili for sky</p>

        <h1 className="home__title">
          <span className="home__title-line">Read the</span>
          <span className="home__title-line home__title-line--accent">Kenyan sky.</span>
        </h1>

        <p className="home__lede">
          Every county, every town — the hour ahead, the week ahead, and a
          plain-language answer to the only question that matters: what is the
          weather today?
        </p>

        {/* The hero search field, supplied by App so it shares one implementation
            with the masthead rather than duplicating the combobox. */}
        <div className="home__search">{children}</div>

        {suggestions.length > 0 && (
          <div className="home__starters">
            <p className="home__label">Start somewhere</p>
            <div className="home__chips">
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
      </section>

      <section className="home__features" aria-label="What Anga does">
        <article className="feature">
          <h2 className="feature__title">24 hours, then 7 days</h2>
          <p className="feature__body">
            The next twenty-four hours hour by hour, then the week ahead —
            with rainfall in millimetres under every reading.
          </p>
        </article>
        <article className="feature">
          <h2 className="feature__title">The page becomes the weather</h2>
          <p className="feature__body">
            Sky, light and rain on screen follow the real conditions in the
            town you searched — heavier rainfall really does fall harder.
          </p>
        </article>
        <article className="feature">
          <h2 className="feature__title">Never guesses how fresh it is</h2>
          <p className="feature__body">
            Answers come from a server-side cache, so they arrive instantly —
            and every reading tells you its exact age.
          </p>
        </article>
      </section>
    </div>
  )
}
