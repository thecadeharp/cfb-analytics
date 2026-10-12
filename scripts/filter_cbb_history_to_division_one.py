#!/usr/bin/env python3
"""Remove non-Division-I matchups from the derived CBB history warehouse."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import Any

try:
    from scripts.build_cbb_historical_season import atomic_gzip_json, rebuild_manifest
except ModuleNotFoundError:
    from build_cbb_historical_season import atomic_gzip_json, rebuild_manifest


def filter_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    teams = payload.get("season_end_teams") or []
    division_one_team_ids = {
        str(team.get("team_id"))
        for team in teams
        if isinstance(team, dict) and team.get("team_id") is not None
    }
    games = payload.get("games") or []
    retained = [
        game for game in games
        if str(game.get("home_team_id")) in division_one_team_ids
        and str(game.get("away_team_id")) in division_one_team_ids
    ]
    removed = len(games) - len(retained)
    meta = dict(payload.get("meta") or {})
    meta.update({
        "builder_version": "cbb-history-v1.2",
        "game_count": len(retained),
        "games_with_market": sum(int((game.get("market") or {}).get("book_count") or 0) > 0 for game in retained),
        "division_one_registry_enforced": True,
        "non_division_one_games_removed": int(meta.get("non_division_one_games_removed") or 0) + removed,
    })
    return {**payload, "meta": meta, "games": retained}, removed


def migrate(root: Path) -> dict[str, int]:
    seasons = 0
    removed = 0
    for path in sorted(root.glob("season_*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        filtered, count = filter_payload(payload)
        atomic_gzip_json(path, filtered)
        seasons += 1
        removed += count
        print(f"{path.name}: removed {count}; retained {filtered['meta']['game_count']}")
    rebuild_manifest(root)
    return {"seasons": seasons, "removed": removed}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data/cbb/history"))
    args = parser.parse_args()
    result = migrate(args.root)
    print(f"Filtered {result['seasons']} seasons; removed {result['removed']} non-D-I games")


if __name__ == "__main__":
    main()
