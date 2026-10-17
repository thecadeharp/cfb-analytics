#!/usr/bin/env python3

import unittest
from datetime import datetime, timezone

from scripts.build_availability_report import is_material_status, parse_hdi_payload, parse_pac12_payload

NOW = datetime(2026, 10, 16, 23, 30, tzinfo=timezone.utc)
SOURCE = {"url": "https://conference.example/report"}


class AvailabilityReportTests(unittest.TestCase):
    def test_hdi_excludes_available_and_exempt_players(self):
        payload = {"101": {
            "publishDate": "2026-10-16", "postedTime": "18:00:00", "conferenceTimeZone": "CT",
            "ReportType": "Update 2", "footer": {"date": "2026-10-17"},
            "games": [
                {"teamDisplayName": "Alpha", "rows": [
                    {"name": "QB #7 A. Quarterback", "status": "Questionable", "exemptStatus": "NonExempt"},
                    {"name": "WR #1 A. Receiver", "status": "Available", "exemptStatus": "NonExempt"},
                    {"name": "OL #2 A. Lineman", "status": "Exempt", "exemptStatus": "Exempt"},
                ]},
                {"teamDisplayName": "Beta", "rows": []},
            ],
        }}
        notes, reports = parse_hdi_payload(payload, "SEC", SOURCE, NOW)
        self.assertEqual(len(reports), 1)
        self.assertEqual(len(notes["Alpha"]), 1)
        note = notes["Alpha"][0]
        self.assertEqual(note["player"], "A. Quarterback")
        self.assertEqual(note["position"], "QB")
        self.assertEqual(note["jersey_number"], "7")
        self.assertEqual(note["opponent"], "Beta")
        self.assertTrue(note["withhold_public_signal"])

    def test_non_qb_status_is_visible_without_signal_hold(self):
        self.assertFalse(is_material_status("RB", "Out"))
        self.assertFalse(is_material_status("QB", "Probable"))
        self.assertTrue(is_material_status("QB", "Game Time Decision"))

    def test_pac12_payload_is_normalized(self):
        payload = {"games": [{
            "gameId": "a-b", "dateISO": "2026-10-17", "updatedAtUTC": "2026-10-16T22:00:00Z",
            "notes": "Second Report",
            "away": {"name": "Alpha", "players": [{"name": "A. Defender", "position": "DB", "status": "Out"}]},
            "home": {"name": "Beta", "players": []},
        }]}
        notes, reports = parse_pac12_payload(payload, "Pac-12", SOURCE, NOW)
        self.assertEqual(len(reports), 1)
        self.assertEqual(notes["Alpha"][0]["status"], "Out")
        self.assertEqual(notes["Alpha"][0]["opponent"], "Beta")
        self.assertFalse(notes["Alpha"][0]["withhold_public_signal"])

    def test_hdi_drops_report_after_game_expiration(self):
        payload = {"101": {
            "publishDate": "2026-10-15", "postedTime": "18:00:00", "conferenceTimeZone": "CT",
            "ReportType": "Final", "footer": {"date": "2026-10-15"},
            "games": [
                {"teamDisplayName": "Alpha", "rows": [
                    {"name": "QB #7 A. Quarterback", "status": "Out", "exemptStatus": "NonExempt"},
                ]},
                {"teamDisplayName": "Beta", "rows": []},
            ],
        }}
        notes, reports = parse_hdi_payload(payload, "SEC", SOURCE, NOW)
        self.assertEqual(notes, {})
        self.assertEqual(reports, [])

    def test_pac12_drops_report_after_game_expiration(self):
        payload = {"games": [{
            "gameId": "old-game", "dateISO": "2026-10-15", "updatedAtUTC": "2026-10-15T22:00:00Z",
            "notes": "Final Report",
            "away": {"name": "Alpha", "players": [{"name": "A. Quarterback", "position": "QB", "status": "Out"}]},
            "home": {"name": "Beta", "players": []},
        }]}
        notes, reports = parse_pac12_payload(payload, "Pac-12", SOURCE, NOW)
        self.assertEqual(notes, {})
        self.assertEqual(reports, [])


if __name__ == "__main__":
    unittest.main()
