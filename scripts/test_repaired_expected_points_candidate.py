"""Regression tests for the frozen expected-points candidate."""
import unittest

import numpy as np
import pandas as pd

from fit_repaired_expected_points_candidate import FEATURES, fit, predict


class CandidateTests(unittest.TestCase):
    def test_feature_contract_and_prediction_bounds(self):
        rows = pd.DataFrame({"start_yards_to_endzone": [20, 50, 80, 99, 35, 65, 75, 10],
                             "start_period": [1, 2, 3, 4, 1, 2, 3, 4],
                             "start_score_margin": [-14, -7, 0, 7, 14, 3, -3, 21],
                             "target_offensive_points": [7, 3, 0, 0, 7, 3, 0, 7]})
        coefficients = fit(rows)
        result = predict(rows, coefficients)
        self.assertEqual(len(coefficients), len(FEATURES))
        self.assertTrue(np.isfinite(coefficients).all())
        self.assertTrue(((result >= 0) & (result <= 8)).all())


if __name__ == "__main__":
    unittest.main()
