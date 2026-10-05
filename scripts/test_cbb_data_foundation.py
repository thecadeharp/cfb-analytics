#!/usr/bin/env python3

import unittest

from scripts.build_cbb_data_foundation import build_outputs


class CbbDataFoundationTests(unittest.TestCase):
    def test_builds_current_edges_prior_continuity_and_consensus_market(self):
        directory = [{"id": 1, "sourceId": "1234", "school": "Alpha", "conferenceId": 10}]
        directory += [{"id": i, "school": f"Team {i}", "conferenceId": 10} for i in range(2, 301)]
        prior = [{
            "season": 2026, "teamId": i, "team": "Alpha" if i == 1 else f"Team {i}",
            "record": {"games": 30, "wins": 20, "losses": 10}, "summary": {},
            "teamStats": {"effectiveFieldGoalPct": .51, "turnoverRatio": .18, "offensiveReboundPct": .31, "freeThrowRate": .27},
            "opponentStats": {"effectiveFieldGoalPct": .50, "turnoverRatio": .19, "offensiveReboundPct": .29, "freeThrowRate": .25}, "shotProfile": {},
            "adjustedEfficiency": {"offensiveRating": 110 + i / 100, "defensiveRating": 100, "netRating": 10 + i / 100, "rankings": {"offense": i, "defense": i, "net": i}},
        } for i in range(1, 301)]
        responses = {
            "/teams/directory": {"teams": directory, "conferences": [{"id": 10, "name": "Test Conference", "abbreviation": "TC"}]},
            "/stats/team/leaderboard:2027": [{
                "teamId": 1, "record": {"games": 4, "wins": 3, "losses": 1},
                "summary": {"pace": 68.25, "trackedShots": 220, "rawNetRating": 15.3},
                "teamStats": {"rawOffensiveRating": 112.4, "trueShootingPct": .58, "effectiveFieldGoalPct": .55, "turnoverRatio": .16, "offensiveReboundPct": .34, "freeThrowRate": .29},
                "opponentStats": {"rawOffensiveRating": 97.1, "effectiveFieldGoalPct": .48, "turnoverRatio": .21, "offensiveReboundPct": .25, "freeThrowRate": .24},
                "shotProfile": {"assistedPct": .61, "atRim": {"rate": .39}, "distribution": {"threeRate": .44, "midrangeRate": .17}},
                "adjustedEfficiency": {"offensiveRating": 114.2, "defensiveRating": 96.8, "netRating": 17.4, "rankings": {"offense": 8, "defense": 12, "net": 5}},
            }],
            "/stats/team/leaderboard:2026": prior,
            "/teams/roster": [{"teamId": 1, "team": "Alpha", "season": 2027, "players": [{"id": 101}, {"id": 103}]}],
            "/stats/player/season": [
                {"teamId": 1, "athleteId": 101, "minutes": 600, "points": 300, "usage": 25},
                {"teamId": 1, "athleteId": 102, "minutes": 400, "points": 200, "usage": 20},
            ],
            "/games": [{"id": 99, "startDate": "2026-11-02T00:00:00Z", "status": "scheduled", "homeTeamId": 1, "homeTeam": "Alpha", "awayTeamId": 2, "awayTeam": "Beta"}],
            "/games/media": [{"gameId": 99, "broadcasts": [{"broadcastName": "ESPN2"}]}],
            "/lines": [{"gameId": 99, "lines": [{"provider": "A", "spread": -4, "spreadOpen": -2.5, "overUnder": 145, "overUnderOpen": 143}, {"provider": "B", "spread": -3, "spreadOpen": -2.5, "overUnder": 144, "overUnderOpen": 143}]}],
        }

        def fetch(path, params):
            if path == "/stats/team/leaderboard":
                return responses[f"{path}:{params['season']}"]
            return responses[path]

        teams, board, status = build_outputs(2027, 2026, "start", "end", fetch)
        alpha = next(row for row in teams["teams"] if row["team"] == "Alpha")
        self.assertEqual(alpha["current_efficiency"]["raw_net_per_100"], 15.3)
        self.assertEqual(alpha["current_efficiency"]["adjusted"]["net"], 17.4)
        self.assertEqual(alpha["four_factor_edges"]["effective_fg_pct"], 7.0)
        self.assertEqual(alpha["four_factor_edges"]["turnover_pct"], 5.0)
        self.assertEqual(alpha["four_factors"]["offense"]["effective_fg_pct"], 55.0)
        self.assertEqual(alpha["four_factors"]["defense"]["effective_fg_pct"], 48.0)
        self.assertEqual(alpha["preseason_prior"]["four_factors"]["offense"]["turnover_pct"], 18.0)
        self.assertEqual(alpha["preseason_prior"]["returning_minutes_pct"], 60.0)
        self.assertEqual(alpha["preseason_prior"]["returning_points_pct"], 60.0)
        self.assertEqual(alpha["espn_id"], "1234")
        self.assertEqual(alpha["logo_url"], "https://a.espncdn.com/i/teamlogos/ncaa/500/1234.png")
        self.assertTrue(alpha["sample_ready"])
        self.assertEqual(board["games"][0]["market"]["consensus_home_spread"], -3.5)
        self.assertEqual(board["games"][0]["market"]["spread_move"], -1.0)
        self.assertEqual(board["games"][0]["broadcasts"], ["ESPN2"])
        self.assertEqual(status["meta"]["request_count"], 8)
        self.assertEqual(status["meta"]["builder_version"], "cbb-foundation-v2.2")
        self.assertFalse(status["meta"]["raw_api_data_stored"])


if __name__ == "__main__":
    unittest.main()
