import unittest

from build_cfb_thi_index import (
    adjusted_home_margin,
    apply_verified_score_updates,
    percentile_map,
    resume_result_values,
    schedule_strength_map,
)


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

    def test_schedule_strength_is_average_opponent_power(self):
        games = [
            {"home_team": "A", "away_team": "B"},
            {"home_team": "A", "away_team": "C"},
        ]
        result = schedule_strength_map(
            ["A", "B", "C"], games, {"A": 50.0, "B": 100.0, "C": 20.0}
        )
        self.assertEqual(result, {"A": 60.0, "B": 50.0, "C": 50.0})

    def test_road_win_gets_more_resume_credit_than_home_win(self):
        home, _ = resume_result_values(.8, .8, winner_is_away=False, neutral_site=False, margin=7)
        road, _ = resume_result_values(.8, .8, winner_is_away=True, neutral_site=False, margin=7)
        self.assertAlmostEqual(road - home, .18)

    def test_resume_margin_credit_is_capped(self):
        close, _ = resume_result_values(.5, .5, winner_is_away=False, neutral_site=False, margin=21)
        blowout, _ = resume_result_values(.5, .5, winner_is_away=False, neutral_site=False, margin=70)
        self.assertEqual(close, blowout)

    def test_verified_score_update_advances_only_new_week(self):
        ratings = {"A": 5.0, "B": -5.0}
        games = [
            {"id": 1, "week": 7, "home_team": "A", "away_team": "B", "home_points": 21, "away_points": 20, "neutral_site": True},
            {"id": 2, "week": 8, "home_team": "A", "away_team": "B", "home_points": 10, "away_points": 30, "neutral_site": True},
        ]
        updated = apply_verified_score_updates(ratings, games, 7, 8)
        self.assertAlmostEqual(updated["A"], 2.0)
        self.assertAlmostEqual(updated["B"], -2.0)


if __name__ == "__main__":
    unittest.main()
