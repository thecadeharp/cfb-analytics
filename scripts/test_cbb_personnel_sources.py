#!/usr/bin/env python3

import unittest

from scripts.audit_cbb_personnel_sources import build_audit, normalized


class CbbPersonnelSourceTests(unittest.TestCase):
    def test_name_normalization(self):
        self.assertEqual(normalized("D.J. Burns Jr."), "djburnsjr")

    def test_separates_returners_and_incoming_production(self):
        responses = {
            "/teams/roster": [
                {"teamId": 1, "team": "Alpha", "players": [{"id": 10, "name": "Returner"}, {"id": 20, "name": "Transfer Guy"}]},
                {"teamId": 2, "team": "Beta", "players": []},
            ],
            "/stats/player/season": [
                {"teamId": 1, "athleteId": 10, "minutes": 600},
                {"teamId": 2, "athleteId": 20, "minutes": 500},
                {"teamId": 1, "athleteId": 30, "minutes": 400},
            ],
            "/recruiting/players": [{"athleteId": 40, "committedTo": {"id": 1}}],
            "/recruiting/teams": [{"teamId": 1}],
            "/recruiting/portal": [],
        }
        report = build_audit(2027, 2026, 2026, lambda path, _params: responses[path])
        self.assertEqual(report["id_join"]["matched_current_players"], 2)
        self.assertEqual(report["id_join"]["teams_with_positive_returning_minutes"], 1)
        self.assertEqual(report["id_join"]["teams_with_positive_incoming_transfer_minutes"], 1)
        self.assertFalse(report["meta"]["raw_api_data_stored"])


if __name__ == "__main__":
    unittest.main()
