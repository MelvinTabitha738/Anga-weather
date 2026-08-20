"""Location input normalisation.

This module is the single source of truth for turning arbitrary user input into
a canonical location key. It matters for two separate reasons:

1. Cache correctness. "Nairobi", "nairobi" and "  NAIROBI  " must resolve to one
   cache entry, otherwise the cache fragments and we waste upstream quota.
2. Security. The normalised value becomes part of a cache key, so raw user input
   must never reach the cache backend. We allow a deliberately narrow charset
   and cap the length rather than trying to escape everything.
"""

import re
import unicodedata

# Longest real Kenyan place names are well under this; anything longer is either
# a mistake or an attempt to abuse the cache with unbounded keys.
MAX_INPUT_LENGTH = 64

# Letters, digits, a literal space, and the few separators that occur in Kenyan
# place names: Murang'a (both the ASCII and typographic apostrophe, since phone
# keyboards emit U+2019), Taita-Taveta, Homa Bay.
#
# Note this deliberately matches a literal space rather than \s: \s would admit
# CR/LF/TAB, and control characters have no place in a value that ends up in a
# cache key or a log line.
_ALLOWED_INPUT = re.compile(r"^[\w '’\-.]+$", re.UNICODE)
_NON_SLUG = re.compile(r"[^a-z0-9]+")


class InvalidLocation(ValueError):
    """Raised when user input cannot be a plausible location name."""


def normalize_location(raw: str) -> str:
    """Return the canonical slug for a user-supplied location string.

    >>> normalize_location("  NAIROBI ")
    'nairobi'
    >>> normalize_location("Murang'a")
    'muranga'
    >>> normalize_location("Homa Bay")
    'homa-bay'

    Raises InvalidLocation for empty, over-long or implausible input.
    """
    if raw is None:
        raise InvalidLocation("A location is required.")

    text = str(raw).strip()
    if not text:
        raise InvalidLocation("A location is required.")
    if len(text) > MAX_INPUT_LENGTH:
        raise InvalidLocation(
            f"Location names cannot be longer than {MAX_INPUT_LENGTH} characters."
        )
    if not _ALLOWED_INPUT.match(text):
        raise InvalidLocation("That does not look like a valid location name.")

    # Fold accents to ASCII so "Kisii"/"Kisíi" collapse to one key.
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))

    # Apostrophes join rather than separate: Murang'a -> muranga, not murang-a.
    ascii_text = ascii_text.replace("'", "").replace("\u2019", "")

    slug = _NON_SLUG.sub("-", ascii_text.lower()).strip("-")
    if not slug:
        raise InvalidLocation("That does not look like a valid location name.")
    return slug
