import unittest

from scripts.build_cbb_postgame import build_payload


class CbbPostgameTest(unittest.TestCase):
    def test_builds_team_and_player_box_score(self):
        board = {"meta": {"season": 2027}, "games": [{"game_id": 7, "status": "final", "start_date": "2026-11-01T14:30:00Z", "away": {"team": "Away"}, "home": {"team": "Home"}}]}
        base = {"gameId": 7, "pace": 66.2, "teamStats": {"points": {"total": 74}, "fieldGoals": {"made": 28, "attempted": 55, "pct": .509}, "threePointFieldGoals": {"made": 8, "attempted": 20, "pct": .4}, "freeThrows": {"made": 10, "attempted": 12, "pct": .833}, "rebounds": {"total": 35, "offensive": 8}, "turnovers": {"total": 9}, "fourFactors": {"effectiveFieldGoalPct": .582}, "assists": 17}}
        team_rows = [dict(base, isHome=False, teamId=1, team="Away"), dict(base, isHome=True, teamId=2, team="Home")]
        player = {"name": "Player One", "starter": True, "minutes": 31, "points": 20, "rebounds": {"total": 7}, "assists": 4, "fieldGoals": {"made": 7, "attempted": 12, "pct": .583}}
        player_rows = [{"gameId": 7, "isHome": False, "teamId": 1, "team": "Away", "players": [player]}, {"gameId": 7, "isHome": True, "teamId": 2, "team": "Home", "players": [player]}]
        payload = build_payload(board, team_rows, player_rows)
        self.assertEqual(payload["meta"]["complete_box_score_count"], 1)
        self.assertEqual(payload["games"]["7"]["teams"]["away"]["stats"]["effective_fg_pct"], 58.2)
        self.assertEqual(payload["games"]["7"]["players"]["home"]["players"][0]["points"], 20)


if __name__ == "__main__":
    unittest.main()
