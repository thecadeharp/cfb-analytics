import unittest
from scripts.build_prediction_archive import build as archive_build
from scripts.import_cbb_verified_availability import validate as availability_validate
from scripts.import_cbb_verified_venues import validate as venues_validate


class PregameCompletionTests(unittest.TestCase):
    def test_prediction_archive_keeps_earliest_snapshot(self):
        rows=[{"game_key":"1","captured_at_utc":"2026-01-02Z","model_home_spread":-2},{"game_key":"1","captured_at_utc":"2026-01-01Z","model_home_spread":-1}]
        report=archive_build({"rows":rows},{"spread_decisions":[],"total_decisions":[]})
        self.assertEqual(report["meta"]["cfb_games"],1)
        self.assertEqual(report["rows"][0]["model_home_spread"],-1)

    def test_verified_venue_requires_provenance(self):
        with self.assertRaises(ValueError): venues_validate([{"venue_name":"Gym","city":"A","state":"KS","latitude":1,"longitude":2,"source_url":"","verified_at_utc":"2026-01-01T00:00:00Z"}])

    def test_availability_never_creates_adjustment(self):
        board={"games":[{"game_id":"9"}]}; rows=[{"game_id":"9","team":"A","player":"P","status":"out","source_url":"https://example.com/report","verified_at_utc":"2026-01-01T00:00:00Z"}]
        report=availability_validate(rows,board)
        self.assertIsNone(report[0]["model_adjustment"])


if __name__=="__main__": unittest.main()
