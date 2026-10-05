#!/usr/bin/env python3
"""Build THI's derived CBB player research layer.

The job joins a completed-season statistical prior to the following season's
verified roster. It persists selected, transformed features only, does not
store provider responses, and does not activate public game projections.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import statistics
import tempfile
import urllib.request
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
VERSION = "thi-cbb-player-research-v1.3"
MIN_MINUTES = 100.0
MIN_GAMES = 5.0
ESPN_ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{team_source_id}/roster"


def normalize_espn_roster(team: dict[str, Any], conference: str | None, payload: dict[str, Any], roster_season: int) -> dict[str, Any] | None:
    season = payload.get("season") or {}
    if finite(season.get("year")) != float(roster_season):
        return None
    athletes = payload.get("athletes") or []
    if not isinstance(athletes, list) or not athletes:
        return None
    players = []
    for athlete in athletes:
        if not isinstance(athlete, dict) or not athlete.get("id"):
            continue
        position = athlete.get("position") or {}
        experience = athlete.get("experience") if isinstance(athlete.get("experience"), dict) else {}
        headshot = athlete.get("headshot") if isinstance(athlete.get("headshot"), dict) else {}
        players.append({
            "id": None,
            "sourceId": str(athlete.get("id")),
            "name": athlete.get("fullName") or athlete.get("displayName"),
            "firstName": athlete.get("firstName"),
            "lastName": athlete.get("lastName"),
            "jersey": athlete.get("jersey"),
            "position": position.get("abbreviation") or position.get("name") if isinstance(position, dict) else None,
            "class": experience.get("abbreviation") or experience.get("displayValue"),
            "height": athlete.get("displayHeight"),
            "weight": athlete.get("displayWeight"),
            "headshot": headshot.get("href"),
        })
    if not players:
        return None
    return {
        "teamId": team.get("id"),
        "teamSourceId": str(team.get("sourceId")),
        "team": team.get("school"),
        "conference": conference,
        "season": roster_season,
        "players": players,
    }


def fetch_espn_rosters(directory: dict[str, Any], roster_season: int, max_workers: int = 12) -> tuple[list[dict[str, Any]], int, list[str]]:
    teams = [team for team in directory.get("teams") or [] if isinstance(team, dict) and team.get("sourceId")]
    conferences = {
        str(row.get("id")): row.get("abbreviation") or row.get("name")
        for row in directory.get("conferences") or [] if isinstance(row, dict)
    }

    def fetch_one(team: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        url = ESPN_ROSTER_URL.format(team_source_id=team["sourceId"])
        request = urllib.request.Request(url, headers={"User-Agent": "TheHammerIndex/1.0 roster-reconciliation"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
            conference = conferences.get(str(team.get("conferenceId")))
            return normalize_espn_roster(team, conference, payload, roster_season), None
        except Exception as error:  # One team should not erase a verified national roster build.
            return None, f"{team.get('school')}: {type(error).__name__}"

    rosters: list[dict[str, Any]] = []
    errors: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        for roster, error in executor.map(fetch_one, teams):
            if roster:
                rosters.append(roster)
            if error:
                errors.append(error)
    rosters.sort(key=lambda row: str(row.get("team")))
    return rosters, len(teams), errors


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def rounded(value: Any, digits: int = 3) -> float | None:
    number = finite(value)
    return round(number, digits) if number is not None else None


def normalized(value: Any) -> str:
    return " ".join("".join(character.lower() if character.isalnum() else " " for character in str(value or "")).split())


def robust_value_score(values: list[float], value: float | None, limit: float = 2.5) -> float:
    if value is None or not values:
        return 0.0
    center = statistics.median(values)
    mad = statistics.median(abs(candidate - center) for candidate in values)
    scale = 1.4826 * mad
    if scale < 1e-9:
        scale = statistics.pstdev(values) if len(values) > 1 else 1.0
    return max(-limit, min(limit, (value - center) / max(scale, 1e-9)))


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
    roster_source: str = "cbbd",
    cbbd_request_count: int = 3,
    espn_request_count: int = 0,
    roster_fetch_errors: int = 0,
    recruits: list[dict[str, Any]] | None = None,
    portal: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(players, list) or not isinstance(teams, list) or not isinstance(rosters, list):
        raise RuntimeError("CBBD player, team, and roster responses must be lists")
    if roster_season <= source_season:
        raise RuntimeError("Roster season must follow the completed source-stat season")

    recruits = recruits or []
    portal = portal or []
    team_context = {
        str(row.get("teamId")): {
            "games": finite(row.get("games")),
            "pace": finite(row.get("pace")) or finite((row.get("summary") or {}).get("pace")),
            "possessions": nested(row, "teamStats", "possessions"),
            "adjusted_net": finite((row.get("adjustedEfficiency") or {}).get("netRating")),
            "adjusted_net_rank": ((row.get("adjustedEfficiency") or {}).get("rankings") or {}).get("net"),
        }
        for row in teams if isinstance(row, dict)
    }
    team_strength_values = [row["adjusted_net"] for row in team_context.values() if row.get("adjusted_net") is not None]

    recruit_by_id: dict[str, dict[str, Any]] = {}
    recruit_by_team_name: dict[tuple[str, str], dict[str, Any]] = {}
    for row in recruits:
        if not isinstance(row, dict):
            continue
        athlete_id = row.get("athleteId")
        if athlete_id is not None:
            recruit_by_id[str(athlete_id)] = row
        destination = row.get("committedTo") or {}
        name = normalized(row.get("name") or f"{row.get('firstName') or ''} {row.get('lastName') or ''}")
        if isinstance(destination, dict) and destination.get("id") is not None and name:
            recruit_by_team_name[(str(destination.get("id")), name)] = row

    portal_by_team_name: dict[tuple[str, str], dict[str, Any]] = {}
    for row in portal:
        if not isinstance(row, dict):
            continue
        destination = row.get("destination") or {}
        name = normalized(row.get("name") or f"{row.get('firstName') or ''} {row.get('lastName') or ''}")
        if isinstance(destination, dict) and destination.get("id") is not None and name:
            portal_by_team_name[(str(destination.get("id")), name)] = row
    recruit_ratings = [value for row in recruits if (value := finite(row.get("rating"))) is not None]
    portal_ratings = [value for row in portal if (value := finite(row.get("rating"))) is not None]
    athlete_teams: dict[str, set[str]] = defaultdict(set)
    source_team_minutes: dict[str, float] = defaultdict(float)
    for row in players:
        if not isinstance(row, dict) or row.get("athleteId") is None:
            continue
        athlete_teams[str(row.get("athleteId"))].add(str(row.get("teamId")))
        source_team_minutes[str(row.get("teamId"))] += finite(row.get("minutes")) or 0.0

    active_by_id: dict[str, dict[str, Any]] = {}
    active_by_source: dict[str, dict[str, Any]] = {}
    active_records: dict[str, dict[str, Any]] = {}
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
                "class": roster_player.get("class") or roster_player.get("year") or roster_player.get("classYear"),
                "height": roster_player.get("height") or roster_player.get("displayHeight"),
                "weight": roster_player.get("weight") or roster_player.get("displayWeight"),
                "headshot": roster_player.get("headshot") or roster_player.get("headshotUrl"),
                "team_id": team_roster.get("teamId"),
                "team": team_roster.get("team"),
                "conference": team_roster.get("conference"),
            }
            if athlete_id is not None:
                active_by_id[str(athlete_id)] = roster_record
                roster_key = f"id:{athlete_id}"
            elif source_id:
                roster_key = f"source:{source_id}"
            else:
                continue
            roster_player_keys.add(roster_key)
            if source_id:
                active_by_source[str(source_id)] = roster_record
            active_records[roster_key] = roster_record

    if not roster_player_keys:
        raise RuntimeError("Current-season roster response contained no players")

    matched_roster_keys: set[str] = set()
    matched_historical_keys: set[str] = set()
    prior_sources: dict[str, dict[str, Any]] = {}
    prior_stints: dict[str, list[dict[str, Any]]] = defaultdict(list)
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
        matched_historical_keys.add(source_key)
        roster_key = f"id:{roster_player['athlete_id']}" if roster_player.get("athlete_id") is not None else f"source:{roster_player.get('athlete_source_id')}"
        matched_roster_keys.add(roster_key)
        prior_stints[roster_key].append(source)
        minutes = finite(source.get("minutes")) or 0.0
        games = finite(source.get("games")) or 0.0
        if roster_key not in prior_sources or minutes > (finite(prior_sources[roster_key].get("minutes")) or 0.0):
            prior_sources[roster_key] = source
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
        roster_key = f"id:{roster_player['athlete_id']}" if roster_player.get("athlete_id") is not None else f"source:{roster_player.get('athlete_source_id')}"
        identity = f"{roster_season}:{athlete_id}:{team_id}"
        context = team_context.get(str(source_team_id), {})
        destination_context = team_context.get(str(team_id), {})
        recruit = recruit_by_id.get(str(athlete_id)) or recruit_by_id.get(str(roster_player.get("athlete_source_id")))
        if recruit is None:
            recruit = recruit_by_team_name.get((str(team_id), normalized(roster_player.get("name") or source.get("name"))))
        transfer = portal_by_team_name.get((str(team_id), normalized(roster_player.get("name") or source.get("name"))))
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
            "transfer_between_seasons": not any(str(stint.get("teamId")) == str(team_id) for stint in prior_stints.get(roster_key, [])),
            "multi_team_source_season": len(athlete_teams[str(source.get("athleteId"))]) > 1,
            "sample": {
                "games": int(games),
                "starts": int(finite(source.get("starts")) or 0),
                "minutes": round(minutes, 1),
                "minutes_per_game": rounded(minutes_per_game, 1),
                "source_team_pace": rounded(context.get("pace"), 1),
            },
            "projection_context": {
                "source_team_adjusted_net": rounded(context.get("adjusted_net"), 2),
                "source_team_adjusted_net_rank": context.get("adjusted_net_rank"),
                "destination_team_adjusted_net": rounded(destination_context.get("adjusted_net"), 2),
                "destination_team_adjusted_net_rank": destination_context.get("adjusted_net_rank"),
                "recruit_rating": rounded((recruit or {}).get("rating"), 4),
                "recruit_stars": int(finite((recruit or {}).get("stars")) or 0) or None,
                "portal_rating": rounded((transfer or {}).get("rating"), 4),
                "basis": "transfer projection" if str(source_team_id) != str(team_id) else "returning production",
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
        production_rating = max(1.0, min(99.0, 50 + 12 * all_around * reliability))
        context = row["projection_context"]
        competition = robust_value_score(team_strength_values, finite(context.get("source_team_adjusted_net")))
        destination = robust_value_score(team_strength_values, finite(context.get("destination_team_adjusted_net")))
        recruit_signal = robust_value_score(recruit_ratings, finite(context.get("recruit_rating")), 2.0)
        portal_signal = robust_value_score(portal_ratings, finite(context.get("portal_rating")), 2.0)
        projected_impact = max(1.0, min(99.0, production_rating + 5.0 * competition + 2.0 * destination + 1.5 * recruit_signal + 1.5 * portal_signal))
        context["competition_adjustment"] = round(5.0 * competition, 1)
        context["destination_adjustment"] = round(2.0 * destination, 1)
        context["pedigree_adjustment"] = round(1.5 * recruit_signal + 1.5 * portal_signal, 1)
        row["research_scores"] = {
            "offense": round(50 + 10 * offense * reliability, 1),
            "defense": round(50 + 10 * defense * reliability, 1),
            "all_around": round(50 + 10 * all_around * reliability, 1),
            "prior_production_rating": round(production_rating, 1),
            "projected_impact_rating": round(projected_impact, 1),
            "thi_player_rating": round(projected_impact, 1),
        }

    statistical_prior_count = len(prepared)
    projected_newcomer_count = 0
    for roster_key, active in active_records.items():
        if roster_key in prior_sources:
            continue
        athlete_id = active.get("athlete_id")
        source_id = active.get("athlete_source_id")
        team_id = active.get("team_id")
        name = active.get("name")
        recruit = recruit_by_id.get(str(athlete_id)) if athlete_id is not None else None
        if recruit is None and source_id:
            recruit = recruit_by_id.get(str(source_id))
        if recruit is None:
            recruit = recruit_by_team_name.get((str(team_id), normalized(name)))
        transfer = portal_by_team_name.get((str(team_id), normalized(name)))
        recruit_rating = finite((recruit or {}).get("rating"))
        portal_rating = finite((transfer or {}).get("rating"))
        if recruit_rating is None and portal_rating is None:
            continue
        destination_context = team_context.get(str(team_id), {})
        destination = robust_value_score(team_strength_values, finite(destination_context.get("adjusted_net")))
        recruit_signal = robust_value_score(recruit_ratings, recruit_rating, 2.5)
        portal_signal = robust_value_score(portal_ratings, portal_rating, 2.5)
        pedigree_signal = recruit_signal if recruit_rating is not None else portal_signal
        projected_impact = max(1.0, min(99.0, 50.0 + 12.0 * pedigree_signal + 2.0 * destination))
        basis = "freshman projection" if recruit_rating is not None else "transfer projection"
        empty_metrics = {key: None for key in component_specs}
        empty_metrics.update({
            "assists_per_40": None,
            "turnovers_per_40": None,
            "rebounds_per_40": None,
            "net_rating": None,
            "effective_field_goal_pct": None,
            "free_throw_rate": None,
            "offensive_rebound_pct": None,
            "total_win_shares_per_40": None,
        })
        prepared.append({
            "player_season_id": f"{roster_season}:{athlete_id or source_id}:{team_id}",
            "athlete_id": athlete_id,
            "athlete_source_id": source_id,
            "name": name,
            "team_id": team_id,
            "team": active.get("team"),
            "conference": active.get("conference"),
            "position": active.get("position"),
            "position_group": position_group(active.get("position")),
            "jersey": active.get("jersey"),
            "current_roster_verified": True,
            "source_season": source_season,
            "source_team_id": None,
            "source_team": None,
            "transfer_between_seasons": basis == "transfer projection",
            "multi_team_source_season": False,
            "sample": {"games": 0, "starts": 0, "minutes": 0.0, "minutes_per_game": None, "source_team_pace": None},
            "projection_context": {
                "source_team_adjusted_net": None,
                "source_team_adjusted_net_rank": None,
                "destination_team_adjusted_net": rounded(destination_context.get("adjusted_net"), 2),
                "destination_team_adjusted_net_rank": destination_context.get("adjusted_net_rank"),
                "recruit_rating": rounded(recruit_rating, 4),
                "recruit_stars": int(finite((recruit or {}).get("stars")) or 0) or None,
                "portal_rating": rounded(portal_rating, 4),
                "basis": basis,
                "competition_adjustment": None,
                "destination_adjustment": round(2.0 * destination, 1),
                "pedigree_adjustment": round(12.0 * pedigree_signal, 1),
            },
            "role": "projected newcomer",
            "metrics": empty_metrics,
            "data_quality": {"metrics_available": 0, "metrics_expected": len(empty_metrics), "reliability": 35.0},
            "research_scores": {
                "offense": None,
                "defense": None,
                "all_around": None,
                "prior_production_rating": None,
                "projected_impact_rating": round(projected_impact, 1),
                "thi_player_rating": round(projected_impact, 1),
            },
        })
        projected_newcomer_count += 1

    prepared.sort(key=lambda row: (-row["research_scores"]["thi_player_rating"], -row["sample"]["minutes"], str(row["name"])))
    ratings = [row["research_scores"]["thi_player_rating"] for row in prepared]
    position_counts: defaultdict[str, int] = defaultdict(int)
    for rank, row in enumerate(prepared, 1):
        group = row["position_group"]
        position_counts[group] += 1
        row["ranks"] = {"overall": rank, "position_group": position_counts[group]}
        row["research_scores"]["rating_percentile"] = percentile(ratings, row["research_scores"]["thi_player_rating"])

    rated_by_key: dict[str, dict[str, Any]] = {}
    for row in prepared:
        if row.get("athlete_id") is not None:
            rated_by_key[f"id:{row['athlete_id']}"] = row
        if row.get("athlete_source_id"):
            rated_by_key[f"source:{row['athlete_source_id']}"] = row

    roster_teams: dict[str, dict[str, Any]] = {}
    for roster_key, active in active_records.items():
        rated = rated_by_key.get(roster_key)
        prior = prior_sources.get(roster_key)
        prior_minutes = finite((prior or {}).get("minutes"))
        prior_games = finite((prior or {}).get("games"))
        returning_minutes = sum(
            finite(stint.get("minutes")) or 0.0
            for stint in prior_stints.get(roster_key, [])
            if str(stint.get("teamId")) == str(active.get("team_id"))
        )
        if rated and prior:
            prior_state = "rated"
        elif rated:
            prior_state = "projected_newcomer"
        elif prior:
            prior_state = "below_sample"
        else:
            prior_state = "no_prior_stats"
        team_key = str(active.get("team_id"))
        team_roster = roster_teams.setdefault(team_key, {
            "team_id": active.get("team_id"),
            "team": active.get("team"),
            "conference": active.get("conference"),
            "players": [],
        })
        team_roster["players"].append({
            "roster_player_id": f"{roster_season}:{active.get('athlete_id') or active.get('athlete_source_id')}:{active.get('team_id')}",
            "player_season_id": rated.get("player_season_id") if rated else None,
            "athlete_id": active.get("athlete_id"),
            "athlete_source_id": active.get("athlete_source_id"),
            "name": active.get("name"),
            "position": active.get("position"),
            "position_group": position_group(active.get("position")),
            "jersey": active.get("jersey"),
            "class": active.get("class"),
            "height": active.get("height"),
            "weight": active.get("weight"),
            "headshot": active.get("headshot"),
            "prior_state": prior_state,
            "prior_team": (prior or {}).get("team"),
            "prior_team_id": (prior or {}).get("teamId"),
            "prior_minutes": rounded(prior_minutes, 1),
            "returning_minutes": rounded(returning_minutes, 1),
            "prior_games": int(prior_games) if prior_games is not None else None,
            "transfer_between_seasons": bool(prior and returning_minutes <= 0),
            "role": rated.get("role") if rated else None,
            "thi_player_rating": (rated.get("research_scores") or {}).get("thi_player_rating") if rated else None,
            "rating_percentile": (rated.get("research_scores") or {}).get("rating_percentile") if rated else None,
        })

    team_rosters = []
    for team_roster in roster_teams.values():
        team_roster["players"].sort(key=lambda row: (
            0 if row["prior_state"] in ("rated", "projected_newcomer") else 1 if row["prior_state"] == "below_sample" else 2,
            -(finite(row.get("thi_player_rating")) or -1.0),
            str(row.get("name") or ""),
        ))
        team_roster["player_count"] = len(team_roster["players"])
        team_roster["rated_player_count"] = sum(row["prior_state"] in ("rated", "projected_newcomer") for row in team_roster["players"])
        team_roster["transfer_count"] = sum(row["transfer_between_seasons"] for row in team_roster["players"])
        team_roster["prior_team_minutes"] = round(source_team_minutes.get(str(team_roster.get("team_id")), 0.0), 1)
        team_roster["returning_minutes"] = round(sum(row["returning_minutes"] or 0.0 for row in team_roster["players"]), 1)
        team_roster["returning_minutes_pct"] = round(
            100.0 * team_roster["returning_minutes"] / team_roster["prior_team_minutes"], 2
        ) if team_roster["prior_team_minutes"] > 0 else None
        team_rosters.append(team_roster)
    team_rosters.sort(key=lambda row: str(row.get("team") or ""))

    team_count = len({str(row["team_id"]) for row in prepared})
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "season": roster_season,
            "source_season": source_season,
            "roster_season": roster_season,
            "roster_source": roster_source,
            "activation_state": "research_reference_only",
            "player_count": len(prepared),
            "team_count": team_count,
            "minimum_minutes": min_minutes,
            "minimum_games": min_games,
            "request_count": cbbd_request_count + espn_request_count,
            "cbbd_request_count": cbbd_request_count,
            "espn_request_count": espn_request_count,
            "raw_api_data_stored": False,
            "source_attribution": "Data provided by CollegeBasketballData.com; ratings and calculations by The Hammer Index.",
            "methodology": "Active-roster players are ranked by projected impact. For veterans, THI begins with robust prior production and efficiency, regresses for sample reliability, translates production through the source team's adjusted strength, and adds destination and matched pedigree context. Verified newcomers without a qualified prior use a lower-reliability recruiting or portal projection and show no fabricated prior statistics. Prior Production remains visible separately. This research rating is not a lineup-adjusted game projection.",
        },
        "coverage": {
            "provider_player_rows": len(players),
            "provider_team_rows": len(teams),
            "provider_roster_teams": len(rosters),
            "roster_fetch_errors": roster_fetch_errors,
            "current_roster_players": len(roster_player_keys),
            "current_roster_players_with_source_stats": len(matched_roster_keys),
            "current_roster_players_without_qualified_prior": len(roster_player_keys) - statistical_prior_count,
            "historical_players_withheld_unverified_current": len(historical_keys - matched_historical_keys),
            "qualified_players": statistical_prior_count,
            "rated_players": len(prepared),
            "qualified_teams": team_count,
            "multi_team_source_stints": sum(row["multi_team_source_season"] for row in prepared),
            "between_season_transfers": sum(row["transfer_between_seasons"] for row in prepared),
            "statistical_prior_players": statistical_prior_count,
            "projected_newcomers": projected_newcomer_count,
            "position_groups": dict(Counter(row["position_group"] for row in prepared)),
        },
        "team_rosters": team_rosters,
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
    recruits = fetch_json("/recruiting/players", {"year": args.roster_season - 1}, api_key)
    portal = fetch_json("/recruiting/portal", {"year": args.roster_season - 1}, api_key)
    roster_source = "cbbd"
    cbbd_request_count = 5
    espn_request_count = 0
    roster_fetch_errors = 0
    if not any(isinstance(row, dict) and row.get("players") for row in rosters or []):
        directory = fetch_json("/teams/directory", {"season": args.roster_season}, api_key)
        cbbd_request_count += 1
        rosters, espn_request_count, errors = fetch_espn_rosters(directory, args.roster_season)
        roster_fetch_errors = len(errors)
        roster_source = "espn_current_roster_fallback"
        print(f"CBBD roster feed was empty; ESPN fallback verified {len(rosters)} teams ({roster_fetch_errors} fetch errors).")
    payload = build_player_research(
        args.source_season,
        args.roster_season,
        players,
        teams,
        rosters,
        roster_source=roster_source,
        cbbd_request_count=cbbd_request_count,
        espn_request_count=espn_request_count,
        roster_fetch_errors=roster_fetch_errors,
        recruits=recruits,
        portal=portal,
    )
    atomic_write(args.output, payload)
    print(json.dumps({"meta": payload["meta"], "coverage": payload["coverage"]}, indent=2))


if __name__ == "__main__":
    main()
