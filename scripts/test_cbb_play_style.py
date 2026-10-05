#!/usr/bin/env python3

import unittest

from scripts.build_cbb_play_style import aggregate_game, build_play_style


class CbbPlayStyleTests(unittest.TestCase):
    def test_keeps_only_compact_real_play_metadata(self):
        game = {"game_id": 7, "start_date": "2026-11-01", "home": {"team_id": 1, "team": "Alpha"}, "away": {"team_id": 2, "team": "Beta"}}
        plays = [
            {"teamId": 1, "playType": "Fast Break Layup", "onFloor": [1, 2], "shotInfo": {"range": "rim", "made": True, "assisted": True}},
            {"teamId": 1, "playType": "Jump Shot", "shotInfo": {"range": "three point", "made": False, "assisted": False}},
            {"teamId": 2, "playType": "Jump Shot", "shotInfo": {"range": "midrange", "made": True, "assisted": False}},
            {"teamId": 999, "playType": "Turnover"},
        ]
        result = aggregate_game(game, plays)
        alpha = next(row for row in result["teams"] if row["team_id"] == 1)
        self.assertEqual(alpha["tracked_shots"], 2)
        self.assertEqual(alpha["rim_rate"], 50.0)
        self.assertEqual(alpha["three_rate"], 50.0)
        self.assertEqual(alpha["explicit_transition_plays"], 1)
        self.assertEqual(result["unmatched_play_count"], 1)
        self.assertNotIn("raw_plays", result)

    def test_refresh_is_bounded_and_preserves_existing_games(self):
        board = {"meta": {"season": 2027}, "games": [
            {"game_id": 1, "status": "final", "start_date": "1", "home": {"team_id": 1}, "away": {"team_id": 2}},
            {"game_id": 2, "status": "final", "start_date": "2", "home": {"team_id": 1}, "away": {"team_id": 3}},
            {"game_id": 3, "status": "scheduled", "start_date": "3", "home": {"team_id": 1}, "away": {"team_id": 4}},
        ]}
        existing = {"meta": {"season": 2027}, "games": [{"game_id": 1, "start_date": "1", "teams": []}]}
        calls = []
        payload = build_play_style(board, existing, lambda path, _params: calls.append(path) or [], max_games=1)
        self.assertEqual(calls, ["/plays/game/2"])
        self.assertEqual(payload["meta"]["game_count"], 2)
        self.assertFalse(payload["meta"]["raw_play_by_play_stored"])


if __name__ == "__main__":
    unittest.main()
