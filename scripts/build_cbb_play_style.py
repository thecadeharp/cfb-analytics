#!/usr/bin/env python3
"""Build compact current-season CBB play-style features from CBBD play data.

Raw play-by-play is never published. The output retains only game/team aggregates
needed for shot-location, assist, lineup-coverage and explicit transition research.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.verify_cbb_api_foundation import clean_key, fetch_json
except ModuleNotFoundError:
    from verify_cbb_api_foundation import clean_key, fetch_json


ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-play-style-v1.0"
FINAL_STATUSES = {"final", "completed", "complete"}


def as_plays(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("plays", "items", "data"):
            if isinstance(payload.get(key), list):
                return [row for row in payload[key] if isinstance(row, dict)]
    return []


def team_id_for_play(play: dict[str, Any]) -> str | None:
    for key in ("teamId", "team_id", "possessionTeamId", "offenseTeamId"):
        if play.get(key) is not None:
            return str(play[key])
    team = play.get("team")
    if isinstance(team, dict) and team.get("id") is not None:
        return str(team["id"])
    return None


def shot_zone(shot: dict[str, Any]) -> str | None:
    value = " ".join(str(shot.get(key) or "") for key in ("range", "zone", "type")).lower()
    if any(token in value for token in ("rim", "layup", "dunk", "restricted")):
        return "rim"
    if any(token in value for token in ("three", "3pt", "3-point", "3 point", "arc")):
        return "three"
    if any(token in value for token in ("mid", "jumper", "two point", "2pt", "2-point")):
        return "midrange"
    return None


def aggregate_game(game: dict[str, Any], payload: Any) -> dict[str, Any]:
    teams = {
        str((game.get("home") or {}).get("team_id")): (game.get("home") or {}).get("team"),
        str((game.get("away") or {}).get("team_id")): (game.get("away") or {}).get("team"),
    }
    counters: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    unmatched = 0
    plays = as_plays(payload)
    for play in plays:
        team_id = team_id_for_play(play)
        if team_id not in teams:
            unmatched += 1
            continue
        row = counters[team_id]
        row["plays"] += 1
        if isinstance(play.get("onFloor"), (list, dict)) and play.get("onFloor"):
            row["on_floor_plays"] += 1
        play_type = str(play.get("playType") or play.get("type") or "").lower()
        if "fast break" in play_type or "fastbreak" in play_type or "transition" in play_type:
            row["explicit_transition_plays"] += 1
        shot = play.get("shotInfo") or play.get("shot")
        if not isinstance(shot, dict):
            continue
        row["tracked_shots"] += 1
        zone = shot_zone(shot)
        row[f"{zone}_shots" if zone else "unclassified_shots"] += 1
        made = bool(shot.get("made"))
        if made:
            row["made_shots"] += 1
        if made and bool(shot.get("assisted")):
            row["assisted_shots"] += 1

    team_rows = []
    for team_id, team_name in teams.items():
        row = counters.get(team_id, {})
        shots = int(row.get("tracked_shots", 0))
        plays_count = int(row.get("plays", 0))
        pct = lambda value, total: round(100 * value / total, 2) if total else None
        team_rows.append({
            "team_id": int(team_id) if team_id.isdigit() else team_id,
            "team": team_name,
            "plays": plays_count,
            "tracked_shots": shots,
            "rim_shots": int(row.get("rim_shots", 0)),
            "midrange_shots": int(row.get("midrange_shots", 0)),
            "three_shots": int(row.get("three_shots", 0)),
            "unclassified_shots": int(row.get("unclassified_shots", 0)),
            "made_shots": int(row.get("made_shots", 0)),
            "assisted_shots": int(row.get("assisted_shots", 0)),
            "rim_rate": pct(int(row.get("rim_shots", 0)), shots),
            "midrange_rate": pct(int(row.get("midrange_shots", 0)), shots),
            "three_rate": pct(int(row.get("three_shots", 0)), shots),
            "assisted_rate": pct(int(row.get("assisted_shots", 0)), int(row.get("made_shots", 0))),
            "explicit_transition_plays": int(row.get("explicit_transition_plays", 0)),
            "explicit_transition_rate": pct(int(row.get("explicit_transition_plays", 0)), plays_count),
            "on_floor_coverage_pct": pct(int(row.get("on_floor_plays", 0)), plays_count),
        })
    return {
        "game_id": game.get("game_id"),
        "start_date": game.get("start_date"),
        "teams": team_rows,
        "provider_play_count": len(plays),
        "unmatched_play_count": unmatched,
    }


def rollup(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    sum_fields = (
        "plays", "tracked_shots", "rim_shots", "midrange_shots", "three_shots",
        "unclassified_shots", "made_shots", "assisted_shots", "explicit_transition_plays",
    )
    on_floor_weight: dict[str, float] = defaultdict(float)
    for game in games:
        for team in game.get("teams") or []:
            team_id = str(team.get("team_id"))
            row = totals.setdefault(team_id, {"team_id": team.get("team_id"), "team": team.get("team"), "games": 0, **{key: 0 for key in sum_fields}})
            row["games"] += 1
            for key in sum_fields:
                row[key] += int(team.get(key) or 0)
            if team.get("on_floor_coverage_pct") is not None:
                on_floor_weight[team_id] += float(team["on_floor_coverage_pct"]) * int(team.get("plays") or 0)

    for team_id, row in totals.items():
        shots, plays = row["tracked_shots"], row["plays"]
        pct = lambda value, total: round(100 * value / total, 2) if total else None
        row.update({
            "rim_rate": pct(row["rim_shots"], shots),
            "midrange_rate": pct(row["midrange_shots"], shots),
            "three_rate": pct(row["three_shots"], shots),
            "assisted_rate": pct(row["assisted_shots"], row["made_shots"]),
            "explicit_transition_rate": pct(row["explicit_transition_plays"], plays),
            "on_floor_coverage_pct": round(on_floor_weight[team_id] / plays, 2) if plays else None,
            "sample_state": "tracked" if shots >= 100 else ("developing" if shots >= 25 else "limited"),
        })
    return sorted(totals.values(), key=lambda row: str(row.get("team") or ""))


def build_play_style(
    board: dict[str, Any],
    existing: dict[str, Any] | None,
    fetcher: Callable[[str, dict[str, Any]], Any],
    max_games: int = 40,
) -> dict[str, Any]:
    same_season = (existing or {}).get("meta", {}).get("season") == board.get("meta", {}).get("season")
    stored = {
        str(row.get("game_id")): row
        for row in ((existing or {}).get("games") or []) if same_season and isinstance(row, dict)
    }
    finals = [row for row in board.get("games") or [] if str(row.get("status") or "").lower().replace("_", "") in FINAL_STATUSES]
    pending = [
        row for row in sorted(finals, key=lambda item: str(item.get("start_date") or ""))
        if str(row.get("game_id")) not in stored
    ][:max_games]
    errors = []
    for game in pending:
        game_id = str(game.get("game_id"))
        try:
            stored[game_id] = aggregate_game(game, fetcher(f"/plays/game/{game_id}", {}))
        except RuntimeError as error:
            errors.append({"game_id": game.get("game_id"), "error": str(error)[:180]})
    games = sorted(stored.values(), key=lambda row: (str(row.get("start_date") or ""), str(row.get("game_id") or "")))
    teams = rollup(games)
    return {
        "meta": {
            "version": VERSION,
            "season": board.get("meta", {}).get("season"),
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "games_added": len(pending) - len(errors),
            "game_count": len(games),
            "team_count": len(teams),
            "raw_play_by_play_stored": False,
            "transition_method": "Explicit provider play-type labels only; period clock is never used as a shot-clock proxy.",
            "coverage_policy": "Shot and style metrics display only when provider play metadata identifies a team and supplies the relevant field.",
        },
        "teams": teams,
        "games": games,
        "fetch_errors": errors,
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", type=Path, default=ROOT / "data" / "cbb" / "game_board.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "cbb" / "play_style.json")
    parser.add_argument("--max-games", type=int, default=40)
    args = parser.parse_args()
    api_key = clean_key(os.environ.get("CBBD_API_KEY"))
    if not api_key:
        raise SystemExit("CBBD_API_KEY is required")
    existing = json.loads(args.output.read_text()) if args.output.exists() else None
    payload = build_play_style(json.loads(args.board.read_text()), existing, lambda path, params: fetch_json(path, params, api_key), max(0, args.max_games))
    atomic_write(args.output, payload)
    print(f"{VERSION}: {payload['meta']['game_count']} compact game aggregates, {payload['meta']['games_added']} added")


if __name__ == "__main__":
    main()
