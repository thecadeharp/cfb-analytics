#!/usr/bin/env python3
"""Build THI-derived CBB foundation data from transient CBBD responses.

Provider responses stay in memory. Public files contain compact transformed
features for THI research, never raw endpoint mirrors or player-level exports.
College Football and Model A paths are neither read nor written.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.verify_cbb_api_foundation import clean_key, fetch_json
except ModuleNotFoundError:
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
    provider_priority = {
        "pinnacle": 0,
        "circa sports": 1,
        "betonline": 2,
        "bookmaker": 3,
    }
    priced = [
        row for row in lines
        if (home_price := finite(row.get("homeMoneyline"))) is not None
        and (away_price := finite(row.get("awayMoneyline"))) is not None
        and abs(home_price) >= 100
        and abs(away_price) >= 100
    ]
    reference_moneyline = None
    if priced:
        row = min(
            priced,
            key=lambda item: (
                provider_priority.get(str(item.get("provider") or "").strip().lower(), 100),
                str(item.get("provider") or ""),
            ),
        )
        reference_moneyline = {
            "provider": row.get("provider"),
            "home_price": int(finite(row.get("homeMoneyline"))),
            "away_price": int(finite(row.get("awayMoneyline"))),
            "price_format": "american",
            "validation_scope": "moneyline_only",
        }
        home = finite(row.get("homeMoneyline"))
        away = finite(row.get("awayMoneyline"))
        home_implied = abs(home) / (abs(home) + 100) if home < 0 else 100 / (home + 100)
        away_implied = abs(away) / (abs(away) + 100) if away < 0 else 100 / (away + 100)
        total_implied = home_implied + away_implied
        reference_moneyline["implied_probability"] = {"home": round(home_implied, 8), "away": round(away_implied, 8)}
        reference_moneyline["no_vig_probability"] = {"home": round(home_implied / total_implied, 8), "away": round(away_implied / total_implied, 8)}
        reference_moneyline["overround"] = round(total_implied - 1, 8)
    return {
        "book_count": len(lines),
        "consensus_home_spread": spread,
        "consensus_total": total,
        "opening_home_spread": open_spread,
        "opening_total": open_total,
        "spread_move": rounded(spread - open_spread) if spread is not None and open_spread is not None else None,
        "total_move": rounded(total - open_total) if total is not None and open_total is not None else None,
        "reference_moneyline": reference_moneyline,
        "spread_price_status": "unavailable_from_provider_contract",
    }


def adjusted(stats: dict[str, Any]) -> dict[str, Any]:
    values = stats.get("adjustedEfficiency") or {}
    ranks = values.get("rankings") or {}
    return {
        "offense": rounded(values.get("offensiveRating")),
        "defense": rounded(values.get("defensiveRating")),
        "net": rounded(values.get("netRating")),
        "offense_rank": ranks.get("offense"),
        "defense_rank": ranks.get("defense"),
        "net_rank": ranks.get("net"),
    }


def four_factor_profile(stats: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    team = stats.get("teamStats") or {}
    opponent = stats.get("opponentStats") or {}

    def unit(block: dict[str, Any]) -> dict[str, float | None]:
        return {
            "effective_fg_pct": percent(block.get("effectiveFieldGoalPct")),
            "turnover_pct": percent(block.get("turnoverRatio")),
            "offensive_rebound_pct": percent(block.get("offensiveReboundPct")),
            "free_throw_rate": percent(block.get("freeThrowRate")),
        }

    return {"offense": unit(team), "defense": unit(opponent)}


def shot_profile_summary(stats: dict[str, Any]) -> dict[str, Any]:
    shot_profile = stats.get("shotProfile") or {}
    summary = stats.get("summary") or {}
    return {
        "tracked_shots": int(summary.get("trackedShots") or 0),
        "at_rim_rate": percent((shot_profile.get("atRim") or {}).get("rate")),
        "three_point_rate": percent((shot_profile.get("distribution") or {}).get("threeRate")),
        "midrange_rate": percent((shot_profile.get("distribution") or {}).get("midrangeRate")),
        "assisted_pct": percent(shot_profile.get("assistedPct")),
    }


def continuity_by_team(
    rosters: list[dict[str, Any]],
    prior_players: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    current_ids: dict[str, set[str]] = defaultdict(set)
    for roster in rosters:
        team_id = str(roster.get("teamId"))
        for player in roster.get("players") or []:
            athlete_id = player.get("id")
            if athlete_id is not None:
                current_ids[team_id].add(str(athlete_id))

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for player in prior_players:
        if isinstance(player, dict):
            grouped[str(player.get("teamId"))].append(player)

    output: dict[str, dict[str, Any]] = {}
    for team_id, players in grouped.items():
        roster_ids = current_ids.get(team_id, set())
        total_minutes = sum(finite(row.get("minutes")) or 0 for row in players)
        total_points = sum(finite(row.get("points")) or 0 for row in players)
        total_usage_mass = sum(
            (finite(row.get("usage")) or 0) * (finite(row.get("minutes")) or 0)
            for row in players
        )
        returning = [row for row in players if str(row.get("athleteId")) in roster_ids]
        returning_minutes = sum(finite(row.get("minutes")) or 0 for row in returning)
        returning_points = sum(finite(row.get("points")) or 0 for row in returning)
        returning_usage_mass = sum(
            (finite(row.get("usage")) or 0) * (finite(row.get("minutes")) or 0)
            for row in returning
        )
        output[team_id] = {
            "returning_player_count": len(returning),
            "prior_rotation_count": sum((finite(row.get("minutes")) or 0) >= 100 for row in players),
            "returning_minutes_pct": rounded(100 * returning_minutes / total_minutes) if total_minutes else None,
            "returning_points_pct": rounded(100 * returning_points / total_points) if total_points else None,
            "returning_usage_mass_pct": rounded(100 * returning_usage_mass / total_usage_mass) if total_usage_mass else None,
        }
    return output


def team_profile(
    directory: dict[str, Any],
    conference: dict[str, Any] | None,
    current: dict[str, Any] | None,
    prior: dict[str, Any] | None,
    continuity: dict[str, Any] | None,
    benchmark_season: int,
) -> dict[str, Any]:
    current = current or {}
    prior = prior or {}
    continuity = continuity or {}
    record = current.get("record") or {}
    team_stats = current.get("teamStats") or {}
    opponent_stats = current.get("opponentStats") or {}
    summary = current.get("summary") or {}
    games = int(record.get("games") or 0)
    current_adjusted = adjusted(current)
    prior_adjusted = adjusted(prior)
    espn_id = directory.get("sourceId") or directory.get("source_id")
    return {
        "team_id": directory.get("id"),
        "espn_id": str(espn_id) if espn_id is not None else None,
        "logo_url": f"https://a.espncdn.com/i/teamlogos/ncaa/500/{espn_id}.png" if espn_id is not None else None,
        "team": directory.get("school"),
        "display_name": directory.get("displayName") or directory.get("school"),
        "abbreviation": directory.get("abbreviation"),
        "conference": {
            "id": directory.get("conferenceId"),
            "name": (conference or {}).get("name"),
            "abbreviation": (conference or {}).get("abbreviation"),
        },
        "record": {
            "games": games,
            "wins": int(record.get("wins") or 0),
            "losses": int(record.get("losses") or 0),
        },
        "rating_state": "current_adjusted" if games >= 3 and current_adjusted["net"] is not None else "preseason_prior",
        "current_efficiency": {
            "adjusted": current_adjusted,
            "raw_offense_per_100": rounded(team_stats.get("rawOffensiveRating")),
            "raw_defense_per_100": rounded(opponent_stats.get("rawOffensiveRating")),
            "raw_net_per_100": rounded(summary.get("rawNetRating")),
            "pace_per_40": rounded(summary.get("pace")),
            "true_shooting_pct": percent(team_stats.get("trueShootingPct")),
        },
        "four_factor_edges": {
            "effective_fg_pct": difference(team_stats.get("effectiveFieldGoalPct"), opponent_stats.get("effectiveFieldGoalPct")),
            "turnover_pct": difference(opponent_stats.get("turnoverRatio"), team_stats.get("turnoverRatio")),
            "offensive_rebound_pct": difference(team_stats.get("offensiveReboundPct"), opponent_stats.get("offensiveReboundPct")),
            "free_throw_rate": difference(team_stats.get("freeThrowRate"), opponent_stats.get("freeThrowRate")),
        },
        "four_factors": four_factor_profile(current),
        "shot_profile": shot_profile_summary(current),
        "preseason_prior": {
            "source_season": benchmark_season,
            "adjusted": prior_adjusted,
            "four_factors": four_factor_profile(prior),
            "shot_profile": shot_profile_summary(prior),
            **continuity,
        },
        "sample_ready": games >= 3,
    }


def build_outputs(
    season: int,
    benchmark_season: int,
    start_date: str,
    end_date: str,
    fetcher: Callable[[str, dict[str, Any]], Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    directory = fetcher("/teams/directory", {"season": season})
    current_leaderboard = fetcher("/stats/team/leaderboard", {"season": season})
    prior_leaderboard = fetcher("/stats/team/leaderboard", {"season": benchmark_season})
    rosters = fetcher("/teams/roster", {"season": season})
    prior_players = fetcher("/stats/player/season", {"season": benchmark_season})
    games = fetcher("/games", {"startDateRange": start_date, "endDateRange": end_date})
    media = fetcher("/games/media", {"startDateRange": start_date, "endDateRange": end_date})
    lines = fetcher("/lines", {"startDateRange": start_date, "endDateRange": end_date})

    if not isinstance(directory, dict) or not isinstance(directory.get("teams"), list):
        raise RuntimeError("CBBD team directory response is invalid")
    for name, payload in (
        ("current leaderboard", current_leaderboard), ("prior leaderboard", prior_leaderboard),
        ("rosters", rosters), ("prior players", prior_players), ("games", games),
        ("media", media), ("lines", lines),
    ):
        if not isinstance(payload, list):
            raise RuntimeError(f"CBBD {name} response is not a list")
    if len(directory["teams"]) < 300 or len(prior_leaderboard) < 300:
        raise RuntimeError("CBBD foundation coverage is incomplete")

    conferences = {str(row.get("id")): row for row in directory.get("conferences") or [] if isinstance(row, dict)}
    current_by_id = {str(row.get("teamId")): row for row in current_leaderboard if isinstance(row, dict)}
    prior_by_id = {str(row.get("teamId")): row for row in prior_leaderboard if isinstance(row, dict)}
    continuity = continuity_by_team(rosters, prior_players)
    teams = [
        team_profile(
            row,
            conferences.get(str(row.get("conferenceId"))),
            current_by_id.get(str(row.get("id"))),
            prior_by_id.get(str(row.get("id"))),
            continuity.get(str(row.get("id"))),
            benchmark_season,
        )
        for row in directory["teams"] if isinstance(row, dict)
    ]
    teams.sort(key=lambda row: str(row.get("team") or ""))

    media_by_game = {str(row.get("gameId")): row for row in media if isinstance(row, dict)}
    lines_by_game = {str(row.get("gameId")): row for row in lines if isinstance(row, dict)}
    board = []
    for game in games:
        if not isinstance(game, dict):
            continue
        game_id = str(game.get("id"))
        broadcasts = sorted({
            str(item.get("broadcastName") or "").strip()
            for item in (media_by_game.get(game_id) or {}).get("broadcasts") or []
            if isinstance(item, dict) and str(item.get("broadcastName") or "").strip()
        })
        line_rows = [row for row in (lines_by_game.get(game_id) or {}).get("lines") or [] if isinstance(row, dict)]
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
            "market": market_summary(line_rows),
        })
    board.sort(key=lambda row: (str(row.get("start_date") or ""), str(row.get("game_id") or "")))

    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    team_payload = {
        "meta": {
            "schema_version": "2.0", "season": season, "benchmark_season": benchmark_season,
            "generated_at_utc": generated, "team_count": len(teams),
            "rated_sample_count": sum(bool(row["sample_ready"]) for row in teams),
            "methodology": "THI-transformed efficiency, Four Factor, shot-profile and roster-continuity foundation feeding the separate CBB research model.",
            "source_attribution": "Data provided by CollegeBasketballData.com; calculations by The Hammer Index.",
            "model_usage": "cbb_research_and_projection_inputs",
        },
        "teams": teams,
    }
    board_payload = {
        "meta": {
            "schema_version": "2.0", "season": season, "generated_at_utc": generated,
            "start_date": start_date, "end_date": end_date, "game_count": len(board),
            "market_method": "Median available book line; movement is current minus opening.",
            "projection_status": "projection_board_built_by_separate_versioned_stage",
            "source_attribution": "Data provided by CollegeBasketballData.com.",
        },
        "games": board,
    }
    status_payload = {
        "meta": {
            "schema_version": "2.0", "season": season, "benchmark_season": benchmark_season,
            "generated_at_utc": generated, "request_count": 8,
            "builder_version": "cbb-foundation-v2.3",
            "raw_api_data_stored": False, "cfb_or_model_a_files_accessed": False,
        },
        "coverage": {
            "directory_teams": len(directory["teams"]),
            "current_leaderboard_teams": len(current_leaderboard),
            "benchmark_leaderboard_teams": len(prior_leaderboard),
            "current_rosters": len(rosters),
            "benchmark_player_seasons": len(prior_players),
            "teams_with_continuity": sum(bool(row["preseason_prior"].get("returning_minutes_pct") is not None) for row in teams),
            "window_games": len(games),
            "games_with_broadcasts": sum(bool(row["broadcasts"]) for row in board),
            "games_with_market": sum(row["market"] is not None for row in board),
        },
    }
    return team_payload, board_payload, status_payload


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    today = datetime.now(timezone.utc).date()
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=int(os.environ.get("CBB_SEASON", "2027")))
    parser.add_argument("--benchmark-season", type=int, default=int(os.environ.get("CBB_BENCHMARK_SEASON", "2026")))
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
        args.season, args.benchmark_season, args.start_date, args.end_date,
        lambda path, params: fetch_json(path, params, api_key),
    )
    for name, payload in zip(("team_profiles.json", "game_board.json", "foundation_status.json"), outputs):
        atomic_write(args.output_dir / name, payload)
    print(
        f"CBB foundation: {outputs[0]['meta']['team_count']} teams, "
        f"{outputs[1]['meta']['game_count']} games, 8 API requests"
    )


if __name__ == "__main__":
    main()
