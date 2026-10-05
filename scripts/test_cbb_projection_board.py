#!/usr/bin/env python3

import unittest

from scripts.build_cbb_projection_board import build_board


def profile(team_id: int, games: int) -> dict:
    return {
        "team_id": team_id,
        "team": f"Team {team_id}",
        "record": {"games": games},
        "sample_ready": games >= 3,
        "current_efficiency": {
            "adjusted": {"offense": 110 + team_id, "defense": 100},
            "pace_per_40": 70,
        },
        "four_factor_edges": {
            "effective_fg_pct": team_id,
            "turnover_pct": 0,
            "offensive_rebound_pct": 0,
            "free_throw_rate": 0,
        },
    }


def prior(team_id: int) -> dict:
    return {
        "team_id": team_id,
        "prior_offense": 108 + team_id,
        "prior_defense": 101,
        "prior_tempo": 69,
        "personnel": {"recruiting": {}, "transfers": {}},
    }


class CbbProjectionBoardTests(unittest.TestCase):
    def test_builds_sample_gated_spread_projections_and_withholds_totals_signals(self):
        games = {
            "meta": {"season": 2027},
            "games": [
                {"game_id": 1, "status": "scheduled", "neutral_site": False, "conference_game": False, "home": {"team_id": 1, "team": "Team 1"}, "away": {"team_id": 2, "team": "Team 2"}, "market": {"consensus_home_spread": -1}},
                {"game_id": 2, "status": "scheduled", "neutral_site": True, "conference_game": True, "home": {"team_id": 3, "team": "Team 3"}, "away": {"team_id": 4, "team": "Team 4"}, "market": {"consensus_home_spread": 10}},
                {"game_id": 3, "status": "final", "home": {"team_id": 1}, "away": {"team_id": 2}},
            ],
        }
        profiles = {"teams": [profile(1, 0), profile(2, 0), profile(3, 6), profile(4, 7)]}
        priors = {"meta": {"model_version": "thi-cbb-walk-forward-v0.7-research"}, "teams": [prior(i) for i in range(1, 5)]}
        model = {
            "meta": {"model_version": "thi-cbb-walk-forward-v0.7-research"},
            "models": {
                "margin": {"feature_names": ["raw_margin", "home_court"], "means": {"raw_margin": 0, "home_court": 0}, "scales": {"raw_margin": 1, "home_court": 1}, "coefficients": [0, 1, 1]},
                "total": {"feature_names": ["raw_total"], "means": {"raw_total": 0}, "scales": {"raw_total": 1}, "coefficients": [0, 1]},
                "margin_residual_sd": 13,
            },
        }
        payload = build_board(games, profiles, priors, model)
        self.assertEqual(payload["meta"]["version"], "thi-cbb-projection-board-v0.5")
        self.assertEqual(len(payload["games"]), 2)
        opening = payload["games"][0]["projection"]
        tracked = payload["games"][1]["projection"]
        self.assertEqual(opening["sample_state"], "preseason")
        self.assertFalse(opening["spread_signal_eligible"])
        self.assertEqual(opening["model_input_label"], "prior_based")
        self.assertEqual(opening["game_classification"], "nonconference")
        self.assertEqual(opening["signal_confidence"], "research")
        self.assertTrue(1 <= opening["watchability_score"] <= 99)
        self.assertEqual(tracked["sample_state"], "tracked_sample")
        self.assertTrue(tracked["spread_signal_eligible"])
        self.assertEqual(tracked["signal_confidence"], "developing")
        self.assertIn(tracked["spread_signal_tier"], {"play", "material", "outlier"})
        self.assertFalse(tracked["totals_signal_eligible"])
        self.assertTrue(0 <= tracked["home_win_probability"] <= 100)
        self.assertEqual(len(tracked["matchup_context"]["margin_drivers"]), 2)
        self.assertEqual(tracked["matchup_context"]["home"]["games"], 6)
        self.assertIn("four_factor_matchup", tracked["matchup_context"])

        frozen_margin = opening["home_margin"]
        games["games"][0]["status"] = "final"
        games["games"][0]["home"]["score"] = 70
        games["games"][0]["away"]["score"] = 66
        games["games"][0]["market"] = {"consensus_home_spread": -3, "consensus_total": 138}
        refreshed = build_board(games, profiles, priors, model, payload)
        completed = next(game for game in refreshed["games"] if game["game_id"] == 1)
        self.assertEqual(completed["status"], "final")
        self.assertEqual(completed["home"]["score"], 70)
        self.assertEqual(completed["projection"]["home_margin"], frozen_margin)
        self.assertEqual(completed["closing_market"]["consensus_home_spread"], -3)
        self.assertEqual(refreshed["meta"]["status_counts"]["final"], 1)

    def test_rejects_unapproved_model_version(self):
        with self.assertRaisesRegex(RuntimeError, "v0.7"):
            build_board({"games": []}, {"teams": []}, {"meta": {}}, {"meta": {"model_version": "old"}})


if __name__ == "__main__":
    unittest.main()
