#!/usr/bin/env python3

import unittest

from scripts.build_cbb_live_center import build as build_live
from scripts.build_cbb_model_lab import build as build_lab
from scripts.build_cbb_situational_profiles import build as build_situational
from scripts.build_cbb_coach_profiles import build as build_coaches
from scripts.cbb_game_flow import game_flow


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

    def test_game_flow_builds_pace_factors_and_foul_context(self):
        game = {"away":{"team_id":1,"team":"Away","score":25},"home":{"team_id":2,"team":"Home","score":30},"projection":{"total":140,"projected_possessions":68,"home_margin":4}}
        plays = [
            {"period":1,"clock":"10:00","homeScore":10,"awayScore":8,"teamId":1,"playType":"Turnover"},
            {"period":1,"clock":"09:30","homeScore":12,"awayScore":8,"teamId":2,"playType":"Made shot","shotInfo":{"made":True,"type":"rim"}},
            {"period":1,"clock":"09:00","homeScore":12,"awayScore":8,"teamId":1,"playType":"Personal foul","playerName":"A Player"},
            {"period":2,"clock":"05:00","homeScore":30,"awayScore":25,"teamId":1,"playType":"Made three point shot","shotInfo":{"made":True,"type":"three"}},
        ]
        flow = game_flow(game, plays)
        self.assertIn("projected_40_minute_pace", flow)
        self.assertEqual(len(flow["teams"]), 2)
        self.assertIn("four_factors", flow["teams"][0])
        self.assertIn("live_home_win_probability", flow)

    def test_coach_profiles_require_verified_tenure(self):
        games = {"games":[{"season":2026,"home_team_id":1,"home_team":"A","away_team_id":2,"away_team":"B","market_home_spread":-3,"actual_home_margin":5}]}
        self.assertEqual(build_coaches(games,{"tenures":[]})["coaches"], [])
        tenure = {"tenure_id":"a-coach","team_id":1,"team":"A","coach":"Coach A","start_season":2026,"source_url":"https://example.com","verified_at":"2026-11-11"}
        payload = build_coaches(games,{"tenures":[tenure]})
        self.assertEqual(payload["coaches"][0]["splits"]["overall"]["wins"],1)


if __name__ == "__main__":
    unittest.main()
