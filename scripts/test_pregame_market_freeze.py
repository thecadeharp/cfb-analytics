import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.modules.setdefault("requests", SimpleNamespace())

from scripts.build_projections import (
    freeze_started_markets,
    load_frozen_pregame_markets,
)


class PregameMarketFreezeTests(unittest.TestCase):
    def test_latest_pre_kick_snapshot_replaces_live_provider_quote(self):
        rows = [
            {
                "game_id": 401856849,
                "captured_at_utc": "2026-11-07T16:27:58Z",
                "start_date": "2026-11-07T17:00:00Z",
                "away_team": "BYU",
                "home_team": "Utah",
                "market_at_snapshot": {
                    "home_spread": -4.5,
                    "total": 49.5,
                    "bookmaker": "Consensus (10 books)",
                },
            },
            {
                "game_id": 401856849,
                "captured_at_utc": "2026-11-07T17:47:00Z",
                "start_date": "2026-11-07T17:00:00Z",
                "away_team": "BYU",
                "home_team": "Utah",
                "market_at_snapshot": {
                    "home_spread": -7.5,
                    "total": 58.5,
                    "bookmaker": "Consensus (8 books)",
                },
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "snapshots.jsonl"
            ledger.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            frozen = load_frozen_pregame_markets(ledger)

        odds = {
            "meta": {},
            "games": [{
                "home_team": "Utah",
                "away_team": "BYU",
                "spread_home": -7.5,
                "total": 58.5,
            }],
        }
        schedule = {
            "games": [{
                "home_team": "Utah",
                "away_team": "BYU",
                "start_date": "2026-11-07T17:00:00Z",
            }],
            "team_schedules": {},
        }
        result = freeze_started_markets(
            odds,
            schedule,
            frozen,
            now=datetime(2026, 11, 7, 17, 47, tzinfo=timezone.utc),
        )
        game = result["games"][0]
        self.assertEqual(game["spread_home"], -4.5)
        self.assertEqual(game["total"], 49.5)
        self.assertEqual(game["bookmaker"], "Consensus (10 books)")
        self.assertEqual(game["market_state"], "frozen_pregame")

    def test_post_kick_quote_is_removed_without_verified_snapshot(self):
        odds = {"meta": {}, "games": [{"home_team": "Home", "away_team": "Away", "spread_home": -9}]}
        schedule = {
            "games": [{"home_team": "Home", "away_team": "Away", "start_date": "2026-11-07T17:00:00Z"}],
            "team_schedules": {},
        }
        result = freeze_started_markets(
            odds,
            schedule,
            {},
            now=datetime(2026, 11, 7, 17, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(result["games"], [])
        self.assertEqual(result["meta"]["post_kick_markets_withheld"], 1)


if __name__ == "__main__":
    unittest.main()
