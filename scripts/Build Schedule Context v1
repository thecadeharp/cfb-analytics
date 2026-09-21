#!/usr/bin/env python3
"""Build display-only schedule and situational context for every FBS game."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "schedule_context.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_date(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


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


def team_result(team: str, game: dict[str, Any], results: dict[tuple[int, tuple[str, str]], dict[str, Any]]) -> dict[str, Any] | None:
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


def team_context(
    team: str,
    opponent: str,
    game: dict[str, Any],
    schedule: list[dict[str, Any]],
    results: dict[tuple[int, tuple[str, str]], dict[str, Any]],
    power_ranks: dict[str, int],
) -> dict[str, Any]:
    ordered = sorted(schedule, key=lambda row: str(row.get("start_date") or ""))
    current_index = next((index for index, row in enumerate(ordered) if str(row.get("id")) == str(game.get("id"))), None)
    if current_index is None:
        return {"team": team, "flags": []}

    current = ordered[current_index]
    previous = ordered[current_index - 1] if current_index > 0 else None
    previous_two = ordered[max(0, current_index - 2):current_index]
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

    prior_result = team_result(team, previous, results) if previous else None
    opponent_rank = power_ranks.get(opponent)
    next_opponent = str(following.get("opponent") or "") if following else None
    next_rank = power_ranks.get(next_opponent) if next_opponent else None
    flags: list[dict[str, str]] = []

    if rest_days is not None and rest_days <= 6:
        flags.append({"type": "short_rest", "label": f"Short rest ({rest_days} days)"})
    if rest_days is not None and rest_days >= 12:
        flags.append({"type": "extended_rest", "label": f"Extended rest ({rest_days} days)"})
    if current.get("location") == "away" and road_streak >= 1:
        flags.append({"type": "road_streak", "label": f"Road game #{road_streak + 1} in a row"})
    if current.get("location") == "home" and previous and previous.get("location") == "away":
        label = "Home after a road game"
        if len(previous_two) == 2 and all(item.get("location") == "away" for item in previous_two):
            label = "Home after consecutive road games"
        flags.append({"type": "return_home", "label": label})
    if prior_result and prior_result["margin"] <= -21:
        flags.append({"type": "off_blowout_loss", "label": "Coming off a 21+ point loss"})
    if prior_result and prior_result["margin"] >= 21:
        flags.append({"type": "off_blowout_win", "label": "Coming off a 21+ point win"})
    if next_rank and next_rank <= 25 and (opponent_rank is None or opponent_rank > 50):
        flags.append({"type": "lookahead_watch", "label": f"Top-25 opponent next: {next_opponent}"})
