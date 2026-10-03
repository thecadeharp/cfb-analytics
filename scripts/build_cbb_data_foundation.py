#!/usr/bin/env python3
"""Build THI's public CBB foundation from transient CBBD responses.

Only compact THI summaries and derived metrics are written. Raw API responses
remain in memory and are never committed. College Football and Model A paths
are neither read nor written by this module.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.verify_cbb_api_foundation import clean_key, fetch_json
except ModuleNotFoundError:  # Direct execution: python scripts/build_cbb_data_foundation.py
    from verify_cbb_api_foundation import clean_key, fetch_json


ROOT = Path(__file__).resolve().parents[1]
CBB_DIR = ROOT / "data" / "cbb"


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def rounded(value: Any, digits: int = 2) -> float | None:
    number = finite(value)
    return round(number, digits) if number is not None else None


def percent(value: Any) -> float | None:
    number = finite(value)
    if number is None:
        return None
    return round(number * 100 if abs(number) <= 1.5 else number, 2)


def difference(left: Any, right: Any) -> float | None:
    a, b = percent(left), percent(right)
    return round(a - b, 2) if a is not None and b is not None else None


def nested(row: dict[str, Any], *keys: str) -> Any:
    value: Any = row
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def median(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [number for row in rows if (number := finite(row.get(field))) is not None]
    return round(statistics.median(values), 2) if values else None


def market_summary(lines: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not lines:
        return None
    spread = median(lines, "spread")
    total = median(lines, "overUnder")
    open_spread = median(lines, "spreadOpen")
    open_total = median(lines, "overUnderOpen")
    return {
        "book_count": len(lines),
        "consensus_home_spread": spread,
        "consensus_total": total,
        "opening_home_spread": open_spread,
        "opening_total": open_total,
        "spread_move": rounded(spread - open_spread, 2) if spread is not None and open_spread is not None else None,
        "total_move": rounded(total - open_total, 2) if total is not None and open_total is not None else None,
    }


def team_profile(directory: dict[str, Any], stats: dict[str, Any] | None) -> dict[str, Any]:
    stats = stats or {}
    team_stats = stats.get("teamStats") or {}
    opponent_stats = stats.get("opponentStats") or {}
    factors = team_stats.get("fourFactors") or {}
    opponent_factors = opponent_stats.get("fourFactors") or {}
    shot_profile = stats.get("shotProfile") or {}
    record = stats.get("record") or {}
    summary = stats.get("summary") or {}
    offense = rounded(team_stats.get("rawOffensiveRating"))
    defense = rounded(opponent_stats.get("rawOffensiveRating"))
    if offense is None:
        offense = rounded(team_stats.get("rating"))
    if defense is None:
        defense = rounded(opponent_stats.get("rating"))
    return {
        "team_id": directory.get("id"),
        "team": directory.get("school"),
        "display_name": directory.get("displayName") or directory.get("school"),
        "abbreviation": directory.get("abbreviation"),
        "conference_id": directory.get("conferenceId"),
        "record": {
            "games": int(record.get("games") or stats.get("games") or 0),
            "wins": int(record.get("wins") or stats.get("wins") or 0),
            "losses": int(record.get("losses") or stats.get("losses") or 0),
        },
        "efficiency": {
            "raw_offense_per_100": offense,
            "raw_defense_per_100": defense,
            "raw_net_per_100": rounded(offense - defense) if offense is not None and defense is not None else None,
            "pace_per_40": rounded(summary.get("pace", stats.get("pace"))),
            "true_shooting_pct": percent(team_stats.get("trueShootingPct", team_stats.get("trueShooting"))),
        },
        "four_factor_edges": {
            "effective_fg_pct": difference(factors.get("effectiveFieldGoalPct"), opponent_factors.get("effectiveFieldGoalPct")),
            "turnover_pct": difference(opponent_factors.get("turnoverRatio"), factors.get("turnoverRatio")),
            "offensive_rebound_pct": difference(factors.get("offensiveReboundPct"), opponent_factors.get("offensiveReboundPct")),
            "free_throw_rate": difference(factors.get("freeThrowRate"), opponent_factors.get("freeThrowRate")),
        },
        "shot_profile": {
            "tracked_shots": int(summary.get("trackedShots") or stats.get("trackedShots") or 0),
            "at_rim_rate": percent(nested(shot_profile, "atRim", "rate")),
            "three_point_rate": percent(nested(shot_profile, "distribution", "threeRate")),
            "midrange_rate": percent(nested(shot_profile, "distribution", "midrangeRate")),
            "assisted_pct": percent(shot_profile.get("assistedPct")),
        },
        "sample_ready": int(record.get("games") or stats.get("games") or 0) >= 3,
    }


def build_outputs(
    season: int,
    start_date: str,
    end_date: str,
    fetcher: Callable[[str, dict[str, Any]], Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    directory = fetcher("/teams/directory", {"season": season})
    leaderboard = fetcher("/stats/team/leaderboard", {"season": season})
    games = fetcher("/games", {"startDateRange": start_date, "endDateRange": end_date})
    media = fetcher("/games/media", {"startDateRange": start_date, "endDateRange": end_date})
    lines = fetcher("/lines", {"startDateRange": start_date, "endDateRange": end_date})

    if not isinstance(directory, dict) or not isinstance(directory.get("teams"), list):
        raise RuntimeError("CBBD team directory response is invalid")
    for name, payload in (("leaderboard", leaderboard), ("games", games), ("media", media), ("lines", lines)):
        if not isinstance(payload, list):
            raise RuntimeError(f"CBBD {name} response is not a list")

    stats_by_id = {str(row.get("teamId")): row for row in leaderboard if isinstance(row, dict)}
    teams = [team_profile(row, stats_by_id.get(str(row.get("id")))) for row in directory["teams"]]
    teams.sort(key=lambda row: str(row.get("team") or ""))

    media_by_game = {str(row.get("gameId")): row for row in media if isinstance(row, dict)}
    lines_by_game = {str(row.get("gameId")): row for row in lines if isinstance(row, dict)}
    board = []
    for game in games:
        if not isinstance(game, dict):
            continue
        game_id = str(game.get("id"))
        media_row = media_by_game.get(game_id) or {}
        line_row = lines_by_game.get(game_id) or {}
        broadcasts = sorted({
            str(item.get("broadcastName") or "").strip()
            for item in media_row.get("broadcasts") or []
            if isinstance(item, dict) and str(item.get("broadcastName") or "").strip()
        })
        board.append({
            "game_id": game.get("id"),
            "start_date": game.get("startDate"),
            "status": game.get("status"),
            "start_time_tbd": bool(game.get("startTimeTbd")),
            "neutral_site": bool(game.get("neutralSite")),
            "conference_game": bool(game.get("conferenceGame")),
            "home": {"team_id": game.get("homeTeamId"), "team": game.get("homeTeam"), "conference": game.get("homeConference"), "score": game.get("homePoints")},
            "away": {"team_id": game.get("awayTeamId"), "team": game.get("awayTeam"), "conference": game.get("awayConference"), "score": game.get("awayPoints")},
            "venue": {"name": game.get("venue"), "city": game.get("city"), "state": game.get("state")},
            "broadcasts": broadcasts,
            "market": market_summary([row for row in line_row.get("lines") or [] if isinstance(row, dict)]),
        })
    board.sort(key=lambda row: (str(row.get("start_date") or ""), str(row.get("game_id") or "")))

    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    team_payload = {
        "meta": {
            "schema_version": "1.0",
            "season": season,
            "generated_at_utc": generated,
            "team_count": len(teams),
            "rated_sample_count": sum(bool(row["sample_ready"]) for row in teams),
            "methodology": "THI-derived raw efficiency and Four Factor edges. These are foundation diagnostics, not opponent-adjusted THI ratings or projections.",
            "model_usage": "cbb_research_foundation_only",
        },
        "teams": teams,
    }
    board_payload = {
        "meta": {
            "schema_version": "1.0",
            "season": season,
            "generated_at_utc": generated,
            "start_date": start_date,
            "end_date": end_date,
            "game_count": len(board),
            "market_method": "Median available book line; movement is current minus opening.",
            "projection_status": "not_built_no_thi_spread_or_total",
        },
        "games": board,
    }
    status_payload = {
        "meta": {
            "schema_version": "1.0",
            "season": season,
            "generated_at_utc": generated,
            "request_count": 5,
            "raw_api_data_stored": False,
            "cfb_or_model_a_files_accessed": False,
        },
        "coverage": {
            "directory_teams": len(directory["teams"]),
            "leaderboard_teams": len(leaderboard),
            "window_games": len(games),
            "games_with_broadcasts": sum(bool(row["broadcasts"]) for row in board),
            "games_with_market": sum(row["market"] is not None for row in board),
        },
    }
    return team_payload, board_payload, status_payload


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    today = datetime.now(timezone.utc).date()
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=int(os.environ.get("CBB_SEASON", "2027")))
    parser.add_argument("--start-date", default=(today - timedelta(days=2)).isoformat() + "T00:00:00Z")
    parser.add_argument("--end-date", default=(today + timedelta(days=45)).isoformat() + "T23:59:59Z")
    parser.add_argument("--output-dir", type=Path, default=CBB_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = clean_key(os.environ.get("CBBD_API_KEY"))
    if not api_key:
        raise SystemExit("CBBD_API_KEY is required; add it as a GitHub Actions secret")
    outputs = build_outputs(
        args.season,
        args.start_date,
        args.end_date,
        lambda path, params: fetch_json(path, params, api_key),
    )
    for name, payload in zip(("team_profiles.json", "game_board.json", "foundation_status.json"), outputs):
        atomic_write(args.output_dir / name, payload)
    print(
        f"CBB foundation: {outputs[0]['meta']['team_count']} teams, "
        f"{outputs[1]['meta']['game_count']} games, 5 API requests"
    )


if __name__ == "__main__":
    main()
