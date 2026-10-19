#!/usr/bin/env python3
import unittest
from collections import defaultdict

from scripts.build_roster_assets import add_player_stats


class RosterAssetStatTests(unittest.TestCase):
    def test_defensive_box_score_categories_are_retained(self):
        payload = [{"teams": [{"team": "Notre Dame", "categories": [{"name": "defensive", "types": [
            {"name": "TOT", "athletes": [{"id": "1", "stat": "13"}]},
            {"name": "TFL", "athletes": [{"id": "1", "stat": "2.5"}]},
            {"name": "PD", "athletes": [{"id": "1", "stat": "5"}]},
            {"name": "INT", "athletes": [{"id": "1", "stat": "1"}]},
        ]}]}]}]
        stats = defaultdict(lambda: defaultdict(float))
        add_player_stats(stats, payload)
        row = stats[("Notre Dame", "1")]
        self.assertEqual(row["total_tackles"], 13)
        self.assertEqual(row["tackles_for_loss"], 2.5)
        self.assertEqual(row["passes_defended"], 5)
        self.assertEqual(row["interceptions_def"], 1)


if __name__ == "__main__":
    unittest.main()
