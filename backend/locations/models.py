"""The Kenya gazetteer.

Weather-AI's /v1/weather endpoint resolves coordinates only - there is no
place-name lookup on the free tier - so location search has to be served by us.
That makes this table the one piece of genuinely persistent, relational data in
the application, and the reason PostgreSQL is in the stack.

Weather responses deliberately do NOT live here. They are volatile, expire on a
TTL and need atomic single-flight coordination, all of which belong in Redis.
"""

from django.db import models


class LocationKind(models.TextChoices):
    COUNTY = "county", "County"
    TOWN = "town", "Town"


class Location(models.Model):
    """A Kenyan county or town with the coordinates Weather-AI needs."""

    # Canonical key produced by locations.normalize.normalize_location(). Also
    # forms part of the weather cache key, so it is constrained and indexed.
    slug = models.SlugField(max_length=64, unique=True, db_index=True)

    name = models.CharField(max_length=80)
    county = models.CharField(max_length=80, db_index=True)
    kind = models.CharField(max_length=16, choices=LocationKind.choices)

    latitude = models.DecimalField(max_digits=8, decimal_places=5)
    longitude = models.DecimalField(max_digits=8, decimal_places=5)

    # Hand-assigned search weight so "na" surfaces Nairobi and Nakuru before
    # Nyamira. Higher wins.
    prominence = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-prominence", "name"]
        indexes = [models.Index(fields=["name"])]

    def __str__(self) -> str:
        return f"{self.name}, {self.county}"

    @property
    def display_name(self) -> str:
        """Human label: 'Nairobi' for counties, 'Thika, Kiambu' for towns."""
        if self.kind == LocationKind.COUNTY or self.name == self.county:
            return self.name
        return f"{self.name}, {self.county}"


class LocationAlias(models.Model):
    """An alternative spelling that resolves to a canonical Location.

    Aliases are normalised on save, so 'Nairobi City' and 'Athi River' collapse
    onto the same cache entry as their canonical location instead of each
    triggering a separate upstream request.
    """

    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name="aliases"
    )
    alias = models.SlugField(max_length=64, unique=True, db_index=True)

    class Meta:
        verbose_name_plural = "location aliases"

    def __str__(self) -> str:
        return f"{self.alias} -> {self.location.slug}"
