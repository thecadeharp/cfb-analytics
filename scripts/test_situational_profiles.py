"""Regression tests for research-only team situational profiles."""
import unittest

import numpy as np
import pandas as pd

from build_situational_profiles import (
    EXPECTED_FEATURES,
    build_game_logs,
    build_profiles,
    excitement_profile,
    expected_points,
    reliability,
    summarize,
)


class SituationalProfileTests(unittest.TestCase):
    def sample(self):
        return pd.DataFrame([
            {"game_id": "g1", "team_id": "1", "team": "Alpha", "opponent_id": "2",
             "opponent": "Beta", "start_yards_to_endzone": 75, "start_period": 1,
             "start_score_margin": 0, "target_offensive_points": 7,
             "expected_points": 2.0, "points_over_expected": 5.0, "score_state": "tied",
             "half": "first_half"},
            {"game_id": "g1", "team_id": "1", "team": "Alpha", "opponent_id": "2",
             "opponent": "Beta", "start_yards_to_endzone": 30, "start_period": 2,
             "start_score_margin": 7, "target_offensive_points": 0,
             "expected_points": 3.0, "points_over_expected": -3.0, "score_state": "leading",
             "half": "first_half"},
            {"game_id": "g1", "team_id": "2", "team": "Beta", "opponent_id": "1",
             "opponent": "Alpha", "start_yards_to_endzone": 80, "start_period": 1,
             "start_score_margin": -7, "target_offensive_points": 0,
             "expected_points": 1.5, "points_over_expected": -1.5, "score_state": "trailing",
             "half": "first_half"},
            {"game_id": "g1", "team_id": "2", "team": "Beta", "opponent_id": "1",
             "opponent": "Alpha", "start_yards_to_endzone": 50, "start_period": 3,
             "start_score_margin": -7, "target_offensive_points": 3,
             "expected_points": 2.0, "points_over_expected": 1.0, "score_state": "trailing",
             "half": "second_half"},
        ])

    def test_candidate_design_uses_only_locked_start_context(self):
        frame = pd.DataFrame({
            "start_yards_to_endzone": [100, 50],
            "start_period": [1, 4],
            "start_score_margin": [0, -14],
        })
        coefficients = np.array([1, 2, 3, 4, 5, 6, 7], dtype=float)
        prediction = expected_points(frame, coefficients)
        self.assertEqual(len(EXPECTED_FEATURES), 7)
        self.assertAlmostEqual(prediction[0], 6.0)
        self.assertAlmostEqual(prediction[1], 5.25)
        self.assertTrue(((prediction >= 0) & (prediction <= 8)).all())

    def test_defense_value_reverses_offensive_points_over_expected(self):
        sample = self.sample().loc[lambda x: x.opponent_id.eq("1")]
        result = summarize(sample, defense=True)
        self.assertEqual(result["possessions"], 2)
        self.assertAlmostEqual(result["points_prevented_over_expected_per_possession"], 0.25)
        self.assertAlmostEqual(result["empty_possession_rate"], 0.5)

    def test_profiles_include_both_sides_and_net_value(self):
        profiles = build_profiles(self.sample())
        self.assertEqual([item["team"] for item in profiles], ["Alpha", "Beta"])
        alpha = profiles[0]
        self.assertNotIn("net_possession_rank", alpha)
        self.assertAlmostEqual(alpha["offense"]["points_over_expected_per_possession"], 1.0)
        self.assertAlmostEqual(alpha["defense"]["points_prevented_over_expected_per_possession"], 0.25)
        self.assertEqual(alpha["reliability"], "limited")

    def test_reliability_thresholds_are_possession_based(self):
        self.assertEqual(reliability(24), "limited")
        self.assertEqual(reliability(25), "developing")
        self.assertEqual(reliability(50), "established")

    def test_excitement_score_rewards_late_close_possessions(self):
        game = pd.DataFrame([
            {"team_id": "1", "home_team_id": "1", "start_period": 1,
             "start_clock_minutes": 15, "start_clock_seconds": 0,
             "start_score_margin": 0, "target_offensive_points": 7},
            {"team_id": "2", "home_team_id": "1", "start_period": 4,
             "start_clock_minutes": 8, "start_clock_seconds": 0,
             "start_score_margin": -3, "target_offensive_points": 7},
            {"team_id": "1", "home_team_id": "1", "start_period": 4,
             "start_clock_minutes": 2, "start_clock_seconds": 0,
             "start_score_margin": -4, "target_offensive_points": 7},
        ])
        result = excitement_profile(game, final_margin=3, total_points=59)
        self.assertGreaterEqual(result["score"], 70)
        self.assertEqual(result["fourth_quarter_one_score_possessions"], 2)
        self.assertIn(result["label"], {"High Drama", "Must Rewatch", "Instant Classic"})

    def test_game_log_uses_verified_final_and_possession_values(self):
        possessions = self.sample().assign(
            week=1,
            start_clock_minutes=[15, 4, 8, 10],
            start_clock_seconds=[0, 0, 0, 0],
        )
        verified = pd.DataFrame([
            {"game_id": "g1", "period": 4, "clock.minutes": 0,
             "clock.seconds": 0, "game_play_number": 100,
             "homeTeamId": "1", "awayTeamId": "2",
             "homeTeamName": "Alpha", "awayTeamName": "Beta",
             "homeScore": 14, "awayScore": 10},
        ])
        logs = build_game_logs(possessions, verified)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["winner"], "Alpha")
        self.assertEqual(logs[0]["home"]["possessions"], 2)
        self.assertAlmostEqual(logs[0]["home"]["points_over_expected_per_possession"], 1.0)
        self.assertIn("score", logs[0]["excitement"])


if __name__ == "__main__":
    unittest.main()
