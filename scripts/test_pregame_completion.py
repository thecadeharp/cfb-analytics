import unittest
from scripts.build_prediction_archive import build as archive_build
from scripts.import_cbb_verified_availability import validate as availability_validate
from scripts.import_cbb_verified_venues import validate as venues_validate


class PregameCompletionTests(unittest.TestCase):
    def test_prediction_archive_keeps_earliest_snapshot(self):
        rows=[
            {"game_key":"1","captured_at_utc":"2026-01-02Z","model_home_spread":-2,"model_home_win_probability":56.0},
            {"game_key":"1","captured_at_utc":"2026-01-01Z","model_home_spread":-1,"model_home_win_probability":53.0},
        ]
        clv={"rows":[{"game_key":"1","closing_total":48.5}]}
        report=archive_build({"rows":rows},{"spread_decisions":[],"total_decisions":[]},clv)
        self.assertEqual(report["meta"]["cfb_games"],1)
        self.assertEqual(report["rows"][0]["model_home_spread"],-1)
        self.assertEqual(report["rows"][0]["model_home_win_probability"],53.0)
        self.assertEqual(report["rows"][0]["closing_total"],48.5)

    def test_prediction_archive_freezes_first_side_instead_of_late_flip(self):
        common = {
            "game_key": "401862826", "start_date": "2026-11-14T20:30:00Z",
            "away_team": "Florida Atlantic", "home_team": "Tulsa",
            "result_settled": True,
        }
        rows = [
            {**common, "captured_at_utc": "2026-11-08T16:39:00Z", "snapshot_home_spread": -5.0, "preferred_side": None},
            {**common, "captured_at_utc": "2026-11-10T17:46:00Z", "snapshot_home_spread": -5.5, "preferred_side": "Tulsa", "ats_result": "W"},
            {**common, "captured_at_utc": "2026-11-14T16:40:00Z", "snapshot_home_spread": -6.5, "preferred_side": "Florida Atlantic", "ats_result": "L"},
        ]
        report = archive_build({"rows": rows}, {"spread_decisions": [], "total_decisions": []})
        decision = report["rows"][0]
        self.assertEqual(decision["preferred_side"], "Tulsa")
        self.assertEqual(decision["market_home_spread"], -5.5)
        self.assertEqual(decision["ats_result"], "W")
        self.assertTrue(decision["tracking_locked"])

    def test_verified_venue_requires_provenance(self):
        with self.assertRaises(ValueError): venues_validate([{"venue_name":"Gym","city":"A","state":"KS","latitude":1,"longitude":2,"source_url":"","verified_at_utc":"2026-01-01T00:00:00Z"}])

    def test_availability_never_creates_adjustment(self):
        board={"games":[{"game_id":"9"}]}; rows=[{"game_id":"9","team":"A","player":"P","status":"out","source_url":"https://example.com/report","verified_at_utc":"2026-01-01T00:00:00Z"}]
        report=availability_validate(rows,board)
        self.assertIsNone(report[0]["model_adjustment"])


if __name__=="__main__": unittest.main()
