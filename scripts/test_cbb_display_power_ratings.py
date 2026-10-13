import unittest

from scripts.build_cbb_display_power_ratings import rankdata, spearman, weighted_team_rating


class DisplayPowerRatingsTests(unittest.TestCase):
    def test_recent_season_has_seventy_percent_weight(self):
        rows = [
            (2026, 0.70, 100.0, {"adjusted_offense": 120, "adjusted_defense": 90, "pace": 70}),
            (2025, 0.20, 100.0, {"adjusted_offense": 100, "adjusted_defense": 100, "pace": 68}),
            (2024, 0.10, 100.0, {"adjusted_offense": 100, "adjusted_defense": 100, "pace": 66}),
        ]
        rating = weighted_team_rating(1, rows, 100.0)
        self.assertAlmostEqual(rating["prior_net"], 18.48)
        self.assertEqual(rating["normalized_weights"], {"2026": 0.7, "2025": 0.2, "2024": 0.1})

    def test_missing_history_renormalizes_available_seasons(self):
        rows = [
            (2026, 0.70, 100.0, {"adjusted_offense": 110, "adjusted_defense": 100, "pace": 70}),
            (2025, 0.20, 100.0, None),
            (2024, 0.10, 100.0, {"adjusted_offense": 100, "adjusted_defense": 100, "pace": 66}),
        ]
        rating = weighted_team_rating(1, rows, 100.0)
        self.assertAlmostEqual(rating["prior_net"], 7.7)
        self.assertAlmostEqual(sum(rating["normalized_weights"].values()), 1.0)

    def test_season_center_removes_scoring_environment_shift(self):
        rows = [(2026, 1.0, 110.0, {"adjusted_offense": 115, "adjusted_defense": 105, "pace": 70})]
        rating = weighted_team_rating(1, rows, 100.0)
        self.assertEqual(rating["prior_offense"], 104.4)
        self.assertEqual(rating["prior_defense"], 95.6)
        self.assertEqual(rating["prior_net"], 8.8)

    def test_spearman_detects_order(self):
        self.assertAlmostEqual(spearman([1, 2, 3], [1, 2, 3]), 1.0)
        self.assertAlmostEqual(spearman([1, 2, 3], [3, 2, 1]), -1.0)
        self.assertEqual(rankdata([2, 2, 4]), [1.5, 1.5, 3.0])


if __name__ == "__main__":
    unittest.main()
