import unittest

from build_thi_season_outlook import (
    build_report,
    central_range,
    probability_distribution,
)


class SeasonOutlookTests(unittest.TestCase):
    def test_probability_distribution_is_exact(self):
        result = probability_distribution([0.5, 0.5])
        self.assertEqual(result, [0.25, 0.5, 0.25])

    def test_central_range_uses_distribution_mass(self):
        self.assertEqual(central_range([0.1, 0.2, 0.4, 0.2, 0.1], 0.80), [0, 3])

    def test_conference_projection_uses_only_same_conference_games(self):
        projections = {
            "meta": {"metrics_through_week": 4},
            "season_projections": {
                "Alpha": {
                    "games": 3, "actual_wins": 1, "actual_losses": 0,
                    "expected_wins": 2.25, "most_likely_record": "2-1",
                    "exact_win_distribution": {"0": 0, "1": 25, "2": 50, "3": 25},
                    "schedule": [
                        {"game_id": 1, "opponent": "Beta", "opponent_type": "FBS", "status": "completed", "win_probability": 100},
                        {"game_id": 2, "opponent": "Gamma", "opponent_type": "FBS", "status": "scheduled", "win_probability": 75},
                        {"game_id": 3, "opponent": "Delta", "opponent_type": "FBS", "status": "scheduled", "win_probability": 50},
                    ],
                }
            },
        }
        metrics = {"teams": {
            "Alpha": {"conference": "Test"},
            "Beta": {"conference": "Test"},
            "Gamma": {"conference": "Test"},
            "Delta": {"conference": "Other"},
        }}
        report = build_report(projections, metrics)
        conference = report["teams"]["Alpha"]["conference_outlook"]
        self.assertEqual(conference["games"], 2)
        self.assertEqual(conference["actual_wins"], 1)
        self.assertEqual(conference["expected_wins"], 1.75)
        self.assertEqual(conference["exact_win_distribution"], {"0": 0.0, "1": 25.0, "2": 75.0})
        self.assertFalse(report["meta"]["model_a_touched"])


if __name__ == "__main__":
    unittest.main()
