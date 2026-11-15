import unittest

from scripts.post_discord_alerts import frozen_settled_rows, team_line


class DiscordAlertTests(unittest.TestCase):
    def test_final_alert_keeps_first_tracked_pregame_side(self):
        rows = [
            {
                "game_id": 401856849,
                "captured_at_utc": "2026-09-02T15:27:05Z",
                "start_date": "2026-11-07T20:30:00Z",
                "away_team": "BYU",
                "home_team": "Utah",
                "snapshot_home_spread": -3.0,
                "preferred_side": "BYU",
                "result_settled": True,
            },
            {
                "game_id": 401856849,
                "captured_at_utc": "2026-11-07T16:27:58Z",
                "start_date": "2026-11-07T20:30:00Z",
                "away_team": "BYU",
                "home_team": "Utah",
                "snapshot_home_spread": -4.5,
                "preferred_side": "Utah",
                "result_settled": True,
            },
        ]
        selected = frozen_settled_rows(rows)["401856849"]
        self.assertEqual(selected["preferred_side"], "BYU")
        self.assertEqual(
            team_line(selected["preferred_side"], selected["snapshot_home_spread"], "Utah"),
            "BYU +3.0",
        )

    def test_aligned_snapshot_does_not_precede_first_real_side(self):
        rows = [
            {
                "game_id": 401862826, "captured_at_utc": "2026-11-08T16:39:00Z",
                "start_date": "2026-11-14T20:30:00Z", "home_team": "Tulsa",
                "away_team": "Florida Atlantic", "snapshot_home_spread": -5.0,
                "preferred_side": None, "result_settled": True,
            },
            {
                "game_id": 401862826, "captured_at_utc": "2026-11-10T17:46:00Z",
                "start_date": "2026-11-14T20:30:00Z", "home_team": "Tulsa",
                "away_team": "Florida Atlantic", "snapshot_home_spread": -5.5,
                "preferred_side": "Tulsa", "ats_result": "W", "result_settled": True,
            },
            {
                "game_id": 401862826, "captured_at_utc": "2026-11-14T16:40:00Z",
                "start_date": "2026-11-14T20:30:00Z", "home_team": "Tulsa",
                "away_team": "Florida Atlantic", "snapshot_home_spread": -6.5,
                "preferred_side": "Florida Atlantic", "ats_result": "L", "result_settled": True,
            },
        ]
        selected = frozen_settled_rows(rows)["401862826"]
        self.assertEqual(selected["preferred_side"], "Tulsa")
        self.assertEqual(selected["snapshot_home_spread"], -5.5)
        self.assertEqual(selected["ats_result"], "W")


if __name__ == "__main__":
    unittest.main()
