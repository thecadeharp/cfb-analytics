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

    return {
        "team": team,
        "location": current.get("location"),
        "rest_days": rest_days,
        "consecutive_road_games_entering": road_streak,
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
    results = result_index(results_data)
    team_schedules = schedule_data.get("team_schedules", {})
    power_ranks = {
        name: int(team.get("power_rating_rank"))
        for name, team in metrics_data.get("teams", {}).items()
        if team.get("power_rating_rank")
    }

    contexts: dict[str, Any] = {}
    for game in schedule_data.get("games", []):
        game_id = str(game.get("id") or "")
        if not game_id:
            continue
        away = str(game.get("away_team") or "")
        home = str(game.get("home_team") or "")
        away_context = team_context(away, home, game, team_schedules.get(away, []), results, power_ranks)
        home_context = team_context(home, away, game, team_schedules.get(home, []), results, power_ranks)
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
            "season": 2026,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_usage": "display_only_not_used_by_model_a",
            "status": "BETA — situational flags are descriptive and historically uncalibrated",
            "included": ["rest", "road streak", "return home", "previous result", "blowout response", "lookahead watch", "conference familiarity"],
            "not_yet_included": ["travel distance", "time zones crossed", "injury context"],
        },
        "games": contexts,
    }
    OUTPUT.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} for {len(contexts)} games.")


if __name__ == "__main__":
    main()
