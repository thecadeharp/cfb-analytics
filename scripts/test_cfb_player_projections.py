import unittest

from scripts.build_cfb_player_projections import build


def player(athlete_id, name, team, position, share, rating=70, games=6):
    traditional = {
        "pass_attempts": 180, "completions": 120, "pass_yards": 1500, "pass_tds": 12, "interceptions": 3,
        "rush_attempts": 60, "rush_yards": 300, "targets": 48, "receptions": 36, "receiving_yards": 540,
    }
    workload = {"pass_attempt_share": share, "rush_attempt_share": share, "target_share": share}
    return {
        "athlete_id": athlete_id, "name": name, "team": team, "conference": "Test", "position": position,
        "position_group": position, "status": "active", "games": games, "traditional": traditional,
        "workload": workload, "rating": rating, "national_position_rank": 1, "reliability": 90,
    }


class PlayerProjectionTests(unittest.TestCase):
    def setUp(self):
        self.players = {
            "meta": {"season": 2026, "through_week": 7},
            "players": {
                "1": player("1", "Starter QB", "Alpha", "QB", 90),
                "2": player("2", "Primary RB", "Alpha", "RB", 35),
                "3": player("3", "Reserve WR", "Alpha", "WR", 2),
                "4": player("4", "Opponent QB", "Beta", "QB", 90),
            },
        }
        self.board = {"games": [{
            "game_id": 10, "week": 8, "start_date": "2026-10-24T19:30:00Z", "status": "scheduled",
            "venue": "Test Stadium", "network": "Test", "home": {"team": "Alpha"}, "away": {"team": "Beta"},
            "projection": {"home_spread": -7, "total": 54},
        }]}
        profile = lambda: {"non_garbage": {"offense": {"n_plays": 420, "yards_per_pass_play": 7.5, "yards_per_rush": 4.8}, "defense": {"n_plays": 410, "yards_per_pass_play": 7.0, "yards_per_rush": 4.4}}}
        self.metrics = {"teams": {"Alpha": profile(), "Beta": profile()}}

    def test_builds_position_specific_research_projections(self):
        payload = build(self.players, self.board, self.metrics, {"teams": {}})
        self.assertEqual(payload["meta"]["status"], "research_only")
        self.assertEqual(payload["meta"]["model_usage"], "display_only_not_used_by_model_a")
        self.assertEqual(payload["meta"]["market_data_usage"], "none_ingested_retained_or_displayed")
        names = {row["name"] for row in payload["projections"]}
        self.assertIn("Starter QB", names)
        self.assertIn("Primary RB", names)
        self.assertNotIn("Reserve WR", names)
        quarterback = next(row for row in payload["projections"] if row["name"] == "Starter QB")
        self.assertGreater(quarterback["projection"]["pass_yards"], 0)
        self.assertGreater(quarterback["projection"]["completions"], 0)
        self.assertGreaterEqual(quarterback["projection"]["interceptions"], 0)
        self.assertEqual(quarterback["matchup"]["opponent"], "Beta")

    def test_source_linked_availability_creates_watch_state(self):
        notes = {"teams": {"Alpha": [{"player": "Starter QB", "status": "Questionable", "text": "Official report", "source_url": "https://example.com/report"}]}}
        payload = build(self.players, self.board, self.metrics, notes)
        quarterback = next(row for row in payload["projections"] if row["name"] == "Starter QB")
        self.assertEqual(quarterback["confidence"], "availability_watch")
        self.assertEqual(quarterback["availability"]["status"], "Questionable")


if __name__ == "__main__":
    unittest.main()
