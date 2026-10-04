#!/usr/bin/env python3
"""Validate THI's persisted CBB historical feature warehouse."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any


FORBIDDEN_RAW_KEYS = {
    "fieldGoals",
    "twoPointFieldGoals",
    "threePointFieldGoals",
    "freeThrows",
    "rebounds",
    "turnovers",
    "fouls",
    "assists",
    "steals",
    "blocks",
}


def close(left: Any, right: Any) -> bool:
    try:
        return math.isclose(float(left), float(right), abs_tol=0.01)
    except (TypeError, ValueError):
        return False


def contains_forbidden_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_RAW_KEYS:
                return key
            found = contains_forbidden_key(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = contains_forbidden_key(child)
            if found:
                return found
    return None


def validate_season(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    meta = payload.get("meta") or {}
    games = payload.get("games") or []
    teams = payload.get("season_end_teams") or []
    assert meta.get("builder_version") == "cbb-history-v1.1", f"{path}: wrong builder"
    assert meta.get("raw_api_data_stored") is False, f"{path}: raw-data flag is not false"
    assert len(games) == meta.get("game_count") and len(games) >= 3000, f"{path}: invalid game count"
    assert len(teams) == meta.get("team_count") and len(teams) >= 300, f"{path}: invalid team count"
    forbidden = contains_forbidden_key(payload)
    assert forbidden is None, f"{path}: raw box-score key persisted: {forbidden}"

    game_ids: set[str] = set()
    prior_sort_key: tuple[str, str] | None = None
    market_count = 0
    for game in games:
        game_id = str(game.get("game_id"))
        assert game_id not in game_ids, f"{path}: duplicate game {game_id}"
        game_ids.add(game_id)
        sort_key = (str(game.get("start_date") or ""), game_id)
        assert prior_sort_key is None or sort_key >= prior_sort_key, f"{path}: games are not sorted"
        prior_sort_key = sort_key
        assert game.get("home_team_id") != game.get("away_team_id"), f"{path}: identical team IDs"
        outcome = game.get("outcome") or {}
        home_points = outcome.get("home_points")
        away_points = outcome.get("away_points")
        assert float(home_points) >= 20 and float(away_points) >= 20, f"{path}: implausible/incomplete score"
        assert float(outcome.get("total_points")) >= 40, f"{path}: unplayed game retained"
        assert float(game.get("pace")) >= 30, f"{path}: implausible/incomplete pace"
        assert close(outcome.get("home_margin"), float(home_points) - float(away_points)), f"{path}: bad margin"
        assert close(outcome.get("total_points"), float(home_points) + float(away_points)), f"{path}: bad total"
        if int((game.get("market") or {}).get("book_count") or 0) > 0:
            market_count += 1
    assert market_count == meta.get("games_with_market"), f"{path}: market count mismatch"
    return payload


def validate_warehouse(root: Path, season: int | None = None) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    assert manifest_path.exists(), f"missing {manifest_path}"
    manifest = json.loads(manifest_path.read_text())
    rows = manifest.get("seasons") or []
    if season is not None:
        rows = [row for row in rows if int(row.get("season")) == season]
        assert len(rows) == 1, f"season {season} is missing or duplicated in manifest"
    else:
        assert len(rows) == manifest.get("meta", {}).get("season_count"), "manifest season count mismatch"

    total_games = 0
    for row in rows:
        path = root / row["file"]
        assert path.exists(), f"missing {path}"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == row.get("sha256"), f"{path}: sha256 mismatch"
        assert path.stat().st_size == row.get("bytes"), f"{path}: byte count mismatch"
        payload = validate_season(path)
        assert payload["meta"]["season"] == row.get("season"), f"{path}: season mismatch"
        assert payload["meta"]["game_count"] == row.get("game_count"), f"{path}: game count mismatch"
        total_games += payload["meta"]["game_count"]
    if season is None:
        assert total_games == manifest.get("meta", {}).get("game_count"), "manifest game total mismatch"
    return {"season_count": len(rows), "game_count": total_games}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data/cbb/history"))
    parser.add_argument("--season", type=int)
    args = parser.parse_args()
    result = validate_warehouse(args.root, args.season)
    print(f"Validated {result['season_count']} CBB season(s), {result['game_count']} games")


if __name__ == "__main__":
    main()
