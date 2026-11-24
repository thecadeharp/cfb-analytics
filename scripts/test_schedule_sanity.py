import unittest
from unittest.mock import MagicMock, patch

with patch.dict("sys.modules", {"requests": MagicMock()}):
    from scripts.build_projections import kickoff_local_date


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


if __name__ == "__main__":
    unittest.main()
