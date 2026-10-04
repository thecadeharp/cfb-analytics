#!/usr/bin/env python3

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_cbb_personnel_season import build_season, team_directory


class CbbPersonnelSeasonTests(unittest.TestCase):
    def test_builds_aggregate_recruit_and_transfer_features(self):
        teams = [{"team_id": 1, "team": "Alpha"}, {"team_id": 2, "team": "Beta"}]
        responses = {
            "/recruiting/players": [{"committedTo": {"id": 1}, "rating": .95, "stars": 4}],
            "/recruiting/teams": [{"teamId": 1, "ranking": 10, "rating": 50}],
            "/recruiting/portal": [{"firstName": "Sam", "lastName": "Guard", "origin": {"id": 2}, "destination": {"id": 1}, "rating": .9}],
            "/stats/player/season": [{"teamId": 2, "team": "Beta", "name": "Sam Guard", "minutes": 500, "points": 200, "usage": 22}],
        }
        payload = build_season(2027, teams, lambda path, _params: responses[path])
        alpha = payload["teams"][0]
        self.assertEqual(alpha["recruiting"]["class_player_count"], 1)
        self.assertEqual(alpha["transfers"]["incoming_count"], 1)
        self.assertEqual(alpha["transfers"]["prior_minutes"], 500)
        self.assertEqual(alpha["transfers"]["prior_production_match_count"], 1)
        self.assertFalse(payload["meta"]["raw_api_data_stored"])
        self.assertNotIn("name", alpha["transfers"])

    def test_reads_team_directory_from_clean_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {"season_end_teams": [{"team_id": 1, "team": "Alpha"}]}
            with gzip.open(root / "season_2026.json.gz", "wt", encoding="utf-8") as handle:
                json.dump(payload, handle)
            teams = team_directory(2026, root, root / "missing.json")
            self.assertEqual(teams, [{"team_id": 1, "team": "Alpha"}])


if __name__ == "__main__":
    unittest.main()
