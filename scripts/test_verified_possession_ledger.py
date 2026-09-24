"""Regression cases for missing labels, transitions and duplicate/corrected plays."""
import unittest
import json

import pandas as pd

from build_verified_possession_ledger import build_ledger, review_records
from reconstruct_scoring_events import reconstructed_events


def play(i, drive="a", team="1", kind="Rush", period=1, minute=None, **values):
    row = {"game_id": "g", "id": str(i), "sequenceNumber": i, "game_play_number": i,
           "drive.id": drive, "pos_team_id": team, "def_pos_team_id": "2" if team == "1" else "1",
           "homeTeamId": "1", "awayTeamId": "2", "homeTeamName": "Home", "awayTeamName": "Away",
           "period": period, "clock.minutes": 15-i if minute is None else minute, "clock.seconds": 0,
           "type.text": kind, "text": f"play {i}", "start.yardsToEndzone": 75,
           "start.down": 1, "EPA": 0.2, "EPA_success": 1, "scrimmage_play": True,
           "penalty_no_play": False, "kneel_down": False, "downs_turnover": False,
           "is_pos_team_turnover": False, "drive.result": "unknown", "drive.offensivePlays": 2,
           "scoringType.name": None, "pointAfterAttempt.value": None,
           "offense_score_play": False, "defense_score_play": False,
           "start.homeScore": 0, "start.awayScore": 0, "homeScore": 0, "awayScore": 0,
           "seasonType": 2, "status_type_completed": True}
    if kind == "Rushing Touchdown":
        row.update({"scoringType.name": "touchdown", "pointAfterAttempt.value": 1,
                    "offense_score_play": True, "homeScore": 7 if team == "1" else 0,
                    "awayScore": 7 if team == "2" else 0})
    row.update(values)
    return row


def run(rows):
    frame = pd.DataFrame(rows)
    return build_ledger(frame, reconstructed_events(frame))


