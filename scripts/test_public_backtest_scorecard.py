import unittest

from scripts.build_public_backtest_scorecard import ROOT, cbb_scorecard, cfb_scorecard, exact_binomial_upper_tail, grade, holm_adjust, short_favorite_summary


class PublicBacktestScorecardTests(unittest.TestCase):
    def test_flat_minus_110_is_explicitly_hypothetical(self):
        result = grade(55, 45, 2)
        self.assertEqual(result["record"], "55-45-2")
        self.assertEqual(result["hit_rate"], 55.0)
        self.assertAlmostEqual(result["hypothetical_units"], 5.0)
        self.assertAlmostEqual(result["hypothetical_return_pct"], 4.902)

    def test_exact_test_uses_minus_110_break_even_baseline(self):
        self.assertGreater(exact_binomial_upper_tail(55, 100), 0.25)
        self.assertLess(exact_binomial_upper_tail(65, 100), 0.01)

    def test_holm_adjustment_is_monotone_and_never_smaller(self):
        rows = [{"p_value_vs_flat_minus_110": value} for value in (0.01, 0.03, 0.20)]
        holm_adjust(rows)
        self.assertEqual([row["holm_adjusted_p"] for row in rows], [0.03, 0.06, 0.20])

    def test_published_sources_have_no_duplicate_game_keys(self):
        cfb = cfb_scorecard(ROOT / "data/composite_backtest_report.json")
        cbb = cbb_scorecard(ROOT / "data/cbb/model/walk_forward_predictions.json.gz", ROOT / "data/cbb/model/model_card.json")
        self.assertEqual(cfb["data_integrity"]["duplicate_game_keys"], 0)
        self.assertEqual(cbb["data_integrity"]["duplicate_game_keys"], 0)

    def test_short_favorites_separate_straight_up_and_ats_outcomes(self):
        rows = [
            {"market_home_spread": -3, "actual_home_margin": 2},   # favorite wins SU, loses ATS
            {"market_home_spread": 4, "actual_home_margin": -7},   # away favorite wins SU and ATS
            {"market_home_spread": -8, "actual_home_margin": 20},  # outside predeclared range
        ]
        result = short_favorite_summary(rows)
        self.assertEqual(result["games"], 2)
        self.assertEqual(result["su_record"], "2-0-0")
        self.assertEqual(result["ats_record"], "1-1-0")


if __name__ == "__main__":
    unittest.main()
