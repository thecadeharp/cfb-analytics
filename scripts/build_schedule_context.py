#!/usr/bin/env python3
"""Build display-only Schedule Context v2 for every FBS game.

The output is descriptive research context only. It never modifies Model A,
projections, ratings, signals, or tracked snapshots.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "schedule_context.json"
CFBD_TEAMS_URL = "https://api.collegefootballdata.com/teams/fbs"
SEASON = 2026


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_date(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


ALIASES = {
    "armywestpoint": "army",
    "flaatlantic": "floridaatlantic",
    "fiu": "floridainternational",
    "gasouthern": "georgiasouthern",
    "middletenn": "middletennessee",
    "mississippist": "mississippistate",
    "niu": "northernillinois",
    "southfla": "southflorida",
    "ulm": "ulmonroe",
    "westernky": "westernkentucky",
}


def team_key(value: Any) -> str:
    key = re.sub(r"[^a-z0-9]+", "", str(value or "").lower().replace("university", ""))
    return ALIASES.get(key, key)


def matchup_key(week: Any, away: Any, home: Any) -> tuple[int, tuple[str, str]]:
    return int(week or 0), tuple(sorted((team_key(away), team_key(home))))


def result_index(results: dict[str, Any]) -> dict[tuple[int, tuple[str, str]], dict[str, Any]]:
    return {
        matchup_key(game.get("week"), game.get("away_team"), game.get("home_team")): game
        for game in results.get("games", [])
    }


def team_result(
    team: str,
    game: dict[str, Any],
    results: dict[tuple[int, tuple[str, str]], dict[str, Any]],
) -> dict[str, Any] | None:
    result = results.get(matchup_key(game.get("week"), game.get("away_team"), game.get("home_team")))
    if not result:
        return None
    home_points = result.get("home_points")
    away_points = result.get("away_points")
    if home_points is None or away_points is None:
        return None
    is_home = team_key(team) == team_key(result.get("home_team"))
    team_points = float(home_points if is_home else away_points)
    opponent_points = float(away_points if is_home else home_points)
    margin = team_points - opponent_points
    return {
        "result": "W" if margin > 0 else "L" if margin < 0 else "T",
        "margin": round(margin, 1),
        "score": f"{int(team_points)}-{int(opponent_points)}",
    }


def fetch_team_locations() -> dict[str, dict[str, Any]]:
    """Fetch one in-memory FBS location map; never publish the raw response."""

    token = os.environ.get("CFBD_API_KEY", "").strip()
    if not token:
        raise RuntimeError("CFBD_API_KEY is required for Schedule Context v2 travel estimates.")

    response = requests.get(
        CFBD_TEAMS_URL,
        params={"year": SEASON},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or len(rows) < 100:
        count = len(rows) if isinstance(rows, list) else "not a list"
        raise RuntimeError(f"Unexpected CFBD FBS-team response: {count}")

    locations: dict[str, dict[str, Any]] = {}
    for row in rows:
        school = str(row.get("school") or row.get("team") or "").strip()
        location = row.get("location") or {}
        latitude = finite_number(location.get("latitude"))
        longitude = finite_number(location.get("longitude"))
        if not school or latitude is None or longitude is None:
            continue
        locations[team_key(school)] = {
            "team": school,
            "latitude": latitude,
            "longitude": longitude,
            "timezone": location.get("timezone") or location.get("timeZone"),
            "city": location.get("city"),
            "state": location.get("state"),
            "venue": location.get("name") or location.get("venue"),
        }

    if len(locations) < 100:
        raise RuntimeError(f"Only {len(locations)} usable FBS team locations returned by CFBD.")
    return locations


def team_location(locations: dict[str, dict[str, Any]], team: Any) -> dict[str, Any] | None:
    return locations.get(team_key(team))


def haversine_miles(first: dict[str, Any] | None, second: dict[str, Any] | None) -> float | None:
    if not first or not second:
        return None
    lat1 = finite_number(first.get("latitude"))
    lon1 = finite_number(first.get("longitude"))
    lat2 = finite_number(second.get("latitude"))
    lon2 = finite_number(second.get("longitude"))
    if None in (lat1, lon1, lat2, lon2):
        return None
    radius_miles = 3958.7613
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius_miles * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def condition_locations(game_conditions: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for game_id, game in (game_conditions.get("games") or {}).items():
        location = ((game.get("forecast") or {}).get("location") or {})
        latitude = finite_number(location.get("latitude"))
        longitude = finite_number(location.get("longitude"))
        if latitude is None or longitude is None:
            continue
        output[str(game_id)] = {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": location.get("timezone"),
            "city": location.get("resolved_name"),
            "state": location.get("resolved_admin1"),
            "venue": game.get("venue"),
        }
    return output


def game_site(
    game: dict[str, Any] | None,
    locations: dict[str, dict[str, Any]],
    forecast_locations: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not game:
        return None
    game_id = str(game.get("id") or game.get("game_id") or "")
    if game_id and game_id in forecast_locations:
        site = dict(forecast_locations[game_id])
        if not site.get("timezone"):
            home = team_location(locations, game.get("home_team"))
            site["timezone"] = (home or {}).get("timezone")
        return site
    if game.get("neutral_site"):
        return None
    return team_location(locations, game.get("home_team"))


def timezone_offset_hours(timezone_name: Any, at: datetime | None) -> float | None:
    if not timezone_name or not at:
        return None
    try:
        offset = at.astimezone(ZoneInfo(str(timezone_name))).utcoffset()
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return offset.total_seconds() / 3600 if offset is not None else None


def travel_snapshot(
    team: str,
    current: dict[str, Any],
    previous: dict[str, Any] | None,
    locations: dict[str, dict[str, Any]],
    forecast_locations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    campus = team_location(locations, team)
    current_site = game_site(current, locations, forecast_locations)
    previous_site = game_site(previous, locations, forecast_locations) if previous else campus
    current_date = parse_date(current.get("start_date"))
    campus_offset = timezone_offset_hours((campus or {}).get("timezone"), current_date)
    site_offset = timezone_offset_hours((current_site or {}).get("timezone"), current_date)
    timezone_shift = (
        abs(site_offset - campus_offset)
        if campus_offset is not None and site_offset is not None
        else None
    )
    from_campus = haversine_miles(campus, current_site)
    since_previous = haversine_miles(previous_site, current_site)
    return {
        "miles_from_campus": round(from_campus) if from_campus is not None else None,
        "miles_since_previous_game": round(since_previous) if since_previous is not None else None,
        "timezone_shift_hours": round(timezone_shift, 1) if timezone_shift is not None else None,
        "destination": {
            "city": (current_site or {}).get("city"),
            "state": (current_site or {}).get("state"),
        },
        "method": "great_circle_estimate",
    }


def team_context(
    team: str,
    opponent: str,
    game: dict[str, Any],
    schedule: list[dict[str, Any]],
    results: dict[tuple[int, tuple[str, str]], dict[str, Any]],
    power_ranks: dict[str, int],
    locations: dict[str, dict[str, Any]],
    forecast_locations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(schedule, key=lambda row: str(row.get("start_date") or ""))
    current_index = next((index for index, row in enumerate(ordered) if str(row.get("id")) == str(game.get("id"))), None)
    if current_index is None:
        return {"team": team, "flags": []}

    current = ordered[current_index]
    previous = ordered[current_index - 1] if current_index > 0 else None
    previous_two = ordered[max(0, current_index - 2):current_index]
    window_four = ordered[max(0, current_index - 3):current_index + 1]
    following = ordered[current_index + 1] if current_index + 1 < len(ordered) else None
    current_date = parse_date(current.get("start_date"))
    previous_date = parse_date(previous.get("start_date")) if previous else None
    rest_days = (current_date - previous_date).days if current_date and previous_date else None

    road_streak = 0
    for prior in reversed(ordered[:current_index]):
        if prior.get("location") == "away":
            road_streak += 1
        else:
            break

    road_games_last_four = sum(1 for item in window_four if item.get("location") == "away")
    prior_result = team_result(team, previous, results) if previous else None
    opponent_rank = power_ranks.get(opponent)
    next_opponent = str(following.get("opponent") or "") if following else None
    next_rank = power_ranks.get(next_opponent) if next_opponent else None
    travel = travel_snapshot(team, current, previous, locations, forecast_locations)
    trip_miles = finite_number(travel.get("miles_from_campus"))
    timezone_shift = finite_number(travel.get("timezone_shift_hours"))
    flags: list[dict[str, str]] = []

    if rest_days is not None and rest_days <= 6:
        flags.append({"type": "short_rest", "label": f"Short rest ({rest_days} days)"})
    if rest_days is not None and rest_days >= 12:
        flags.append({"type": "extended_rest", "label": f"Extended rest ({rest_days} days)"})
    if current.get("location") == "away" and road_streak >= 1:
        flags.append({"type": "road_streak", "label": f"Road game #{road_streak + 1} in a row"})
    if road_games_last_four >= 3:
        flags.append({"type": "road_density", "label": f"Road game {road_games_last_four} of last {len(window_four)}"})
    if current.get("location") == "home" and previous and previous.get("location") == "away":
        label = "Home after a road game"
        if len(previous_two) == 2 and all(item.get("location") == "away" for item in previous_two):
            label = "Home after consecutive road games"
        flags.append({"type": "return_home", "label": label})
    if (current.get("location") == "away" or current.get("neutral_site")) and trip_miles is not None:
        if trip_miles >= 1500:
            flags.append({"type": "cross_country_travel", "label": f"Cross-country trip ({round(trip_miles):,} mi)"})
        elif trip_miles >= 750:
            flags.append({"type": "long_travel", "label": f"Long-distance trip ({round(trip_miles):,} mi)"})
    if timezone_shift is not None and timezone_shift >= 2:
        flags.append({"type": "timezone_change", "label": f"{timezone_shift:g}-hour time-zone change"})
    if prior_result and prior_result["margin"] <= -21:
        flags.append({"type": "off_blowout_loss", "label": "Coming off a 21+ point loss"})
    if prior_result and prior_result["margin"] >= 21:
        flags.append({"type": "off_blowout_win", "label": "Coming off a 21+ point win"})
    if next_rank and next_rank <= 25 and (opponent_rank is None or opponent_rank > 50):
        flags.append({"type": "lookahead_watch", "label": f"Top-25 opponent next: {next_opponent}"})

    return {
        "team": team,
        "location": current.get("location"),
        "rest_days": rest_days,
        "consecutive_road_games_entering": road_streak,
        "road_games_last_four": road_games_last_four,
        "travel": travel,
        "previous_game": {
            "opponent": previous.get("opponent") if previous else None,
            "location": previous.get("location") if previous else None,
            **(prior_result or {}),
        },
        "next_game": {
            "opponent": next_opponent,
            "location": following.get("location") if following else None,
            "opponent_power_rank": next_rank,
        },
        "flags": flags,
    }


def main() -> None:
    schedule_data = load(DATA / "schedule.json")
    results_data = load(DATA / "results.json")
    metrics_data = load(DATA / "cfb_metrics.json")
    conditions_path = DATA / "game_conditions.json"
    game_conditions = load(conditions_path) if conditions_path.exists() else {}
    locations = fetch_team_locations()
    forecast_locations = condition_locations(game_conditions)
    results = result_index(results_data)
    team_schedules = schedule_data.get("team_schedules", {})
    power_ranks = {
        name: int(team.get("power_rating_rank"))
        for name, team in metrics_data.get("teams", {}).items()
        if team.get("power_rating_rank")
    }

    contexts: dict[str, Any] = {}
    travel_coverage = 0
    for game in schedule_data.get("games", []):
        game_id = str(game.get("id") or "")
        if not game_id:
            continue
        away = str(game.get("away_team") or "")
        home = str(game.get("home_team") or "")
        away_context = team_context(
            away, home, game, team_schedules.get(away, []), results, power_ranks, locations, forecast_locations
        )
        home_context = team_context(
            home, away, game, team_schedules.get(home, []), results, power_ranks, locations, forecast_locations
        )
        travel_coverage += sum(
            1
            for item in (away_context, home_context)
            if finite_number((item.get("travel") or {}).get("miles_from_campus")) is not None
        )
        contexts[game_id] = {
            "game_id": game_id,
            "week": game.get("week"),
            "away_team": away,
            "home_team": home,
            "conference_game": bool(
                game.get("away_conference")
                and game.get("away_conference") == game.get("home_conference")
            ),
            "neutral_site": bool(game.get("neutral_site")),
            "away": away_context,
            "home": home_context,
        }

    output = {
        "meta": {
            "season": SEASON,
            "version": "schedule-context-v2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_usage": "display_only_not_used_by_model_a",
            "status": "BETA — situational flags are descriptive and historically uncalibrated",
            "team_locations_loaded": len(locations),
            "team_game_travel_estimates": travel_coverage,
            "travel_method": "great-circle estimate from CFBD team/stadium coordinates",
            "included": [
                "rest",
                "road streak",
                "road-game density",
                "return home",
                "previous result",
                "blowout response",
                "lookahead watch",
                "conference familiarity",
                "travel distance",
                "time-zone change",
            ],
            "not_included": ["injury context", "airline routing", "team-specific travel logistics"],
        },
        "games": contexts,
    }
    OUTPUT.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Loaded {len(locations)} FBS team locations from CFBD.")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} for {len(contexts)} games with {travel_coverage} team-game travel estimates.")


if __name__ == "__main__":
    main()
