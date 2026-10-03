#!/usr/bin/env python3

import unittest

from scripts.verify_cbb_api_foundation import build_report


class CbbApiFoundationTests(unittest.TestCase):
    def test_report_keeps_only_coverage_metadata(self):
        teams = [{"id": index, "school": f"Team {index}"} for index in range(364)]
        responses = {
            "/teams/directory": {
                "season": 2027,
                "teams": teams,
                "conferences": [{"id": 1, "name": "Conference"}],
            },
            "/games": [
                {
                    "id": 1,
                    "season": 2027,
                    "startDate": "2026-11-02T00:00:00Z",
                    "homeTeamId": 1,
                    "homeTeam": "Home",
                    "awayTeamId": 2,
                    "awayTeam": "Away",
                    "status": "scheduled",
                }
            ],
            "/ratings/adjusted": [
                {
                    "season": 2026,
                    "teamId": index,
                    "team": f"Team {index}",
                    "offensiveRating": 100.0,
                    "defensiveRating": 100.0,
                    "netRating": 0.0,
                }
                for index in range(364)
            ],
            "/lines/providers": [{"id": 1, "name": "Provider"}],
        }

        report = build_report(2027, 2026, lambda path, _params: responses[path])

        self.assertEqual(report["meta"]["request_count"], 4)
        self.assertFalse(report["meta"]["raw_api_data_stored"])
        self.assertEqual(report["checks"]["team_directory"]["team_count"], 364)
        self.assertEqual(report["checks"]["benchmark_adjusted_ratings"]["record_count"], 364)
        self.assertNotIn("teams", report)


if __name__ == "__main__":
    unittest.main()
