import unittest
from unittest.mock import MagicMock, patch

with patch.dict("sys.modules", {"requests": MagicMock()}):
    from scripts.build_projections import classify_schedule_phase, kickoff_local_date


class ScheduleSanityTests(unittest.TestCase):
    def test_midnight_utc_kickoff_keeps_prior_eastern_calendar_date(self):
        self.assertEqual(
            kickoff_local_date("2026-11-29T00:00:00.000Z"),
            "2026-11-28",
        )

    def test_daytime_utc_kickoff_keeps_eastern_calendar_date(self):
        self.assertEqual(
            kickoff_local_date("2026-10-10T19:30:00.000Z"),
            "2026-10-10",
        )

    def test_invalid_timestamp_does_not_pass_sanity_contract(self):
        self.assertEqual(kickoff_local_date("not-a-timestamp"), "")

    def test_postseason_defaults_to_bowl_without_overloading_week(self):
        result = classify_schedule_phase(
            {"week": 1, "notes": "Citrus Bowl"},
            "postseason",
        )
        self.assertEqual(result["schedule_phase"], "bowl")
        self.assertEqual(result["bowl_name"], "Citrus Bowl")
        self.assertIsNone(result["postseason_round"])

    def test_cfp_round_is_classified_from_provider_notes(self):
        result = classify_schedule_phase(
            {"week": 1, "notes": "College Football Playoff Quarterfinal"},
            "postseason",
        )
        self.assertEqual(result["schedule_phase"], "cfp")
        self.assertEqual(result["postseason_round"], "quarterfinal")
        self.assertEqual(result["display_label"], "CFP Quarterfinals")

    def test_verified_registry_overrides_provider_label(self):
        result = classify_schedule_phase(
            {"notes": "Bowl Game"},
            "postseason",
            {
                "schedule_phase": "cfp",
                "postseason_round": "semifinal",
                "bowl_name": "Peach Bowl",
            },
        )
        self.assertEqual(result["postseason_round"], "semifinal")
        self.assertEqual(result["bowl_name"], "Peach Bowl")
        self.assertEqual(result["display_label"], "CFP Semifinals")


if __name__ == "__main__":
    unittest.main()
