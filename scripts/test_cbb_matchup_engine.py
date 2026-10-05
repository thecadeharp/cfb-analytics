#!/usr/bin/env python3

import unittest

from scripts.build_cbb_matchup_engine import build_matchups


class CbbMatchupEngineTests(unittest.TestCase):
    def test_builds_display_only_possession_factor_and_style_context(self):
        board = {"meta": {"version": "thi-cbb-projection-board-v0.5"}, "games": [{
            "game_id": 10, "start_date": "2026-11-01", "status": "scheduled",
            "home": {"team_id": 1, "team": "Alpha"}, "away": {"team_id": 2, "team": "Beta"},
            "projection": {"projected_possessions": 73.2, "matchup_context": {
                "home": {"tempo": 76}, "away": {"tempo": 67},
                "four_factor_matchup": {
                    "home": {"effective_fg_pct": 55, "turnover_pct": 15, "offensive_rebound_pct": 36, "free_throw_rate": 40},
                    "away": {"effective_fg_pct": 50, "turnover_pct": 21, "offensive_rebound_pct": 29, "free_throw_rate": 26},
                },
            }},
        }]}
        profiles = {"teams": [
            {"team_id": 1, "shot_profile": {"tracked_shots": 10}, "preseason_prior": {"shot_profile": {"tracked_shots": 200, "at_rim_rate": 42, "midrange_rate": 18, "three_point_rate": 40, "assisted_pct": 61}}},
            {"team_id": 2, "shot_profile": {"tracked_shots": 150, "at_rim_rate": 35, "midrange_rate": 20, "three_point_rate": 45, "assisted_pct": 55}},
        ]}
        style = {"meta": {"version": "thi-cbb-play-style-v1.0"}, "teams": [{"team_id": 1, "tracked_shots": 120, "rim_rate": 48, "midrange_rate": 12, "three_rate": 40, "assisted_rate": 65, "explicit_transition_rate": 9, "on_floor_coverage_pct": 80, "sample_state": "tracked"}]}
        payload = build_matchups(board, profiles, style)
        game = payload["games"][0]
        self.assertEqual(game["pace_environment"]["band"], "fast")
        self.assertEqual(game["pace_environment"]["clash_label"], "strong")
        self.assertEqual(game["factor_advantages"][0]["advantage_team"], "Alpha")
        self.assertEqual(game["factor_advantages"][1]["advantage_team"], "Alpha")
        self.assertEqual(game["shot_style"]["home"]["source"], "current_play_by_play")
        self.assertEqual(game["shot_style"]["away"]["source"], "current_observed")
        self.assertFalse(game["research_status"]["feeds_public_spread"])
        self.assertEqual(payload["meta"]["model_usage"], "display_only_research_layer")


if __name__ == "__main__":
    unittest.main()
