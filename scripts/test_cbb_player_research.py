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
        self.assertEqual(payload["meta"]["version"], "thi-cbb-player-research-v1.3")
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
        self.assertEqual(sum(row["player_count"] for row in payload["team_rosters"]), 12)
        self.assertTrue(all(row["rated_player_count"] == row["player_count"] for row in payload["team_rosters"]))
        self.assertTrue(all(row["returning_minutes_pct"] == 100.0 for row in payload["team_rosters"]))
        for row in payload["players"]:
            rating = row["research_scores"]["thi_player_rating"]
            self.assertTrue(math.isfinite(rating))
            self.assertGreaterEqual(rating, 1)
            self.assertLessEqual(rating, 99)
            self.assertIn("prior_production_rating", row["research_scores"])
            self.assertIn("competition_adjustment", row["projection_context"])

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
        self.assertEqual(payload["team_rosters"][0]["player_count"], 2)
        roster_states = {row["name"]: row["prior_state"] for row in payload["team_rosters"][0]["players"]}
        self.assertEqual(roster_states[qualified["name"]], "rated")
        self.assertEqual(roster_states[low_sample["name"]], "below_sample")
        self.assertNotIn(departed["name"], roster_states)
        self.assertIsNone(payload["team_rosters"][0]["returning_minutes_pct"])
        self.assertNotIn("raw", payload)

    def test_derives_returning_minutes_against_full_prior_team_minutes(self):
        returning = player(1, 4, 1)
        departed = player(2, 3, 1)
        teams = [{"teamId": 1, "games": 30, "pace": 68, "teamStats": {"possessions": 2000}}]
        payload = build_player_research(2026, 2027, [returning, departed], teams, [roster([returning], 1)])
        team = payload["team_rosters"][0]
        expected = 100 * returning["minutes"] / (returning["minutes"] + departed["minutes"])
        self.assertAlmostEqual(team["returning_minutes_pct"], expected, places=2)

    def test_projected_impact_translates_equal_production_by_team_strength(self):
        strong = player(1, 4, 1)
        weak = dict(strong, teamId=2, team="Team 2", athleteId=2002, athleteSourceId="source-weak", name="Weak Schedule Player")
        teams = [
            {"teamId": 1, "adjustedEfficiency": {"netRating": 25, "rankings": {"net": 5}}},
            {"teamId": 2, "adjustedEfficiency": {"netRating": -12, "rankings": {"net": 330}}},
            {"teamId": 3, "adjustedEfficiency": {"netRating": 0, "rankings": {"net": 170}}},
        ]
        payload = build_player_research(
            2026,
            2027,
            [strong, weak],
            teams,
            [roster([strong], 1), roster([weak], 2)],
            min_minutes=0,
            min_games=0,
        )
        by_name = {row["name"]: row for row in payload["players"]}
        self.assertGreater(
            by_name[strong["name"]]["research_scores"]["projected_impact_rating"],
            by_name[weak["name"]]["research_scores"]["projected_impact_rating"],
        )
        self.assertEqual(
            by_name[strong["name"]]["research_scores"]["prior_production_rating"],
            by_name[weak["name"]]["research_scores"]["prior_production_rating"],
        )

    def test_adds_verified_recruit_without_fabricating_prior_stats(self):
        veteran = player(1, 4, 1)
        newcomer = {
            "athleteId": 9001,
            "athleteSourceId": "freshman-source",
            "name": "Elite Freshman",
            "position": "G",
        }
        current_roster = roster([veteran], 1)
        current_roster["players"].append({
            "id": newcomer["athleteId"],
            "sourceId": newcomer["athleteSourceId"],
            "name": newcomer["name"],
            "position": newcomer["position"],
        })
        recruits = [{
            "athleteId": newcomer["athleteId"],
            "firstName": "Elite",
            "lastName": "Freshman",
            "rating": 0.995,
            "stars": 5,
            "committedTo": {"id": 1},
        }]
        payload = build_player_research(
            2026,
            2027,
            [veteran],
            [{"teamId": 1, "adjustedEfficiency": {"netRating": 20}}],
            [current_roster],
            min_minutes=0,
            min_games=0,
            recruits=recruits,
        )
        freshman = next(row for row in payload["players"] if row["name"] == newcomer["name"])
        self.assertEqual(freshman["projection_context"]["basis"], "freshman projection")
        self.assertIsNone(freshman["research_scores"]["prior_production_rating"])
        self.assertEqual(freshman["sample"]["minutes"], 0.0)
        self.assertEqual(payload["coverage"]["projected_newcomers"], 1)

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
