import unittest

from scripts.build_public_backtest_scorecard import grade


class PublicBacktestScorecardTests(unittest.TestCase):
    def test_minus_110_roi_uses_units_risked_and_keeps_pushes(self):
        result = grade(55, 45, 2)
        self.assertEqual(result["record"], "55-45-2")
        self.assertEqual(result["hit_rate"], 55.0)
        self.assertAlmostEqual(result["profit_units"], 5.0)
        self.assertAlmostEqual(result["roi_pct"], 4.902)


if __name__ == "__main__":
    unittest.main()
