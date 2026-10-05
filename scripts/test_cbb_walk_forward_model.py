#!/usr/bin/env python3

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_cbb_walk_forward_model import (
    MARGIN_FEATURES,
    initial_states,
    add_personnel_features,
    current_priors,
    metrics,
    load_seasons,
    projection_features,
)


class CbbWalkForwardModelTests(unittest.TestCase):
    def test_personnel_differences_decay_with_current_season_games(self):
        personnel = {
            2026: {
                "1": {"recruiting": {"team_rating": 60, "class_player_count": 4}, "transfers": {"prior_minutes": 1000, "prior_points": 400, "incoming_count": 3, "mean_incoming_rating": .9}},
                "2": {"recruiting": {"team_rating": 40, "class_player_count": 2}, "transfers": {"prior_minutes": 100, "prior_points": 40, "incoming_count": 1, "mean_incoming_rating": .7}},
            },
            (2026, "median_recruit_rating"): 50,
            (2026, "median_transfer_rating"): .8,
        }
        opener = {}
        mature = {}
        add_personnel_features(opener, 2026, 1, 2, 0, 0, personnel)
        add_personnel_features(mature, 2026, 1, 2, 9, 9, personnel)
        self.assertGreater(opener["personnel_transfer_minutes"], mature["personnel_transfer_minutes"])
        self.assertAlmostEqual(opener["personnel_recruit_rating"] / 10, mature["personnel_recruit_rating"])

    def test_current_season_end_rating_cannot_initialize_same_season(self):
        current = [{
            "team_id": 1,
            "adjusted_offense": 999,
            "adjusted_defense": 1,
            "continuity_from_prior": {"returning_minutes_pct": 50},
        }]
        previous = [{"team_id": 1, "adjusted_offense": 110, "adjusted_defense": 95, "pace": 70}]
        state = initial_states(current, previous, 100, 68)["1"]
        self.assertEqual(state.offense, 105)
        self.assertEqual(state.defense, 97.5)
        self.assertNotEqual(state.offense, 999)

    def test_market_data_is_not_a_model_feature(self):
        self.assertFalse(any("market" in name or "spread" in name or "total_close" in name for name in MARGIN_FEATURES))

    def test_neutral_site_removes_home_court_feature(self):
        states = initial_states([{"team_id": 1}, {"team_id": 2}], [], 100, 68)
        neutral = projection_features({"neutral_site": True}, states["1"], states["2"], 100)
        campus = projection_features({"neutral_site": False}, states["1"], states["2"], 100)
        self.assertEqual(neutral["home_court"], 0)
        self.assertEqual(campus["home_court"], 1)
        self.assertEqual(neutral["early_home"], 0)
        self.assertEqual(campus["nonconference_home"], 1)
        self.assertEqual(campus["raw_margin_curve"], campus["raw_margin"] * abs(campus["raw_margin"]))

    def test_rejects_pre_cleanup_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "season_2026.json.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                json.dump({"meta": {"season": 2026, "builder_version": "cbb-history-v1.0"}}, handle)
            with self.assertRaisesRegex(RuntimeError, "clean cbb-history-v1.1"):
                load_seasons(Path(tmp))

    def test_current_priors_prefer_verified_roster_continuity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profiles = {
                "meta": {"season": 2027},
                "teams": [{
                    "team_id": 1,
                    "team": "Test",
                    "conference": {"name": "Test Conf"},
                    "preseason_prior": {"returning_minutes_pct": None, "adjusted": {"offense": 120, "defense": 90}},
                }],
            }
            players = {
                "meta": {"version": "thi-cbb-player-research-v1.3"},
                "team_rosters": [{"team_id": 1, "returning_minutes_pct": 62.5}],
            }
            profile_path = root / "profiles.json"
            player_path = root / "players.json"
            profile_path.write_text(json.dumps(profiles))
            player_path.write_text(json.dumps(players))
            payload = current_priors(
                profile_path,
                [{"team_id": 1, "adjusted_offense": 120, "adjusted_defense": 90, "pace": 68}],
                {2027: {}},
                player_path,
            )
            row = payload["teams"][0]
            self.assertEqual(row["returning_minutes_pct"], 62.5)
            self.assertEqual(row["continuity_source"], "verified_current_roster_join")
            self.assertEqual(row["prior_tempo"], 68)
            self.assertEqual(payload["meta"]["verified_roster_continuity_count"], 1)
            self.assertGreater(row["prior_net"], 15)

    def test_evaluation_reports_context_and_probability_calibration(self):
        rows = []
        for index, probability in enumerate((0.2, 0.7, 0.8, 0.4)):
            rows.append({
                "home_games_before": index * 2,
                "away_games_before": index * 2,
                "conference_game": index % 2 == 0,
                "neutral_site": index == 1,
                "projected_home_margin": (-4, 5, 8, -2)[index],
                "actual_home_margin": (-6, 3, 10, 1)[index],
                "projected_total": 140 + index,
                "actual_total": 138 + index,
                "home_win_probability": probability,
                "market_home_spread": (3, -4, -7, 1)[index],
                "market_total": 139 + index,
            })
        report = metrics(rows)
        self.assertEqual(report["context_slices"]["season_opener"]["games"], 1)
        self.assertEqual(report["context_slices"]["settled_sample"]["games"], 1)
        self.assertEqual(report["context_slices"]["neutral_site"]["games"], 1)
        self.assertEqual(sum(row["games"] for row in report["win_probability_calibration"]), 4)


if __name__ == "__main__":
    unittest.main()
