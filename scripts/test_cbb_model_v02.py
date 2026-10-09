#!/usr/bin/env python3

import unittest
from pathlib import Path
from unittest import mock

import scripts.research_cbb_model_v02 as challenger
from scripts.research_cbb_model_v02 import FEATURE_SETS, INNER_FOLDS, candidate_table, score


class CbbModelV02Tests(unittest.TestCase):
    def test_challenger_selection_uses_only_inner_chronological_folds(self):
        self.assertEqual(INNER_FOLDS, (2022, 2023, 2024))
        self.assertNotIn(2025, INNER_FOLDS)
        self.assertNotIn(2026, INNER_FOLDS)
        self.assertIn("incumbent_full", FEATURE_SETS)

    def test_candidate_table_and_scoring_are_deterministic(self):
        rows = []
        for season in range(2019, 2025):
            for index in range(8):
                raw = float(index - 3)
                rows.append({
                    "season": season,
                    "features": {name: raw if name == "raw_margin" else 0.0 for names in FEATURE_SETS.values() for name in names},
                    "actual_home_margin": raw * 1.5 + 1,
                    "market_home_spread": -raw,
                })
        table = candidate_table(rows)
        self.assertEqual(len(table), len(FEATURE_SETS) * 4)
        self.assertEqual(table, candidate_table(rows))
        report = score([row for row in rows if row["season"] == 2024], {
            "feature_names": ["raw_margin"], "means": {"raw_margin": 0}, "scales": {"raw_margin": 1}, "coefficients": [1, 1.5],
        })
        self.assertEqual(report["margin_mae"], 0)

    def test_build_accepts_current_single_list_row_generator_contract(self):
        rows = [{"season": season} for season in (2019, 2025, 2026)]
        selected = {
            "name": "challenger", "ridge": 2.0, "feature_names": ["raw_margin"],
            "mean_margin_mae": 9.9, "worst_margin_mae": 10.1, "folds": [],
        }
        incumbent = {
            "name": "incumbent_full", "ridge": 4.0, "feature_names": ["raw_margin"],
            "mean_margin_mae": 10.0, "worst_margin_mae": 10.2, "folds": [],
        }
        scores = {
            "games": 1, "margin_mae": 10.0, "margin_rmse": 10.0,
            "winner_accuracy": 50.0, "margin_bias": 0.0, "edge_5_games": 0,
            "edge_5_record": "0-0-0", "edge_5_hit_rate": None,
        }
        with (
            mock.patch.object(challenger, "load_seasons", return_value={}),
            mock.patch.object(challenger, "load_personnel", return_value={}),
            mock.patch.object(challenger, "generate_rows", return_value=rows),
            mock.patch.object(challenger, "add_challenger_features"),
            mock.patch.object(challenger, "candidate_table", return_value=[selected, incumbent]),
            mock.patch.object(challenger, "fit_ridge", return_value={}),
            mock.patch.object(challenger, "score", return_value=scores),
        ):
            payload = challenger.build(Path("history"), Path("personnel"))
        self.assertEqual(payload["candidate_count"], 2)
        self.assertEqual(payload["selected_candidate"]["name"], "challenger")


if __name__ == "__main__":
    unittest.main()
