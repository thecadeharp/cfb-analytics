"""Regression tests for the sealed 2025 expected-points evaluation gate."""
import unittest

import numpy as np
import pandas as pd

from evaluate_sealed_expected_points_2025 import (
    context_rows,
    fit_baseline,
    game_bootstrap_interval,
    predict_baseline,
)


class SealedHoldoutTests(unittest.TestCase):
    def test_context_uses_possession_team_perspective(self):
        targets = pd.DataFrame({
            "game_id": ["g", "g"],
            "drive_id": ["d1", "d2"],
            "possession_team_id": ["home", "away"],
        })
        raw = pd.DataFrame({"homeTeamId": ["home"], "awayTeamId": ["away"]})
        findings = [
            {"drive_id": "d1", "status": "raw_confirmed",
             "reconstructed_home": 14, "reconstructed_away": 7},
            {"drive_id": "d2", "status": "repairable_stale_stamp",
             "reconstructed_home": 14, "reconstructed_away": 10},
        ]
        result, repaired = context_rows(targets, findings, raw)
        self.assertEqual(result.start_score_margin.tolist(), [7.0, -4.0])
        self.assertEqual(repaired, 1)

    def test_unresolved_context_quarantines_game(self):
        targets = pd.DataFrame({"game_id": ["g"], "drive_id": ["d1"],
                                "possession_team_id": ["home"]})
        raw = pd.DataFrame({"homeTeamId": ["home"], "awayTeamId": ["away"]})
        findings = [{"drive_id": "d1", "status": "unresolved_score_contradiction",
                     "reconstructed_home": 0, "reconstructed_away": 0}]
        with self.assertRaisesRegex(ValueError, "unresolved_score_context"):
            context_rows(targets, findings, raw)

    def test_baseline_bounds_and_game_bootstrap(self):
        frame = pd.DataFrame({
            "game_id": ["a", "a", "b", "b", "c", "c", "d", "d"],
            "start_yards_to_endzone": [20, 40, 60, 80, 30, 50, 70, 90],
            "start_period": [1, 2, 3, 4, 1, 2, 3, 4],
            "target_offensive_points": [7, 3, 0, 0, 7, 3, 0, 0],
        })
        prediction = predict_baseline(frame, fit_baseline(frame))
        self.assertTrue(np.isfinite(prediction).all())
        self.assertTrue(((prediction >= 0) & (prediction <= 8)).all())
        interval = game_bootstrap_interval(frame, prediction + 0.5, prediction)
        self.assertEqual(len(interval), 2)
        self.assertLessEqual(interval[0], interval[1])


if __name__ == "__main__":
    unittest.main()
