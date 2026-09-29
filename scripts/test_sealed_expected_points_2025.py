"""Regression tests for the sealed 2025 expected-points evaluation gate."""
import unittest

import numpy as np
import pandas as pd

from evaluate_sealed_expected_points_2025 import (
    EXPECTED_HOLDOUT_GAMES,
    EXPECTED_HOLDOUT_POSSESSIONS,
    fit_baseline,
    game_bootstrap_interval,
    load_locked_candidate,
    load_matched_historical,
    load_sealed_holdout,
    predict_baseline,
)


class SealedHoldoutTests(unittest.TestCase):
    def test_locked_inputs_recover_exact_frozen_samples(self):
        candidate, _ = load_locked_candidate()
        historical, coverage = load_matched_historical(candidate)
        holdout = load_sealed_holdout()
        self.assertEqual(len(historical), candidate["approved_sample"]["possessions"])
        self.assertEqual(historical.game_id.nunique(), candidate["approved_sample"]["games"])
        self.assertEqual(coverage, candidate["approved_sample"]["coverage"])
        self.assertEqual(len(holdout), EXPECTED_HOLDOUT_POSSESSIONS)
        self.assertEqual(holdout.game_id.nunique(), EXPECTED_HOLDOUT_GAMES)

    def test_holdout_contains_only_model_inputs_identity_and_target(self):
        holdout = load_sealed_holdout()
        self.assertEqual(set(holdout), {
            "game_id", "drive_id", "start_yards_to_endzone", "start_period",
            "start_score_margin", "target_offensive_points",
        })
        self.assertFalse(holdout.duplicated(["game_id", "drive_id"]).any())
        self.assertTrue(holdout.start_period.between(1, 4).all())
        self.assertTrue(holdout.target_offensive_points.between(0, 8).all())

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
