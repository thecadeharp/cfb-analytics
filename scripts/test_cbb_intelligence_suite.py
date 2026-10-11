import unittest
from scripts.build_cbb_intelligence_suite import build_suite

class IntelligenceSuiteTests(unittest.TestCase):
    def test_builds_coordinated_research_without_inventing_newcomer_stats(self):
        profiles={"teams":[{"team_id":1,"record":{"games":0},"shot_profile":{"tracked_shots":0},"preseason_prior":{"shot_profile":{"tracked_shots":100,"at_rim_rate":40}}}]}
        priors={"meta":{"season":2027},"teams":[{"team_id":1,"team":"Alpha","prior_net":10,"prior_offense":110,"prior_defense":100,"prior_tempo":70,"continuity_source":"verified","personnel":{}}]}
        players={"players":[{"player_season_id":"p1","team_id":1,"team":"Alpha","name":"Veteran","sample":{"minutes_per_game":30},"metrics":{"points_per_40":20,"rebounds_per_40":8,"assists_per_40":4},"research_scores":{"thi_player_rating":80},"data_quality":{"reliability":90}},{"player_season_id":"p2","team_id":1,"team":"Alpha","name":"Freshman","sample":{},"metrics":{},"research_scores":{"thi_player_rating":75},"data_quality":{"reliability":35}}]}
        board={"games":[
            {"game_id":"g0","start_date":"2026-11-09T00:00:00Z","status":"scheduled","neutral_site":False,"conference_game":False,"home":{"team_id":3,"team":"Gamma"},"away":{"team_id":1,"team":"Alpha"},"market":{},"projection":{"home_margin":-2,"home_win_probability":43,"matchup_context":{"home_court":{"points":3.1}}}},
            {"game_id":"g1","start_date":"2026-11-10T00:00:00Z","status":"scheduled","neutral_site":False,"conference_game":False,"home":{"team_id":1,"team":"Alpha"},"away":{"team_id":2,"team":"Beta"},"market":{},"projection":{"home_margin":4,"home_win_probability":64,"matchup_context":{"home_court":{"points":4.2}}}},
        ]}; tracking={"summary":{}}
        model={"models":{"margin":{"feature_names":["home_court"],"coefficients":[0,3],"means":{"home_court":0},"scales":{"home_court":1}}},"promotion_gate":{"eligible_for_public_projection_engine":False,"checks":{"margin_generalizes":True,"totals_generalize":False}}}
        home_court={"meta":{"national_points":2.8},"teams":[{"team_id":1,"team":"Alpha","home_court_points":4.2,"sample":{"campus_games":40},"four_factor_home_road":{}}]}
        payload=build_suite(profiles,priors,players,board,tracking,model,home_court)
        veteran=next(row for row in payload["player_projections"] if row["name"]=="Veteran"); freshman=next(row for row in payload["player_projections"] if row["name"]=="Freshman")
        self.assertIsNotNone(veteran["projected_points"]); self.assertIsNone(freshman["projected_points"])
        self.assertEqual(freshman["projection_state"],"role_only"); self.assertEqual(payload["home_court"]["national_points"],2.8)
        self.assertEqual(len(payload["team_dossiers"]),1)
        self.assertEqual(payload["meta"]["version"],"thi-cbb-intelligence-suite-v1.3")
        self.assertEqual(payload["validation_registry"]["gate_summary"]["passed"],1)
        self.assertEqual(payload["validation_registry"]["gate_summary"]["total"],2)
        factor_states={row["factor"]:row["status"] for row in payload["validation_registry"]["factors"]}
        self.assertEqual(factor_states["Program-specific home-court effect"],"active")
        self.assertEqual(factor_states["Injuries and availability"],"unavailable")
        context=next(row for row in payload["game_context"] if row["game_id"]=="g1")
        self.assertEqual(context["home_court_points"],4.2)
        away_context=next(row for row in payload["game_context"] if row["game_id"]=="g0")
        self.assertEqual(away_context["home_court_points"],3.1)
        self.assertEqual(context["availability"]["status"],"not_sourced")
        self.assertIn("back_to_back", context["teams"]["home"]["flags"])
        dossier=payload["team_dossiers"][0]
        self.assertEqual(dossier["forecast"]["games_in_window"],2)
        self.assertIn("resume", dossier)
        self.assertEqual(dossier["resume"]["games_graded"],0)
        self.assertEqual(dossier["projected_core_lineup"]["state"],"projected_rotation_not_observed_lineup")

    def test_integrity_audit_controls_player_publication(self):
        profiles={"teams":[]}; priors={"meta":{"season":2027},"teams":[]}
        players={"meta":{"roster_verification_status":"provider_verified"},"players":[{"player_season_id":"p1","team_id":1,"team":"Alpha","name":"Unverified","sample":{},"metrics":{},"research_scores":{"thi_player_rating":70},"data_quality":{"reliability":20}}]}
        board={"games":[]}; tracking={"summary":{}}
        model={"models":{"margin":{"feature_names":["home_court"],"coefficients":[0,3],"scales":{"home_court":1}}},"promotion_gate":{"checks":{}}}
        audit={"meta":{"status":"withheld"},"checks":{"official_spot_checks":False}}
        payload=build_suite(profiles,priors,players,board,tracking,model,roster_audit=audit)
        self.assertEqual(payload["player_projections"],[])
        self.assertEqual(payload["meta"]["roster_verification_status"],"withheld_unverified_fallback")
        self.assertEqual(payload["meta"]["roster_audit_status"],"withheld")

if __name__ == "__main__": unittest.main()
