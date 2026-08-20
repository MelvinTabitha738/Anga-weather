"""Read-side query helpers for the gazetteer.

Kept separate from the views so the weather service can resolve a location
without importing view code, and so the lookup rules are testable in isolation.
"""

from django.db.models import Q

from locations.models import Location, LocationAlias
from locations.normalize import InvalidLocation, normalize_location

DEFAULT_SEARCH_LIMIT = 8
MAX_SEARCH_LIMIT = 25


class LocationNotFound(LookupError):
    """Raised when input is well-formed but matches no Kenyan location."""


def resolve_location(raw: str) -> Location:
    """Resolve user input to exactly one Location.

    Tries the canonical slug first, then the alias table, so 'Diani' and
    'Ukunda' converge on a single row - and therefore a single cache entry.

    Raises InvalidLocation for malformed input and LocationNotFound when the
    input is plausible but not a Kenyan location we cover.
    """
    slug = normalize_location(raw)

    location = Location.objects.filter(slug=slug).first()
    if location is not None:
        return location

    alias = (
        LocationAlias.objects.select_related("location").filter(alias=slug).first()
    )
    if alias is not None:
        return alias.location

    raise LocationNotFound(slug)


def search_locations(query: str | None, limit: int = DEFAULT_SEARCH_LIMIT):
    """Return ranked suggestions for a partial location query.

    An empty query returns the most prominent locations, which the frontend
    uses to populate its initial suggestions.
    """
    limit = max(1, min(int(limit or DEFAULT_SEARCH_LIMIT), MAX_SEARCH_LIMIT))

    text = (query or "").strip()
    if not text:
        return list(Location.objects.all()[:limit])

    try:
        slug = normalize_location(text)
    except InvalidLocation:
        # Malformed input is not an error for a search box - it just matches
        # nothing. The weather endpoint is where validation is strict.
        return []

    matches = (
        Location.objects.filter(
            Q(slug__startswith=slug)
            | Q(name__icontains=text)
            | Q(county__icontains=text)
            | Q(aliases__alias__startswith=slug)
        )
        .distinct()
        .order_by("-prominence", "name")
    )
    return list(matches[:limit])
