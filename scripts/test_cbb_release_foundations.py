import unittest
from scripts.build_cbb_operations_context import build as operations_build
from scripts.build_cbb_platform_health import build as health_build
from scripts.build_trends_lab import build as trends_build

class ReleaseFoundationTests(unittest.TestCase):
    def test_trends_grade_settled_games_without_claiming_missing_splits(self):
        rows=[{"season":2025,"margin":7,"total":130,"spread":-3,"market_total":140,"neutral":False,"conference":True,"home_favorite":True,"favorite_size":3} for _ in range(220)]
        payload=trends_build(rows,rows)
        self.assertEqual(payload["sports"]["cbb"]["cards"][0]["hit_rate"],100.0)
        self.assertEqual(payload["planned_splits"][0]["status"],"awaiting_point_in_time_rankings")

    def test_operations_never_invents_availability_or_mileage(self):
        board={"games":[{"game_id":1,"start_date":"2026-11-01T12:00:00Z","neutral_site":True,"venue":{"name":"Arena","city":"X","state":"NY"},"home":{"team_id":1,"team":"A"},"away":{"team_id":2,"team":"B"}}]}
        payload=operations_build(board,{}, {"reports":[]})
        self.assertIsNone(payload["games"][0]["teams"]["away"]["travel_miles"])
        self.assertEqual(payload["games"][0]["availability"]["status"],"no_verified_report")

    def test_health_catches_duplicate_games(self):
        game={"game_id":1,"status":"scheduled","home":{},"away":{}}
        health=health_build({"games":[game,game]},{"teams":[{}]*300},{"players":[{}]*1500},{"spread_decisions":[]},{"games":[{},{}],"coverage":{}})
        self.assertFalse(health["checks"]["unique_games"])
        self.assertEqual(health["meta"]["status"],"attention_required")

if __name__ == "__main__": unittest.main()
