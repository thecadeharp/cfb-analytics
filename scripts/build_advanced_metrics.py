"""Build display-only advanced metrics from SportsDataverse play-by-play.

The source is the public, analysis-ready 2026 cfbfastR dataset derived from
ESPN play-by-play and enriched with the open cfbfastR EPA model. This script
does not call CFBD and does not read or write any Model A output except for
reading the existing team-name list from data/cfb_metrics.json.
"""

import json
import os
import sys
import tempfile

import pandas as pd
import requests

from advanced_metrics import write_advanced_metrics


YEAR = 2026
METRICS_PATH = "data/cfb_metrics.json"
PBP_URL = (
    "https://raw.githubusercontent.com/sportsdataverse/"
    "cfbfastR-cfb-data/main/cfb/pbp/parquet/play_by_play_2026.parquet"
)

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
    if value is None or pd.isna(value):
        return None
    name = str(value).strip()
    return TEAM_NAME_ALIASES.get(name, name)


def number(value, default=None):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def boolean(value):
    if value is None or pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def download_dataset():
    print("Downloading 2026 SportsDataverse play-by-play...")
    response = requests.get(PBP_URL, timeout=90)
    response.raise_for_status()
    if len(response.content) < 10_000:
        raise RuntimeError("Downloaded play-by-play file is unexpectedly small")

    temp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
    try:
        temp.write(response.content)
        temp.close()
        return pd.read_parquet(temp.name)
    finally:
        if not temp.closed:
            temp.close()
        if os.path.exists(temp.name):
            os.remove(temp.name)


def row_value(row, *columns, default=None):
    for column in columns:
        if column in row.index and not pd.isna(row[column]):
            return row[column]
    return default


def is_garbage_time(period, offense_score, defense_score):
    period = int(number(period, 1))
    margin = abs(number(offense_score, 0) - number(defense_score, 0))
    return (period >= 4 and margin >= 28) or (period >= 3 and margin >= 38)


def normalize_row(row):
    offense = normalize_team(row_value(row, "start.pos_team.name", "pos_team"))
    defense = normalize_team(row_value(row, "start.def_pos_team.name", "def_pos_team"))
    home = normalize_team(row_value(row, "homeTeamName", "home_team"))
    away = normalize_team(row_value(row, "awayTeamName", "away_team"))
    offense_score = row_value(row, "start.pos_team_score", "pos_team_score", default=0)
    defense_score = row_value(row, "start.def_pos_team_score", "def_pos_team_score", default=0)
    period = row_value(row, "period", "period.number", default=1)
    yards = number(row_value(row, "statYardage", "yds_rushed", default=0), 0)
    pass_play = boolean(row_value(row, "pass", "pass_attempt", default=False)) or boolean(
        row_value(row, "sack", default=False)
    )
    rush_play = boolean(row_value(row, "rush", default=False)) and not boolean(
        row_value(row, "sack", default=False)
    )

    success_value = row_value(row, "EPA_success", default=None)
    if success_value is None:
        down = int(number(row_value(row, "down", "start.down", default=1), 1))
        distance = number(row_value(row, "distance", "start.distance", default=10), 10)
        if down == 1:
            success = yards >= distance * 0.50
        elif down == 2:
            success = yards >= distance * 0.70
        else:
            success = yards >= distance
    else:
        success = boolean(success_value)

    return {
        "game_id": str(row_value(row, "game_id", default="")),
        "offense": offense,
        "defense": defense,
        "home": home,
        "away": away,
        "offense_score": number(offense_score, 0),
        "defense_score": number(defense_score, 0),
        "period": int(number(period, 1)),
        "down": number(row_value(row, "down", "start.down")),
        "distance": number(row_value(row, "distance", "start.distance")),
        "yards_to_goal": number(
            row_value(row, "start.yardsToEndzone", "yardsToGoal")
        ),
        "yards_gained": yards,
        "play_type": str(row_value(row, "type.text", "orig_play_type", default="")),
        "play_text": str(row_value(row, "text", "cleaned_text", default="")),
        "epa": number(row_value(row, "EPA", "EPA_scrimmage")),
        "is_pass": pass_play,
        "is_rush": rush_play,
        "success": success,
        "explosive": (pass_play and yards >= 15) or (rush_play and yards >= 10),
        "havoc": boolean(row_value(row, "havoc", default=False)),
        "garbage_time": is_garbage_time(period, offense_score, defense_score),
    }


def main():
    with open(METRICS_PATH, "r", encoding="utf-8") as file:
        metrics = json.load(file)

    teams = set((metrics.get("teams") or {}).keys())
    if len(teams) < 100:
        print("❌ Existing team list contains fewer than 100 teams")
        sys.exit(1)

    frame = download_dataset()
    required = {"game_id", "pos_team", "def_pos_team", "EPA"}
    missing = required.difference(frame.columns)
    if missing:
        raise RuntimeError(f"SportsDataverse schema missing columns: {sorted(missing)}")

    if "status_type_completed" in frame.columns:
        frame = frame[frame["status_type_completed"].map(boolean)]
    if "season" in frame.columns:
        frame = frame[pd.to_numeric(frame["season"], errors="coerce") == YEAR]

    plays = []
    for _, row in frame.iterrows():
        play = normalize_row(row)
        if play["offense"] not in teams or play["defense"] not in teams:
            continue
        if play["epa"] is None:
            continue
        if not play["is_pass"] and not play["is_rush"]:
            continue
        plays.append(play)

    if not plays:
        print("❌ No qualifying completed-game plays were available")
        sys.exit(1)

    through_week = int(pd.to_numeric(frame.get("week"), errors="coerce").max() or 0)
    completed_games = len({play["game_id"] for play in plays})
    write_advanced_metrics(plays, teams, through_week, completed_games)

    print(f"Source rows: {len(frame):,}")
    print(f"Qualifying FBS scrimmage plays: {len(plays):,}")
    print(f"Completed games represented: {completed_games}")
    print("✅ No CFBD calls were made")
    print("✅ Model A files were not changed")


if __name__ == "__main__":
    main()
