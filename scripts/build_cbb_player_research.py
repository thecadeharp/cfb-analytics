#!/usr/bin/env python3
"""Build THI's derived CBB player research layer.

The job joins a completed-season statistical prior to the following season's
verified roster. It persists selected, transformed features only, does not
store provider responses, and does not activate public game projections.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.verify_cbb_api_foundation import clean_key, fetch_json
except ModuleNotFoundError:
    from verify_cbb_api_foundation import clean_key, fetch_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "cbb" / "player_ratings.json"
VERSION = "thi-cbb-player-research-v1.1"
MIN_MINUTES = 100.0
MIN_GAMES = 5.0


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def rounded(value: Any, digits: int = 3) -> float | None:
    number = finite(value)
    return round(number, digits) if number is not None else None


def nested(row: dict[str, Any], group: str, field: str) -> float | None:
    block = row.get(group) or {}
    return finite(block.get(field)) if isinstance(block, dict) else None


def per_40(value: Any, minutes: float) -> float | None:
    number = finite(value)
    return round(40 * number / minutes, 3) if number is not None and minutes > 0 else None


def position_group(position: Any) -> str:
    text = str(position or "").upper().replace(" ", "")
    if "C" in text and "G" not in text:
        return "frontcourt"
    if "F" in text and "G" not in text:
        return "frontcourt"
    if "G" in text and "F" not in text:
        return "backcourt"
    if text:
        return "wing"
    return "unclassified"


def role_label(usage: float | None, minutes_per_game: float | None) -> str:
    usage = usage or 0.0
    minutes_per_game = minutes_per_game or 0.0
    if usage >= 28 and minutes_per_game >= 20:
        return "primary creator"
    if usage >= 23 and minutes_per_game >= 18:
        return "high-usage starter"
    if minutes_per_game >= 24:
        return "core starter"
    if minutes_per_game >= 14:
        return "rotation"
    return "limited role"


def robust_scores(rows: list[dict[str, Any]], key: str, invert: bool = False) -> list[float]:
    values = [finite(row["metrics"].get(key)) for row in rows]
    observed = [value for value in values if value is not None]
    if not observed:
        return [0.0] * len(rows)
    center = statistics.median(observed)
    mad = statistics.median(abs(value - center) for value in observed)
    scale = 1.4826 * mad
    if scale < 1e-9:
        scale = statistics.pstdev(observed) if len(observed) > 1 else 1.0
    if scale < 1e-9:
        scale = 1.0
    output = []
    for value in values:
        score = 0.0 if value is None else max(-3.0, min(3.0, (value - center) / scale))
        output.append(-score if invert else score)
    return output


def percentile(values: list[float], value: float) -> float:
    if len(values) <= 1:
        return 50.0
    below = sum(candidate < value for candidate in values)
    equal = sum(candidate == value for candidate in values)
    return round(100 * (below + 0.5 * equal) / len(values), 1)


def build_player_research(
    source_season: int,
    roster_season: int,
    players: list[dict[str, Any]],
    teams: list[dict[str, Any]],
    rosters: list[dict[str, Any]],
    min_minutes: float = MIN_MINUTES,
    min_games: float = MIN_GAMES,
) -> dict[str, Any]:
    if not isinstance(players, list) or not isinstance(teams, list) or not isinstance(rosters, list):
        raise RuntimeError("CBBD player, team, and roster responses must be lists")
    if roster_season <= source_season:
        raise RuntimeError("Roster season must follow the completed source-stat season")

    team_context = {
        str(row.get("teamId")): {
            "games": finite(row.get("games")),
            "pace": finite(row.get("pace")),
            "possessions": nested(row, "teamStats", "possessions"),
        }
        for row in teams if isinstance(row, dict)
    }
    athlete_teams: dict[str, set[str]] = defaultdict(set)
    for row in players:
        if not isinstance(row, dict) or row.get("athleteId") is None:
            continue
        athlete_teams[str(row.get("athleteId"))].add(str(row.get("teamId")))

    active_by_id: dict[str, dict[str, Any]] = {}
    active_by_source: dict[str, dict[str, Any]] = {}
    roster_player_keys: set[str] = set()
    for team_roster in rosters:
        if not isinstance(team_roster, dict):
            continue
        for roster_player in team_roster.get("players") or []:
            if not isinstance(roster_player, dict):
                continue
            athlete_id = roster_player.get("id")
            source_id = roster_player.get("sourceId")
            roster_record = {
                "athlete_id": athlete_id,
                "athlete_source_id": source_id,
                "name": roster_player.get("name"),
                "position": roster_player.get("position"),
                "jersey": roster_player.get("jersey"),
                "team_id": team_roster.get("teamId"),
                "team": team_roster.get("team"),
                "conference": team_roster.get("conference"),
            }
            if athlete_id is not None:
                active_by_id[str(athlete_id)] = roster_record
                roster_player_keys.add(f"id:{athlete_id}")
            elif source_id:
                roster_player_keys.add(f"source:{source_id}")
            if source_id:
                active_by_source[str(source_id)] = roster_record

    if not roster_player_keys:
        raise RuntimeError("Current-season roster response contained no players")

    matched_roster_keys: set[str] = set()
    qualified_sources: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    historical_keys: set[str] = set()
    for source in players:
        if not isinstance(source, dict):
            continue
        athlete_id = source.get("athleteId")
        source_id = source.get("athleteSourceId")
        source_key = f"id:{athlete_id}" if athlete_id is not None else f"source:{source_id}"
        historical_keys.add(source_key)
        roster_player = active_by_id.get(str(athlete_id)) if athlete_id is not None else None
        if roster_player is None and source_id:
            roster_player = active_by_source.get(str(source_id))
        if roster_player is None:
            continue
        roster_key = f"id:{roster_player['athlete_id']}" if roster_player.get("athlete_id") is not None else f"source:{roster_player.get('athlete_source_id')}"
        matched_roster_keys.add(roster_key)
        minutes = finite(source.get("minutes")) or 0.0
        games = finite(source.get("games")) or 0.0
        if minutes < min_minutes or games < min_games:
            continue
        current = qualified_sources.get(roster_key)
        if current is None or minutes > (finite(current[0].get("minutes")) or 0.0):
            qualified_sources[roster_key] = (source, roster_player)

    prepared: list[dict[str, Any]] = []
    for source, roster_player in qualified_sources.values():
        minutes = finite(source.get("minutes")) or 0.0
        games = finite(source.get("games")) or 0.0
        athlete_id = roster_player.get("athlete_id") or source.get("athleteId")
        team_id = roster_player.get("team_id")
        source_team_id = source.get("teamId")
        identity = f"{roster_season}:{athlete_id}:{team_id}"
        context = team_context.get(str(source_team_id), {})
        minutes_per_game = minutes / games if games else None
        usage = finite(source.get("usage"))
        metrics = {
            "points_per_40": per_40(source.get("points"), minutes),
            "assists_per_40": per_40(source.get("assists"), minutes),
            "turnovers_per_40": per_40(source.get("turnovers"), minutes),
            "steals_per_40": per_40(source.get("steals"), minutes),
            "blocks_per_40": per_40(source.get("blocks"), minutes),
            "rebounds_per_40": per_40(nested(source, "rebounds", "total"), minutes),
            "defensive_rebounds_per_40": per_40(nested(source, "rebounds", "defensive"), minutes),
            "offensive_rebounds_per_40": per_40(nested(source, "rebounds", "offensive"), minutes),
            "usage": rounded(usage),
            "offensive_rating": rounded(source.get("offensiveRating")),
            "defensive_rating": rounded(source.get("defensiveRating")),
            "net_rating": rounded(source.get("netRating")),
            "porpag": rounded(source.get("PORPAG")),
            "effective_field_goal_pct": rounded(source.get("effectiveFieldGoalPct")),
            "true_shooting_pct": rounded(source.get("trueShootingPct")),
            "assist_turnover_ratio": rounded(source.get("assistsTurnoverRatio")),
            "free_throw_rate": rounded(source.get("freeThrowRate")),
            "offensive_rebound_pct": rounded(source.get("offensiveReboundPct")),
            "offensive_win_shares_per_40": per_40(nested(source, "winShares", "offensive"), minutes),
            "defensive_win_shares_per_40": per_40(nested(source, "winShares", "defensive"), minutes),
            "total_win_shares_per_40": rounded(nested(source, "winShares", "totalPer40")),
        }
        available = sum(value is not None for value in metrics.values())
        reliability = min(1.0, math.sqrt(minutes / 800.0)) * min(1.0, games / 25.0)
        prepared.append({
            "player_season_id": identity,
            "athlete_id": athlete_id,
            "athlete_source_id": roster_player.get("athlete_source_id") or source.get("athleteSourceId"),
            "name": roster_player.get("name") or source.get("name"),
            "team_id": team_id,
            "team": roster_player.get("team"),
            "conference": roster_player.get("conference"),
            "position": roster_player.get("position") or source.get("position"),
            "position_group": position_group(roster_player.get("position") or source.get("position")),
            "jersey": roster_player.get("jersey"),
            "current_roster_verified": True,
            "source_season": source_season,
            "source_team_id": source_team_id,
            "source_team": source.get("team"),
            "transfer_between_seasons": str(source_team_id) != str(team_id),
            "multi_team_source_season": len(athlete_teams[str(source.get("athleteId"))]) > 1,
            "sample": {
                "games": int(games),
                "starts": int(finite(source.get("starts")) or 0),
                "minutes": round(minutes, 1),
                "minutes_per_game": rounded(minutes_per_game, 1),
                "source_team_pace": rounded(context.get("pace"), 1),
            },
            "role": role_label(usage, minutes_per_game),
            "metrics": metrics,
            "data_quality": {
                "metrics_available": available,
                "metrics_expected": len(metrics),
                "reliability": round(100 * reliability, 1),
            },
            "_reliability": reliability,
        })

    if not prepared:
        raise RuntimeError("No players met the THI sample contract")

    component_specs = {
        "porpag": False,
        "true_shooting_pct": False,
        "offensive_rating": False,
        "points_per_40": False,
        "assist_turnover_ratio": False,
        "offensive_win_shares_per_40": False,
        "offensive_rebounds_per_40": False,
        "defensive_rating": True,
        "defensive_win_shares_per_40": False,
        "steals_per_40": False,
        "blocks_per_40": False,
        "defensive_rebounds_per_40": False,
    }
    zscores = {key: robust_scores(prepared, key, invert) for key, invert in component_specs.items()}
    offense_weights = {
        "porpag": .24,
        "true_shooting_pct": .15,
        "offensive_rating": .15,
        "points_per_40": .12,
        "assist_turnover_ratio": .12,
        "offensive_win_shares_per_40": .12,
        "offensive_rebounds_per_40": .10,
    }
    defense_weights = {
        "defensive_rating": .28,
        "defensive_win_shares_per_40": .28,
        "steals_per_40": .18,
        "blocks_per_40": .14,
        "defensive_rebounds_per_40": .12,
    }
    for index, row in enumerate(prepared):
        offense = sum(weight * zscores[key][index] for key, weight in offense_weights.items())
        defense = sum(weight * zscores[key][index] for key, weight in defense_weights.items())
        all_around = .72 * offense + .28 * defense
        reliability = row.pop("_reliability")
        rating = max(1.0, min(99.0, 50 + 12 * all_around * reliability))
        row["research_scores"] = {
            "offense": round(50 + 10 * offense * reliability, 1),
            "defense": round(50 + 10 * defense * reliability, 1),
            "all_around": round(50 + 10 * all_around * reliability, 1),
            "thi_player_rating": round(rating, 1),
        }

    prepared.sort(key=lambda row: (-row["research_scores"]["thi_player_rating"], -row["sample"]["minutes"], str(row["name"])))
    ratings = [row["research_scores"]["thi_player_rating"] for row in prepared]
    position_counts: defaultdict[str, int] = defaultdict(int)
    for rank, row in enumerate(prepared, 1):
        group = row["position_group"]
        position_counts[group] += 1
        row["ranks"] = {"overall": rank, "position_group": position_counts[group]}
        row["research_scores"]["rating_percentile"] = percentile(ratings, row["research_scores"]["thi_player_rating"])

    team_count = len({str(row["team_id"]) for row in prepared})
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "season": roster_season,
            "source_season": source_season,
            "roster_season": roster_season,
            "activation_state": "research_reference_only",
            "player_count": len(prepared),
            "team_count": team_count,
            "minimum_minutes": min_minutes,
            "minimum_games": min_games,
            "request_count": 3,
            "raw_api_data_stored": False,
            "source_attribution": "Data provided by CollegeBasketballData.com; ratings and calculations by The Hammer Index.",
            "methodology": "Active roster players only. Ratings use the prior completed season's robust standardized production and efficiency components, regressed by sample reliability. Not opponent-adjusted or lineup-adjusted in v1.1.",
        },
        "coverage": {
            "provider_player_rows": len(players),
            "provider_team_rows": len(teams),
            "provider_roster_teams": len(rosters),
            "current_roster_players": len(roster_player_keys),
            "current_roster_players_with_source_stats": len(matched_roster_keys),
            "current_roster_players_without_qualified_prior": len(roster_player_keys) - len(prepared),
            "historical_players_excluded_not_current": len(historical_keys - roster_player_keys),
            "qualified_players": len(prepared),
            "qualified_teams": team_count,
            "multi_team_source_stints": sum(row["multi_team_source_season"] for row in prepared),
            "between_season_transfers": sum(row["transfer_between_seasons"] for row in prepared),
            "position_groups": dict(Counter(row["position_group"] for row in prepared)),
        },
        "players": prepared,
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
    parser.add_argument("--source-season", type=int, default=int(os.environ.get("CBB_PLAYER_SOURCE_SEASON", "2026")))
    parser.add_argument("--roster-season", type=int, default=int(os.environ.get("CBB_PLAYER_ROSTER_SEASON", "2027")))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    api_key = clean_key(os.environ.get("CBBD_API_KEY"))
    if not api_key:
        raise SystemExit("CBBD_API_KEY is required")
    players = fetch_json("/stats/player/season", {"season": args.source_season}, api_key)
    teams = fetch_json("/stats/team/season", {"season": args.source_season}, api_key)
    rosters = fetch_json("/teams/roster", {"season": args.roster_season}, api_key)
    payload = build_player_research(args.source_season, args.roster_season, players, teams, rosters)
    atomic_write(args.output, payload)
    print(json.dumps({"meta": payload["meta"], "coverage": payload["coverage"]}, indent=2))


if __name__ == "__main__":
    main()
