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
    if period <= 2:
        return margin >= 38
    if period == 3:
        return margin >= 28
    return margin >= 22


def normalize_row(row):
    offense = normalize_team(row_value(row, "start.pos_team.name", "pos_team"))
    defense = normalize_team(row_value(row, "start.def_pos_team.name", "def_pos_team"))
    home = normalize_team(row_value(row, "homeTeamName", "home_team"))
    away = normalize_team(row_value(row, "awayTeamName", "away_team"))
    offense_score = row_value(row, "start.pos_team_score", "pos_team_score", default=0)
    defense_score = row_value(row, "start.def_pos_team_score", "def_pos_team_score", default=0)
    period = row_value(row, "period", "period.number", default=1)
    play_type = str(row_value(row, "type.text", "orig_play_type", default=""))
    play_text = str(row_value(row, "text", "cleaned_text", default=""))
    description = f"{play_type} {play_text}".lower()
    yards = number(row_value(row, "statYardage", "yds_rushed", default=0), 0)
    pass_play = boolean(row_value(row, "pass", "pass_attempt", default=False)) or boolean(
        row_value(row, "sack", default=False)
    )
    rush_play = boolean(row_value(row, "rush", default=False)) and not boolean(
        row_value(row, "sack", default=False)
    )

    # New situational research uses the same play-start fields as the
    # historical builder. Missing values must never become a 0-0 game or a
    # first-and-10 play merely because older display metrics have fallbacks.
    start_down = number(row_value(row, "start.down"))
    start_distance = number(row_value(row, "start.distance"))
    start_home_score = number(row_value(row, "start.homeScore"))
    start_away_score = number(row_value(row, "start.awayScore"))
    clock_minute = number(row_value(row, "clock.minutes"))
    clock_second = number(row_value(row, "clock.seconds"))
    period_number = number(period)
    situational_valid = (
        period_number is not None and period_number in (1, 2, 3, 4)
        and number(row_value(row, "seasonType")) == 2
        and start_down in (1, 2, 3, 4) and start_distance is not None
        and start_home_score is not None and start_away_score is not None
        and clock_minute is not None and clock_second is not None
        and 0 <= clock_minute <= 15 and 0 <= clock_second <= 59
        and (clock_minute != 15 or clock_second == 0)
        and boolean(row_value(row, "scrimmage_play", default=True))
        and boolean(row_value(row, "action_play", default=True))
        and not boolean(row_value(row, "kneel_down", default=False))
        and not boolean(row_value(row, "penalty_no_play", default=False))
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
        "drive_id": row_value(row, "drive_id", "drive.id", "driveId"),
        "offense": offense,
        "defense": defense,
        "home": home,
        "away": away,
        "offense_score": number(offense_score, 0),
        "offense_score_after": number(
            row_value(
                row,
                "end.pos_team_score",
                "end.pos_team.score",
                "pos_team_score_after",
                default=offense_score,
            ),
            number(offense_score, 0),
        ),
        "defense_score": number(defense_score, 0),
        "period": int(number(period, 1)),
        "down": number(row_value(row, "down", "start.down")),
        "distance": number(row_value(row, "distance", "start.distance")),
        "situational_down": start_down,
        "situational_distance": start_distance,
        "yards_to_goal": number(
            row_value(row, "start.yardsToEndzone", "yardsToGoal")
        ),
        "yards_gained": yards,
        "play_type": play_type,
        "play_text": play_text,
        "epa": number(row_value(row, "EPA", "EPA_scrimmage")),
        "is_pass": pass_play,
        "is_rush": rush_play,
        "success": success,
        "situational_success": boolean(success_value) if success_value is not None else None,
        "explosive": (pass_play and yards >= 15) or (rush_play and yards >= 10),
        "sack": boolean(row_value(row, "sack", "is_sack", default=False)) or "sack" in description,
        "tfl": (
            boolean(row_value(row, "tackle_for_loss", "tfl", default=False))
            or "tackle for loss" in description
            or yards < 0
        ),
        "fumble": boolean(row_value(row, "fumble", default=False)) or "fumble" in description,
        "fumble_lost": boolean(row_value(row, "fumble_lost", "fumbleLost", default=False)) or "fumble lost" in description,
        "forced_fumble": boolean(row_value(row, "forced_fumble", default=False)) or "forced fumble" in description,
        "pass_breakup": boolean(row_value(row, "pass_breakup", "pbu", default=False)) or "broken up" in description,
        "touchdown": boolean(row_value(row, "touchdown", default=False)) or "touchdown" in description,
        "havoc": boolean(row_value(row, "havoc", default=False)),
        "garbage_time": is_garbage_time(period, offense_score, defense_score),
        "situational_valid": situational_valid,
        "situational_garbage_time": (
            is_garbage_time(period, start_home_score, start_away_score)
            if situational_valid else True
        ),
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
    required.update({
        "seasonType", "period", "start.down", "start.distance", "start.yardsToEndzone",
        "start.homeScore", "start.awayScore", "clock.minutes", "clock.seconds",
    })
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
