import unittest
from datetime import datetime, timezone

from scripts.refresh_cbb_markets import active_window, capture_window, odds_api_lines, refresh


class RefreshCbbMarketsTests(unittest.TestCase):
    def test_force_targets_first_upcoming_slate_before_opening_week(self):
        now = datetime(2026, 10, 24, tzinfo=timezone.utc)
        board = {
            "games": [
                {"game_id": 1, "status": "scheduled", "start_date": "2026-11-02T23:00:00Z"},
                {"game_id": 2, "status": "scheduled", "start_date": "2026-11-04T00:00:00Z"},
                {"game_id": 3, "status": "scheduled", "start_date": "2026-11-07T00:00:00Z"},
            ]
        }
        self.assertEqual(active_window(board, now, 72), [])
        selected = capture_window(board, now, 72, force=True)
        self.assertEqual([game["game_id"] for game in selected], [1, 2])

    def test_transforms_draftkings_event_to_internal_game(self):
        board = {
            "games": [{
                "game_id": 44,
                "home": {"team": "UConn"},
                "away": {"team": "American University"},
            }]
        }
        events = [{
            "home_team": "UConn Huskies",
            "away_team": "American Eagles",
            "bookmakers": [{
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {"key": "spreads", "outcomes": [{"name": "UConn Huskies", "point": -24.5}, {"name": "American Eagles", "point": 24.5}]},
                    {"key": "totals", "outcomes": [{"name": "Over", "point": 146.5}, {"name": "Under", "point": 146.5}]},
                    {"key": "h2h", "outcomes": [{"name": "UConn Huskies", "price": -5000}, {"name": "American Eagles", "price": 1800}]},
                ],
            }],
        }]
        rows = odds_api_lines(board, events, {"44"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["lines"][0]["provider"], "DraftKings")
        self.assertEqual(rows[0]["lines"][0]["spread"], -24.5)
        self.assertEqual(rows[0]["lines"][0]["overUnder"], 146.5)

    def test_freezes_first_open_and_preserves_neutral_site(self):
        now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        board = {"meta": {}, "games": [{"game_id": 9, "status": "scheduled", "start_date": "2026-11-03T00:00:00Z", "neutral_site": True, "away": {"team": "Ohio State"}, "home": {"team": "BYU"}, "market": None}]}
        self.assertEqual(len(active_window(board, now, 72)), 1)
        lines = [{"gameId": 9, "lines": [{"spread": -2.5, "spreadOpen": -1.5, "overUnder": 145.5, "overUnderOpen": 144.0}]}]
        board, history, changed = refresh(board, None, lines, now, {"9"})
        self.assertEqual(changed, 1)
        self.assertTrue(board["games"][0]["neutral_site"])
        self.assertEqual(board["games"][0]["market"]["opening_home_spread"], -1.5)
        later = datetime(2026, 11, 2, 1, tzinfo=timezone.utc)
        moved = [{"gameId": 9, "lines": [{"spread": -3.0, "spreadOpen": -2.0, "overUnder": 146.0, "overUnderOpen": 145.0}]}]
        board, history, changed = refresh(board, history, moved, later, {"9"})
        self.assertEqual(changed, 1)
        self.assertEqual(board["games"][0]["market"]["opening_home_spread"], -1.5)
        self.assertEqual(board["games"][0]["market"]["spread_move"], -1.5)
        self.assertEqual(len(history["games"]["9"]), 2)


if __name__ == "__main__":
    unittest.main()
