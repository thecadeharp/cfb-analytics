#!/usr/bin/env python3

import unittest

from scripts.enrich_cbb_schedule import enrich


class CbbScheduleEnrichmentTests(unittest.TestCase):
    def test_only_confirmed_time_replaces_tbd_and_broadcast_is_merged(self):
        profiles = {"teams": [
            {"team_id": 1, "espn_id": "10"},
            {"team_id": 2, "espn_id": "20"},
        ]}
        board = {"meta": {}, "games": [{
            "game_id": 99,
            "start_date": "2026-11-06T05:00:00.000Z",
            "start_time_tbd": True,
            "home": {"team_id": 1},
            "away": {"team_id": 2},
            "broadcasts": [],
        }]}
        payload = {"events": [{
            "id": "abc",
            "date": "2026-11-07T00:00Z",
            "competitions": [{
                "timeValid": True,
                "competitors": [
                    {"team": {"id": "10"}},
                    {"team": {"id": "20"}},
                ],
                "broadcasts": [{"media": {"shortName": "SEC Network"}}],
            }],
        }]}
        result = enrich(board, profiles, lambda _team_id: payload)
        game = result["games"][0]
        self.assertEqual(game["start_date"], "2026-11-07T00:00:00.000Z")
        self.assertFalse(game["start_time_tbd"])
        self.assertEqual(game["broadcasts"], ["SEC Network"])
        self.assertEqual(result["meta"]["schedule_enrichment"]["times_updated"], 1)
        self.assertEqual(result["meta"]["schedule_enrichment"]["broadcasts_updated"], 1)

    def test_unconfirmed_time_does_not_replace_existing_schedule(self):
        profiles = {"teams": [
            {"team_id": 1, "espn_id": "10"},
            {"team_id": 2, "espn_id": "20"},
        ]}
        board = {"meta": {}, "games": [{
            "start_date": "2026-11-06T05:00:00.000Z",
            "start_time_tbd": True,
            "home": {"team_id": 1}, "away": {"team_id": 2}, "broadcasts": [],
        }]}
        payload = {"events": [{
            "id": "abc", "date": "2026-11-07T05:00Z",
            "competitions": [{"timeValid": False, "competitors": [
                {"team": {"id": "10"}}, {"team": {"id": "20"}},
            ], "broadcasts": []}],
        }]}
        result = enrich(board, profiles, lambda _team_id: payload)
        self.assertEqual(result["games"][0]["start_date"], "2026-11-06T05:00:00.000Z")
        self.assertTrue(result["games"][0]["start_time_tbd"])


if __name__ == "__main__":
    unittest.main()
