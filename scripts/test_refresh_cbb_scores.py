#!/usr/bin/env python3

import unittest
from datetime import datetime, timezone

from scripts.refresh_cbb_scores import canonical_status, refresh


class CbbScorePulseTests(unittest.TestCase):
    def test_normalizes_provider_statuses(self):
        self.assertEqual(canonical_status("in_progress"), "live")
        self.assertEqual(canonical_status("Halftime"), "live")
        self.assertEqual(canonical_status("Final"), "final")
        self.assertEqual(canonical_status("scheduled"), "scheduled")

    def test_updates_scores_and_preserves_frozen_projection(self):
        games = {
            "meta": {"season": 2027},
            "games": [
                {"game_id": 1, "start_date": "2026-11-02T11:00:00Z", "status": "scheduled", "home": {"score": 0}, "away": {"score": 0}},
                {"game_id": 2, "start_date": "2026-11-02T08:00:00Z", "status": "scheduled", "home": {"score": 0}, "away": {"score": 0}},
            ],
        }
        board = {
            "meta": {"season": 2027, "status_counts": {"upcoming": 2, "live": 0, "final": 0}},
            "games": [
                {**games["games"][0], "projection": {"home_margin": -2.7}},
                {**games["games"][1], "projection": {"home_margin": -0.9}},
            ],
        }
        responses = {
            "/games": [
                {"id": 1, "status": "in_progress", "homePoints": 31, "awayPoints": 34},
                {"id": 2, "status": "final", "homePoints": 72, "awayPoints": 78},
            ],
            "/scoreboard": [{"id": 1, "status": "in_progress", "homePoints": 33, "awayPoints": 36, "period": 2, "clock": "17:42"}],
        }
        result = refresh(games, board, lambda path, _params: responses[path], datetime(2026, 11, 2, 12, tzinfo=timezone.utc))

        live, final = board["games"]
        self.assertEqual((live["status"], live["home"]["score"], live["away"]["score"]), ("live", 33, 36))
        self.assertEqual(live["live"], {"period": 2, "clock": "17:42", "detail": None})
        self.assertEqual((final["status"], final["home"]["score"], final["away"]["score"]), ("final", 72, 78))
        self.assertEqual(live["projection"]["home_margin"], -2.7)
        self.assertEqual(final["projection"]["home_margin"], -0.9)
        self.assertEqual(board["meta"]["status_counts"], {"upcoming": 0, "live": 1, "final": 1})
        self.assertEqual(result["newly_final_ids"], ["2"])

    def test_skips_provider_when_no_game_is_near_tipoff(self):
        board = {"meta": {}, "games": [{"game_id": 1, "start_date": "2026-11-04T20:00:00Z", "status": "scheduled"}]}
        called = []
        result = refresh(board, board, lambda path, params: called.append((path, params)), datetime(2026, 11, 2, 12, tzinfo=timezone.utc))
        self.assertFalse(result["active_window"])
        self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
