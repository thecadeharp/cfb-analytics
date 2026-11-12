import unittest

from scripts.check_paywall_rights import active_blockers, load_register


class PaywallRightsTests(unittest.TestCase):
    def test_register_has_no_active_bespoke_permission_source(self):
        payload = load_register()
        bespoke = [row for row in payload["sources"] if row.get("active") and row.get("paywall_status") == "prohibited_without_bespoke_permission"]
        self.assertEqual(bespoke, [])

    def test_current_paid_launch_fails_closed_on_unresolved_rights(self):
        blockers = active_blockers(load_register())
        self.assertTrue(blockers)
        self.assertIn("espn_disney", {row["id"] for row in blockers})


if __name__ == "__main__":
    unittest.main()
