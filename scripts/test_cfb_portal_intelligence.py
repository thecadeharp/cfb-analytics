import unittest
from scripts.build_cfb_portal_intelligence import build_payload

class PortalIntelligenceTests(unittest.TestCase):
    def test_classifies_positions_and_verified_juco(self):
        rows=[
            {"firstName":"A","lastName":"Q","position":"QB","origin":{"school":"Old"},"destination":{"school":"New"},"rating":.91},
            {"name":"B Edge","position":"EDGE","origin":{"school":"Example Community College"},"destination":{"school":"New"},"rating":.88},
        ]
        payload=build_payload({"teams":[]},rows)
        self.assertEqual(payload["position_impact"][0]["offense"]["count"],1)
        self.assertEqual(payload["position_impact"][0]["defense"]["count"],1)
        self.assertTrue(payload["players"][1]["juco"] or payload["players"][0]["juco"])

if __name__=="__main__": unittest.main()
