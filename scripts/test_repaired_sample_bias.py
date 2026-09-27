"""Regression tests for repaired-ledger sample accounting."""
import unittest

import pandas as pd

from audit_repaired_sample_bias import build_report


class BiasAuditTests(unittest.TestCase):
    def test_cohorts_are_mutually_exclusive_and_complete(self):
        table = pd.DataFrame([
            {"season": 2022, "game_id": "1", "drive_id": "a", "target_offensive_points": 0, "start_yards_to_endzone": 75, "start_period": 1},
            {"season": 2022, "game_id": "2", "drive_id": "b", "target_offensive_points": 7, "start_yards_to_endzone": 40, "start_period": 4},
            {"season": 2022, "game_id": "3", "drive_id": "c", "target_offensive_points": 3, "start_yards_to_endzone": 55, "start_period": 2},
        ])
        strict = {"excluded_games": [{"game_id": "2"}, {"game_id": "3"}]}
        audit = {"games": [{"game_id": "2", "recoverable": True}, {"game_id": "3", "recoverable": False}]}
        report = build_report(table, strict, audit)
        self.assertEqual(report["full_sample"]["games"], 3)
        self.assertEqual(report["cohorts"]["strict_eligible"]["games"], 1)
        self.assertEqual(report["cohorts"]["repaired"]["games"], 1)
        self.assertEqual(report["cohorts"]["quarantined"]["games"], 1)
        self.assertEqual(sum(x["possessions"] for x in report["cohorts"].values()), 3)


if __name__ == "__main__":
    unittest.main()
