#!/usr/bin/env python3

import unittest
from datetime import datetime, timedelta, timezone

from scripts.audit_data_freshness import (
    acceptable_completed_weeks,
    current_cfb_week,
    in_scoreboard_live_window,
    live_status_freshness,
    parse_time,
    postgame_covers_results,
    required_checks_pass,
    upcoming_market_coverage,
    within_age,
)


class DataFreshnessAuditTests(unittest.TestCase):
    def test_live_cbb_status_requires_thirty_minute_freshness(self):
        now = datetime(2026, 11, 24, 13, tzinfo=timezone.utc)
        stale = live_status_freshness(
            {
                "meta": {"generated_at_utc": "2026-11-24T12:00:00Z"},
                "games": [{"status": "live"}],
            },
            now,
            timestamp_paths=["meta.generated_at_utc"],
        )
        self.assertFalse(stale["live_status_fresh"])

    def test_final_only_cbb_board_does_not_require_live_cadence(self):
        now = datetime(2026, 11, 24, 13, tzinfo=timezone.utc)
        status = live_status_freshness(
            {
                "meta": {"generated_at_utc": "2026-11-24T01:00:00Z"},
                "games": [{"status": "final"}],
            },
            now,
            timestamp_paths=["meta.generated_at_utc"],
        )
        self.assertTrue(status["live_status_fresh"])

    def test_near_term_market_coverage_requires_half_the_slate(self):
        now = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
        games = []
        for index in range(4):
            games.append({
                "status": "scheduled",
                "start_date": f"2026-11-25T0{index}:00:00Z",
                "market": {
                    "home_spread": -3.5 if index < 2 else None,
                    "total": 51.5 if index < 2 else None,
                },
            })
        coverage = upcoming_market_coverage(
            {"games": games},
            now,
            spread_path="market.home_spread",
            total_path="market.total",
        )
        self.assertEqual(coverage["required_games"], 2)
        self.assertTrue(coverage["spread_coverage_ok"])
        self.assertTrue(coverage["total_coverage_ok"])

    def test_empty_near_term_market_payload_fails_coverage(self):
        now = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
        coverage = upcoming_market_coverage(
            {"games": [{
                "status": "scheduled",
                "start_date": "2026-11-25T00:00:00Z",
                "market": {},
            }]},
            now,
            spread_path="market.home_spread",
            total_path="market.total",
        )
        self.assertFalse(coverage["spread_coverage_ok"])
        self.assertFalse(coverage["total_coverage_ok"])

    def test_market_coverage_horizon_excludes_unposted_future_slates(self):
        now = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
        coverage = upcoming_market_coverage(
            {"games": [
                {
                    "status": "scheduled",
                    "start_date": "2026-11-26T12:00:00Z",
                    "market": {"spread": -4.5, "total": 151.5},
                },
                {
                    "status": "scheduled",
                    "start_date": "2026-11-28T12:00:00Z",
                    "market": {},
                },
            ]},
            now,
            spread_path="market.spread",
            total_path="market.total",
            horizon_hours=36,
        )
        self.assertEqual(coverage["eligible_games"], 1)
        self.assertTrue(coverage["spread_coverage_ok"])
        self.assertTrue(coverage["total_coverage_ok"])

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
