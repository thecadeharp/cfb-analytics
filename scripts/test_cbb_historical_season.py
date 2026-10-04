#!/usr/bin/env python3

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_cbb_historical_season import (
    atomic_gzip_json,
    build_season,
    paired_game,
    rebuild_manifest,
    season_windows,
)
from scripts.validate_cbb_historical_warehouse import validate_warehouse


class CbbHistoricalSeasonTests(unittest.TestCase):
    def test_rejects_zeroed_canceled_game_rows(self):
        row = {
            "gameId": 99,
            "isHome": True,
            "teamStats": {"points": {"total": 0}, "possessions": 0},
            "opponentStats": {"points": {"total": 0}, "possessions": 0},
            "pace": 0,
        }
        self.assertIsNone(paired_game(row, None))

    def test_month_windows_cover_regular_season_without_overlap(self):
        windows = season_windows(2024)
        self.assertEqual(len(windows), 6)
        self.assertEqual(windows[0][0], "2023-11-01T00:00:00Z")
        self.assertEqual(windows[-1][1], "2024-05-15T23:59:59Z")
        self.assertIn("2024-02-29", windows[3][1])

    def test_builds_deduplicated_derived_games_and_manifest(self):
        teams = [{"id": i, "school": f"Team {i}"} for i in range(1, 301)]
        leaderboard = [{
            "teamId": i, "team": f"Team {i}", "record": {"games": 30},
            "summary": {"pace": 68},
            "adjustedEfficiency": {"offensiveRating": 110, "defensiveRating": 100, "netRating": 10, "rankings": {"net": i}},
        } for i in range(1, 301)]
        box_rows = []
        for game_id in range(1, 3001):
            home_id = (game_id % 300) + 1
            away_id = ((game_id + 1) % 300) + 1
            box_rows.append({
                "gameId": game_id, "seasonType": "regular", "startDate": "2023-11-10T00:00:00Z",
                "teamId": home_id, "team": f"Team {home_id}", "opponentId": away_id, "opponent": f"Team {away_id}",
                "isHome": True, "neutralSite": False, "conferenceGame": False, "pace": 70,
                "teamStats": {"points": {"total": 80}, "possessions": 70, "rating": 114.3, "trueShooting": .60, "fourFactors": {"effectiveFieldGoalPct": .57, "turnoverRatio": .14, "offensiveReboundPct": .35, "freeThrowRate": .30}},
                "opponentStats": {"points": {"total": 70}, "possessions": 70, "rating": 100, "trueShooting": .52, "fourFactors": {"effectiveFieldGoalPct": .49, "turnoverRatio": .20, "offensiveReboundPct": .25, "freeThrowRate": .20}},
            })
        lines = [{"gameId": 1, "lines": [{"provider": "A", "spread": -5, "spreadOpen": -4, "overUnder": 145, "overUnderOpen": 143}]}]
        responses = {
            "/teams/directory": {"teams": teams},
            "/stats/team/leaderboard": leaderboard,
            "/teams/roster": [{"teamId": 1, "players": [{"id": 101}]}],
            "/stats/player/season": [{"teamId": 1, "athleteId": 101, "minutes": 500, "points": 200, "usage": 20}],
            "/games/teams": box_rows,
            "/lines": lines,
        }
        payload = build_season(2024, lambda path, _params: responses[path])
        self.assertEqual(payload["meta"]["request_count"], 16)
        self.assertEqual(payload["meta"]["game_count"], 3000)
        self.assertEqual(payload["meta"]["games_with_market"], 1)
        self.assertEqual(payload["games"][0]["outcome"]["home_margin"], 10)
        self.assertEqual(payload["games"][0]["home"]["effective_fg_pct"], 57)
        self.assertNotIn("fieldGoals", payload["games"][0]["home"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            atomic_gzip_json(root / "season_2024.json.gz", payload)
            manifest = rebuild_manifest(root)
            self.assertEqual(manifest["meta"]["season_count"], 1)
            self.assertEqual(manifest["meta"]["game_count"], 3000)
            with gzip.open(root / "season_2024.json.gz", "rt", encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved["meta"]["builder_version"], "cbb-history-v1.1")
            self.assertEqual(validate_warehouse(root), {"season_count": 1, "game_count": 3000})


if __name__ == "__main__":
    unittest.main()
