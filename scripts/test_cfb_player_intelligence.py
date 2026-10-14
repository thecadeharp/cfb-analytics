#!/usr/bin/env python3
import unittest

from scripts.audit_cfb_player_intelligence import audit
from scripts.build_player_intelligence import empty_stats, position_group, usage_volume


class CfbPlayerIntelligenceTests(unittest.TestCase):
    def test_roster_position_wins_over_incidental_usage(self):
        stats = empty_stats()
        stats["pass_attempts"] = 1
        stats["rush_attempts"] = 1
        stats["targets"] = 66
        self.assertEqual(position_group("WR", stats), "WR")
        self.assertEqual(position_group("TE", stats), "TE")
        self.assertEqual(position_group("DB", stats), "DEF")

    def test_position_specific_volume_counts_all_relevant_usage(self):
        stats = {"pass_attempts": 0, "rush_attempts": 1, "targets": 66, "defensive_disruptions": 0}
        self.assertEqual(usage_volume("WR", stats), 67)
        self.assertEqual(usage_volume("RB", stats), 67)
        self.assertEqual(usage_volume("QB", stats), 1)

    def test_audit_rejects_wrong_receiver_cohort_and_volume(self):
        roster = {"teams":{"Ohio State":{"players":[{"athlete_id":"1","name":"Receiver","position":"WR"}]}}}
        player = {
            "athlete_id":"1", "name":"Receiver", "team":"Ohio State", "position":"WR",
            "position_group":"RB", "traditional":{"rush_attempts":1,"targets":66},
            "primary_volume":1, "rating":None, "national_position_rank":None,
        }
        payload = {
            "meta":{"model_usage":"display_only_not_used_by_model_a"},
            "players":{"1":player}, "teams":{"Ohio State":["1"]},
            "leaderboards":{"QB":[],"RB":[],"WR":[],"TE":[],"DEF":[]},
        }
        report = audit(payload, roster)
        self.assertFalse(report["checks"]["position_cohort_consistency"])
        self.assertFalse(report["checks"]["position_specific_volume"])


if __name__ == "__main__":
    unittest.main()
