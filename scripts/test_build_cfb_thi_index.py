import unittest

from build_cfb_thi_index import adjusted_home_margin, percentile_map


class ThiIndexTests(unittest.TestCase):
    def test_neutral_game_has_no_home_adjustment(self):
        game = {"home_points": 24, "away_points": 20, "neutral_site": True}
        self.assertEqual(adjusted_home_margin(game), 4.0)

    def test_non_neutral_game_removes_home_edge(self):
        game = {"home_points": 24, "away_points": 20, "neutral_site": False}
        self.assertEqual(adjusted_home_margin(game), 1.5)

    def test_margin_is_capped(self):
        game = {"home_points": 70, "away_points": 0, "neutral_site": True}
        self.assertEqual(adjusted_home_margin(game), 28.0)

    def test_percentile_orders_values(self):
        result = percentile_map({"A": 3.0, "B": 1.0, "C": 2.0})
        self.assertEqual(result, {"B": 0.0, "C": 50.0, "A": 100.0})


if __name__ == "__main__":
    unittest.main()
