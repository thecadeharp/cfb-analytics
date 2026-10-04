#!/usr/bin/env python3

import math
import unittest

from scripts.build_cbb_player_research import build_player_research


def player(index: int, quality: float, team_id: int = 1) -> dict:
    minutes = 300 + index * 20
    return {
        "season": 2026,
        "teamId": team_id,
        "team": f"Team {team_id}",
        "conference": "TST",
        "athleteId": 1000 + index,
        "athleteSourceId": f"source-{index}",
        "name": f"Player {index}",
        "position": "G" if index % 2 else "F",
        "games": 20,
        "starts": 15,
        "minutes": minutes,
        "points": 100 + quality * 45,
        "turnovers": 30 - quality * 2,
        "fouls": 20,
        "assists": 35 + quality * 8,
        "steals": 10 + quality * 3,
        "blocks": 4 + quality * 2,
        "usage": 18 + quality,
        "offensiveRating": 100 + quality * 2,
        "defensiveRating": 110 - quality * 2,
        "netRating": -10 + quality * 4,
        "PORPAG": quality,
        "effectiveFieldGoalPct": 45 + quality * 2,
        "trueShootingPct": 48 + quality * 2,
        "assistsTurnoverRatio": 1 + quality / 2,
        "freeThrowRate": 20 + quality,
        "offensiveReboundPct": 3 + quality / 2,
        "rebounds": {"total": 50 + quality * 8, "defensive": 35 + quality * 5, "offensive": 15 + quality * 3},
        "winShares": {"totalPer40": quality / 2, "total": quality, "defensive": quality / 3, "offensive": quality * 2 / 3},
    }


class CbbPlayerResearchTests(unittest.TestCase):
    def test_builds_ranked_identity_safe_research_rows(self):
        players = [player(i, float(i), 1 + i % 2) for i in range(12)]
        teams = [
            {"teamId": 1, "games": 30, "pace": 68, "teamStats": {"possessions": 2000}},
            {"teamId": 2, "games": 30, "pace": 72, "teamStats": {"possessions": 2100}},
        ]
        payload = build_player_research(2026, players, teams, min_minutes=0, min_games=0)
        self.assertEqual(payload["meta"]["version"], "thi-cbb-player-research-v1.0")
        self.assertEqual(payload["meta"]["activation_state"], "research_reference_only")
        self.assertFalse(payload["meta"]["raw_api_data_stored"])
        self.assertEqual(len(payload["players"]), 12)
        self.assertEqual(payload["players"][0]["name"], "Player 11")
        self.assertEqual(payload["players"][0]["ranks"]["overall"], 1)
        self.assertEqual(len({row["player_season_id"] for row in payload["players"]}), 12)
        for row in payload["players"]:
            rating = row["research_scores"]["thi_player_rating"]
            self.assertTrue(math.isfinite(rating))
            self.assertGreaterEqual(rating, 1)
            self.assertLessEqual(rating, 99)

    def test_enforces_sample_floor_and_marks_multi_team_stints(self):
        qualified = player(1, 2, 1)
        second_stint = dict(qualified, teamId=2, team="Team 2", minutes=150)
        low_sample = player(2, 3, 1)
        low_sample["minutes"] = 20
        teams = [
            {"teamId": 1, "games": 30, "pace": 68, "teamStats": {"possessions": 2000}},
            {"teamId": 2, "games": 30, "pace": 70, "teamStats": {"possessions": 2050}},
        ]
        payload = build_player_research(2026, [qualified, second_stint, low_sample], teams)
        self.assertEqual(len(payload["players"]), 2)
        self.assertTrue(all(row["multi_team_season"] for row in payload["players"]))
        self.assertNotIn("raw", payload)


if __name__ == "__main__":
    unittest.main()
