import unittest

from scripts.resolve_cbb_venue_geocodes import choose, name_score, target_venues


class VenueGeocodeTests(unittest.TestCase):
    def test_named_arena_with_matching_city_and_state_is_accepted(self):
        venue = {"name": "Dean E. Smith Center", "city": "Chapel Hill", "state": "NC"}
        payload = {"features": [{
            "properties": {"name": "Dean E. Smith Student Activities Center", "city": "Chapel Hill", "state": "North Carolina", "countrycode": "US", "osm_type": "W", "osm_id": 44345694, "osm_key": "leisure", "osm_value": "stadium"},
            "geometry": {"coordinates": [-79.0438119, 35.8994837]},
        }]}
        selected, _ = choose(venue, payload)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["source_url"], "https://www.openstreetmap.org/way/44345694")

    def test_city_centroid_and_wrong_state_are_rejected(self):
        venue = {"name": "Arena", "city": "Chapel Hill", "state": "NC"}
        payload = {"features": [
            {"properties": {"city": "Chapel Hill", "state": "North Carolina", "countrycode": "US", "osm_type": "R", "osm_id": 1, "osm_key": "place", "osm_value": "city"}, "geometry": {"coordinates": [-79, 35]}},
            {"properties": {"name": "Arena", "city": "Durham", "state": "South Carolina", "countrycode": "US", "osm_type": "W", "osm_id": 2, "osm_key": "leisure", "osm_value": "stadium"}, "geometry": {"coordinates": [-78, 36]}},
        ]}
        selected, _ = choose(venue, payload)
        self.assertIsNone(selected)

    def test_target_venues_are_unique(self):
        game = {"venue": {"name": "Arena", "city": "City", "state": "NY"}}
        self.assertEqual(len(target_venues({"games": [game, game]})), 1)

    def test_name_score_handles_expanded_arena_name(self):
        self.assertGreaterEqual(name_score("Dean E. Smith Center", "Dean E. Smith Student Activities Center"), 0.72)

    def test_single_shared_brand_word_does_not_create_exact_match(self):
        self.assertLess(name_score("Broadview Center", "Broadview Federal Credit Union"), 0.92)

    def test_same_name_non_venue_object_is_rejected(self):
        venue = {"name": "Capital One Arena", "city": "Washington", "state": "DC"}
        payload = {"features": [{
            "properties": {"name": "Capital One Arena", "city": "Washington", "state": "District of Columbia", "countrycode": "US", "osm_type": "N", "osm_id": 9, "osm_key": "amenity", "osm_value": "toilets"},
            "geometry": {"coordinates": [-77.0, 38.9]},
        }]}
        self.assertIsNone(choose(venue, payload)[0])


if __name__ == "__main__":
    unittest.main()
