import unittest

from scripts.build_cbb_venue_audit import apply_overrides, build_audit


class CbbVenueAuditTests(unittest.TestCase):
    def test_official_override_resolves_false_campus_venue(self):
        board = {"games": [
            {"game_id": 1, "neutral_site": False, "home": {"team_id": 2, "team": "B"}, "away": {"team_id": 3, "team": "C"}, "venue": {"name": "B Arena", "city": "B", "state": "BB"}},
            {"game_id": 2, "neutral_site": True, "home": {"team_id": 2, "team": "B"}, "away": {"team_id": 4, "team": "D"}, "venue": {"name": "B Arena", "city": "B", "state": "BB"}},
        ]}
        overrides = {"games": {"2": {"neutral_site": True, "venue": {"name": "Event Arena", "city": "E", "state": "EE"}, "verification": "official"}}}
        resolved = apply_overrides(board, overrides)
        self.assertEqual(resolved["games"][1]["venue"]["name"], "Event Arena")
        audit = build_audit(board, overrides)
        self.assertEqual(audit["meta"]["status"], "healthy")
        self.assertEqual(audit["summary"]["official_overrides"], 1)
        self.assertEqual(audit["games"][0]["home_court_points_required"], 0.0)

    def test_missing_neutral_venue_stays_safe_without_blocking_refresh(self):
        board = {"games": [{
            "game_id": 3,
            "neutral_site": True,
            "home": {"team_id": 2, "team": "B"},
            "away": {"team_id": 4, "team": "D"},
            "venue": {},
        }]}
        audit = build_audit(board, {"games": {}})
        self.assertEqual(audit["meta"]["status"], "healthy")
        self.assertEqual(audit["summary"]["provider_neutral_venue_pending"], 1)
        self.assertEqual(audit["summary"]["unresolved_reviews"], 0)
        self.assertEqual(audit["games"][0]["home_court_points_required"], 0.0)


if __name__ == "__main__":
    unittest.main()
