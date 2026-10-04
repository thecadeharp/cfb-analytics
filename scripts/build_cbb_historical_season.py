#!/usr/bin/env python3
"""Build one season of THI-derived CBB historical research features.

CBBD responses remain transient. The persisted gzip contains paired matchup
features, outcomes, market benchmarks, end-of-season ratings, and team-level
continuity summaries. It is not a raw endpoint mirror.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.build_cbb_data_foundation import continuity_by_team
    from scripts.verify_cbb_api_foundation import clean_key, fetch_json
except ModuleNotFoundError:
    from build_cbb_data_foundation import continuity_by_team
    from verify_cbb_api_foundation import clean_key, fetch_json


ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = ROOT / "data" / "cbb" / "history"
SCHEMA_VERSION = "1.0"
BUILDER_VERSION = "cbb-history-v1.1"


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def rounded(value: Any, digits: int = 4) -> float | None:
    number = finite(value)
    return round(number, digits) if number is not None else None


def percent(value: Any) -> float | None:
    number = finite(value)
    if number is None:
        return None
    return round(number * 100 if abs(number) <= 1.5 else number, 4)


def season_windows(season: int) -> list[tuple[str, str]]:
    previous = season - 1
    return [
        (f"{previous}-11-01T00:00:00Z", f"{previous}-11-30T23:59:59Z"),
        (f"{previous}-12-01T00:00:00Z", f"{previous}-12-31T23:59:59Z"),
        (f"{season}-01-01T00:00:00Z", f"{season}-01-31T23:59:59Z"),
        (f"{season}-02-01T00:00:00Z", f"{season}-02-29T23:59:59Z" if season % 4 == 0 else f"{season}-02-28T23:59:59Z"),
        (f"{season}-03-01T00:00:00Z", f"{season}-03-31T23:59:59Z"),
        (f"{season}-04-01T00:00:00Z", f"{season}-05-15T23:59:59Z"),
    ]


def median(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [number for row in rows if (number := finite(row.get(field))) is not None]
    return round(statistics.median(values), 3) if values else None


def market_features(line_record: dict[str, Any] | None) -> dict[str, Any]:
    rows = [row for row in (line_record or {}).get("lines") or [] if isinstance(row, dict)]
    close_spread = median(rows, "spread")
    close_total = median(rows, "overUnder")
    open_spread = median(rows, "spreadOpen")
    open_total = median(rows, "overUnderOpen")
    return {
        "book_count": len(rows),
        "home_spread_close": close_spread,
        "total_close": close_total,
        "home_spread_open": open_spread,
        "total_open": open_total,
        "spread_move": rounded(close_spread - open_spread, 3) if close_spread is not None and open_spread is not None else None,
        "total_move": rounded(close_total - open_total, 3) if close_total is not None and open_total is not None else None,
    }


def unit_features(unit: dict[str, Any]) -> dict[str, Any]:
    factors = unit.get("fourFactors") or {}
    points = unit.get("points") or {}
    return {
        "points": rounded(points.get("total"), 1),
        "possessions": rounded(unit.get("possessions"), 2),
        "efficiency": rounded(unit.get("rating"), 3),
        "true_shooting_pct": percent(unit.get("trueShooting")),
        "effective_fg_pct": percent(factors.get("effectiveFieldGoalPct")),
        "turnover_pct": percent(factors.get("turnoverRatio")),
        "offensive_rebound_pct": percent(factors.get("offensiveReboundPct")),
        "free_throw_rate": percent(factors.get("freeThrowRate")),
    }


def paired_game(row: dict[str, Any], line_record: dict[str, Any] | None) -> dict[str, Any] | None:
    if row.get("isHome") is not True:
        return None
    home = unit_features(row.get("teamStats") or {})
    away = unit_features(row.get("opponentStats") or {})
    home_points = finite(home.get("points"))
    away_points = finite(away.get("points"))
    if home_points is None or away_points is None:
        return None
    # CBBD can retain canceled/postponed matchups as zeroed team-game rows.
    # A played Division I game must have a plausible score and possession sample.
    if home_points < 20 or away_points < 20 or home_points + away_points < 40:
        return None
    possessions = finite(row.get("pace"))
    if possessions is None:
        samples = [value for value in (finite(home.get("possessions")), finite(away.get("possessions"))) if value is not None]
        possessions = statistics.mean(samples) if samples else None
    if possessions is None or possessions < 30:
        return None
    return {
        "game_id": row.get("gameId"),
        "start_date": row.get("startDate"),
        "season_type": row.get("seasonType"),
        "conference_game": bool(row.get("conferenceGame")),
        "neutral_site": bool(row.get("neutralSite")),
        "home_team_id": row.get("teamId"),
        "home_team": row.get("team"),
        "away_team_id": row.get("opponentId"),
        "away_team": row.get("opponent"),
        "pace": rounded(possessions, 2),
        "home": home,
        "away": away,
        "outcome": {
            "home_points": rounded(home_points, 1),
            "away_points": rounded(away_points, 1),
            "home_margin": rounded(home_points - away_points, 1),
            "total_points": rounded(home_points + away_points, 1),
        },
        "market": market_features(line_record),
    }


def season_end_team_rows(
    directory: dict[str, Any],
    leaderboard: list[dict[str, Any]],
    continuity: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    names = {str(row.get("id")): row.get("school") for row in directory.get("teams") or [] if isinstance(row, dict)}
    rows = []
    for record in leaderboard:
        if not isinstance(record, dict):
            continue
        team_id = str(record.get("teamId"))
        adjusted = record.get("adjustedEfficiency") or {}
        rankings = adjusted.get("rankings") or {}
        rows.append({
            "team_id": record.get("teamId"),
            "team": record.get("team") or names.get(team_id),
            "games": int((record.get("record") or {}).get("games") or 0),
            "adjusted_offense": rounded(adjusted.get("offensiveRating"), 3),
            "adjusted_defense": rounded(adjusted.get("defensiveRating"), 3),
            "adjusted_net": rounded(adjusted.get("netRating"), 3),
            "adjusted_net_rank": rankings.get("net"),
            "pace": rounded((record.get("summary") or {}).get("pace"), 3),
            "continuity_from_prior": continuity.get(team_id) or {},
        })
    rows.sort(key=lambda row: (str(row.get("team") or ""), str(row.get("team_id") or "")))
    return rows


def build_season(
    season: int,
    fetcher: Callable[[str, dict[str, Any]], Any],
) -> dict[str, Any]:
    directory = fetcher("/teams/directory", {"season": season})
    leaderboard = fetcher("/stats/team/leaderboard", {"season": season})
    rosters = fetcher("/teams/roster", {"season": season})
    prior_players = fetcher("/stats/player/season", {"season": season - 1})
    if not isinstance(directory, dict) or not isinstance(directory.get("teams"), list):
        raise RuntimeError("invalid team directory response")
    for name, payload in (("leaderboard", leaderboard), ("rosters", rosters), ("prior players", prior_players)):
        if not isinstance(payload, list):
            raise RuntimeError(f"invalid {name} response")
    if len(directory["teams"]) < 300 or len(leaderboard) < 300:
        raise RuntimeError(f"season {season} does not have full Division I coverage")

    game_rows: dict[str, dict[str, Any]] = {}
    line_rows: dict[str, dict[str, Any]] = {}
    for start_date, end_date in season_windows(season):
        params = {"startDateRange": start_date, "endDateRange": end_date}
        box = fetcher("/games/teams", params)
        lines = fetcher("/lines", params)
        if not isinstance(box, list) or not isinstance(lines, list):
            raise RuntimeError(f"season {season} monthly endpoint returned an invalid response")
        for row in box:
            if isinstance(row, dict) and row.get("gameId") is not None and row.get("isHome") is True:
                game_rows[str(row.get("gameId"))] = row
        for row in lines:
            if isinstance(row, dict) and row.get("gameId") is not None:
                line_rows[str(row.get("gameId"))] = row

    games = []
    for game_id, row in game_rows.items():
        paired = paired_game(row, line_rows.get(game_id))
        if paired:
            games.append(paired)
    games.sort(key=lambda row: (str(row.get("start_date") or ""), str(row.get("game_id") or "")))
    if len(games) < 3000:
        raise RuntimeError(f"season {season} produced only {len(games)} completed games")

    continuity = continuity_by_team(rosters, prior_players)
    team_rows = season_end_team_rows(directory, leaderboard, continuity)
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "builder_version": BUILDER_VERSION,
            "season": season,
            "generated_at_utc": generated,
            "request_count": 16,
            "game_count": len(games),
            "team_count": len(team_rows),
            "games_with_market": sum(row["market"]["book_count"] > 0 for row in games),
            "raw_api_data_stored": False,
            "feature_timing": "postgame_realized_features; walk_forward_pregame_features_not_yet_built",
            "source_attribution": "Data provided by CollegeBasketballData.com; feature engineering by The Hammer Index.",
        },
        "season_end_teams": team_rows,
        "games": games,
    }


def atomic_gzip_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n").encode()
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            zipped.write(encoded)
    temporary.replace(path)


def rebuild_manifest(output_dir: Path) -> dict[str, Any]:
    seasons = []
    for path in sorted(output_dir.glob("season_*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        seasons.append({
            "season": payload["meta"]["season"],
            "file": path.name,
            "game_count": payload["meta"]["game_count"],
            "team_count": payload["meta"]["team_count"],
            "games_with_market": payload["meta"]["games_with_market"],
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        })
    manifest = {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "builder_version": BUILDER_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "season_count": len(seasons),
            "game_count": sum(row["game_count"] for row in seasons),
        },
        "seasons": seasons,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "manifest.json"
    with tempfile.NamedTemporaryFile("w", dir=output_dir, delete=False, encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(target)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, default=HISTORY_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = clean_key(os.environ.get("CBBD_API_KEY"))
    if not api_key:
        raise SystemExit("CBBD_API_KEY is required")
    payload = build_season(args.season, lambda path, params: fetch_json(path, params, api_key))
    target = args.output_dir / f"season_{args.season}.json.gz"
    atomic_gzip_json(target, payload)
    manifest = rebuild_manifest(args.output_dir)
    print(
        f"CBB history {args.season}: {payload['meta']['game_count']} games, "
        f"{payload['meta']['team_count']} teams, {payload['meta']['games_with_market']} market games; "
        f"manifest now has {manifest['meta']['season_count']} seasons"
    )


if __name__ == "__main__":
    main()
