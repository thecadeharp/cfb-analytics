#!/usr/bin/env python3
"""Build compact CBB postgame box scores and advanced metrics for the public UI."""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.cbb_game_flow import game_flow
    from scripts.verify_cbb_api_foundation import clean_key, fetch_json
except ModuleNotFoundError:
    from cbb_game_flow import game_flow
    from verify_cbb_api_foundation import clean_key, fetch_json


ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-postgame-v2.0"


def finite(value: Any, digits: int = 2) -> float | None:
    try:
        parsed = float(value)
        return round(parsed, digits) if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def pct(value: Any) -> float | None:
    parsed = finite(value, 4)
    if parsed is None:
        return None
    return round(parsed * 100 if abs(parsed) <= 1.5 else parsed, 1)


def shooting(row: dict[str, Any], key: str) -> dict[str, Any]:
    value = row.get(key) or {}
    return {
        "made": finite(value.get("made"), 0),
        "attempted": finite(value.get("attempted"), 0),
        "pct": pct(value.get("pct")),
    }


def team_stats(row: dict[str, Any]) -> dict[str, Any]:
    stats = row.get("teamStats") or {}
    factors = stats.get("fourFactors") or {}
    rebounds = stats.get("rebounds") or {}
    points = stats.get("points") or {}
    turnovers = stats.get("turnovers") or {}
    return {
        "points": finite(points.get("total"), 0),
        "field_goals": shooting(stats, "fieldGoals"),
        "three_point_field_goals": shooting(stats, "threePointFieldGoals"),
        "free_throws": shooting(stats, "freeThrows"),
        "rebounds": finite(rebounds.get("total"), 0),
        "offensive_rebounds": finite(rebounds.get("offensive"), 0),
        "assists": finite(stats.get("assists"), 0),
        "turnovers": finite(turnovers.get("total"), 0),
        "steals": finite(stats.get("steals"), 0),
        "blocks": finite(stats.get("blocks"), 0),
        "points_in_paint": finite(points.get("inPaint"), 0),
        "points_off_turnovers": finite(points.get("offTurnovers"), 0),
        "fast_break_points": finite(points.get("fastBreak"), 0),
        "largest_lead": finite(points.get("largestLead"), 0),
        "possessions": finite(stats.get("possessions")),
        "offensive_rating": finite(stats.get("rating"), 1),
        "true_shooting_pct": pct(stats.get("trueShooting")),
        "effective_fg_pct": pct(factors.get("effectiveFieldGoalPct")),
        "turnover_pct": pct(factors.get("turnoverRatio")),
        "offensive_rebound_pct": pct(factors.get("offensiveReboundPct")),
        "free_throw_rate": pct(factors.get("freeThrowRate")),
        "game_score": finite(stats.get("gameScore"), 1),
    }


def player_stats(row: dict[str, Any]) -> dict[str, Any]:
    rebounds = row.get("rebounds") or {}
    return {
        "athlete_id": row.get("athleteId"),
        "name": row.get("name") or "Unknown player",
        "position": row.get("position"),
        "starter": bool(row.get("starter")),
        "minutes": finite(row.get("minutes"), 1),
        "points": finite(row.get("points"), 0),
        "rebounds": finite(rebounds.get("total"), 0),
        "assists": finite(row.get("assists"), 0),
        "steals": finite(row.get("steals"), 0),
        "blocks": finite(row.get("blocks"), 0),
        "turnovers": finite(row.get("turnovers"), 0),
        "fouls": finite(row.get("fouls"), 0),
        "field_goals": shooting(row, "fieldGoals"),
        "three_point_field_goals": shooting(row, "threePointFieldGoals"),
        "free_throws": shooting(row, "freeThrows"),
        "usage_pct": pct(row.get("usage")),
        "true_shooting_pct": pct(row.get("trueShootingPct")),
        "effective_fg_pct": pct(row.get("effectiveFieldGoalPct")),
        "offensive_rating": finite(row.get("offensiveRating"), 1),
        "defensive_rating": finite(row.get("defensiveRating"), 1),
        "net_rating": finite(row.get("netRating"), 1),
        "game_score": finite(row.get("gameScore"), 1),
    }


def rotation_summary(side: dict[str, Any] | None) -> dict[str, Any]:
    players = (side or {}).get("players") or []
    starters = [row for row in players if row.get("starter")]
    bench = [row for row in players if not row.get("starter")]
    total = lambda rows, key: round(sum(float(row.get(key) or 0) for row in rows), 1)
    return {
        "starter_points": total(starters, "points"), "bench_points": total(bench, "points"),
        "starter_minutes": total(starters, "minutes"), "bench_minutes": total(bench, "minutes"),
        "heavy_minutes": [{"player": row["name"], "minutes": row["minutes"]} for row in players if float(row.get("minutes") or 0) >= 34],
        "foul_outs": [{"player": row["name"], "fouls": row["fouls"]} for row in players if float(row.get("fouls") or 0) >= 5],
    }


