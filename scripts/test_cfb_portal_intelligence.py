import unittest

from scripts.build_cfb_portal_intelligence import build_payload, rating_score


class PortalIntelligenceTests(unittest.TestCase):
    def test_normalizes_rating_scale_and_builds_unit_impact(self):
        rows = [
            {"firstName": "A", "lastName": "Q", "position": "QB", "origin": {"school": "Old"}, "destination": {"school": "New"}, "rating": .91},
            {"name": "B Edge", "position": "EDGE", "origin": {"school": "Old 2"}, "destination": {"school": "New"}, "rating": .88},
        ]
        payload = build_payload({"teams": []}, rows, [])
        impact = payload["position_impact"][0]
        self.assertEqual(impact["offense"]["count"], 1)
        self.assertEqual(impact["offense"]["avg_rating"], 91.0)
        self.assertEqual(impact["defense"]["avg_rating"], 88.0)
        self.assertEqual(impact["combined_quality_points"], 19.0)
        self.assertEqual(payload["players"][1]["rating_score"], 91.0)

    def test_builds_verified_juco_recruits_from_separate_endpoint(self):
        juco = [{
            "id": "1", "athleteId": "10", "name": "Junior Player", "position": "WR",
            "school": "Example Community College", "committedTo": "State U",
            "ranking": 7, "stars": 4, "rating": .895,
        }]
        payload = build_payload({"teams": []}, [], juco)
        self.assertEqual(len(payload["juco"]), 1)
        self.assertEqual(payload["juco"][0]["destination"], "State U")
        self.assertEqual(payload["juco"][0]["rating_score"], 89.5)
        self.assertEqual(payload["juco"][0]["recruit_type"], "JUCO")

    def test_preserves_100_point_ratings(self):
        self.assertEqual(rating_score(88.4), 88.4)
        self.assertEqual(rating_score(.884), 88.4)
        self.assertIsNone(rating_score(None))


if __name__ == "__main__":
    unittest.main()
