import unittest

from scripts.build_cbb_platform_health import build


class CbbPlatformHealthTests(unittest.TestCase):
    def payload(self, drivers=None):
        board = {"games": [{
            "game_id": 1,
            "neutral_site": True,
            "status": "scheduled",
            "home": {"team_id": 1},
            "away": {"team_id": 2},
            "projection": {"matchup_context": {"home_court": {"points": 0.0}, "margin_drivers": drivers or []}},
        }]}
        profiles = {"teams": [{"team_id": index} for index in range(300)]}
        players = {"players": [{} for _ in range(1500)]}
        tracking = {"spread_decisions": []}
        operations = {"games": [{}], "coverage": {}}
        foundation = {"coverage": {"roster_fetch_errors": 0}}
        readiness = {"meta": {"status": "ready"}}
        return build(board, profiles, players, tracking, operations, foundation, readiness)

    def test_neutral_site_audit_rejects_home_context_driver(self):
        healthy = self.payload()
        self.assertTrue(healthy["checks"]["neutral_site_home_context_zero"])
        failed = self.payload([{"feature": "early_home", "margin_points": -2.8}])
        self.assertFalse(failed["checks"]["neutral_site_home_context_zero"])
        self.assertEqual(failed["meta"]["status"], "attention_required")

    def test_strict_roster_audit_overrides_provider_claim(self):
        players = {"meta": {"roster_verification_status": "provider_verified"}, "players": [{} for _ in range(1500)]}
        result = build(
            {"games": []}, {"teams": [{"team_id": index} for index in range(300)]}, players,
            {"spread_decisions": []}, {"games": [], "coverage": {}},
            {"coverage": {"roster_fetch_errors": 0}}, roster_audit={"meta": {"status": "withheld"}},
        )
        self.assertEqual(result["coverage"]["provider_roster_status"], "provider_verified")
        self.assertEqual(result["coverage"]["roster_verification_status"], "withheld_by_thi_audit")
        self.assertEqual(result["coverage"]["published_roster_players"], 0)
        self.assertTrue(result["checks"]["roster_layer_safe"])


if __name__ == "__main__":
    unittest.main()
