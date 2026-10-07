import unittest

from scripts.build_cbb_home_court import fit_home_court


class CbbHomeCourtTests(unittest.TestCase):
    def test_regularized_fit_separates_program_courts_and_team_strength(self):
        games = []
        seasons = [2025, 2026]
        strengths = {"1": 8.0, "2": 2.0, "3": -3.0}
        courts = {"1": 4.5, "2": 2.5, "3": 1.0}
        for season in seasons:
            for _repeat in range(24):
                for home, away in (("1","2"),("2","1"),("1","3"),("3","1"),("2","3"),("3","2")):
                    games.append({"season":season,"home_team_id":int(home),"away_team_id":int(away),"margin":strengths[home]-strengths[away]+courts[home]})
        national, effects, _strength, _sd = fit_home_court(games, seasons)
        self.assertGreater(effects["1"], effects["2"])
        self.assertGreater(effects["2"], effects["3"])
        self.assertGreater(effects["1"]-effects["3"], 1.0)
        self.assertGreater(national, 1.0)


if __name__ == "__main__": unittest.main()
