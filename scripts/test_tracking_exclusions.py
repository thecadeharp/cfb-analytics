#!/usr/bin/env python3
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TrackingExclusionContractTest(unittest.TestCase):
    def test_northwestern_iowa_is_diagnostic_only(self):
        settled = json.loads((ROOT / "data/reports/settled_results.json").read_text())
        rows = [row for row in settled["rows"] if str(row.get("game_key")) == "401858513"]
        self.assertTrue(rows)
        self.assertTrue(all(row.get("tracking_eligible") is False for row in rows))
        self.assertTrue(all(row.get("diagnostic_only") is True for row in rows))
        self.assertEqual({row.get("tracking_exclusion_code") for row in rows}, {"late_material_player_scratch"})

    def test_excluded_game_is_not_in_qualified_signal_record(self):
        settled = json.loads((ROOT / "data/reports/settled_results.json").read_text())
        first = {}
        for row in settled["rows"]:
            key = str(row.get("game_key") or "")
            stamp = str(row.get("captured_at_utc") or "")
            if key and (key not in first or stamp < str(first[key].get("captured_at_utc") or "")):
                first[key] = row
        qualified = [row for row in first.values() if row.get("result_settled") and row.get("tracking_eligible", True) is not False]
        self.assertNotIn("401858513", {str(row.get("game_key")) for row in qualified})
        self.assertEqual(settled["counts"]["qualified_tracking_games_excluded"], 1)


if __name__ == "__main__":
    unittest.main()
