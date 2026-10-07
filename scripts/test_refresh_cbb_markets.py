import unittest
from datetime import datetime, timezone

from scripts.refresh_cbb_markets import active_window, refresh


class RefreshCbbMarketsTests(unittest.TestCase):
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
