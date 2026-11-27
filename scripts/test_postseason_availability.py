import unittest

from scripts.validate_postseason_availability import validate


class PostseasonAvailabilityTests(unittest.TestCase):
    def test_empty_registry_is_valid_and_model_isolation_is_explicit(self):
        self.assertEqual(validate({
            "meta": {"model_usage": "traditional_bowl_display_and_research_scenario_only"},
            "games": {},
        }), [])

    def test_manual_points_and_unpriced_staff_adjustments_are_rejected(self):
        errors = validate({
            "meta": {"model_usage": "traditional_bowl_display_and_research_scenario_only"},
            "games": {
                "1": {"teams": {
                    "A": {
                        "certainty": "confirmed",
                        "players": [{
                            "player": "Example Player",
                            "category": "opt_out",
                            "source_url": "https://example.com/player",
                            "verified_at_utc": "2026-12-10T12:00:00Z",
                            "availability_adjustment_points": 4,
                        }],
                        "staff_notes": [{
                            "text": "Interim coach",
                            "source_url": "https://example.com/coach",
                            "points": -2,
                        }],
                    },
                    "B": {"certainty": "developing"},
                }},
            },
        })
        self.assertTrue(any("manual point adjustments" in error for error in errors))
        self.assertTrue(any("staff context must remain unpriced" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
