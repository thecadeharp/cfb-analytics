#!/usr/bin/env python3

import unittest

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


if __name__ == "__main__":
    unittest.main()
