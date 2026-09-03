"""Fetch current-season plays and build display-only advanced metrics.

This script does not read or write projections, ratings, model weights, or any
other Model A output. It only creates data/advanced_metrics.json.
"""

import json
import os
import sys
import time

import requests

from advanced_metrics import write_advanced_metrics


YEAR = 2026
BASE_URL = "https://api.collegefootballdata.com"
METRICS_PATH = "data/cfb_metrics.json"

TEAM_NAME_ALIASES = {
    "Sam José State": "San Jose State",
    "Sam Jose State": "San Jose State",
    "San José State": "San Jose State",
    "Appalachian State": "App State",
    "Connecticut": "UConn",
    "Louisiana Monroe": "UL Monroe",
    "Southern Mississippi": "Southern Miss",
    "UT San Antonio": "UTSA",
}


def normalize_team(value):
    if value is None:
        return None
    name = str(value).strip()
    return TEAM_NAME_ALIASES.get(name, name)


def first_value(data, *keys, default=None):
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)
    return default


def number(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_api_key(value):
    key = str(value or "").strip().replace("\r", "").replace("\n", "")
    if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
        key = key[1:-1].strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key


def fetch_plays(api_key, week):
    response = requests.get(
        f"{BASE_URL}/plays",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        params={
            "year": YEAR,
            "week": week,
            "seasonType": "regular",
            "classification": "fbs",
        },
        timeout=45,
    )
    if response.status_code in (401, 403):
        raise RuntimeError("CFBD authentication failed")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected CFBD response for Week {week}")
    return payload


def fetch_completed_game_ids(api_key, week):
    response = requests.get(
        f"{BASE_URL}/games",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        params={
            "year": YEAR,
            "week": week,
            "seasonType": "regular",
            "classification": "fbs",
        },
        timeout=45,
    )
    if response.status_code in (401, 403):
        raise RuntimeError("CFBD authentication failed")
    response.raise_for_status()
    games = response.json()
    completed = set()
    for game in games if isinstance(games, list) else []:
        is_complete = first_value(game, "completed", default=False) is True
        has_score = (
            first_value(game, "homePoints", "home_points") is not None
            and first_value(game, "awayPoints", "away_points") is not None
        )
        if is_complete or has_score:
            game_id = first_value(game, "id", "gameId", "game_id")
            if game_id is not None:
                completed.add(str(game_id))
    return completed


def description(play):
    return f"{play.get('play_type', '')} {play.get('play_text', '')}".lower()


def is_excluded(play):
    text = description(play)
    return any(
        phrase in text
        for phrase in (
            "kickoff", "extra point", "timeout", "end of", "coin toss",
            "penalty", "two point", "2-point",
        )
    )


def is_pass(play):
    text = description(play)
    return any(word in text for word in ("pass", "sack", "interception"))


def is_rush(play):
    text = description(play)
    if "sack" in text:
        return False
    return any(word in text for word in ("rush", "run ", "rushed"))


def is_success(play):
    yards = number(play.get("yards_gained"), 0)
    distance = number(play.get("distance"), 10)
    down = int(number(play.get("down"), 1))
    if distance <= 0:
        return False
    if down == 1:
        return yards >= distance * 0.50
    if down == 2:
        return yards >= distance * 0.70
    if down in (3, 4):
        return yards >= distance
    return False


def is_havoc(play):
    text = description(play)
    return any(
        phrase in text
        for phrase in (
            "sack", "interception", "fumble", "tackle for loss", "tfl",
            "pass breakup", "broken up",
        )
    )


def is_garbage_time(play):
    period = int(number(play.get("period"), 1))
    margin = abs(
        number(play.get("offense_score"), 0)
        - number(play.get("defense_score"), 0)
    )
    return (period >= 4 and margin >= 28) or (period >= 3 and margin >= 38)


def normalize_play(raw):
    play = {
        "game_id": first_value(raw, "gameId", "game_id"),
        "offense": normalize_team(first_value(raw, "offense")),
        "defense": normalize_team(first_value(raw, "defense")),
        "home": normalize_team(first_value(raw, "home")),
        "away": normalize_team(first_value(raw, "away")),
        "offense_score": first_value(raw, "offenseScore", "offense_score", default=0),
        "defense_score": first_value(raw, "defenseScore", "defense_score", default=0),
        "period": first_value(raw, "period", default=1),
        "down": first_value(raw, "down"),
        "distance": first_value(raw, "distance"),
        "yards_to_goal": first_value(raw, "yardsToGoal", "yards_to_goal"),
        "yards_gained": first_value(raw, "yardsGained", "yards_gained", default=0),
        "play_type": first_value(raw, "playType", "play_type", default=""),
        "play_text": first_value(raw, "playText", "play_text", default=""),
        "epa": first_value(raw, "ppa"),
    }
    play["is_pass"] = is_pass(play)
    play["is_rush"] = is_rush(play)
    play["success"] = is_success(play)
    yards = number(play.get("yards_gained"), 0)
    play["explosive"] = (
        (play["is_pass"] and yards >= 15)
        or (play["is_rush"] and yards >= 10)
    )
    play["havoc"] = is_havoc(play)
    play["garbage_time"] = is_garbage_time(play)
    return play


def main():
    api_key = clean_api_key(os.environ.get("CFBD_API_KEY"))
    if not api_key:
        print("❌ CFBD_API_KEY is missing")
        sys.exit(1)

    with open(METRICS_PATH, "r", encoding="utf-8") as file:
        metrics = json.load(file)

    teams = set((metrics.get("teams") or {}).keys())
    if len(teams) < 100:
        print("❌ Existing team list contains fewer than 100 teams")
        sys.exit(1)

    through_week = int((metrics.get("meta") or {}).get("through_week") or 0)
    all_plays = []
    raw_count = 0
    completed_game_ids = set()

    print(f"Building display-only advanced metrics through Week {through_week}")
    for week in range(0, through_week + 1):
        week_completed_ids = fetch_completed_game_ids(api_key, week)
        completed_game_ids.update(week_completed_ids)
        raw_plays = fetch_plays(api_key, week)
        raw_count += len(raw_plays)
        accepted = 0
        for raw in raw_plays:
            play = normalize_play(raw)
            if str(play.get("game_id")) not in week_completed_ids:
                continue
            if play["offense"] not in teams or play["defense"] not in teams:
                continue
            if is_excluded(play):
                continue
            if number(play.get("epa")) is None:
                continue
            if not play["is_pass"] and not play["is_rush"]:
                continue
            play["epa"] = number(play["epa"])
            all_plays.append(play)
            accepted += 1
        print(f"   Week {week}: {accepted:,} qualifying plays")
        time.sleep(0.2)

    if not all_plays:
        print("❌ No qualifying FBS plays were returned")
        sys.exit(1)

    write_advanced_metrics(
        all_plays,
        teams,
        through_week,
        len(completed_game_ids),
    )
    print(f"Raw plays received: {raw_count:,}")
    print(f"Qualifying plays written: {len(all_plays):,}")
    print("✅ Model A files were not changed")


if __name__ == "__main__":
    main()
