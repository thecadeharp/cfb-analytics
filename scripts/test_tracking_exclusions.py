#!/usr/bin/env python3
import json
import unittest
from pathlib import Path

from scripts.settle_results import summarize


ROOT = Path(__file__).resolve().parents[1]


class TrackingExclusionContractTest(unittest.TestCase):
    def test_material_late_scratches_are_declared_diagnostic_only(self):
        payload = json.loads((ROOT / "data/tracking_exclusions.json").read_text())
        exclusions = {str(row.get("game_id")): row for row in payload.get("exclusions") or []}
        self.assertEqual({"401858513", "401856882"}, set(exclusions))
        for row in exclusions.values():
            self.assertTrue(row.get("exclude_from_qualified_tracking"))
            self.assertTrue(row.get("retain_diagnostic_errors"))
            self.assertEqual("late_material_player_scratch", row.get("code"))

    def test_excluded_rows_do_not_change_qualified_records(self):
        rows = [
            {"result_settled": True, "ats_result": "W", "total_result": "W", "model_margin_error": 1.0},
            {"result_settled": True, "ats_result": "L", "total_result": "L", "model_margin_error": 20.0,
             "tracking_eligible": False, "diagnostic_only": True},
        ]
        summary = summarize(rows)
        self.assertEqual(1, summary["settled_rows"])
        self.assertEqual(1, summary["ats_wins"])
        self.assertEqual(0, summary["ats_losses"])
        self.assertEqual(1, summary["total_wins"])
        self.assertEqual(0, summary["total_losses"])


if __name__ == "__main__":
    unittest.main()
