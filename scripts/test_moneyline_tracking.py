import unittest

from scripts.settle_results import moneyline_decision


class CfbMoneylineTrackingTests(unittest.TestCase):
    def test_qualifying_snapshot_is_graded_with_probability_clv(self):
        snapshot = {
            "home_team": "Home",
            "away_team": "Away",
            "model": {"home_win_probability": 70, "home_spread": -6},
            "market_at_snapshot": {
                "moneyline_policy_version": "relative-market-fit-v1-2026-11-25",
                "moneyline_book_count": 3,
                "reference_moneyline": {"home_price": -150, "away_price": 135, "no_vig_probability": {"home": .58, "away": .42}},
            },
        }
        closing = {"closing_market": {"reference_moneyline": {"home_price": -170, "away_price": 150, "no_vig_probability": {"home": .61, "away": .39}}}}
        result = {"home_points": 30, "away_points": 20}
        decision = moneyline_decision(snapshot, closing, result)
        self.assertTrue(decision["moneyline_tracking_eligible"])
        self.assertEqual(decision["moneyline_result"], "W")
        self.assertEqual(decision["moneyline_price"], -150)
        self.assertEqual(decision["moneyline_clv_probability_points"], 3.0)
        self.assertAlmostEqual(decision["moneyline_roi_units"], .6667)

    def test_price_outside_policy_is_not_tracked(self):
        snapshot = {
            "home_team": "Home",
            "away_team": "Away",
            "model": {"home_win_probability": 90, "home_spread": -20},
            "market_at_snapshot": {
                "moneyline_policy_version": "relative-market-fit-v1-2026-11-25",
                "moneyline_book_count": 4,
                "reference_moneyline": {"home_price": -300, "away_price": 240, "no_vig_probability": {"home": .72, "away": .28}},
            },
        }
        self.assertEqual(moneyline_decision(snapshot, None, {"home_points": 40, "away_points": 10}), {})


if __name__ == "__main__":
    unittest.main()
