/**
 * First view, before a location is chosen. Offers a few well-known places so
 * the user can get to weather in one tap rather than having to type.
 */
export default function EmptyState({ suggestions = [], onSelect }) {
  return (
    <section className="state">
      <h1 className="state__title">Weather for Kenya.</h1>
      <p className="state__body">
        Search any Kenyan county or town for current conditions — or start with one of these.
      </p>
      <div className="state__actions">
        {suggestions.map((place) => (
          <button
            key={place.slug}
            type="button"
            className="button"
            onClick={() => onSelect(place.slug, place.label)}
          >
            {place.name}
          </button>
        ))}
      </div>
    </section>
  )
}
