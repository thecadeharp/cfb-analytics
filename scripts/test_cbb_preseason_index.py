#!/usr/bin/env python3

import unittest

from scripts.build_cbb_preseason_index import FEATURES, evaluation, feature_row


class CbbPreseasonIndexTests(unittest.TestCase):
    def test_conference_identity_is_not_a_rating_feature(self):
        self.assertFalse(any("conference" in name for name in FEATURES))

    def test_feature_row_uses_roster_continuity_and_personnel(self):
        row = feature_row(
            {"adjusted_net": 20, "adjusted_offense": 120, "adjusted_defense": 100},
            {"returning_minutes_pct": 60, "returning_points_pct": 55, "returning_usage_mass_pct": 50},
            {
                "recruiting": {"team_rating": 50, "mean_player_rating": .94, "top_player_rating": .98, "class_player_count": 3, "four_star_count": 2, "five_star_count": 1},
                "transfers": {"prior_minutes": 1000, "prior_points": 400, "prior_usage_mass": 20000, "mean_incoming_rating": .9, "top_incoming_rating": .95, "incoming_count": 2, "prior_production_match_count": 2},
            },
            {"recruit_rating": 30, "recruit_mean": .88, "recruit_top": .9, "transfer_rating": .8, "transfer_top": .85},
        )
        self.assertEqual(row["prior_net_x_returning"], 12)
        self.assertEqual(row["recruit_count"], 3)
        self.assertGreater(row["transfer_points"], 0)

    def test_evaluation_compares_candidate_to_carry_forward(self):
        rows = [
            {"team_id": 1, "team": "A", "predicted_net": 10.0, "carry_forward_net": 7.0, "target_net": 11.0},
            {"team_id": 2, "team": "B", "predicted_net": 2.0, "carry_forward_net": 5.0, "target_net": 1.0},
        ]
        report = evaluation(rows)
        self.assertEqual(report["teams"], 2)
        self.assertLess(report["rating_mae"], report["carry_forward_mae"])
        self.assertEqual(report["rank_correlation"], 1.0)


if __name__ == "__main__":
    unittest.main()
