#!/usr/bin/env python3

import unittest
from datetime import datetime, timezone

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

    def test_verified_missing_event_is_added_and_conflicting_tbd_row_is_quarantined(self):
        profiles = {"teams": [
            {"team_id": 189, "espn_id": "2440", "team": "Nevada", "conference": {"abbreviation": "Mountain West"}},
            {"team_id": 311, "espn_id": "2540", "team": "UC Santa Barbara", "conference": {"abbreviation": "Big West"}},
            {"team_id": 1551, "espn_id": None, "team": "South Carolina Beaufort", "conference": None},
        ]}
        board = {
            "meta": {"start_date": "2026-11-09T00:00:00Z", "end_date": "2026-12-26T23:59:59Z"},
            "games": [{
                "game_id": 372765,
                "start_date": "2026-11-11T05:00:00.000Z",
                "status": "scheduled",
                "start_time_tbd": True,
                "home": {"team_id": 1551, "team": "South Carolina Beaufort"},
                "away": {"team_id": 189, "team": "Nevada"},
                "broadcasts": [],
            }],
        }
        payload = {"events": [{
            "id": "401911454",
            "date": "2026-11-12T02:00Z",
            "competitions": [{
                "timeValid": True,
                "competitors": [
                    {"homeAway": "home", "team": {"id": "2540"}},
                    {"homeAway": "away", "team": {"id": "2440"}},
                ],
                "venue": {"fullName": "The Thunderdome", "address": {"city": "Santa Barbara", "state": "CA"}},
                "broadcasts": [{"media": {"shortName": "ESPN+"}}],
            }],
        }]}
        result = enrich(
            board,
            profiles,
            lambda team_id: payload if team_id in {"2440", "2540"} else {"events": []},
            now=datetime(2026, 11, 11, 18, tzinfo=timezone.utc),
        )
        added = next(game for game in result["games"] if str(game["game_id"]) == "401911454")
        phantom = next(game for game in result["games"] if str(game["game_id"]) == "372765")
        self.assertEqual(added["home"]["team"], "UC Santa Barbara")
        self.assertEqual(added["away"]["team"], "Nevada")
        self.assertEqual(added["broadcasts"], ["ESPN+"])
        self.assertEqual(added["schedule_source"], "ESPN verified fallback")
        self.assertEqual(phantom["status"], "schedule_conflict")
        self.assertEqual(result["meta"]["schedule_enrichment"]["games_added"], 1)
        self.assertEqual(result["meta"]["schedule_enrichment"]["conflicts_quarantined"], 1)

    def test_missing_event_is_not_duplicated_when_pair_already_exists(self):
        profiles = {"teams": [
            {"team_id": 1, "espn_id": "10", "team": "One", "conference": {"abbreviation": "A"}},
            {"team_id": 2, "espn_id": "20", "team": "Two", "conference": {"abbreviation": "B"}},
        ]}
        board = {"meta": {}, "games": [{
            "game_id": 99,
            "start_date": "2026-11-12T02:00:00.000Z",
            "status": "scheduled",
            "start_time_tbd": False,
            "home": {"team_id": 1},
            "away": {"team_id": 2},
            "broadcasts": [],
        }]}
        payload = {"events": [{
            "id": "401",
            "date": "2026-11-12T02:00Z",
            "competitions": [{
                "timeValid": True,
                "competitors": [
                    {"homeAway": "home", "team": {"id": "10"}},
                    {"homeAway": "away", "team": {"id": "20"}},
                ],
                "broadcasts": [],
            }],
        }]}
        result = enrich(
            board,
            profiles,
            lambda _team_id: payload,
            now=datetime(2026, 11, 11, 18, tzinfo=timezone.utc),
        )
        self.assertEqual(len(result["games"]), 1)
        self.assertEqual(result["meta"]["schedule_enrichment"]["games_added"], 0)

    def test_verified_missing_final_is_retained_with_scores(self):
        profiles = {"teams": [
            {"team_id": 1, "espn_id": "10", "team": "One", "conference": {"abbreviation": "A"}},
            {"team_id": 2, "espn_id": "20", "team": "Two", "conference": {"abbreviation": "B"}},
        ]}
        board = {
            "meta": {"start_date": "2026-11-09T00:00:00Z", "end_date": "2026-12-26T23:59:59Z"},
            "games": [],
        }
        payload = {"events": [{
            "id": "401",
            "date": "2026-11-12T02:00Z",
            "status": {"type": {"state": "post", "completed": True}},
            "competitions": [{
                "timeValid": True,
                "neutralSite": True,
                "competitors": [
                    {"homeAway": "home", "score": "81", "team": {"id": "10"}},
                    {"homeAway": "away", "score": "74", "team": {"id": "20"}},
                ],
            }],
        }]}
        result = enrich(
            board,
            profiles,
            lambda _team_id: payload,
            now=datetime(2026, 11, 12, 5, tzinfo=timezone.utc),
        )
        added = result["games"][0]
        self.assertEqual(added["status"], "final")
        self.assertEqual((added["home"]["score"], added["away"]["score"]), (81, 74))
        self.assertTrue(added["neutral_site"])


if __name__ == "__main__":
    unittest.main()
