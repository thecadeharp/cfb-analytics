import csv
import json
import tempfile
import unittest
from pathlib import Path

from audit_cfbd_training_pack import audit_pack


class TrainingPackAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.csv_path = self.root / "pack.csv"
        self.projections_path = self.root / "projections.json"
        columns = [
            "id", "start_date", "season", "season_type", "week",
            "neutral_site", "home_team", "home_conference", "home_elo",
            "home_talent", "away_team", "away_conference", "away_elo",
            "away_talent", "spread", "home_adjusted_epa",
        ]
        with self.csv_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerow({
                "id": "1", "start_date": "2026-10-10 19:30:00",
                "season": 2026, "season_type": "regular", "week": 6,
                "neutral_site": "False", "home_team": "San José State",
                "home_conference": "Mountain West", "home_elo": 1500,
                "home_talent": 20, "away_team": "Wyoming",
                "away_conference": "Mountain West", "away_elo": 1450,
                "away_talent": 15, "spread": -3.5,
                "home_adjusted_epa": 0.1,
            })
        self.projections_path.write_text(json.dumps({
            "meta": {"metrics_through_week": 5},
            "games": [{
                "game_id": 1, "start_date": "2026-10-10T19:30:00.000Z",
                "neutral_site": False,
                "home": {"team": "San Jose State", "conference": "Mountain West"},
                "away": {"team": "Wyoming", "conference": "Mountain West"},
                "market": {"home_spread": -4.0},
            }],
        }))

    def tearDown(self):
        self.temp.cleanup()

    def test_passes_with_accent_normalization_and_safe_timing(self):
        report = audit_pack(self.csv_path, self.projections_path)
        self.assertEqual(report["meta"]["status"], "PASS")
        self.assertEqual(report["scope"]["matched_games"], 1)
        self.assertEqual(len(report["diagnostics"]["safe_name_normalizations"]), 1)
        self.assertEqual(report["opening_to_current_market"]["paired_games"], 1)

    def test_rejects_leaky_timing(self):
        payload = json.loads(self.projections_path.read_text())
        payload["meta"]["metrics_through_week"] = 6
        self.projections_path.write_text(json.dumps(payload))
        report = audit_pack(self.csv_path, self.projections_path)
        self.assertEqual(report["meta"]["status"], "FAIL")
        self.assertFalse(report["checks"]["pregame_feature_timing_is_safe"])

    def test_kickoff_change_is_warning_when_game_identity_is_stable(self):
        payload = json.loads(self.projections_path.read_text())
        payload["games"][0]["start_date"] = "2026-10-10T20:30:00.000Z"
        self.projections_path.write_text(json.dumps(payload))
        report = audit_pack(self.csv_path, self.projections_path)
        self.assertEqual(report["meta"]["status"], "PASS_WITH_WARNINGS")
        self.assertFalse(report["advisories"]["start_times_match_current_board"])


if __name__ == "__main__":
    unittest.main()
