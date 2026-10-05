import unittest
from scripts.build_cbb_intelligence_suite import build_suite

class IntelligenceSuiteTests(unittest.TestCase):
    def test_builds_coordinated_research_without_inventing_newcomer_stats(self):
        profiles={"teams":[{"team_id":1,"record":{"games":0},"shot_profile":{"tracked_shots":0},"preseason_prior":{"shot_profile":{"tracked_shots":100,"at_rim_rate":40}}}]}
        priors={"meta":{"season":2027},"teams":[{"team_id":1,"team":"Alpha","prior_net":10,"prior_offense":110,"prior_defense":100,"prior_tempo":70,"continuity_source":"verified","personnel":{}}]}
        players={"players":[{"player_season_id":"p1","team_id":1,"team":"Alpha","name":"Veteran","sample":{"minutes_per_game":30},"metrics":{"points_per_40":20,"rebounds_per_40":8,"assists_per_40":4},"research_scores":{"thi_player_rating":80},"data_quality":{"reliability":90}},{"player_season_id":"p2","team_id":1,"team":"Alpha","name":"Freshman","sample":{},"metrics":{},"research_scores":{"thi_player_rating":75},"data_quality":{"reliability":35}}]}
        board={"games":[]}; tracking={"summary":{}}
        model={"models":{"margin":{"feature_names":["home_court"],"coefficients":[0,3],"means":{"home_court":0},"scales":{"home_court":1}}}}
        payload=build_suite(profiles,priors,players,board,tracking,model)
        veteran=next(row for row in payload["player_projections"] if row["name"]=="Veteran"); freshman=next(row for row in payload["player_projections"] if row["name"]=="Freshman")
        self.assertIsNotNone(veteran["projected_points"]); self.assertIsNone(freshman["projected_points"])
        self.assertEqual(freshman["projection_state"],"role_only"); self.assertEqual(payload["home_court"]["national_points"],3.0)
        self.assertEqual(len(payload["team_dossiers"]),1)

if __name__ == "__main__": unittest.main()
