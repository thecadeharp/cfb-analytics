#!/usr/bin/env python3

import unittest

from scripts.verify_cbb_api_foundation import build_report


class CbbApiFoundationTests(unittest.TestCase):
    def test_report_proves_tier_endpoints_without_storing_rows(self):
        teams = [{"id": i, "school": f"Team {i}", "conferenceId": 1} for i in range(365)]
        leaderboard = [{
            "season": 2026, "teamId": i, "team": f"Team {i}", "record": {},
            "summary": {}, "teamStats": {}, "opponentStats": {}, "adjustedEfficiency": {},
        } for i in range(365)]
        players = [{
            "season": 2026, "teamId": i % 365, "athleteId": i, "name": f"Player {i}",
            "games": 30, "minutes": 500, "points": 200, "usage": 20,
        } for i in range(1200)]
        responses = {
            "/teams/directory": {"teams": teams, "conferences": [{"id": 1, "name": "Conference"}]},
            "/games": [{"id": 1, "season": 2027, "startDate": "2026-11-02T00:00:00Z", "homeTeamId": 1, "awayTeamId": 2, "status": "scheduled"}],
            "/ratings/adjusted": [{"season": 2026, "teamId": i, "team": f"Team {i}", "offensiveRating": 100, "defensiveRating": 100, "netRating": 0} for i in range(365)],
            "/stats/team/leaderboard": leaderboard,
            "/teams/roster": [{"teamId": i, "team": f"Team {i}", "season": 2027, "players": []} for i in range(365)],
            "/stats/player/season": players,
            "/lines/providers": [{"id": 1, "name": "Provider"}],
            "/scoreboard": [],
        }

        report = build_report(2027, 2026, lambda path, _params: responses[path])

        self.assertEqual(report["meta"]["request_count"], 8)
        self.assertFalse(report["meta"]["raw_api_data_stored"])
        self.assertEqual(report["checks"]["team_directory"]["team_count"], 365)
        self.assertEqual(report["checks"]["benchmark_team_leaderboard"]["record_count"], 365)
        self.assertEqual(report["checks"]["live_scoreboard"]["status"], "empty")
        self.assertNotIn("responses", report)


if __name__ == "__main__":
    unittest.main()
