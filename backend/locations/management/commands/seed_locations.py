"""Idempotently load the Kenya gazetteer into PostgreSQL.

Safe to run on every deploy: existing rows are updated in place, so coordinate
or prominence corrections roll out without duplicating locations.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from locations.data import ALL_LOCATIONS
from locations.models import Location, LocationAlias
from locations.normalize import normalize_location


class Command(BaseCommand):
    help = "Seed or refresh the Kenya gazetteer (47 counties + major towns)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--prune",
            action="store_true",
            help="Delete locations that are no longer present in locations/data.py.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        created = updated = alias_count = 0
        seen_slugs = set()

        for name, county, kind, lat, lon, prominence, aliases in ALL_LOCATIONS:
            slug = normalize_location(name)
            seen_slugs.add(slug)

            location, was_created = Location.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "county": county,
                    "kind": kind,
                    "latitude": lat,
                    "longitude": lon,
                    "prominence": prominence,
                },
            )
            created += was_created
            updated += not was_created

            for raw_alias in aliases:
                alias = normalize_location(raw_alias)
                # An alias identical to the canonical slug carries no
                # information and would collide with the location lookup.
                if alias == slug:
                    continue
                _, alias_created = LocationAlias.objects.update_or_create(
                    alias=alias, defaults={"location": location}
                )
                alias_count += alias_created

        if options["prune"]:
            stale = Location.objects.exclude(slug__in=seen_slugs)
            removed = stale.count()
            stale.delete()
            self.stdout.write(f"Pruned {removed} location(s) no longer in data.py.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Gazetteer ready: {created} created, {updated} updated, "
                f"{alias_count} new alias(es). "
                f"{Location.objects.count()} locations total."
            )
        )
