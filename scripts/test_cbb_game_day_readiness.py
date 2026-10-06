#!/usr/bin/env python3

import unittest
from datetime import datetime, timezone

from scripts.build_cbb_game_day_readiness import build


class CbbGameDayReadinessTests(unittest.TestCase):
    def test_requires_frozen_projection_score_and_close_for_tracked_final(self):
        now = datetime(2026, 11, 3, tzinfo=timezone.utc)
        board = {
            "meta": {"version": "thi-cbb-projection-board-v0.5", "season": 2027, "generated_at_utc": "2026-11-03T00:00:00Z"},
            "games": [{
                "game_id": 1, "status": "final", "away": {"score": 70}, "home": {"score": 75},
                "market": {"consensus_home_spread": -3}, "closing_market": {"consensus_home_spread": -4},
                "projection": {"home_margin": 5},
            }],
        }
        tracking = {"meta": {"projection_board_version": "thi-cbb-projection-board-v0.5"}, "spread_decisions": []}
        payload = build(board, tracking, now)
        self.assertEqual(payload["meta"]["status"], "ready")
        self.assertEqual(payload["coverage"]["finals_with_frozen_projection"], 1)
        board["games"][0]["closing_market"] = None
        failed = build(board, tracking, now)
        self.assertEqual(failed["meta"]["status"], "attention_required")
        self.assertIn("all_final_games_have_closing_market_when_opening_market_exists", failed["exceptions"])


if __name__ == "__main__":
    unittest.main()
