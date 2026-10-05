#!/usr/bin/env python3

import unittest

from scripts.build_cbb_model_tracking import build_tracking


def game(game_id, edge, eligible, home_score, away_score, pregame=-3, close=-5):
    return {
        "game_id": game_id,
        "start_date": "2027-01-10T00:00:00Z",
        "status": "final",
        "home": {"team_id": 1, "team": "Home", "score": home_score},
        "away": {"team_id": 2, "team": "Away", "score": away_score},
        "market": {"consensus_home_spread": pregame, "consensus_total": 140},
        "closing_market": {"consensus_home_spread": close, "consensus_total": 141},
        "projection": {
            "home_margin": 6,
            "total": 145,
            "spread_edge": edge,
            "spread_signal_eligible": eligible,
            "spread_signal_tier": "play",
            "signal_confidence": "developing",
            "total_edge": 5,
            "totals_signal_eligible": False,
        },
    }


class CbbModelTrackingTests(unittest.TestCase):
    def test_grades_frozen_line_and_calculates_clv(self):
        board = {
            "meta": {"version": "thi-cbb-projection-board-v0.5", "model_version": "thi-cbb-walk-forward-v0.7-research", "season": 2027},
            "games": [
                game(1, 3, True, 75, 70),
                game(2, -4, True, 70, 76, pregame=3, close=5),
                game(3, 2, False, 80, 70),
            ],
        }
        payload = build_tracking(board)
        summary = payload["summary"]["spread"]
        self.assertEqual((summary["wins"], summary["losses"], summary["pushes"]), (2, 0, 0))
        self.assertEqual(summary["hit_rate"], 100.0)
        self.assertEqual(summary["average_clv"], 2.0)
        self.assertEqual(summary["beat_close_pct"], 100.0)
        self.assertEqual(payload["summary"]["totals"]["games"], 0)
        self.assertEqual(payload["summary"]["projection_accuracy"]["games"], 3)

    def test_rejects_unfrozen_board_version(self):
        with self.assertRaisesRegex(RuntimeError, "v0.5"):
            build_tracking({"meta": {"version": "old"}, "games": []})


if __name__ == "__main__":
    unittest.main()
