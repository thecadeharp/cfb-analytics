#!/usr/bin/env python3
import unittest

from scripts.audit_cfb_player_intelligence import audit
from scripts.build_player_intelligence import empty_stats, position_group, rating_metrics, usage_volume


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

    def test_audit_requires_rating_decomposition_for_rated_players(self):
        roster = {"teams":{"Ohio State":{"players":[{"athlete_id":"1","name":"Receiver","position":"WR"}]}}}
        player = {
            "athlete_id":"1", "name":"Receiver", "team":"Ohio State", "position":"WR",
            "position_group":"WR", "traditional":{"targets":20}, "primary_volume":20,
            "rating":75.0, "rating_components":None, "national_position_rank":1,
        }
        payload = {
            "meta":{"model_usage":"display_only_not_used_by_model_a"},
            "players":{"1":player}, "teams":{"Ohio State":["1"]},
            "leaderboards":{"QB":[],"RB":[],"WR":["1"],"TE":[],"DEF":[]},
        }
        report = audit(payload, roster)
        self.assertFalse(report["checks"]["rating_decomposition_integrity"])

    def test_qb_rating_metrics_penalize_interceptions(self):
        base = {
            "games": 5, "advanced": {"opponent_adjusted_epa_per_opportunity": .3, "success_rate": 55},
            "traditional": {"pass_attempts": 100, "completions": 70, "pass_yards": 1000, "pass_tds": 10, "rush_attempts": 20, "rush_yards": 100, "rush_tds": 2},
            "workload": {},
        }
        clean = rating_metrics("QB", base)
        turnover_heavy = rating_metrics("QB", {**base, "traditional": {**base["traditional"], "interceptions": 5}})
        self.assertGreater(clean["turnover_avoidance"], turnover_heavy["turnover_avoidance"])

    def test_wr_rating_metrics_reward_yards_and_touchdowns(self):
        row = {
            "games": 7, "advanced": {"opponent_adjusted_epa_per_opportunity": .8, "success_rate": 60},
            "traditional": {"targets": 70, "receptions": 50, "receiving_yards": 1000, "receiving_tds": 12},
            "workload": {"target_share": 35},
        }
        metrics = rating_metrics("WR", row)
        self.assertEqual(metrics["receiving_dominance"], 1360)
        self.assertAlmostEqual(metrics["yards_per_target"], 100 / 7)


if __name__ == "__main__":
    unittest.main()
