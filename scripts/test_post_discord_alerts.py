import unittest

from scripts.post_discord_alerts import latest_settled_rows, team_line


class DiscordAlertTests(unittest.TestCase):
    def test_final_alert_uses_latest_tracked_pregame_side(self):
        rows = [
            {
                "game_id": 401856849,
                "captured_at_utc": "2026-09-02T15:27:05Z",
                "snapshot_home_spread": -3.0,
                "preferred_side": "BYU",
                "result_settled": True,
            },
            {
                "game_id": 401856849,
                "captured_at_utc": "2026-11-07T16:27:58Z",
                "snapshot_home_spread": -4.5,
                "preferred_side": "Utah",
                "result_settled": True,
            },
        ]
        selected = latest_settled_rows(rows)["401856849"]
        self.assertEqual(selected["preferred_side"], "Utah")
        self.assertEqual(
            team_line(selected["preferred_side"], selected["snapshot_home_spread"], "Utah"),
            "Utah -4.5",
        )


if __name__ == "__main__":
    unittest.main()
