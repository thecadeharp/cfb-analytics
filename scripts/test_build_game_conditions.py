import unittest

from build_game_conditions import normalized_venue_name, weather_neutral_venue


class IndoorVenueTests(unittest.TestCase):
    def test_provider_false_cannot_make_allegiant_outdoor(self):
        self.assertEqual(
            weather_neutral_venue("Allegiant Stadium", False),
            (True, "venue_registry"),
        )

    def test_retractable_roof_venue_is_weather_neutral_without_roof_status(self):
        self.assertEqual(
            weather_neutral_venue("AT&T Stadium", False),
            (True, "venue_registry"),
        )

    def test_provider_indoor_flag_remains_authoritative(self):
        self.assertEqual(
            weather_neutral_venue("Unknown Event Center", True),
            (True, "provider"),
        )

    def test_outdoor_stadium_remains_outdoor(self):
        self.assertEqual(
            weather_neutral_venue("Michigan Stadium", False),
            (False, None),
        )

    def test_venue_normalization_handles_punctuation(self):
        self.assertEqual(normalized_venue_name("U.S. Bank Stadium"), "u s bank stadium")


if __name__ == "__main__":
    unittest.main()
