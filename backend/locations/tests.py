"""Gazetteer tests: normalisation, resolution and search ranking.

Normalisation is security-relevant - its output becomes part of a cache key -
so the rejection cases matter as much as the happy path.
"""

from django.test import SimpleTestCase, TestCase

from locations.models import Location, LocationAlias
from locations.normalize import InvalidLocation, normalize_location
from locations.selectors import LocationNotFound, resolve_location, search_locations


class NormalizeTests(SimpleTestCase):
    def test_collapses_case_and_whitespace(self):
        for variant in ["Nairobi", "nairobi", "  NAIROBI  ", "NaIrObI", "\tNairobi\n"]:
            self.assertEqual(normalize_location(variant), "nairobi")

    def test_apostrophes_join_rather_than_split(self):
        self.assertEqual(normalize_location("Murang'a"), "muranga")
        self.assertEqual(normalize_location("Murang’a"), "muranga")

    def test_multiword_names_become_hyphenated(self):
        self.assertEqual(normalize_location("Homa Bay"), "homa-bay")
        self.assertEqual(normalize_location("Trans  Nzoia"), "trans-nzoia")
        self.assertEqual(normalize_location("Taita-Taveta"), "taita-taveta")

    def test_accents_fold_to_ascii(self):
        self.assertEqual(normalize_location("Kisïi"), "kisii")

    def test_empty_input_rejected(self):
        for value in ["", "   ", None]:
            with self.assertRaises(InvalidLocation):
                normalize_location(value)

    def test_overlong_input_rejected(self):
        with self.assertRaises(InvalidLocation):
            normalize_location("n" * 65)

    def test_characters_that_could_poison_a_cache_key_are_rejected(self):
        for hostile in [
            "nairobi\r\nSET evil 1",   # CRLF injection into a cache protocol
            "../../etc/passwd",        # path traversal
            "nairobi*",                # Redis glob
            "{nairobi}",               # Redis hash-tag
            "DROP TABLE locations;",
            "<script>alert(1)</script>",
        ]:
            with self.assertRaises(InvalidLocation):
                normalize_location(hostile)

    def test_output_charset_is_always_safe(self):
        for value in ["Nairobi", "Homa Bay", "Murang'a", "Taita-Taveta", "Ol Kalou"]:
            slug = normalize_location(value)
            self.assertRegex(slug, r"^[a-z0-9-]+$")


class ResolutionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.nairobi = Location.objects.create(
            slug="nairobi", name="Nairobi", county="Nairobi", kind="county",
            latitude="-1.28640", longitude="36.81720", prominence=100,
        )
        cls.nakuru = Location.objects.create(
            slug="nakuru", name="Nakuru", county="Nakuru", kind="county",
            latitude="-0.30310", longitude="36.08000", prominence=90,
        )
        cls.thika = Location.objects.create(
            slug="thika", name="Thika", county="Kiambu", kind="town",
            latitude="-1.03330", longitude="37.06930", prominence=80,
        )
        LocationAlias.objects.create(alias="nairobi-city", location=cls.nairobi)

    def test_resolves_canonical_slug(self):
        self.assertEqual(resolve_location("Nairobi").slug, "nairobi")

    def test_resolves_via_alias(self):
        self.assertEqual(resolve_location("Nairobi City").slug, "nairobi")

    def test_unknown_place_raises_not_found(self):
        with self.assertRaises(LocationNotFound):
            resolve_location("Kampala")

    def test_malformed_input_raises_invalid_before_lookup(self):
        with self.assertRaises(InvalidLocation):
            resolve_location("../../secrets")

    def test_display_name_qualifies_towns_with_their_county(self):
        self.assertEqual(self.thika.display_name, "Thika, Kiambu")
        self.assertEqual(self.nairobi.display_name, "Nairobi")


class SearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Location.objects.create(
            slug="nairobi", name="Nairobi", county="Nairobi", kind="county",
            latitude="-1.28640", longitude="36.81720", prominence=100,
        )
        Location.objects.create(
            slug="nakuru", name="Nakuru", county="Nakuru", kind="county",
            latitude="-0.30310", longitude="36.08000", prominence=90,
        )
        Location.objects.create(
            slug="nyamira", name="Nyamira", county="Nyamira", kind="county",
            latitude="-0.56330", longitude="34.93580", prominence=60,
        )
        thika = Location.objects.create(
            slug="thika", name="Thika", county="Kiambu", kind="town",
            latitude="-1.03330", longitude="37.06930", prominence=80,
        )
        LocationAlias.objects.create(alias="chania", location=thika)

    def test_prefix_search_ranks_by_prominence(self):
        results = search_locations("na")
        slugs = [r.slug for r in results]
        self.assertEqual(slugs[:2], ["nairobi", "nakuru"])

    def test_search_matches_county_as_well_as_name(self):
        slugs = [r.slug for r in search_locations("Kiambu")]
        self.assertIn("thika", slugs)

    def test_search_matches_aliases(self):
        slugs = [r.slug for r in search_locations("chania")]
        self.assertIn("thika", slugs)

    def test_empty_query_returns_most_prominent(self):
        results = search_locations("")
        self.assertEqual(results[0].slug, "nairobi")

    def test_malformed_query_returns_nothing_rather_than_raising(self):
        self.assertEqual(search_locations("../../etc"), [])

    def test_limit_is_capped(self):
        self.assertLessEqual(len(search_locations("", limit=9999)), 25)

    def test_results_are_deduplicated(self):
        slugs = [r.slug for r in search_locations("thika")]
        self.assertEqual(len(slugs), len(set(slugs)))
