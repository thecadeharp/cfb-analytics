#!/usr/bin/env python3

import unittest

from scripts.build_cbb_live_center import build as build_live
from scripts.build_cbb_model_lab import build as build_lab
from scripts.build_cbb_situational_profiles import build as build_situational


class CbbResearchSurfaceTests(unittest.TestCase):
    def test_model_lab_compares_chronological_baselines(self):
        games = [{"split":"test","actual_home_margin":5,"actual_total":140,"projected_home_margin":3,"projected_total":145,"market_home_spread":-4,"market_total":141,"features":{"raw_margin":2,"raw_total":144}}]
        payload = build_lab({"games":games},{"meta":{"model_version":"v","activation_state":"research_only"}},{})
        self.assertEqual(payload["splits"]["test"]["incumbent_margin"]["mae"],2)
        self.assertEqual(payload["splits"]["test"]["market_margin"]["mae"],1)
        self.assertFalse(payload["challenger"]["promotion_recommended"])

    def test_situational_profiles_are_program_level(self):
        games = [{"season":2026,"home_team_id":1,"home_team":"A","away_team_id":2,"away_team":"B","market_home_spread":-3,"actual_home_margin":5,"neutral_site":False,"conference_game":True,"home_rest_days":2,"away_rest_days":1}]
        payload = build_situational({"games":games})
        home = next(row for row in payload["teams"] if row["team_id"] == 1)
        away = next(row for row in payload["teams"] if row["team_id"] == 2)
        self.assertEqual(home["splits"]["overall"]["wins"],1)
        self.assertEqual(away["splits"]["overall"]["losses"],1)
        self.assertIn("not attributed to a coach", payload["meta"]["policy"])

    def test_live_center_is_empty_without_live_games_or_key(self):
        payload = build_live({"games":[{"game_id":1,"status":"scheduled"}]}, None)
        self.assertEqual(payload["games"],[])
        self.assertEqual(payload["meta"]["live_game_count"],0)


if __name__ == "__main__":
    unittest.main()
