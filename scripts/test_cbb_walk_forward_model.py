#!/usr/bin/env python3

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_cbb_walk_forward_model import (
    MARGIN_FEATURES,
    initial_states,
    load_seasons,
    projection_features,
)


class CbbWalkForwardModelTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
