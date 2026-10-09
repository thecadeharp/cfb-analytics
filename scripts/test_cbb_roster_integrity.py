#!/usr/bin/env python3
import unittest
from scripts.audit_cbb_roster_integrity import audit


class RosterIntegrityTests(unittest.TestCase):
    def test_withholds_stale_fallback_and_failed_official_check(self):
        payload = {"meta":{"roster_verification_status":"withheld_unverified_fallback","roster_season":2027},"team_rosters":[{"team_id":136,"team":"LSU","players":[{"athlete_source_id":str(i),"name":f"Old {i}","position":"G"} for i in range(8)]}]}
        spots = {"teams":[{"team_id":136,"team":"LSU","official_players":["Current Player"],"source_url":"official"}]}
        report = audit(payload, spots, expected_teams=1)
        self.assertEqual(report["meta"]["status"], "withheld")
        self.assertFalse(report["checks"]["provider_declares_verified_rosters"])
        self.assertFalse(report["checks"]["official_spot_checks"])

    def test_passes_complete_provider_verified_sample(self):
        players=[{"athlete_source_id":str(i),"name":"Current Player" if i==0 else f"Player {i}","position":"F"} for i in range(10)]
        payload={"meta":{"roster_verification_status":"provider_verified","roster_season":2027},"team_rosters":[{"team_id":1,"team":"Alpha","players":players}]}
        spots={"teams":[{"team_id":1,"team":"Alpha","official_players":["Current Player"]}]}
        self.assertEqual(audit(payload,spots,expected_teams=1)["meta"]["status"],"passed")


if __name__ == "__main__": unittest.main()
