import unittest

from scripts.segment_tracking import (
    build_conference_team_tracking,
    build_segment_tracking,
    classify_cbb,
    classify_cfb,
    summarize_rows,
)


class SegmentTrackingTest(unittest.TestCase):
    def test_classification_contract_matches_public_filters(self):
        self.assertEqual(classify_cfb("ACC", "SEC"), "p4_vs_p4")
        self.assertEqual(classify_cfb("MAC", "Mountain West"), "g6_vs_g6")
        self.assertEqual(classify_cfb("Big Ten", "Sun Belt"), "cross_tier_or_other")
        self.assertEqual(classify_cbb("Big East", "ACC"), "p5_vs_p5")
        self.assertEqual(classify_cbb("WCC", "A-10"), "mid_major_vs_mid_major")
        self.assertEqual(classify_cbb("SEC", "WCC"), "mixed_tier")

    def test_summary_includes_uncertainty_clv_and_sample_guardrail(self):
        rows = [
            {"result": "win", "clv": 1.5, "model_edge": 4.0},
            {"result": "loss", "clv": -0.5, "model_edge": 6.0},
            {"result": "push", "clv": 0.0, "model_edge": 5.0},
        ]
        summary = summarize_rows(rows, result_key="result", clv_key="clv", edge_key="model_edge")
        self.assertEqual((summary["wins"], summary["losses"], summary["pushes"]), (1, 1, 1))
        self.assertEqual(summary["hit_rate"], 50.0)
        self.assertEqual(summary["average_clv"], 0.333)
        self.assertEqual(summary["average_model_edge"], 5.0)
        self.assertEqual(summary["hit_rate_ci_95"]["method"], "wilson_95")
        self.assertEqual(summary["sample_warning"], "n_below_100")

    def test_segment_ledger_keeps_all_edge_bands_and_period_splits(self):
        spreads = [
            {"matchup_segment": "p5_vs_p5", "result": "win", "clv": 1, "model_edge": 6, "week": 1, "calendar_month_et": "2026-11"},
            {"matchup_segment": "p5_vs_p5", "result": "loss", "clv": -1, "model_edge": 3, "week": 1, "calendar_month_et": "2026-11"},
            {"matchup_segment": "mid_major_vs_mid_major", "result": "win", "clv": 0.5, "model_edge": 2, "week": 1, "calendar_month_et": "2026-11"},
        ]
        totals = [
            {"matchup_segment": "p5_vs_p5", "result": "win", "clv": 2, "model_edge": 7, "week": 1, "calendar_month_et": "2026-11"},
        ]
        ledger = build_segment_tracking(
            spreads,
            totals,
            included_segments=("p5_vs_p5", "mid_major_vs_mid_major"),
            spread_result_key="result",
            total_result_key="result",
            spread_clv_key="clv",
            total_clv_key="clv",
        )
        p5 = ledger["segments"]["p5_vs_p5"]
        self.assertEqual(p5["all_spreads"]["games"], 2)
        self.assertEqual(p5["spread_disagreements_2_5_plus"]["games"], 2)
        self.assertEqual(p5["spread_disagreements_5_plus"]["games"], 1)
        self.assertEqual(p5["tracked_totals_4_plus"]["games"], 1)
        self.assertIn("1", p5["by_week"])
        self.assertIn("2026-11", p5["by_month"])
        self.assertEqual(ledger["visibility"], "data_only_not_rendered_in_public_ui")

    def test_all_conferences_and_teams_receive_descriptive_tracking(self):
        games = [
            {"home_team": "A", "away_team": "B", "home_conference": "SEC", "away_conference": "SEC", "margin_error": 3, "margin_bias": 3, "total_error": 4, "total_bias": -4},
            {"home_team": "C", "away_team": "D", "home_conference": "Big Sky", "away_conference": "MWC", "margin_error": 2, "margin_bias": 2, "total_error": 1, "total_bias": 1},
        ]
        spreads = [
            {**games[0], "pick_team": "A", "result": "win", "clv": 1, "model_edge": 4},
            {**games[1], "pick_team": "D", "result": "loss", "clv": -1, "model_edge": 6},
        ]
        totals = [
            {**games[0], "result": "win", "clv": 0.5, "model_edge": 7},
            {**games[1], "result": "loss", "clv": -0.5, "model_edge": 5},
        ]
        ledger = build_conference_team_tracking(
            games,
            spreads,
            totals,
            spread_result_key="result",
            total_result_key="result",
            spread_clv_key="clv",
            total_clv_key="clv",
            margin_error_key="margin_error",
            margin_bias_key="margin_bias",
            total_error_key="total_error",
            total_bias_key="total_bias",
        )
        self.assertEqual(set(ledger["conferences"]), {"BIG SKY", "MOUNTAIN WEST", "SEC"})
        self.assertEqual(set(ledger["teams"]), {"A", "B", "C", "D"})
        self.assertEqual(ledger["conferences"]["SEC"]["intra_conference_spreads"]["games"], 1)
        self.assertEqual(ledger["conferences"]["MOUNTAIN WEST"]["model_favored_conference_team"]["games"], 1)
        self.assertEqual(ledger["conferences"]["BIG SKY"]["model_opposed_conference_team"]["games"], 1)
        self.assertEqual(ledger["teams"]["D"]["forecasting"]["margin_signed_bias"], -2.0)


if __name__ == "__main__":
    unittest.main()