def build_payload(board: dict[str, Any], team_rows: list[dict[str, Any]], player_rows: list[dict[str, Any]], flow_by_game: dict[str, Any] | None = None) -> dict[str, Any]:
    finals = {str(game.get("game_id")): game for game in board.get("games", []) if str(game.get("status", "")).lower() == "final"}
    teams: dict[str, dict[str, Any]] = {}
    players: dict[str, dict[str, Any]] = {}
    for row in team_rows:
        game_id = str(row.get("gameId"))
        if game_id in finals and isinstance(row, dict):
            teams.setdefault(game_id, {})["home" if row.get("isHome") else "away"] = {
                "team_id": row.get("teamId"), "team": row.get("team"), "pace": finite(row.get("pace")), "stats": team_stats(row)
            }
    for row in player_rows:
        game_id = str(row.get("gameId"))
        if game_id in finals and isinstance(row, dict):
            roster = [player_stats(player) for player in row.get("players", []) if isinstance(player, dict)]
            roster.sort(key=lambda player: (not player["starter"], -(player["minutes"] or 0), player["name"]))
            players.setdefault(game_id, {})["home" if row.get("isHome") else "away"] = {
                "team_id": row.get("teamId"), "team": row.get("team"), "players": roster
            }
    games = {}
    for game_id, game in finals.items():
        games[game_id] = {
            "game_id": game.get("game_id"), "start_date": game.get("start_date"),
            "away_team": game.get("away", {}).get("team"), "home_team": game.get("home", {}).get("team"),
            "pace": (teams.get(game_id, {}).get("home") or {}).get("pace"),
            "teams": teams.get(game_id, {}), "players": players.get(game_id, {}),
            "rotation_summary": {side: rotation_summary(players.get(game_id, {}).get(side)) for side in ("away", "home")},
            "game_flow": (flow_by_game or {}).get(game_id),
        }
    complete = sum(bool(row.get("teams", {}).get("home") and row.get("teams", {}).get("away") and row.get("players", {}).get("home") and row.get("players", {}).get("away")) for row in games.values())
    return {
        "meta": {
            "version": VERSION, "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "season": board.get("meta", {}).get("season"), "final_game_count": len(games), "complete_box_score_count": complete,
            "model_usage": "display_only_postgame; never used by the predictive model",
            "source_attribution": "Box score data provided by CollegeBasketballData.com; presentation by The Hammer Index.",
        },
        "games": games,
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
    parser.add_argument("--board", type=Path, default=ROOT / "data/cbb/projection_board.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/cbb/postgame.json")
    parser.add_argument("--lookback-days", type=int, default=14)
    args = parser.parse_args()
    key = clean_key(os.environ.get("CBBD_API_KEY"))
    if not key:
        raise SystemExit("CBBD_API_KEY is required")
    board = json.loads(args.board.read_text())
    now = datetime.now(timezone.utc)
    finals = [game for game in board.get("games", []) if str(game.get("status", "")).lower() == "final"]
    starts = []
    for game in finals:
        try:
            starts.append(datetime.fromisoformat(str(game.get("start_date")).replace("Z", "+00:00")))
        except (TypeError, ValueError):
            pass
    start = min(starts) - timedelta(hours=6) if starts else now - timedelta(days=args.lookback_days)
    start = max(start, now - timedelta(days=max(1, args.lookback_days)))
    params = {"startDateRange": start.isoformat().replace("+00:00", "Z"), "endDateRange": (now + timedelta(hours=6)).isoformat().replace("+00:00", "Z")}
    team_rows = fetch_json("/games/teams", params, key)
    player_rows = fetch_json("/games/players", params, key)
    if not isinstance(team_rows, list) or not isinstance(player_rows, list):
        raise RuntimeError("CBBD postgame endpoints returned an invalid response")
    profiles_path = ROOT / "data/cbb/team_profiles.json"
    profiles = json.loads(profiles_path.read_text()) if profiles_path.exists() else None
    flows = {}
    for game in finals:
        game_id = str(game.get("game_id"))
        try:
            game_start = datetime.fromisoformat(str(game.get("start_date")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            game_start = now
        if game_start < start:
            continue
        try:
            flows[game_id] = game_flow(game, fetch_json(f"/plays/game/{game_id}", {}, key), profiles)
        except RuntimeError:
            continue
    payload = build_payload(board, team_rows, player_rows, flows)
    atomic_write(args.output, payload)
    print(f"{VERSION}: {payload['meta']['complete_box_score_count']}/{payload['meta']['final_game_count']} completed box scores")


if __name__ == "__main__":
    main()
