#!/usr/bin/env python3
"""
THE HAMMER INDEX
build_postgame_analytics.py

Canonical postgame analytics builder for The Hammer Index.

Builds a retrospective per-game package for every FINAL in data/results.json
using the public SportsDataverse/cfbfastR 2026 play-by-play parquet.

CANONICAL POSTGAME METRICS
- EPA/play and total EPA
- Pass and rush EPA
- Pass and rush success rates
- Explosive-play rate and EPA dependency
- Standard-down and passing-down EPA/success
- Early-down and third/fourth-down performance
- Fourth-down attempts, success rate, and EPA
- Sack rate allowed
- Stuff rate allowed
- TFL rate allowed
- Drive efficiency and drive success rate
- Three-and-out rate
- Scoring-opportunity efficiency
- Red-zone trips and points per trip
- Red-zone overperformance
- Average starting field position
- Turnover EPA impact
- Garbage-time share
- EPA volatility
- Postgame Win Expectancy
- Adjusted Final Score
- THI Reality Check

SAFETY
- No CFBD calls.
- Does not modify Model A.
- Does not rewrite frozen pregame projections.
- Every final receives a postgame record.
- If matching PBP has not arrived yet, the record is pending and automatically
  retried by the existing settlement workflow.
- Postgame Win Expectancy / Adjusted Final Score / Red-Zone Overperformance are
  explicitly BETA until historical calibration is completed.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = ROOT / "data" / "results.json"
OUTPUT_PATH = ROOT / "data" / "postgame_analytics.json"

YEAR = int(os.getenv("CFB_SEASON", "2026"))

PBP_URL = (
    "https://raw.githubusercontent.com/sportsdataverse/"
    f"cfbfastR-cfb-data/main/cfb/pbp/parquet/play_by_play_{YEAR}.parquet"
)

PENDING_RETRY_MINUTES = 15
RED_ZONE_EXPECTED_POINTS_PER_TRIP_BETA = 4.7

SESSION = requests.Session()
SESSION.headers.update(
    {
        "Accept": "*/*",
        "User-Agent": "the-hammer-index-postgame/2.0",
    }
)


# =============================================================================
# BASIC HELPERS
# =============================================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return payload if isinstance(payload, dict) else fallback


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def clean_number(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or pd.isna(value):
            return default
        number = float(value)
        if not math.isfinite(number):
            return default
        return number
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int | None = None) -> int | None:
    number = clean_number(value)
    return int(number) if number is not None else default


def as_bool(value: Any) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except TypeError:
        pass
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "t"}
    return bool(value)


def pct(value: float | None, digits: int = 1) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value * 100.0, digits)


def rnd(value: float | None, digits: int = 2) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def population_std(values: list[float]) -> float | None:
    if not values:
        return None
    avg = sum(values) / len(values)
    variance = sum((value - avg) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def first_present(row: pd.Series, *names: str, default: Any = None) -> Any:
    for name in names:
        if name not in row.index:
            continue
        value = row[name]
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        if value is not None and value != "":
            return value
    return default


# =============================================================================
# TEAM NORMALIZATION
# =============================================================================

DISPLAY_ALIASES = {
    "Sam José State": "San Jose State",
    "Sam Jose State": "San Jose State",
    "San José State": "San Jose State",
    "Appalachian State": "App State",
    "Connecticut": "UConn",
    "Louisiana Monroe": "UL Monroe",
    "Southern Mississippi": "Southern Miss",
    "UT San Antonio": "UTSA",
    "Ark.-Pine Bluff": "Arkansas Pine Bluff",
    "Arkansas-Pine Bluff": "Arkansas Pine Bluff",
    "N.C. A&T": "North Carolina A&T",
    "NC A&T": "North Carolina A&T",
    "Georgia St.": "Georgia State",
    "LIU": "Long Island University",
}


def display_team(value: Any) -> str:
    text = str(value or "").strip()
    return DISPLAY_ALIASES.get(text, text)


def team_key(value: Any) -> str:
    text = display_team(value).lower()
    text = (
        text.replace("&", "and")
        .replace("’", "'")
        .replace("é", "e")
        .replace("í", "i")
    )
    text = re.sub(r"\buniversity\b", "", text)
    text = re.sub(r"\bst\.?\b", "state", text)
    text = re.sub(r"\bmich\.?\b", "michigan", text)
    text = re.sub(r"[^a-z0-9]+", "", text)

    aliases = {
        "umass": "massachusetts",
        "usc": "southerncalifornia",
        "southerncal": "southerncalifornia",
        "miamifla": "miami",
        "miamiflorida": "miami",
        "olemiss": "mississippi",
        "southernmiss": "southernmississippi",
        "appstate": "appalachianstate",
        "uconn": "connecticut",
        "ulmonroe": "louisianamonroe",
        "utsa": "texassanantonio",
        "utep": "texaselpaso",
        "ucf": "centralflorida",
        "byu": "brighamyoung",
        "lsu": "louisianastate",
        "smu": "southernmethodist",
        "tcu": "texaschristian",
        "arkpinebluff": "arkansaspinebluff",
        "liu": "longisland",
        "longislanduniversity": "longisland",
        "ncandt": "northcarolinaandt",
        "georgiast": "georgiastate",
    }
    return aliases.get(text, text)


def matchup_key(away: Any, home: Any) -> str:
    away_key = team_key(away)
    home_key = team_key(home)
    return f"{away_key}@{home_key}" if away_key and home_key else ""


def same_team(a: Any, b: Any) -> bool:
    return team_key(a) == team_key(b)


# =============================================================================
# PBP DOWNLOAD / NORMALIZATION
# =============================================================================

def download_pbp() -> pd.DataFrame:
    print(f"Downloading SportsDataverse/cfbfastR {YEAR} PBP...")
    response = SESSION.get(PBP_URL, timeout=120)
    response.raise_for_status()

    if len(response.content) < 10_000:
        raise RuntimeError("PBP parquet download was unexpectedly small")

    temp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
    path = temp.name
    try:
        temp.write(response.content)
        temp.close()
        return pd.read_parquet(path)
    finally:
        try:
            temp.close()
        except Exception:
            pass
        if os.path.exists(path):
            os.remove(path)


def infer_score_after(
    row: pd.Series,
    offense_score: float,
    defense_score: float,
) -> tuple[float, float]:
    off_after = clean_number(
        first_present(
            row,
            "end.pos_team_score",
            "end_pos_team_score",
            "pos_team_score_after",
            "offense_score_after",
        )
    )
    def_after = clean_number(
        first_present(
            row,
            "end.def_pos_team_score",
            "end_def_pos_team_score",
            "defense_score_after",
        )
    )
    return (
        off_after if off_after is not None else offense_score,
        def_after if def_after is not None else defense_score,
    )


def infer_turnover(row: pd.Series, play_type: str, text: str) -> bool:
    explicit = any(
        as_bool(first_present(row, column, default=False))
        for column in (
            "turnover",
            "is_turnover",
            "fumble_lost",
            "fumbleLost",
            "interception",
            "interception_thrown",
            "interceptionThrown",
        )
    )
    if explicit:
        return True

    blob = f"{play_type} {text}".lower()
    if "intercepted" in blob or "interception" in blob:
        return True
    if "fumble" in blob and (
        "lost" in blob
        or "recovered by" in blob
        or "turnover" in blob
    ):
        return True
    return False


def infer_touchdown(row: pd.Series, play_type: str, text: str) -> bool:
    if any(
        as_bool(first_present(row, column, default=False))
        for column in ("touchdown", "td", "is_touchdown")
    ):
        return True
    return "touchdown" in f"{play_type} {text}".lower()


def infer_field_goal(row: pd.Series, play_type: str, text: str) -> bool:
    if any(
        as_bool(first_present(row, column, default=False))
        for column in ("field_goal_made", "fg_made", "fieldGoalMade")
    ):
        return True
    blob = f"{play_type} {text}".lower()
    return "field goal" in blob and any(
        token in blob for token in ("good", "made", "is good")
    )


def infer_sack(row: pd.Series, play_type: str, text: str) -> bool:
    if as_bool(first_present(row, "sack", "is_sack", default=False)):
        return True
    blob = f"{play_type} {text}".lower()
    return "sacked" in blob or "sack" in play_type.lower()


def infer_tfl(row: pd.Series, yards: float, play_type: str, text: str) -> bool:
    if any(
        as_bool(first_present(row, column, default=False))
        for column in (
            "tackle_for_loss",
            "tackleForLoss",
            "tfl",
            "TFL",
        )
    ):
        return True
    blob = f"{play_type} {text}".lower()
    if "tackle for loss" in blob:
        return True
    return yards < 0


def infer_first_down(
    row: pd.Series,
    yards: float,
    down: int | None,
    distance: float | None,
    play_type: str,
    text: str,
) -> bool:
    if any(
        as_bool(first_present(row, column, default=False))
        for column in (
            "first_down",
            "firstDown",
            "first_down_rush",
            "first_down_pass",
        )
    ):
        return True

    blob = f"{play_type} {text}".lower()
    if "first down" in blob:
        return True

    return (
        down is not None
        and distance is not None
        and distance > 0
        and yards >= distance
    )


def is_garbage_time(
    period: int,
    offense_score: float,
    defense_score: float,
) -> bool:
    margin = abs(offense_score - defense_score)
    return (period >= 4 and margin >= 28) or (period >= 3 and margin >= 38)


def normalize_play(row: pd.Series, row_index: int) -> dict[str, Any] | None:
    offense = display_team(
        first_present(row, "start.pos_team.name", "pos_team", "offense")
    )
    defense = display_team(
        first_present(row, "start.def_pos_team.name", "def_pos_team", "defense")
    )
    home = display_team(
        first_present(row, "homeTeamName", "home_team", "homeTeam")
    )
    away = display_team(
        first_present(row, "awayTeamName", "away_team", "awayTeam")
    )

    if not offense or not defense:
        return None

    game_id = str(first_present(row, "game_id", "gameId", default="")).strip()
    if not game_id:
        return None

    offense_score = clean_number(
        first_present(
            row,
            "start.pos_team_score",
            "pos_team_score",
            "offense_score",
            default=0,
        ),
        0,
    ) or 0.0
    defense_score = clean_number(
        first_present(
            row,
            "start.def_pos_team_score",
            "def_pos_team_score",
            "defense_score",
            default=0,
        ),
        0,
    ) or 0.0

    off_after, def_after = infer_score_after(
        row,
        offense_score,
        defense_score,
    )

    period = as_int(
        first_present(row, "period", "period.number", default=1),
        1,
    ) or 1

    down = as_int(first_present(row, "down", "start.down"))
    distance = clean_number(
        first_present(row, "distance", "start.distance")
    )
    yards_to_goal = clean_number(
        first_present(
            row,
            "start.yardsToEndzone",
            "yardsToGoal",
            "yards_to_goal",
        )
    )
    yards = clean_number(
        first_present(
            row,
            "statYardage",
            "yards_gained",
            "yds_rushed",
            default=0,
        ),
        0,
    ) or 0.0

    play_type = str(
        first_present(
            row,
            "type.text",
            "orig_play_type",
            "play_type",
            default="",
        )
    )
    play_text = str(
        first_present(
            row,
            "text",
            "cleaned_text",
            "play_text",
            default="",
        )
    )

    epa = clean_number(
        first_present(row, "EPA", "EPA_scrimmage", "epa")
    )
    if epa is None:
        return None

    sack = infer_sack(row, play_type, play_text)

    is_pass = (
        as_bool(first_present(row, "pass", "pass_attempt", default=False))
        or sack
    )
    is_rush = (
        as_bool(first_present(row, "rush", "rush_attempt", default=False))
        and not sack
    )

    lower_blob = f"{play_type} {play_text}".lower()
    if not is_pass and not is_rush:
        if any(
            token in lower_blob
            for token in (
                "pass ",
                "pass complete",
                "pass incomplete",
                "sacked",
            )
        ):
            is_pass = True
        elif any(
            token in lower_blob
            for token in ("rush", "run for", "rushed")
        ):
            is_rush = True

    if not is_pass and not is_rush:
        return None

    success_raw = first_present(
        row,
        "EPA_success",
        "success",
        default=None,
    )

    if success_raw is not None:
        success = as_bool(success_raw)
    else:
        if down is None or distance is None or distance <= 0:
            success = epa > 0
        elif down == 1:
            success = yards >= distance * 0.50
        elif down == 2:
            success = yards >= distance * 0.70
        else:
            success = yards >= distance

    explosive = (
        (is_pass and yards >= 15)
        or (is_rush and yards >= 10)
    )

    # Standard-down definition:
    # 1st down; 2nd-and-7 or less; 3rd/4th-and-4 or less.
    standard_down = (
        down == 1
        or (down == 2 and distance is not None and distance <= 7)
        or (
            down in {3, 4}
            and distance is not None
            and distance <= 4
        )
    )

    passing_down = (
        (down == 2 and distance is not None and distance >= 8)
        or (
            down in {3, 4}
            and distance is not None
            and distance >= 5
        )
    )

    drive_id = first_present(
        row,
        "drive_id",
        "driveId",
        "start.drive.id",
        "drive_number",
        "driveNumber",
    )

    return {
        "row_index": row_index,
        "game_id": game_id,
        "offense": offense,
        "defense": defense,
        "home": home,
        "away": away,
        "offense_score": offense_score,
        "defense_score": defense_score,
        "offense_score_after": off_after,
        "defense_score_after": def_after,
        "period": period,
        "down": down,
        "distance": distance,
        "yards_to_goal": yards_to_goal,
        "yards_gained": yards,
        "epa": epa,
        "success": bool(success),
        "is_pass": bool(is_pass),
        "is_rush": bool(is_rush),
        "sack": bool(sack),
        "stuff": bool(is_rush and yards <= 0),
        "tfl": infer_tfl(row, yards, play_type, play_text),
        "first_down": infer_first_down(
            row,
            yards,
            down,
            distance,
            play_type,
            play_text,
        ),
        "explosive": bool(explosive),
        "standard_down": bool(standard_down),
        "passing_down": bool(passing_down),
        "early_down": down in {1, 2},
        "money_down": down in {3, 4},
        "fourth_down": down == 4,
        "turnover": infer_turnover(row, play_type, play_text),
        "touchdown": infer_touchdown(row, play_type, play_text),
        "field_goal": infer_field_goal(row, play_type, play_text),
        "garbage_time": is_garbage_time(
            period,
            offense_score,
            defense_score,
        ),
        "drive_id": str(drive_id) if drive_id is not None else None,
    }


def normalize_frame(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if "season" in frame.columns:
        season = pd.to_numeric(frame["season"], errors="coerce")
        frame = frame[season == YEAR]

    plays: list[dict[str, Any]] = []
    for index, (_, row) in enumerate(frame.iterrows()):
        play = normalize_play(row, index)
        if play is not None:
            plays.append(play)
    return plays


# =============================================================================
# GAME MATCHING
# =============================================================================

def build_game_index(
    plays: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for play in plays:
        grouped[play["game_id"]].append(play)

    games: dict[str, dict[str, Any]] = {}

    for game_id, rows in grouped.items():
        rows.sort(key=lambda play: play["row_index"])

        home = next(
            (play["home"] for play in rows if play.get("home")),
            "",
        )
        away = next(
            (play["away"] for play in rows if play.get("away")),
            "",
        )

        if not home or not away:
            participants: list[str] = []
            for play in rows:
                for team in (
                    play.get("offense"),
                    play.get("defense"),
                ):
                    if team and team not in participants:
                        participants.append(team)

            if len(participants) >= 2:
                away = away or participants[0]
                home = home or participants[1]

        games[game_id] = {
            "game_id": game_id,
            "away": away,
            "home": home,
            "matchup_key": matchup_key(away, home),
            "plays": rows,
        }

    return games


def find_pbp_game(
    final: dict[str, Any],
    games: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    provider_id = str(final.get("game_id") or "")

    if provider_id and provider_id in games:
        return games[provider_id]

    target = matchup_key(
        final.get("away_team"),
        final.get("home_team"),
    )

    if target:
        exact = [
            game
            for game in games.values()
            if game.get("matchup_key") == target
        ]
        if len(exact) == 1:
            return exact[0]

    reverse = matchup_key(
        final.get("home_team"),
        final.get("away_team"),
    )

    if reverse:
        exact = [
            game
            for game in games.values()
            if game.get("matchup_key") == reverse
        ]
        if len(exact) == 1:
            return exact[0]

    return None


# =============================================================================
# DRIVE HELPERS
# =============================================================================

def assign_drive_keys(plays: list[dict[str, Any]]) -> None:
    inferred_sequence = 0
    previous_offense = None
    previous_provider_drive = None

    for play in plays:
        explicit = play.get("drive_id")

        if explicit:
            play["_drive_key"] = f"provider:{explicit}"
            previous_offense = play.get("offense")
            previous_provider_drive = explicit
            continue

        offense = play.get("offense")

        if previous_offense is None or offense != previous_offense:
            inferred_sequence += 1

        play["_drive_key"] = (
            f"inferred:{inferred_sequence}:{team_key(offense)}"
        )
        previous_offense = offense
        previous_provider_drive = None


def drive_points(rows: list[dict[str, Any]]) -> float:
    before = float(rows[0].get("offense_score") or 0)
    after = max(
        float(
            play.get("offense_score_after")
            or play.get("offense_score")
            or 0
        )
        for play in rows
    )

    points = max(0.0, after - before)

    if points <= 0:
        if any(play.get("touchdown") for play in rows):
            points = 7.0
        elif any(play.get("field_goal") for play in rows):
            points = 3.0

    return points


def summarize_drives(
    plays: list[dict[str, Any]],
    team: str,
) -> dict[str, Any]:
    offense_plays = [
        play
        for play in plays
        if same_team(play.get("offense"), team)
    ]

    drives: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for play in offense_plays:
        drives[play["_drive_key"]].append(play)

    drive_count = len(drives)
    scoring_drives = 0
    positive_epa_drives = 0
    three_and_outs = 0
    scoring_opportunities = 0
    scoring_opportunity_points = 0.0
    red_zone_trips = 0
    red_zone_points = 0.0
    points_total = 0.0
    yards_total = 0.0
    start_yards_to_goal: list[float] = []

    for rows in drives.values():
        rows.sort(key=lambda play: play["row_index"])

        if rows[0].get("yards_to_goal") is not None:
            start_yards_to_goal.append(
                float(rows[0]["yards_to_goal"])
            )

        drive_epa = sum(
            float(play.get("epa") or 0)
            for play in rows
        )

        if drive_epa > 0:
            positive_epa_drives += 1

        yards = sum(
            float(play.get("yards_gained") or 0)
            for play in rows
        )
        yards_total += yards

        points = drive_points(rows)
        points_total += points

        if points > 0:
            scoring_drives += 1

        opportunity = any(
            play.get("yards_to_goal") is not None
            and float(play["yards_to_goal"]) <= 40
            for play in rows
        )

        if opportunity:
            scoring_opportunities += 1
            scoring_opportunity_points += points

        red_zone_trip = any(
            play.get("yards_to_goal") is not None
            and float(play["yards_to_goal"]) <= 20
            for play in rows
        )

        if red_zone_trip:
            red_zone_trips += 1
            red_zone_points += points

        scrimmage_count = len(rows)
        earned_first_down = any(
            play.get("first_down")
            for play in rows
        )

        if (
            scrimmage_count <= 3
            and not earned_first_down
            and points <= 0
        ):
            three_and_outs += 1

    points_per_drive = (
        points_total / drive_count
        if drive_count
        else None
    )

    drive_success_rate = (
        positive_epa_drives / drive_count
        if drive_count
        else None
    )

    three_and_out_rate = (
        three_and_outs / drive_count
        if drive_count
        else None
    )

    points_per_opportunity = (
        scoring_opportunity_points / scoring_opportunities
        if scoring_opportunities
        else None
    )

    red_zone_points_per_trip = (
        red_zone_points / red_zone_trips
        if red_zone_trips
        else None
    )

    red_zone_overperformance = (
        red_zone_points_per_trip
        - RED_ZONE_EXPECTED_POINTS_PER_TRIP_BETA
        if red_zone_points_per_trip is not None
        else None
    )

    return {
        "drives": drive_count,
        "scoring_drives": scoring_drives,
        "points_per_drive": points_per_drive,
        "yards_per_drive": (
            yards_total / drive_count
            if drive_count
            else None
        ),
        "drive_success_rate": drive_success_rate,
        "three_and_outs": three_and_outs,
        "three_and_out_rate": three_and_out_rate,
        "scoring_opportunities": scoring_opportunities,
        "points_per_scoring_opportunity": points_per_opportunity,
        "red_zone_trips": red_zone_trips,
        "red_zone_points_per_trip": red_zone_points_per_trip,
        "red_zone_overperformance": red_zone_overperformance,
        "avg_start_yards_to_goal": mean(start_yards_to_goal),
    }


# =============================================================================
# TEAM / SPLIT METRICS
# =============================================================================

def split_summary(
    plays: list[dict[str, Any]],
) -> dict[str, Any]:
    if not plays:
        return {
            "plays": 0,
            "epa_total": None,
            "epa_per_play": None,
            "success_rate": None,
        }

    epa_values = [
        float(play["epa"])
        for play in plays
    ]

    return {
        "plays": len(plays),
        "epa_total": sum(epa_values),
        "epa_per_play": mean(epa_values),
        "success_rate": (
            sum(1 for play in plays if play["success"])
            / len(plays)
        ),
    }


def team_summary(
    competitive_plays: list[dict[str, Any]],
    all_plays: list[dict[str, Any]],
    team: str,
) -> dict[str, Any]:
    offense = [
        play
        for play in competitive_plays
        if same_team(play.get("offense"), team)
    ]

    offense_all = [
        play
        for play in all_plays
        if same_team(play.get("offense"), team)
    ]

    pass_plays = [
        play for play in offense
        if play["is_pass"]
    ]
    rush_plays = [
        play for play in offense
        if play["is_rush"]
    ]
    standard_downs = [
        play for play in offense
        if play["standard_down"]
    ]
    passing_downs = [
        play for play in offense
        if play["passing_down"]
    ]
    early_downs = [
        play for play in offense
        if play["early_down"]
    ]
    money_downs = [
        play for play in offense
        if play["money_down"]
    ]
    fourth_downs = [
        play for play in offense
        if play["fourth_down"]
    ]

    overall = split_summary(offense)
    passing = split_summary(pass_plays)
    rushing = split_summary(rush_plays)
    standard = split_summary(standard_downs)
    passing_down = split_summary(passing_downs)
    early = split_summary(early_downs)
    money = split_summary(money_downs)
    fourth = split_summary(fourth_downs)

    explosive_plays = [
        play for play in offense
        if play["explosive"]
    ]

    positive_epa = sum(
        max(float(play["epa"]), 0.0)
        for play in offense
    )
    explosive_positive_epa = sum(
        max(float(play["epa"]), 0.0)
        for play in explosive_plays
    )

    sacks = sum(
        1 for play in pass_plays
        if play["sack"]
    )
    sack_rate_allowed = (
        sacks / len(pass_plays)
        if pass_plays
        else None
    )

    stuff_count = sum(
        1 for play in rush_plays
        if play["stuff"]
    )
    stuff_rate_allowed = (
        stuff_count / len(rush_plays)
        if rush_plays
        else None
    )

    tfl_count = sum(
        1 for play in offense
        if play["tfl"]
    )
    tfl_rate_allowed = (
        tfl_count / len(offense)
        if offense
        else None
    )

    turnovers = [
        play for play in offense_all
        if play["turnover"]
    ]
    turnover_epa = sum(
        float(play["epa"])
        for play in turnovers
    )

    epa_values = [
        float(play["epa"])
        for play in offense
    ]

    drive = summarize_drives(
        all_plays,
        team,
    )

    return {
        "overall": overall,
        "passing": passing,
        "rushing": rushing,
        "standard_downs": standard,
        "passing_downs": passing_down,
        "early_downs": early,
        "money_downs": money,
        "fourth_downs": fourth,
        "explosive_plays": len(explosive_plays),
        "explosive_rate": (
            len(explosive_plays) / len(offense)
            if offense
            else None
        ),
        "explosive_epa_dependency": (
            explosive_positive_epa / positive_epa
            if positive_epa > 0
            else None
        ),
        "sacks_allowed": sacks,
        "sack_rate_allowed": sack_rate_allowed,
        "stuffs_allowed": stuff_count,
        "stuff_rate_allowed": stuff_rate_allowed,
        "tfl_allowed": tfl_count,
        "tfl_rate_allowed": tfl_rate_allowed,
        "turnovers": len(turnovers),
        "turnover_epa_impact": turnover_epa,
        "epa_volatility": population_std(epa_values),
        **drive,
    }


# =============================================================================
# HEADLINE RETROSPECTIVE METRICS
# =============================================================================

def quality_margin(
    home: dict[str, Any],
    away: dict[str, Any],
) -> float:
    """
    BETA retrospective quality margin.

    Uses only process metrics from the game. Historical evaluation/calibration
    will tune or replace these coefficients.
    """
    home_overall = home["overall"]
    away_overall = away["overall"]

    epa_diff = (
        (home_overall.get("epa_per_play") or 0)
        - (away_overall.get("epa_per_play") or 0)
    )

    success_diff = (
        (home_overall.get("success_rate") or 0)
        - (away_overall.get("success_rate") or 0)
    )

    explosive_diff = (
        (home.get("explosive_rate") or 0)
        - (away.get("explosive_rate") or 0)
    )

    drive_success_diff = (
        (home.get("drive_success_rate") or 0)
        - (away.get("drive_success_rate") or 0)
    )

    opportunity_diff = (
        (home.get("scoring_opportunities") or 0)
        - (away.get("scoring_opportunities") or 0)
    )

    home_start = home.get("avg_start_yards_to_goal")
    away_start = away.get("avg_start_yards_to_goal")

    field_position_edge = 0.0

    if home_start is not None and away_start is not None:
        field_position_edge = away_start - home_start

    turnover_epa_edge = (
        (home.get("turnover_epa_impact") or 0)
        - (away.get("turnover_epa_impact") or 0)
    )

    margin = (
        12.0 * epa_diff
        + 26.0 * success_diff
        + 12.0 * explosive_diff
        + 10.0 * drive_success_diff
        + 1.10 * opportunity_diff
        + 0.16 * field_position_edge
        + 0.35 * turnover_epa_edge
    )

    return clamp(
        margin,
        -42.0,
        42.0,
    )


def postgame_win_expectancy(
    home_quality_margin: float,
) -> float:
    return 1.0 / (
        1.0
        + math.exp(
            -home_quality_margin / 7.5
        )
    )


def adjusted_score(
    actual_home: int,
    actual_away: int,
    home: dict[str, Any],
    away: dict[str, Any],
    quality_margin_home: float,
) -> tuple[float, float]:
    """
    BETA adjusted final score.

    Expected scoring level comes from drive/opportunity quality and is stabilized
    by the actual total only enough to avoid absurd tiny-sample outputs.
    """
    total_opportunities = (
        (home.get("scoring_opportunities") or 0)
        + (away.get("scoring_opportunities") or 0)
    )

    total_drives = (
        (home.get("drives") or 0)
        + (away.get("drives") or 0)
    )

    process_total = (
        4.2 * total_opportunities
        if total_opportunities > 2
        else actual_home + actual_away
    )

    home_ppd = home.get("points_per_drive")
    away_ppd = away.get("points_per_drive")

    if (
        total_drives
        and home_ppd is not None
        and away_ppd is not None
    ):
        drive_total = (
            (home_ppd + away_ppd)
            / 2.0
            * total_drives
        )
        process_total = (
            0.70 * process_total
            + 0.30 * drive_total
        )

    actual_total = actual_home + actual_away

    expected_total = clamp(
        0.85 * process_total
        + 0.15 * actual_total,
        24.0,
        90.0,
    )

    home_score = (
        expected_total
        + quality_margin_home
    ) / 2.0

    away_score = (
        expected_total
        - quality_margin_home
    ) / 2.0

    return (
        round(max(0.0, home_score), 1),
        round(max(0.0, away_score), 1),
    )


def reality_check_label(
    actual_margin: float,
    adjusted_margin: float,
) -> tuple[str, str]:
    delta = actual_margin - adjusted_margin

    if abs(delta) <= 5:
        return (
            "ABOUT RIGHT",
            "The scoreboard was broadly consistent with the underlying game quality.",
        )

    same_winner = (
        actual_margin == 0
        or adjusted_margin == 0
        or (actual_margin > 0) == (adjusted_margin > 0)
    )

    if not same_winner:
        return (
            "MISLEADING FINAL",
            "The underlying play profile favored the opposite team from the final scoreboard.",
        )

    if abs(actual_margin) > abs(adjusted_margin):
        return (
            "CLOSER THAN IT LOOKED",
            "The final margin was larger than the underlying efficiency and possession profile suggested.",
        )

    return (
        "MORE DECISIVE THAN IT LOOKED",
        "The underlying game quality was stronger than the final margin suggested.",
    )


# =============================================================================
# FINAL RECORD
# =============================================================================

def build_full_record(
    final: dict[str, Any],
    pbp_game: dict[str, Any],
) -> dict[str, Any]:
    away = str(
        final.get("away_team")
        or pbp_game.get("away")
        or ""
    )
    home = str(
        final.get("home_team")
        or pbp_game.get("home")
        or ""
    )

    away_points = int(final.get("away_points"))
    home_points = int(final.get("home_points"))

    plays = list(pbp_game["plays"])
    assign_drive_keys(plays)

    competitive = [
        play
        for play in plays
        if not play["garbage_time"]
    ]

    if len(competitive) < 20:
        competitive = plays

    home_stats = team_summary(
        competitive,
        plays,
        home,
    )
    away_stats = team_summary(
        competitive,
        plays,
        away,
    )

    home_quality_margin = quality_margin(
        home_stats,
        away_stats,
    )

    home_pwe = postgame_win_expectancy(
        home_quality_margin
    )
    away_pwe = 1.0 - home_pwe

    adjusted_home, adjusted_away = adjusted_score(
        home_points,
        away_points,
        home_stats,
        away_stats,
        home_quality_margin,
    )

    actual_margin = (
        home_points
        - away_points
    )
    adjusted_margin = (
        adjusted_home
        - adjusted_away
    )

    reality_label, reality_note = reality_check_label(
        actual_margin,
        adjusted_margin,
    )

    garbage_plays = sum(
        1 for play in plays
        if play["garbage_time"]
    )

    garbage_share = (
        garbage_plays / len(plays)
        if plays
        else None
    )

    def pack_split(split: dict[str, Any]) -> dict[str, Any]:
        return {
            "plays": split.get("plays"),
            "epa_total": rnd(
                split.get("epa_total"),
                2,
            ),
            "epa_per_play": rnd(
                split.get("epa_per_play"),
                3,
            ),
            "success_rate": pct(
                split.get("success_rate")
            ),
        }

    def pack_team(stats: dict[str, Any]) -> dict[str, Any]:
        return {
            "overall": pack_split(stats["overall"]),
            "passing": pack_split(stats["passing"]),
            "rushing": pack_split(stats["rushing"]),
            "standard_downs": pack_split(stats["standard_downs"]),
            "passing_downs": pack_split(stats["passing_downs"]),
            "early_downs": pack_split(stats["early_downs"]),
            "third_fourth_downs": pack_split(stats["money_downs"]),
            "fourth_down": {
                **pack_split(stats["fourth_downs"]),
                "attempts": stats["fourth_downs"].get("plays"),
            },
            "explosiveness": {
                "explosive_plays": stats.get("explosive_plays"),
                "explosive_play_rate": pct(
                    stats.get("explosive_rate")
                ),
                "explosive_epa_dependency": pct(
                    stats.get("explosive_epa_dependency")
                ),
            },
            "negative_play_rates": {
                "sacks_allowed": stats.get("sacks_allowed"),
                "sack_rate_allowed": pct(
                    stats.get("sack_rate_allowed")
                ),
                "stuffs_allowed": stats.get("stuffs_allowed"),
                "stuff_rate_allowed": pct(
                    stats.get("stuff_rate_allowed")
                ),
                "tfl_allowed": stats.get("tfl_allowed"),
                "tfl_rate_allowed": pct(
                    stats.get("tfl_rate_allowed")
                ),
            },
            "drives": {
                "drives": stats.get("drives"),
                "points_per_drive": rnd(
                    stats.get("points_per_drive"),
                    2,
                ),
                "yards_per_drive": rnd(
                    stats.get("yards_per_drive"),
                    1,
                ),
                "drive_success_rate": pct(
                    stats.get("drive_success_rate")
                ),
                "three_and_outs": stats.get("three_and_outs"),
                "three_and_out_rate": pct(
                    stats.get("three_and_out_rate")
                ),
            },
            "scoring_opportunities": {
                "opportunities": stats.get("scoring_opportunities"),
                "points_per_opportunity": rnd(
                    stats.get("points_per_scoring_opportunity"),
                    2,
                ),
            },
            "red_zone": {
                "trips": stats.get("red_zone_trips"),
                "points_per_trip": rnd(
                    stats.get("red_zone_points_per_trip"),
                    2,
                ),
                "overperformance_points_per_trip": rnd(
                    stats.get("red_zone_overperformance"),
                    2,
                ),
                "beta_expected_points_per_trip": (
                    RED_ZONE_EXPECTED_POINTS_PER_TRIP_BETA
                ),
            },
            "field_position": {
                "avg_start_yards_to_goal": rnd(
                    stats.get("avg_start_yards_to_goal"),
                    1,
                ),
            },
            "turnovers": {
                "turnovers": stats.get("turnovers"),
                "turnover_epa_impact": rnd(
                    stats.get("turnover_epa_impact"),
                    2,
                ),
            },
            "epa_volatility": rnd(
                stats.get("epa_volatility"),
                3,
            ),
        }

    return {
        "game_id": str(
            final.get("game_id")
            or ""
        ),
        "pbp_game_id": pbp_game.get("game_id"),
        "matchup_key": matchup_key(
            away,
            home,
        ),
        "season": int(
            final.get("season")
            or YEAR
        ),
        "week": int(
            final.get("week")
            or 0
        ),
        "away_team": away,
        "home_team": home,
        "away_points": away_points,
        "home_points": home_points,
        "analysis_status": "available",
        "analysis_level": "full",
        "source": "SportsDataverse/cfbfastR PBP",
        "source_note": (
            "Retrospective only. Does not alter the frozen pregame THI projection."
        ),
        "calibration_status": (
            "BETA — historical calibration pending"
        ),
        "headline": {
            "postgame_win_expectancy": {
                "away_pct": pct(away_pwe),
                "home_pct": pct(home_pwe),
                "winner": (
                    home
                    if home_pwe >= 0.5
                    else away
                ),
            },
            "adjusted_final_score": {
                "away": adjusted_away,
                "home": adjusted_home,
            },
            "reality_check": {
                "label": reality_label,
                "note": reality_note,
                "actual_margin": actual_margin,
                "adjusted_margin": rnd(
                    adjusted_margin,
                    1,
                ),
            },
        },
        "away_metrics": pack_team(
            away_stats
        ),
        "home_metrics": pack_team(
            home_stats
        ),
        "game_context": {
            "total_scrimmage_plays": len(plays),
            "competitive_scrimmage_plays": len(competitive),
            "garbage_time_plays": garbage_plays,
            "garbage_time_share": pct(
                garbage_share
            ),
        },
        "definitions": {
            "standard_down": (
                "1st down; 2nd-and-7 or less; 3rd/4th-and-4 or less."
            ),
            "passing_down": (
                "2nd-and-8+; 3rd/4th-and-5+."
            ),
            "drive_success_rate": (
                "Share of offensive drives with positive cumulative EPA."
            ),
            "three_and_out_rate": (
                "Share of drives with three or fewer qualifying scrimmage plays, "
                "no first down, and no points."
            ),
            "scoring_opportunity": (
                "Drive that reaches the opponent 40-yard line or closer."
            ),
            "red_zone_trip": (
                "Drive that reaches the opponent 20-yard line or closer."
            ),
            "red_zone_overperformance": (
                f"Points per red-zone trip minus the temporary beta baseline "
                f"of {RED_ZONE_EXPECTED_POINTS_PER_TRIP_BETA:.1f}. "
                "This baseline will be historically calibrated."
            ),
            "sack_rate_allowed": (
                "Sacks divided by qualifying pass plays/dropbacks."
            ),
            "stuff_rate_allowed": (
                "Rushes stopped for zero or negative yards divided by rush attempts."
            ),
            "tfl_rate_allowed": (
                "Qualifying offensive plays ending in a tackle for loss / negative yardage "
                "divided by all qualifying scrimmage plays."
            ),
            "turnover_epa_impact": (
                "Sum of offensive EPA on turnover plays; more negative means greater lost value."
            ),
            "epa_volatility": (
                "Population standard deviation of competitive-play EPA."
            ),
        },
        "generated_at": iso_now(),
    }


def pending_record(
    final: dict[str, Any],
    note: str,
) -> dict[str, Any]:
    away = str(
        final.get("away_team")
        or ""
    )
    home = str(
        final.get("home_team")
        or ""
    )

    return {
        "game_id": str(
            final.get("game_id")
            or ""
        ),
        "matchup_key": matchup_key(
            away,
            home,
        ),
        "season": int(
            final.get("season")
            or YEAR
        ),
        "week": int(
            final.get("week")
            or 0
        ),
        "away_team": away,
        "home_team": home,
        "away_points": final.get("away_points"),
        "home_points": final.get("home_points"),
        "analysis_status": "pending",
        "analysis_level": "scoreboard_only",
        "source": "Final score available; PBP pending",
        "source_note": note,
        "calibration_status": (
            "BETA — historical calibration pending"
        ),
        "generated_at": iso_now(),
    }


# =============================================================================
# RETRY / MAIN
# =============================================================================

def should_download(
    finals: list[dict[str, Any]],
    existing: dict[str, Any],
) -> bool:
    by_matchup = {
        game.get("matchup_key"): game
        for game in (existing.get("games") or [])
        if isinstance(game, dict)
        and game.get("matchup_key")
    }

    for final in finals:
        key = matchup_key(
            final.get("away_team"),
            final.get("home_team"),
        )
        row = by_matchup.get(key)

        if not row:
            return True

        # Version 2 requires the canonical selected metric package.
        # Rebuild any older "available" row that does not contain it.
        if row.get("analysis_status") == "available":
            if (
                "away_metrics" not in row
                or "home_metrics" not in row
            ):
                return True
            continue

        generated = row.get("generated_at")

        if not generated:
            return True

        try:
            when = datetime.fromisoformat(
                str(generated).replace(
                    "Z",
                    "+00:00",
                )
            )
            age_minutes = (
                utc_now()
                - when.astimezone(timezone.utc)
            ).total_seconds() / 60.0

            if age_minutes >= PENDING_RETRY_MINUTES:
                return True
        except Exception:
            return True

    return False


def main() -> None:
    results = read_json(
        RESULTS_PATH,
        {"games": []},
    )

    finals = [
        game
        for game in (results.get("games") or [])
        if isinstance(game, dict)
        and str(
            game.get("game_state")
            or game.get("status")
            or ""
        ).lower()
        in {"final", "completed"}
    ]

    if not finals:
        write_json(
            OUTPUT_PATH,
            {
                "meta": {
                    "season": YEAR,
                    "schema_version": "2.0-canonical-postgame",
                    "generated_at": iso_now(),
                    "final_games": 0,
                    "available": 0,
                    "pending": 0,
                    "source": "SportsDataverse/cfbfastR PBP",
                    "model_a_touched": False,
                },
                "games": [],
            },
        )
        print("No finals available yet.")
        return

    existing = read_json(
        OUTPUT_PATH,
        {"games": []},
    )

    existing_by_matchup = {
        game.get("matchup_key"): game
        for game in (existing.get("games") or [])
        if isinstance(game, dict)
        and game.get("matchup_key")
    }

    if not should_download(
        finals,
        existing,
    ):
        print(
            "No new finals, no old-schema rows, "
            "and no pending postgame records due for retry."
        )
        return

    try:
        frame = download_pbp()
        plays = normalize_frame(frame)
        games = build_game_index(plays)

        print(
            f"Normalized {len(plays):,} qualifying scrimmage plays "
            f"across {len(games)} games."
        )

    except Exception as exc:
        print(
            f"WARNING: PBP unavailable: {exc}"
        )

        output_games: list[dict[str, Any]] = []

        for final in finals:
            key = matchup_key(
                final.get("away_team"),
                final.get("home_team"),
            )
            prior = existing_by_matchup.get(key)

            if (
                prior
                and prior.get("analysis_status")
                == "available"
                and "away_metrics" in prior
                and "home_metrics" in prior
            ):
                output_games.append(prior)
            else:
                output_games.append(
                    pending_record(
                        final,
                        (
                            "PBP source could not be refreshed. "
                            "Automatic retry scheduled."
                        ),
                    )
                )

        available = sum(
            1
            for game in output_games
            if game.get("analysis_status")
            == "available"
        )

        write_json(
            OUTPUT_PATH,
            {
                "meta": {
                    "season": YEAR,
                    "schema_version": "2.0-canonical-postgame",
                    "generated_at": iso_now(),
                    "final_games": len(output_games),
                    "available": available,
                    "pending": (
                        len(output_games)
                        - available
                    ),
                    "source": "SportsDataverse/cfbfastR PBP",
                    "model_a_touched": False,
                    "warning": str(exc),
                },
                "games": output_games,
            },
        )
        return

    output_games: list[dict[str, Any]] = []

    for final in finals:
        pbp_game = find_pbp_game(
            final,
            games,
        )

        if pbp_game is None:
            output_games.append(
                pending_record(
                    final,
                    (
                        "Final is recorded, but matching play-by-play has not arrived yet. "
                        "The settlement workflow will retry automatically."
                    ),
                )
            )
            continue

        try:
            output_games.append(
                build_full_record(
                    final,
                    pbp_game,
                )
            )
        except Exception as exc:
            print(
                "WARNING: postgame build failed for "
                f"{final.get('away_team')} @ "
                f"{final.get('home_team')}: {exc}"
            )
            output_games.append(
                pending_record(
                    final,
                    (
                        "PBP matched, but canonical postgame generation failed: "
                        f"{exc}"
                    ),
                )
            )

    available = sum(
        1
        for game in output_games
        if game.get("analysis_status")
        == "available"
    )

    pending = (
        len(output_games)
        - available
    )

    write_json(
        OUTPUT_PATH,
        {
            "meta": {
                "season": YEAR,
                "schema_version": "2.0-canonical-postgame",
                "generated_at": iso_now(),
                "final_games": len(output_games),
                "available": available,
                "pending": pending,
                "source": "SportsDataverse/cfbfastR PBP",
                "source_url": PBP_URL,
                "model_a_touched": False,
                "notes": [
                    "Every final receives a postgame record.",
                    "Full metrics appear only when matching PBP is available.",
                    "Pending games retry automatically.",
                    "Canonical selected postgame metric package is schema v2.0.",
                    "Postgame Win Expectancy, Adjusted Final Score, and Red-Zone Overperformance are beta until historical calibration.",
                    "No CFBD calls are made.",
                ],
            },
            "games": output_games,
        },
    )

    print(
        f"Canonical postgame analytics: "
        f"{available} available, "
        f"{pending} pending, "
        f"{len(output_games)} finals total."
    )
    print("✅ No CFBD calls were made")
    print("✅ Model A was not changed")


if __name__ == "__main__":
    main()
