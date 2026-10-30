#!/usr/bin/env python3

import unittest
from datetime import datetime, timedelta, timezone

from scripts.audit_data_freshness import (
    acceptable_completed_weeks,
    current_cfb_week,
    in_scoreboard_live_window,
    parse_time,
    postgame_covers_results,
    required_checks_pass,
    within_age,
)


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

    def test_live_score_slo_starts_at_kickoff_not_before(self):
        projections = {"games": [{
            "start_date": "2026-10-30T23:30:00Z",
            "status": "scheduled",
        }]}
        self.assertFalse(in_scoreboard_live_window(
            projections, datetime(2026, 10, 30, 22, 30, tzinfo=timezone.utc)
        ))
        self.assertTrue(in_scoreboard_live_window(
            projections, datetime(2026, 10, 30, 23, 30, tzinfo=timezone.utc)
        ))

    def test_weekly_delivery_grace_matches_sunday_through_monday_window(self):
        sunday = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        monday = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
        tuesday = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(acceptable_completed_weeks(8, sunday), {6, 7, 8})
        self.assertEqual(acceptable_completed_weeks(8, monday), {6, 7, 8})
        self.assertEqual(acceptable_completed_weeks(8, tuesday), {7, 8})

    def test_prior_public_player_week_is_accepted_during_delivery_grace(self):
        sunday = datetime(2026, 10, 25, 16, 0, tzinfo=timezone.utc)
        acceptable = acceptable_completed_weeks(9, sunday)
        self.assertIn(7, acceptable)
        self.assertNotIn(6, acceptable)

    def test_postgame_coverage_requires_every_published_final(self):
        results = {"games": [{"game_id": "101"}, {"game_id": 202}]}
        complete = {"games": {"101": {}, "202": {}}}
        missing = {"games": {"101": {}}}
        self.assertTrue(postgame_covers_results(results, complete))
        self.assertFalse(postgame_covers_results(results, missing))

    def test_immutable_derived_asset_can_pass_with_stale_informational_age(self):
        checks = {"timestamp_present": True, "fresh": False, "games": True}
        self.assertFalse(required_checks_pass(checks))
        self.assertTrue(required_checks_pass(checks, freshness_required=False))
        self.assertFalse(required_checks_pass(
            {**checks, "games": False}, freshness_required=False
        ))


if __name__ == "__main__":
    unittest.main()
