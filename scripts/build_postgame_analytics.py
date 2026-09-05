#!/usr/bin/env python3
"""
THE HAMMER INDEX
build_postgame_analytics.py

Build a per-game retrospective postgame analytics layer for every FINAL in
data/results.json using the public SportsDataverse/cfbfastR 2026 play-by-play.

IMPORTANT
- No CFBD calls.
- Does not modify Model A.
- Does not rewrite any frozen pregame projection.
- Every final receives a record in data/postgame_analytics.json.
- If play-by-play has not arrived yet, that game's record is marked pending and
  will be retried on a later settlement run.
- Postgame Win Expectancy / Adjusted Final Score are explicitly BETA until the
  historical calibration suite is completed.

Primary output:
    data/postgame_analytics.json
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

# Avoid downloading the full parquet on every 5-minute scoreboard run if there
# is nothing new to process. Pending games are retried every 15 minutes.
PENDING_RETRY_MINUTES = 15

SESSION = requests.Session()
SESSION.headers.update(
    {
        "Accept": "*/*",
        "User-Agent": "the-hammer-index-postgame/1.0",
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


def first_present(row: pd.Series, *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row.index:
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


def infer_score_after(row: pd.Series, offense_score: float, defense_score: float) -> tuple[float, float]:
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
            "def_pos_team_score_after",
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
    blob = f"{play_type} {text}".lower()
    return "touchdown" in blob


def infer_field_goal(row: pd.Series, play_type: str, text: str) -> bool:
    made = any(
        as_bool(first_present(row, column, default=False))
        for column in ("field_goal_made", "fg_made", "fieldGoalMade")
    )
    if made:
        return True
    blob = f"{play_type} {text}".lower()
    return "field goal" in blob and any(
        token in blob for token in ("good", "made", "is good")
    )


def is_garbage_time(period: int, offense_score: float, defense_score: float) -> bool:
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
    ) or 0
    defense_score = clean_number(
        first_present(
            row,
            "start.def_pos_team_score",
            "def_pos_team_score",
            "defense_score",
            default=0,
        ),
        0,
    ) or 0

    off_after, def_after = infer_score_after(row, offense_score, defense_score)

    period = as_int(first_present(row, "period", "period.number", default=1), 1) or 1
    down = as_int(first_present(row, "down", "start.down"))
    distance = clean_number(first_present(row, "distance", "start.distance"))
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
    ) or 0

    play_type = str(
        first_present(row, "type.text", "orig_play_type", "play_type", default="")
    )
    play_text = str(
        first_present(row, "text", "cleaned_text", "play_text", default="")
    )

    epa = clean_number(first_present(row, "EPA", "EPA_scrimmage", "epa"))

    is_pass = (
        as_bool(first_present(row, "pass", "pass_attempt", default=False))
        or as_bool(first_present(row, "sack", default=False))
    )
    is_rush = (
        as_bool(first_present(row, "rush", "rush_attempt", default=False))
        and not as_bool(first_present(row, "sack", default=False))
    )

    # Some cfbfastR rows have pass/rush flags missing while the play type/text is clear.
    lower_blob = f"{play_type} {play_text}".lower()
    if not is_pass and not is_rush:
        if any(token in lower_blob for token in ("pass ", "pass complete", "pass incomplete", "sacked")):
            is_pass = True
        elif any(token in lower_blob for token in ("rush", "run for", "rushed")):
            is_rush = True

    scrimmage = is_pass or is_rush
    if not scrimmage or epa is None:
        return None

    success_raw = first_present(row, "EPA_success", "success", default=None)
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

    drive_id = first_present(
        row,
        "drive_id",
        "driveId",
        "start.drive.id",
        "drive_number",
        "driveNumber",
    )

    start_yard_line = clean_number(
        first_present(
            row,
            "start.yardLine",
            "start_yard_line",
            "yard_line",
        )
    )

    kickoff_ts = first_present(
        row,
        "game_date",
        "start_date",
        "game_datetime",
        "date",
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
        "start_yard_line": start_yard_line,
        "yards_gained": yards,
        "epa": epa,
        "success": bool(success),
        "explosive": bool(explosive),
        "turnover": infer_turnover(row, play_type, play_text),
        "touchdown": infer_touchdown(row, play_type, play_text),
        "field_goal": infer_field_goal(row, play_type, play_text),
        "garbage_time": is_garbage_time(period, offense_score, defense_score),
        "drive_id": str(drive_id) if drive_id is not None else None,
        "kickoff_ts": str(kickoff_ts) if kickoff_ts is not None else None,
    }


def normalize_frame(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if "season" in frame.columns:
        season = pd.to_numeric(frame["season"], errors="coerce")
        frame = frame[season == YEAR]

    # Keep all games; do not filter to FBS-only teams. That gives FBS-FCS finals
    # the best possible chance of receiving full analysis.
    plays: list[dict[str, Any]] = []
    for index, (_, row) in enumerate(frame.iterrows()):
        play = normalize_play(row, index)
        if play is not None:
            plays.append(play)
    return plays


# =============================================================================
# GAME MATCHING
# =============================================================================

def build_game_index(plays: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for play in plays:
        grouped[play["game_id"]].append(play)

    out: dict[str, dict[str, Any]] = {}
    for game_id, rows in grouped.items():
        rows.sort(key=lambda play: play["row_index"])

        home = next((play["home"] for play in rows if play.get("home")), "")
        away = next((play["away"] for play in rows if play.get("away")), "")

        # If explicit home/away names are unavailable, infer from participants.
        if not home or not away:
            participants = []
            for play in rows:
                for team in (play.get("offense"), play.get("defense")):
                    if team and team not in participants:
                        participants.append(team)
            if len(participants) >= 2:
                away = away or participants[0]
                home = home or participants[1]

        out[game_id] = {
            "game_id": game_id,
            "away": away,
            "home": home,
            "matchup_key": matchup_key(away, home),
            "plays": rows,
        }
    return out


def find_pbp_game(
    final: dict[str, Any],
    games: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    provider_id = str(final.get("game_id") or "")
    if provider_id and provider_id in games:
        return games[provider_id]

    target = matchup_key(final.get("away_team"), final.get("home_team"))
    if target:
        exact = [
            game for game in games.values()
            if game.get("matchup_key") == target
        ]
        if len(exact) == 1:
            return exact[0]

    # Reverse orientation fallback for neutral-site/provider orientation quirks.
    reverse = matchup_key(final.get("home_team"), final.get("away_team"))
    if reverse:
        reverse_matches = [
            game for game in games.values()
            if game.get("matchup_key") == reverse
        ]
        if len(reverse_matches) == 1:
            return reverse_matches[0]

    return None


# =============================================================================
# DRIVE / TEAM METRICS
# =============================================================================

def assign_drive_keys(plays: list[dict[str, Any]]) -> None:
    sequence = 0
    previous_offense = None

    for play in plays:
        explicit = play.get("drive_id")
        if explicit:
            play["_drive_key"] = f"provider:{explicit}"
            previous_offense = play.get("offense")
            continue

        offense = play.get("offense")
        if previous_offense is None or offense != previous_offense:
            sequence += 1
        play["_drive_key"] = f"inferred:{sequence}:{team_key(offense)}"
        previous_offense = offense


def summarize_drives(
    plays: list[dict[str, Any]],
    team: str,
) -> dict[str, Any]:
    team_plays = [play for play in plays if same_team(play.get("offense"), team)]
    drives: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for play in team_plays:
        drives[play["_drive_key"]].append(play)

    opportunities = 0
    opportunity_points = 0.0
    scoring_drives = 0
    drive_points_total = 0.0
    start_positions: list[float] = []
    yards_per_drive: list[float] = []

    for rows in drives.values():
        rows.sort(key=lambda play: play["row_index"])

        start = rows[0]
        if start.get("yards_to_goal") is not None:
            start_positions.append(float(start["yards_to_goal"]))

        yards_per_drive.append(
            sum(float(play.get("yards_gained") or 0) for play in rows)
        )

        is_opportunity = any(
            play.get("yards_to_goal") is not None
            and float(play["yards_to_goal"]) <= 40
            for play in rows
        )
        if is_opportunity:
            opportunities += 1

        before = float(rows[0].get("offense_score") or 0)
        after = max(
            float(play.get("offense_score_after") or play.get("offense_score") or 0)
            for play in rows
        )
        drive_points = max(0.0, after - before)

        # If post-play score fields are absent, infer obvious scoring outcomes.
        if drive_points <= 0:
            if any(play.get("touchdown") for play in rows):
                drive_points = 7.0
            elif any(play.get("field_goal") for play in rows):
                drive_points = 3.0

        drive_points_total += drive_points
        if drive_points > 0:
            scoring_drives += 1
        if is_opportunity:
            opportunity_points += drive_points

    drive_count = len(drives)

    return {
        "drives": drive_count,
        "scoring_drives": scoring_drives,
        "scoring_drive_rate": (
            scoring_drives / drive_count if drive_count else None
        ),
        "points_per_drive": (
            drive_points_total / drive_count if drive_count else None
        ),
        "yards_per_drive": (
            sum(yards_per_drive) / len(yards_per_drive)
            if yards_per_drive else None
        ),
        "scoring_opportunities": opportunities,
        "points_per_scoring_opportunity": (
            opportunity_points / opportunities if opportunities else None
        ),
        "avg_start_yards_to_goal": (
            sum(start_positions) / len(start_positions)
            if start_positions else None
        ),
    }


def same_team(a: Any, b: Any) -> bool:
    return team_key(a) == team_key(b)


def team_summary(
    core: list[dict[str, Any]],
    all_plays: list[dict[str, Any]],
    team: str,
) -> dict[str, Any]:
    offense = [play for play in core if same_team(play.get("offense"), team)]
    defense = [play for play in core if same_team(play.get("defense"), team)]
    offense_all = [play for play in all_plays if same_team(play.get("offense"), team)]

    plays = len(offense)
    epa_total = sum(float(play["epa"]) for play in offense)
    success_count = sum(1 for play in offense if play["success"])
    explosive_count = sum(1 for play in offense if play["explosive"])
    turnovers = sum(1 for play in offense_all if play["turnover"])

    positive_epa = sum(max(float(play["epa"]), 0.0) for play in offense)
    explosive_positive_epa = sum(
        max(float(play["epa"]), 0.0)
        for play in offense
        if play["explosive"]
    )

    early = [play for play in offense if play.get("down") in {1, 2}]
    late = [play for play in offense if play.get("down") in {3, 4}]
    redzone = [
        play for play in offense
        if play.get("yards_to_goal") is not None
        and float(play["yards_to_goal"]) <= 20
    ]

    leading = 0
    tied = 0
    for play in offense:
        off_score = float(play.get("offense_score") or 0)
        def_score = float(play.get("defense_score") or 0)
        if off_score > def_score:
            leading += 1
        elif off_score == def_score:
            tied += 1

    drive = summarize_drives(all_plays, team)

    return {
        "plays": plays,
        "epa_total": epa_total,
        "epa_per_play": epa_total / plays if plays else None,
        "success_rate": success_count / plays if plays else None,
        "explosive_rate": explosive_count / plays if plays else None,
        "explosive_plays": explosive_count,
        "explosive_epa_share": (
            explosive_positive_epa / positive_epa if positive_epa > 0 else None
        ),
        "turnovers": turnovers,
        "early_down_epa_per_play": (
            sum(float(play["epa"]) for play in early) / len(early)
            if early else None
        ),
        "early_down_success_rate": (
            sum(1 for play in early if play["success"]) / len(early)
            if early else None
        ),
        "late_down_epa_per_play": (
            sum(float(play["epa"]) for play in late) / len(late)
            if late else None
        ),
        "late_down_success_rate": (
            sum(1 for play in late if play["success"]) / len(late)
            if late else None
        ),
        "red_zone_epa_per_play": (
            sum(float(play["epa"]) for play in redzone) / len(redzone)
            if redzone else None
        ),
        "red_zone_success_rate": (
            sum(1 for play in redzone if play["success"]) / len(redzone)
            if redzone else None
        ),
        "red_zone_plays": len(redzone),
        "control_share": (
            (leading + 0.5 * tied) / plays if plays else None
        ),
        "defensive_epa_allowed": (
            sum(float(play["epa"]) for play in defense) / len(defense)
            if defense else None
        ),
        **drive,
    }


# =============================================================================
# POSTGAME DERIVED METRICS
# =============================================================================

def difference(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return a - b


def quality_margin(
    home: dict[str, Any],
    away: dict[str, Any],
) -> float:
    """
    BETA retrospective quality margin.

    This intentionally uses process metrics rather than the final score:
      EPA/play differential
      success-rate differential
      explosive-rate differential
      scoring-opportunity differential
      field-position differential
      turnover margin (dampened)

    Historical calibration will replace/tune these coefficients.
    """
    epa_diff = (home.get("epa_per_play") or 0) - (away.get("epa_per_play") or 0)
    success_diff = (home.get("success_rate") or 0) - (away.get("success_rate") or 0)
    explosive_diff = (home.get("explosive_rate") or 0) - (away.get("explosive_rate") or 0)
    opp_diff = (home.get("scoring_opportunities") or 0) - (away.get("scoring_opportunities") or 0)

    home_start = home.get("avg_start_yards_to_goal")
    away_start = away.get("avg_start_yards_to_goal")
    field_edge = 0.0
    if home_start is not None and away_start is not None:
        # Lower yards-to-goal at drive start is better.
        field_edge = away_start - home_start

    turnover_margin = (away.get("turnovers") or 0) - (home.get("turnovers") or 0)

    margin = (
        12.0 * epa_diff
        + 30.0 * success_diff
        + 14.0 * explosive_diff
        + 1.25 * opp_diff
        + 0.18 * field_edge
        + 1.25 * turnover_margin
    )
    return clamp(margin, -42.0, 42.0)


def adjusted_score(
    actual_home: int,
    actual_away: int,
    home: dict[str, Any],
    away: dict[str, Any],
    margin: float,
) -> tuple[float, float]:
    """
    BETA adjusted score.

    Expected total is driven primarily by scoring opportunities and drive
    quality, then bounded to plausible CFB scoring. The quality margin is split
    around that expected total.
    """
    total_opps = (
        (home.get("scoring_opportunities") or 0)
        + (away.get("scoring_opportunities") or 0)
    )
    total_drives = (
        (home.get("drives") or 0)
        + (away.get("drives") or 0)
    )

    # 4.2 points per scoring opportunity is a neutral placeholder that will be
    # calibrated historically. Blend with actual total only enough to stabilize
    # tiny/missing drive samples.
    process_total = 4.2 * total_opps
    if total_opps <= 2:
        process_total = actual_home + actual_away

    if total_drives:
        drive_ppd = (
            (home.get("points_per_drive") or 0)
            + (away.get("points_per_drive") or 0)
        ) / 2.0
        if drive_ppd > 0:
            drive_total = drive_ppd * total_drives
            process_total = 0.70 * process_total + 0.30 * drive_total

    actual_total = actual_home + actual_away
    expected_total = clamp(
        0.85 * process_total + 0.15 * actual_total,
        24.0,
        90.0,
    )

    home_score = (expected_total + margin) / 2.0
    away_score = (expected_total - margin) / 2.0

    home_score = max(0.0, home_score)
    away_score = max(0.0, away_score)

    return round(home_score, 1), round(away_score, 1)


def postgame_win_expectancy(home_quality_margin: float) -> float:
    # BETA logistic mapping. Calibration suite will fit this historically.
    return 1.0 / (1.0 + math.exp(-home_quality_margin / 7.5))


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


def variance_score(
    home: dict[str, Any],
    away: dict[str, Any],
) -> float:
    turnover_margin = abs(
        (home.get("turnovers") or 0)
        - (away.get("turnovers") or 0)
    )

    explosive_gap = abs(
        (home.get("explosive_epa_share") or 0)
        - (away.get("explosive_epa_share") or 0)
    )

    late_early_gap = 0.0
    for team in (home, away):
        late = team.get("late_down_success_rate")
        early = team.get("early_down_success_rate")
        if late is not None and early is not None:
            late_early_gap += abs(late - early)

    redzone_gap = abs(
        (home.get("red_zone_success_rate") or 0)
        - (away.get("red_zone_success_rate") or 0)
    )

    score = (
        turnover_margin * 14.0
        + explosive_gap * 35.0
        + late_early_gap * 35.0
        + redzone_gap * 22.0
    )
    return round(clamp(score, 0.0, 100.0), 1)


def game_control(
    home: dict[str, Any],
    away: dict[str, Any],
) -> tuple[float | None, float | None]:
    home_control = home.get("control_share")
    away_control = away.get("control_share")
    if home_control is None or away_control is None:
        return None, None

    total = home_control + away_control
    if total <= 0:
        return 0.5, 0.5

    return home_control / total, away_control / total


def build_full_record(
    final: dict[str, Any],
    pbp_game: dict[str, Any],
) -> dict[str, Any]:
    away = str(final.get("away_team") or pbp_game.get("away") or "")
    home = str(final.get("home_team") or pbp_game.get("home") or "")
    away_points = int(final.get("away_points"))
    home_points = int(final.get("home_points"))

    plays = list(pbp_game["plays"])
    assign_drive_keys(plays)

    core = [play for play in plays if not play["garbage_time"]]
    if len(core) < 20:
        core = plays

    home_stats = team_summary(core, plays, home)
    away_stats = team_summary(core, plays, away)

    home_margin_quality = quality_margin(home_stats, away_stats)
    home_pwe = postgame_win_expectancy(home_margin_quality)
    away_pwe = 1.0 - home_pwe

    adjusted_home, adjusted_away = adjusted_score(
        home_points,
        away_points,
        home_stats,
        away_stats,
        home_margin_quality,
    )

    actual_margin = home_points - away_points
    adjusted_margin = adjusted_home - adjusted_away
    reality_label, reality_note = reality_check_label(
        actual_margin,
        adjusted_margin,
    )

    home_control, away_control = game_control(home_stats, away_stats)

    field_position_edge = difference(
        away_stats.get("avg_start_yards_to_goal"),
        home_stats.get("avg_start_yards_to_goal"),
    )

    garbage_plays = sum(1 for play in plays if play["garbage_time"])
    garbage_rate = garbage_plays / len(plays) if plays else 0.0

    turnover_margin_home = (
        (away_stats.get("turnovers") or 0)
        - (home_stats.get("turnovers") or 0)
    )

    return {
        "game_id": str(final.get("game_id") or ""),
        "pbp_game_id": pbp_game.get("game_id"),
        "matchup_key": matchup_key(away, home),
        "season": int(final.get("season") or YEAR),
        "week": int(final.get("week") or 0),
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
        "calibration_status": "BETA — historical calibration pending",
        "headline": {
            "postgame_win_expectancy": {
                "home_pct": pct(home_pwe),
                "away_pct": pct(away_pwe),
                "winner": home if home_pwe >= 0.5 else away,
            },
            "adjusted_final_score": {
                "away": adjusted_away,
                "home": adjusted_home,
            },
            "reality_check": {
                "label": reality_label,
                "note": reality_note,
                "actual_margin": actual_margin,
                "adjusted_margin": rnd(adjusted_margin, 1),
            },
        },
        "game_control": {
            "home_pct": pct(home_control),
            "away_pct": pct(away_control),
        },
        "efficiency": {
            "home_epa_per_play": rnd(home_stats.get("epa_per_play"), 3),
            "away_epa_per_play": rnd(away_stats.get("epa_per_play"), 3),
            "epa_margin": rnd(
                difference(
                    home_stats.get("epa_per_play"),
                    away_stats.get("epa_per_play"),
                ),
                3,
            ),
            "home_success_rate": pct(home_stats.get("success_rate")),
            "away_success_rate": pct(away_stats.get("success_rate")),
            "success_rate_margin_pp": rnd(
                (
                    difference(
                        home_stats.get("success_rate"),
                        away_stats.get("success_rate"),
                    )
                    or 0
                ) * 100.0,
                1,
            ),
        },
        "explosiveness": {
            "home_explosive_rate": pct(home_stats.get("explosive_rate")),
            "away_explosive_rate": pct(away_stats.get("explosive_rate")),
            "home_explosive_plays": home_stats.get("explosive_plays"),
            "away_explosive_plays": away_stats.get("explosive_plays"),
            "home_explosive_epa_dependence_pct": pct(
                home_stats.get("explosive_epa_share")
            ),
            "away_explosive_epa_dependence_pct": pct(
                away_stats.get("explosive_epa_share")
            ),
        },
        "turnovers": {
            "home_turnovers": home_stats.get("turnovers"),
            "away_turnovers": away_stats.get("turnovers"),
            "home_turnover_margin": turnover_margin_home,
            "home_turnover_luck_proxy_points": rnd(turnover_margin_home * 3.5, 1),
            "note": (
                "Turnover Luck is a transparent leverage proxy (3.5 points per "
                "turnover of margin), not a claim that every turnover was random."
            ),
        },
        "finishing_drives": {
            "home_scoring_opportunities": home_stats.get("scoring_opportunities"),
            "away_scoring_opportunities": away_stats.get("scoring_opportunities"),
            "home_points_per_opportunity": rnd(
                home_stats.get("points_per_scoring_opportunity"), 2
            ),
            "away_points_per_opportunity": rnd(
                away_stats.get("points_per_scoring_opportunity"), 2
            ),
        },
        "drive_efficiency": {
            "home_drives": home_stats.get("drives"),
            "away_drives": away_stats.get("drives"),
            "home_points_per_drive": rnd(home_stats.get("points_per_drive"), 2),
            "away_points_per_drive": rnd(away_stats.get("points_per_drive"), 2),
            "home_yards_per_drive": rnd(home_stats.get("yards_per_drive"), 1),
            "away_yards_per_drive": rnd(away_stats.get("yards_per_drive"), 1),
            "home_scoring_drive_rate": pct(home_stats.get("scoring_drive_rate")),
            "away_scoring_drive_rate": pct(away_stats.get("scoring_drive_rate")),
        },
        "field_position": {
            "home_avg_start_yards_to_goal": rnd(
                home_stats.get("avg_start_yards_to_goal"), 1
            ),
            "away_avg_start_yards_to_goal": rnd(
                away_stats.get("avg_start_yards_to_goal"), 1
            ),
            "home_field_position_edge_yards": rnd(field_position_edge, 1),
        },
        "early_downs": {
            "home_epa_per_play": rnd(
                home_stats.get("early_down_epa_per_play"), 3
            ),
            "away_epa_per_play": rnd(
                away_stats.get("early_down_epa_per_play"), 3
            ),
            "home_success_rate": pct(
                home_stats.get("early_down_success_rate")
            ),
            "away_success_rate": pct(
                away_stats.get("early_down_success_rate")
            ),
        },
        "money_downs": {
            "home_epa_per_play": rnd(
                home_stats.get("late_down_epa_per_play"), 3
            ),
            "away_epa_per_play": rnd(
                away_stats.get("late_down_epa_per_play"), 3
            ),
            "home_success_rate": pct(
                home_stats.get("late_down_success_rate")
            ),
            "away_success_rate": pct(
                away_stats.get("late_down_success_rate")
            ),
            "home_overperformance_vs_early_pp": rnd(
                (
                    difference(
                        home_stats.get("late_down_success_rate"),
                        home_stats.get("early_down_success_rate"),
                    )
                    or 0
                ) * 100.0,
                1,
            ),
            "away_overperformance_vs_early_pp": rnd(
                (
                    difference(
                        away_stats.get("late_down_success_rate"),
                        away_stats.get("early_down_success_rate"),
                    )
                    or 0
                ) * 100.0,
                1,
            ),
        },
        "red_zone": {
            "home_plays": home_stats.get("red_zone_plays"),
            "away_plays": away_stats.get("red_zone_plays"),
            "home_epa_per_play": rnd(
                home_stats.get("red_zone_epa_per_play"), 3
            ),
            "away_epa_per_play": rnd(
                away_stats.get("red_zone_epa_per_play"), 3
            ),
            "home_success_rate": pct(
                home_stats.get("red_zone_success_rate")
            ),
            "away_success_rate": pct(
                away_stats.get("red_zone_success_rate")
            ),
        },
        "garbage_time": {
            "total_scrimmage_plays": len(plays),
            "competitive_scrimmage_plays": len(core),
            "garbage_time_plays": garbage_plays,
            "garbage_time_play_rate": pct(garbage_rate),
        },
        "variance": {
            "game_variance_score": variance_score(home_stats, away_stats),
            "scale": "0-100; higher = more turnover/explosive/late-down/red-zone variance",
        },
        "generated_at": iso_now(),
    }


def pending_record(final: dict[str, Any], note: str) -> dict[str, Any]:
    away = str(final.get("away_team") or "")
    home = str(final.get("home_team") or "")
    return {
        "game_id": str(final.get("game_id") or ""),
        "matchup_key": matchup_key(away, home),
        "season": int(final.get("season") or YEAR),
        "week": int(final.get("week") or 0),
        "away_team": away,
        "home_team": home,
        "away_points": final.get("away_points"),
        "home_points": final.get("home_points"),
        "analysis_status": "pending",
        "analysis_level": "scoreboard_only",
        "source": "Final score available; PBP pending",
        "source_note": note,
        "calibration_status": "BETA — historical calibration pending",
        "generated_at": iso_now(),
    }


# =============================================================================
# RETRY / MAIN
# =============================================================================

def should_download(
    finals: list[dict[str, Any]],
    existing: dict[str, Any],
) -> bool:
    existing_games = existing.get("games") or []
    by_matchup = {
        game.get("matchup_key"): game
        for game in existing_games
        if isinstance(game, dict) and game.get("matchup_key")
    }

    for final in finals:
        key = matchup_key(final.get("away_team"), final.get("home_team"))
        row = by_matchup.get(key)
        if not row:
            return True
        if row.get("analysis_status") == "available":
            continue

        generated = row.get("generated_at")
        if not generated:
            return True
        try:
            when = datetime.fromisoformat(str(generated).replace("Z", "+00:00"))
            age_minutes = (utc_now() - when.astimezone(timezone.utc)).total_seconds() / 60
            if age_minutes >= PENDING_RETRY_MINUTES:
                return True
        except Exception:
            return True

    return False


def main() -> None:
    results = read_json(RESULTS_PATH, {"games": []})
    finals = [
        game
        for game in (results.get("games") or [])
        if isinstance(game, dict)
        and str(game.get("game_state") or game.get("status") or "").lower()
        in {"final", "completed"}
    ]

    if not finals:
        write_json(
            OUTPUT_PATH,
            {
                "meta": {
                    "season": YEAR,
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

    existing = read_json(OUTPUT_PATH, {"games": []})
    existing_by_matchup = {
        game.get("matchup_key"): game
        for game in (existing.get("games") or [])
        if isinstance(game, dict) and game.get("matchup_key")
    }

    if not should_download(finals, existing):
        print("No new finals and no pending postgame records due for retry.")
        return

    try:
        frame = download_pbp()
        plays = normalize_frame(frame)
        games = build_game_index(plays)
        print(f"Normalized {len(plays):,} scrimmage plays across {len(games)} games.")
    except Exception as exc:
        print(f"WARNING: PBP unavailable: {exc}")
        # Preserve all available analyses and ensure every final still has a record.
        output_games = []
        for final in finals:
            key = matchup_key(final.get("away_team"), final.get("home_team"))
            prior = existing_by_matchup.get(key)
            if prior and prior.get("analysis_status") == "available":
                output_games.append(prior)
            else:
                output_games.append(
                    pending_record(
                        final,
                        "PBP source could not be refreshed. Automatic retry scheduled.",
                    )
                )

        available = sum(
            1 for game in output_games
            if game.get("analysis_status") == "available"
        )
        write_json(
            OUTPUT_PATH,
            {
                "meta": {
                    "season": YEAR,
                    "generated_at": iso_now(),
                    "final_games": len(output_games),
                    "available": available,
                    "pending": len(output_games) - available,
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
        pbp_game = find_pbp_game(final, games)

        if pbp_game is None:
            output_games.append(
                pending_record(
                    final,
                    "Final is recorded, but matching play-by-play has not arrived yet. "
                    "The settlement workflow will retry automatically.",
                )
            )
            continue

        try:
            output_games.append(
                build_full_record(final, pbp_game)
            )
        except Exception as exc:
            print(
                f"WARNING: postgame build failed for "
                f"{final.get('away_team')} @ {final.get('home_team')}: {exc}"
            )
            output_games.append(
                pending_record(
                    final,
                    f"PBP matched, but analysis generation failed: {exc}",
                )
            )

    available = sum(
        1 for game in output_games
        if game.get("analysis_status") == "available"
    )
    pending = len(output_games) - available

    write_json(
        OUTPUT_PATH,
        {
            "meta": {
                "season": YEAR,
                "generated_at": iso_now(),
                "final_games": len(output_games),
                "available": available,
                "pending": pending,
                "source": "SportsDataverse/cfbfastR PBP",
                "source_url": PBP_URL,
                "model_a_touched": False,
                "notes": [
                    "Every final receives a postgame record.",
                    "Full metrics appear when matching PBP is available.",
                    "Pending games retry automatically.",
                    "Postgame Win Expectancy and Adjusted Final Score are beta until historical calibration.",
                    "No CFBD calls are made.",
                ],
            },
            "games": output_games,
        },
    )

    print(
        f"Postgame analytics: {available} available, {pending} pending, "
        f"{len(output_games)} finals total."
    )
    print("✅ No CFBD calls were made")
    print("✅ Model A was not changed")


if __name__ == "__main__":
    main()
