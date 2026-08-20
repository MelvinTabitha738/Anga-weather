"""Capture and inspect one real Weather-AI response.

Weather-AI does not publish a response schema, so weather/adapter.py maps each
field from a list of candidate paths. This command spends exactly ONE request
from the monthly quota to show what the upstream actually returns, so those
candidate lists can be pruned to the verified path for each field.

    python manage.py probe_upstream
    python manage.py probe_upstream --lat -4.0435 --lon 39.6682 --save raw.json

It prints the raw body, the adapter's interpretation, and the observed
X-RateLimit-* state. The API key is never printed.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from weather import quota
from weather.adapter import normalize_upstream
from weather.client import WeatherAIClient
from weather.exceptions import UpstreamError


class Command(BaseCommand):
    help = "Fetch one live Weather-AI response and show how the adapter maps it."

    def add_arguments(self, parser):
        # Nairobi, matching the example coordinates in the Weather-AI docs.
        parser.add_argument("--lat", type=float, default=-1.2864)
        parser.add_argument("--lon", type=float, default=36.8172)
        parser.add_argument("--units", default="metric", choices=["metric", "imperial"])
        parser.add_argument("--save", help="Write the raw JSON body to this path.")

    def handle(self, *args, **options):
        client = WeatherAIClient()

        self.stdout.write(
            f"Requesting /v1/weather lat={options['lat']} lon={options['lon']} "
            f"units={options['units']} (costs 1 request)..."
        )

        try:
            raw = client.fetch_weather(options["lat"], options["lon"], options["units"])
        except UpstreamError as exc:
            raise CommandError(f"{type(exc).__name__}: {exc}") from exc

        pretty = json.dumps(raw, indent=2, sort_keys=True, default=str)

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== RAW UPSTREAM BODY ==="))
        self.stdout.write(pretty)

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== TOP-LEVEL KEYS ==="))
        self.stdout.write(", ".join(sorted(raw.keys())) or "(none)")

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== ADAPTER OUTPUT ==="))
        mapped = normalize_upstream(raw, units=options["units"])
        self.stdout.write(json.dumps(mapped, indent=2, sort_keys=True, default=str))

        missing = sorted(k for k, v in mapped.items() if v is None)
        if missing:
            self.stdout.write(
                self.style.WARNING(
                    "\nUnmapped fields (no candidate path matched): " + ", ".join(missing)
                )
            )
            self.stdout.write(
                "Update FIELD_CANDIDATES in weather/adapter.py using the raw body above."
            )
        else:
            self.stdout.write(self.style.SUCCESS("\nEvery adapter field resolved."))

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== OBSERVED QUOTA ==="))
        self.stdout.write(json.dumps(quota.get_quota(), indent=2, default=str))

        if options["save"]:
            with open(options["save"], "w", encoding="utf-8") as handle:
                handle.write(pretty)
            self.stdout.write(self.style.SUCCESS(f"\nRaw body written to {options['save']}"))