class LedgerTests(unittest.TestCase):
    def test_review_missing_values_are_json_null(self):
        review = pd.DataFrame({
            "game_id": ["g", "g"],
            "drive_id": pd.Series(["a", float("nan")], dtype="str"),
            "play_id": [123.0, float("nan")],
            "reason": ["duplicate_play_id", "clock_reversal_in_source_sequence"],
        })
        result = json.loads(json.dumps(review_records(review), allow_nan=False))
        self.assertIsNone(result[1]["drive_id"])
        self.assertIsNone(result[1]["play_id"])
        self.assertEqual(result[0]["drive_id"], "a")
        self.assertEqual(result[0]["play_id"], 123)

    def test_nullable_and_empty_review_records(self):
        review = pd.DataFrame({"drive_id": pd.Series([pd.NA], dtype="string"),
                               "play_id": pd.Series([pd.NA], dtype="Int64")})
        self.assertEqual(json.loads(json.dumps(review_records(review), allow_nan=False)),
                         [{"drive_id": None, "play_id": None}])
        self.assertEqual(review_records(review.head(0)), [])

    def base(self):
        return [play(1), play(2, kind="Punt"), play(3, "b", "2"),
                play(4, "b", "2", "Rushing Touchdown")]

    def test_scoreless_and_scoring_drives(self):
        ledger, events, _, report = run(self.base())
        self.assertEqual(ledger.offensive_points.tolist(), [0, 7])
        self.assertEqual(report["checked_scoreless_possessions"], 1)
        self.assertEqual(events.points.sum(), ledger.assigned_offensive_points.sum())
        self.assertFalse(ledger.training_eligible.any())

    def test_kickoff_timeout_carryover_does_not_change_owner(self):
        rows = self.base() + [play(5, "b", "1", "Kickoff"), play(6, "b", "1", "Timeout")]
        ledger, _, _, _ = run(rows)
        self.assertEqual(ledger.offensive_points.tolist(), [0, 7])

    def test_unassigned_score_never_becomes_zero(self):
        rows = self.base() + [play(5, None, "1", "Rushing Touchdown")]
        ledger, _, _, report = run(rows)
        self.assertTrue(ledger.offensive_points.isna().all())
        self.assertEqual(report["unassigned_offensive_points"], 7)

    def test_duplicate_score_is_quarantined_not_silently_deduplicated(self):
        rows = self.base()
        rows.append(rows[-1].copy())
        ledger, events, _, report = run(rows)
        self.assertTrue(ledger.offensive_points.isna().all())
        self.assertEqual(len(events), 2)
        self.assertIn("duplicate_play_id", report["issue_counts"])

    def test_conflicting_duplicate_id(self):
        rows = self.base() + [play(1, kind="Pass Incompletion")]
        ledger, _, _, report = run(rows)
        self.assertIn("conflicting_play_id", report["issue_counts"])
        self.assertTrue(ledger.offensive_points.isna().all())

    def test_drive_reappearing_after_opponent(self):
        rows = self.base() + [play(5, "a", kind="Punt")]
        ledger, _, _, report = run(rows)
        self.assertIn("drive_reappears_after_other_drive", report["issue_counts"])
        self.assertTrue(ledger.offensive_points.isna().all())

    def test_clock_reversal_is_flagged(self):
        rows = self.base()
        rows[1]["clock.minutes"] = 15
        _, _, _, report = run(rows)
        self.assertIn("clock_reversal_in_source_sequence", report["issue_counts"])

    def test_missing_field_position_does_not_borrow_later_value(self):
        rows = self.base()
        rows[0]["start.yardsToEndzone"] = None
        ledger, _, _, _ = run(rows)
        self.assertTrue(pd.isna(ledger.iloc[0].offensive_points))
        self.assertTrue(pd.isna(ledger.iloc[0].start_yards_to_endzone))

    def test_overtime_and_return_points_remain_separate(self):
        rows = self.base() + [play(5, "c", "1", "Rushing Touchdown", period=5),
                               play(6, "b", "2", "Kickoff Return Touchdown",
                                    **{"scoringType.name": "touchdown", "pointAfterAttempt.value": 1,
                                       "offense_score_play": True})]
        ledger, events, _, report = run(rows)
        self.assertEqual(len(ledger), 2)
        self.assertEqual(report["assigned_offensive_points"], 7)
        self.assertEqual(set(events.status), {"assigned", "overtime_separate", "nonoffensive_separate"})

    def test_penalty_only_drive_is_unresolved(self):
        ledger, _, _, report = run(self.base() + [play(5, "c", kind="Penalty")])
        self.assertEqual(report["keys_without_possession_evidence"], 1)
        self.assertTrue(ledger.offensive_points.isna().all())

    def test_fumble_from_other_team_does_not_get_ignored(self):
        rows = self.base() + [play(5, "b", "1", "Fumble")]
        ledger, _, _, report = run(rows)
        self.assertEqual(report["unassigned_offensive_events"], 1)
        self.assertTrue(ledger.offensive_points.isna().all())

    def test_different_ids_with_same_scoring_fingerprint(self):
        rows = self.base()
        copy = rows[-1].copy()
        copy["id"] = "99"
        rows.append(copy)
        _, _, _, report = run(rows)
        self.assertIn("duplicate_scoring_fingerprint", report["issue_counts"])

    def test_missing_clock_is_quarantined(self):
        rows = self.base()
        rows[0]["clock.minutes"] = None
        ledger, _, _, report = run(rows)
        self.assertIn("invalid_core_clock", report["issue_counts"])
        self.assertTrue(ledger.offensive_points.isna().all())

    def test_drive_cannot_continue_across_halftime(self):
        rows = self.base()
        rows[0]["period"] = 2
        rows[1]["period"] = 3
        _, _, _, report = run(rows)
        self.assertIn("drive_crosses_halftime", report["issue_counts"])

    def test_raw_score_stamp_does_not_supply_points(self):
        rows = self.base()
        rows[1]["homeScore"] = 40
        ledger, _, _, _ = run(rows)
        self.assertEqual(ledger.iloc[0].offensive_points, 0)


if __name__ == "__main__":
    unittest.main()
