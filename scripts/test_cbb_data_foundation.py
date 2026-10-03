#!/usr/bin/env python3

import unittest

from scripts.build_cbb_data_foundation import build_outputs


class CbbDataFoundationTests(unittest.TestCase):
    def test_builds_derived_team_edges_and_consensus_market(self):
        responses = {
            "/teams/directory": {"teams": [{"id": 1, "school": "Alpha", "conferenceId": 10}]},
            "/stats/team/leaderboard": [{
                "teamId": 1,
                "record": {"games": 4, "wins": 3, "losses": 1},
                "summary": {"pace": 68.25, "trackedShots": 220},
                "teamStats": {"rawOffensiveRating": 112.4, "trueShootingPct": .58, "fourFactors": {"effectiveFieldGoalPct": .55, "turnoverRatio": .16, "offensiveReboundPct": .34, "freeThrowRate": .29}},
                "opponentStats": {"rawOffensiveRating": 97.1, "fourFactors": {"effectiveFieldGoalPct": .48, "turnoverRatio": .21, "offensiveReboundPct": .25, "freeThrowRate": .24}},
                "shotProfile": {"assistedPct": .61, "atRim": {"rate": .39}, "distribution": {"threeRate": .44, "midrangeRate": .17}},
            }],
            "/games": [{"id": 99, "startDate": "2026-11-02T00:00:00Z", "status": "scheduled", "homeTeamId": 1, "homeTeam": "Alpha", "awayTeamId": 2, "awayTeam": "Beta"}],
            "/games/media": [{"gameId": 99, "broadcasts": [{"broadcastName": "ESPN2"}]}],
            "/lines": [{"gameId": 99, "lines": [{"provider": "A", "spread": -4, "spreadOpen": -2.5, "overUnder": 145, "overUnderOpen": 143}, {"provider": "B", "spread": -3, "spreadOpen": -2.5, "overUnder": 144, "overUnderOpen": 143}]}],
        }
        teams, board, status = build_outputs(2027, "start", "end", lambda path, _params: responses[path])
        alpha = teams["teams"][0]
        self.assertEqual(alpha["efficiency"]["raw_net_per_100"], 15.3)
        self.assertEqual(alpha["four_factor_edges"]["effective_fg_pct"], 7.0)
        self.assertEqual(alpha["four_factor_edges"]["turnover_pct"], 5.0)
        self.assertTrue(alpha["sample_ready"])
        self.assertEqual(board["games"][0]["market"]["consensus_home_spread"], -3.5)
        self.assertEqual(board["games"][0]["market"]["spread_move"], -1.0)
        self.assertEqual(board["games"][0]["broadcasts"], ["ESPN2"])
        self.assertFalse(status["meta"]["raw_api_data_stored"])


if __name__ == "__main__":
    unittest.main()
