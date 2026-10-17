#!/usr/bin/env python3

import unittest
from datetime import datetime, timedelta, timezone

from scripts.audit_data_freshness import current_cfb_week, parse_time, within_age


class DataFreshnessAuditTests(unittest.TestCase):
    def test_parse_time_normalizes_to_utc(self):
        self.assertEqual(
            parse_time("2026-10-16T20:00:00-04:00"),
            datetime(2026, 10, 17, 0, 0, tzinfo=timezone.utc),
        )

    def test_freshness_window_rejects_stale_and_future_assets(self):
        now = datetime(2026, 10, 17, 1, 0, tzinfo=timezone.utc)
        self.assertTrue(within_age(now - timedelta(minutes=29), now, 0.5))
        self.assertFalse(within_age(now - timedelta(minutes=31), now, 0.5))
        self.assertFalse(within_age(now + timedelta(minutes=16), now, 0.5))

    def test_active_week_ignores_past_and_final_games(self):
        now = datetime(2026, 10, 17, 1, 0, tzinfo=timezone.utc)
        projections = {"games": [
            {"week": 6, "start_date": "2026-10-10T16:00:00Z", "status": "final"},
            {"week": 7, "start_date": "2026-10-17T16:00:00Z", "status": "scheduled"},
            {"week": 8, "start_date": "2026-10-24T16:00:00Z", "status": "scheduled"},
        ]}
        self.assertEqual(current_cfb_week(projections, now), 7)


if __name__ == "__main__":
    unittest.main()
