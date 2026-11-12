#!/usr/bin/env python3
import unittest

from scripts.build_cfb_live_center import build


class CfbLiveCenterTest(unittest.TestCase):
    def test_builds_analysis_only_live_center(self):
        live = {"games": [{"game_id": "espn-x", "away_team": "Notre Dame", "home_team": "USC", "status": "live"}]}
        projections = {"games": [{
            "game_id": 401234, "away": {"team": "Notre Dame"}, "home": {"team": "USC"},
            "projection": {"home_spread": 3.5, "total": 55.5},
        }]}
        provider = {
            "status": "in_progress", "period": 2, "clock": "08:00", "possession": "USC", "down": 2, "distance": 6, "yardsToGoal": 44,
            "teams": [
                {"team": "Notre Dame", "homeAway": "away", "points": 14, "epaPerPlay": .22, "successRate": .48},
                {"team": "USC", "homeAway": "home", "points": 10, "epaPerPlay": .11, "successRate": .42},
            ],
            "drives": [{"id": "1", "offense": "Notre Dame", "result": "TD", "pointsGained": 7, "plays": [
                {"homeScore": 10, "awayScore": 14, "period": 2, "clock": "08:00", "team": "Notre Dame", "rushPass": "pass", "yardsGained": 22, "epa": 1.2, "success": True, "garbageTime": False, "playType": "Pass"}
            ]}],
        }
        seen = []
        result = build(live, projections, "secret", lambda game_id, _key: seen.append(game_id) or provider)
        self.assertEqual(seen, [401234])
        self.assertEqual(result["meta"]["tracked_game_count"], 1)
        game = result["games"][0]
        self.assertEqual(game["game_flow"]["explosive_plays"], 1)
        self.assertIn("projected_final", game["live_estimate"])
        flat = str(result).lower()
        self.assertNotIn("live odds", flat.replace("no live odds", ""))
        self.assertNotIn("moneyline", flat)

    def test_missing_key_is_safe(self):
        result = build({"games": [{"away_team": "A", "home_team": "B"}]}, {"games": [{"game_id": 1, "away": {"team": "A"}, "home": {"team": "B"}}]}, None)
        self.assertEqual(result["games"], [])
        self.assertEqual(len(result["fetch_errors"]), 1)


if __name__ == "__main__":
    unittest.main()
