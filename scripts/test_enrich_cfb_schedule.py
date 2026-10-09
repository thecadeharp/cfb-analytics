#!/usr/bin/env python3

import unittest

from scripts.enrich_cfb_schedule import enrich


class CfbScheduleEnrichmentTests(unittest.TestCase):
    def test_exact_existing_game_receives_display_metadata_only(self):
        schedule = {
            "meta": {},
            "games": [{"id": 99, "start_date": "2026-10-09T12:00:00.000Z", "venue": None}],
            "team_schedules": {"Alpha": [{"id": 99, "start_date": "2026-10-09T12:00:00.000Z"}]},
        }
        projections = {"games": [{"game_id": 99, "start_date": "2026-10-09T12:00:00.000Z", "projection": {"home_spread": -3.5}}]}
        metrics = {"teams": {"Alpha": {}, "Beta State": {}}}
        directory = {"sports": [{"leagues": [{"teams": [
            {"team": {"id": "1", "location": "Alpha"}},
            {"team": {"id": "2", "location": "Beta State"}},
        ]}]}]}
        payload = {"events": [{"id": "99", "date": "2026-10-09T23:00Z", "competitions": [{
            "timeValid": True,
            "venue": {"fullName": "Example Stadium"},
            "broadcasts": [{"media": {"shortName": "ESPN"}}],
        }]}]}

        schedule, projections = enrich(schedule, projections, metrics, directory, lambda _team_id: payload)
        game = projections["games"][0]
        self.assertEqual(game["start_date"], "2026-10-09T23:00:00.000Z")
        self.assertEqual(game["network"], "ESPN")
        self.assertEqual(game["venue"], "Example Stadium")
        self.assertEqual(game["projection"]["home_spread"], -3.5)
        self.assertFalse(schedule["meta"]["display_metadata_enrichment"]["model_a_touched"])

    def test_unknown_event_is_not_added(self):
        schedule = {"meta": {}, "games": [{"id": 99}], "team_schedules": {}}
        projections = {"games": [{"game_id": 99}]}
        metrics = {"teams": {"Alpha": {}}}
        directory = {"sports": [{"leagues": [{"teams": [{"team": {"id": "1", "location": "Alpha"}}]}]}]}
        payload = {"events": [{"id": "100", "date": "2026-10-10T00:00Z", "competitions": [{
            "timeValid": True, "venue": {"fullName": "Wrong Stadium"}, "broadcasts": []
        }]}]}
        schedule, projections = enrich(schedule, projections, metrics, directory, lambda _team_id: payload)
        self.assertNotIn("venue", projections["games"][0])
        self.assertEqual(len(schedule["games"]), 1)


if __name__ == "__main__":
    unittest.main()
