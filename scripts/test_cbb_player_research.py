#!/usr/bin/env python3

import math
import unittest

from scripts.build_cbb_player_research import build_player_research, normalize_espn_roster


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


def roster(players: list[dict], team_id: int = 1, team: str | None = None) -> dict:
    return {
        "teamId": team_id,
        "team": team or f"Team {team_id}",
        "conference": "TST",
        "season": 2027,
        "players": [
            {
                "id": row["athleteId"],
                "sourceId": row["athleteSourceId"],
                "name": row["name"],
                "position": row["position"],
                "jersey": str(index + 1),
            }
            for index, row in enumerate(players)
        ],
    }


class CbbPlayerResearchTests(unittest.TestCase):
    def test_builds_ranked_identity_safe_research_rows(self):
        players = [player(i, float(i), 1 + i % 2) for i in range(12)]
        teams = [
            {"teamId": 1, "games": 30, "pace": 68, "teamStats": {"possessions": 2000}},
            {"teamId": 2, "games": 30, "pace": 72, "teamStats": {"possessions": 2100}},
        ]
        rosters = [roster([row], row["teamId"]) for row in players]
        payload = build_player_research(2026, 2027, players, teams, rosters, min_minutes=0, min_games=0)
        self.assertEqual(payload["meta"]["version"], "thi-cbb-player-research-v1.1")
        self.assertEqual(payload["meta"]["source_season"], 2026)
        self.assertEqual(payload["meta"]["roster_season"], 2027)
        self.assertEqual(payload["meta"]["roster_source"], "cbbd")
        self.assertEqual(payload["meta"]["activation_state"], "research_reference_only")
        self.assertFalse(payload["meta"]["raw_api_data_stored"])
        self.assertEqual(len(payload["players"]), 12)
        self.assertEqual(payload["players"][0]["name"], "Player 11")
        self.assertEqual(payload["players"][0]["ranks"]["overall"], 1)
        self.assertEqual(len({row["player_season_id"] for row in payload["players"]}), 12)
        self.assertTrue(all(row["current_roster_verified"] for row in payload["players"]))
        for row in payload["players"]:
            rating = row["research_scores"]["thi_player_rating"]
            self.assertTrue(math.isfinite(rating))
            self.assertGreaterEqual(rating, 1)
            self.assertLessEqual(rating, 99)

    def test_filters_departures_and_maps_transfers_to_current_roster(self):
        qualified = player(1, 2, 1)
        second_stint = dict(qualified, teamId=2, team="Team 2", minutes=150)
        low_sample = player(2, 3, 1)
        low_sample["minutes"] = 20
        departed = player(3, 9, 1)
        teams = [
            {"teamId": 1, "games": 30, "pace": 68, "teamStats": {"possessions": 2000}},
            {"teamId": 2, "games": 30, "pace": 70, "teamStats": {"possessions": 2050}},
        ]
        current_rosters = [roster([qualified, low_sample], 3, "New Team")]
        payload = build_player_research(2026, 2027, [qualified, second_stint, low_sample, departed], teams, current_rosters)
        self.assertEqual(len(payload["players"]), 1)
        self.assertEqual(payload["players"][0]["name"], qualified["name"])
        self.assertEqual(payload["players"][0]["team"], "New Team")
        self.assertEqual(payload["players"][0]["source_team"], "Team 1")
        self.assertTrue(payload["players"][0]["multi_team_source_season"])
        self.assertTrue(payload["players"][0]["transfer_between_seasons"])
        self.assertEqual(payload["coverage"]["historical_players_withheld_unverified_current"], 1)
        self.assertNotIn("raw", payload)

    def test_rejects_same_or_older_roster_season(self):
        with self.assertRaisesRegex(RuntimeError, "Roster season"):
            build_player_research(2026, 2026, [], [], [])

    def test_normalizes_only_the_requested_espn_roster_season(self):
        team = {"id": 72, "sourceId": "150", "school": "Duke"}
        payload = {
            "season": {"year": 2027, "displayName": "2026-27"},
            "athletes": [{
                "id": "5454779",
                "fullName": "Current Player",
                "jersey": "5",
                "position": {"abbreviation": "G"},
            }],
        }
        roster_row = normalize_espn_roster(team, "ACC", payload, 2027)
        self.assertEqual(roster_row["teamId"], 72)
        self.assertEqual(roster_row["players"][0]["sourceId"], "5454779")
        self.assertEqual(roster_row["players"][0]["position"], "G")
        self.assertIsNone(normalize_espn_roster(team, "ACC", payload, 2026))


if __name__ == "__main__":
    unittest.main()
