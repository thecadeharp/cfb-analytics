"""Build display-only advanced team metrics from CFBD play-by-play.

This module is intentionally isolated from Model A. It receives the same
normalized scrimmage plays already downloaded by weekly_update.py and writes a
separate public data file. Nothing here changes ratings or projections.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime


OUTPUT_PATH = "data/advanced_metrics.json"
MIN_SAMPLE = 4


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value, digits=3):
    number = _number(value)
    return round(number, digits) if number is not None else None


def _mean(values, digits=3):
    clean = [_number(value) for value in values]
    clean = [value for value in clean if value is not None]
    if len(clean) < MIN_SAMPLE:
        return None
    return round(sum(clean) / len(clean), digits)


def _rate(flags, digits=1):
    values = list(flags)
    if len(values) < MIN_SAMPLE:
        return None
    return round(sum(bool(value) for value in values) * 100 / len(values), digits)


def _description(play):
    return f"{play.get('play_type', '')} {play.get('play_text', '')}".lower()


def _is_sack(play):
    return "sack" in _description(play)


def _is_turnover(play):
    text = _description(play)
    if "interception" in text:
        return True
    if "fumble" not in text:
        return False
    if any(
        phrase in text
        for phrase in ("fumble lost", "fumble recovery (opponent)", "fumble return touchdown")
    ):
        return True
    defense = str(play.get("defense") or "").lower()
    return bool(defense and "recover" in text and defense in text)


def _is_standard_down(play):
    down = int(_number(play.get("down")) or 0)
    distance = _number(play.get("distance"))
    if not down or distance is None:
        return False
    if down == 1:
        return True
    if down == 2:
        return distance <= 7
    if down in (3, 4):
        return distance <= 4
    return False


def _line_yards(yards):
    yards = _number(yards) or 0.0
    if yards < 0:
        return yards * 1.2
    if yards <= 4:
        return yards
    if yards <= 10:
        return 4 + (yards - 4) * 0.5
    return 7.0


def _second_level_yards(yards):
    yards = max(_number(yards) or 0.0, 0.0)
    return min(max(yards - 5, 0.0), 5.0)


def _open_field_yards(yards):
    yards = max(_number(yards) or 0.0, 0.0)
    return max(yards - 10, 0.0)


def _side_metrics(plays, team=None, side="offense"):
    if not plays:
        return {"n_plays": 0}

    pass_plays = [play for play in plays if play.get("is_pass")]
    rush_plays = [play for play in plays if play.get("is_rush")]
    early = [play for play in plays if int(_number(play.get("down")) or 0) in (1, 2)]
    late = [play for play in plays if int(_number(play.get("down")) or 0) in (3, 4)]
    standard = [play for play in plays if _is_standard_down(play)]
    passing = [
        play for play in plays
        if int(_number(play.get("down")) or 0) in (1, 2, 3, 4)
        and not _is_standard_down(play)
    ]
    power = [
        play for play in rush_plays
        if int(_number(play.get("down")) or 0) in (3, 4)
        and (_number(play.get("distance")) or 99) <= 2
    ]
    red_zone = [
        play for play in plays
        if (_number(play.get("yards_to_goal")) is not None)
        and _number(play.get("yards_to_goal")) <= 20
    ]
    first_half = [play for play in plays if int(_number(play.get("period")) or 0) <= 2]
    second_half = [play for play in plays if int(_number(play.get("period")) or 0) >= 3]
    team_field = "offense" if side == "offense" else "defense"
    home = [
        play for play in plays
        if play.get(team_field) == team and team == play.get("home")
    ]
    away = [
        play for play in plays
        if play.get(team_field) == team and team == play.get("away")
    ]

    return {
        "n_plays": len(plays),
        "epa_play": _mean(play.get("epa") for play in plays),
        "success_rate": _rate(play.get("success") for play in plays),
        "explosive_rate": _rate(play.get("explosive") for play in plays),
        "early_down_epa": _mean(play.get("epa") for play in early),
        "early_down_plays": len(early),
        "late_down_epa": _mean(play.get("epa") for play in late),
        "late_down_plays": len(late),
        "standard_down_success_rate": _rate(play.get("success") for play in standard),
        "standard_down_plays": len(standard),
        "passing_down_success_rate": _rate(play.get("success") for play in passing),
        "passing_down_plays": len(passing),
        "stuff_rate": _rate((_number(play.get("yards_gained")) or 0) <= 0 for play in rush_plays),
        "rush_attempts": len(rush_plays),
        "sack_rate": _rate(_is_sack(play) for play in pass_plays),
        "pass_plays": len(pass_plays),
        "tfl_rate": _rate((_number(play.get("yards_gained")) or 0) < 0 for play in plays),
        "power_success_rate": _rate(play.get("success") for play in power),
        "power_attempts": len(power),
        "turnovers": sum(_is_turnover(play) for play in plays),
        "turnover_rate": _rate(_is_turnover(play) for play in plays),
        "line_yards_per_rush": _mean(
            [_line_yards(play.get("yards_gained")) for play in rush_plays], 2
        ),
        "second_level_yards_per_rush": _mean(
            [_second_level_yards(play.get("yards_gained")) for play in rush_plays], 2
        ),
        "open_field_yards_per_rush": _mean(
            [_open_field_yards(play.get("yards_gained")) for play in rush_plays], 2
        ),
        "red_zone_epa": _mean(play.get("epa") for play in red_zone),
        "red_zone_success_rate": _rate(play.get("success") for play in red_zone),
        "red_zone_plays": len(red_zone),
        "first_half_epa": _mean(play.get("epa") for play in first_half),
        "first_half_plays": len(first_half),
        "second_half_epa": _mean(play.get("epa") for play in second_half),
        "second_half_plays": len(second_half),
        "home_epa": _mean(play.get("epa") for play in home),
        "home_plays": len(home),
        "away_epa": _mean(play.get("epa") for play in away),
        "away_plays": len(away),
    }


def _team_view(plays, team, side):
    key = "offense" if side == "offense" else "defense"
    return [play for play in plays if play.get(key) == team]


def build_advanced_metrics(plays, teams, through_week, completed_games):
    non_garbage = [play for play in plays if not play.get("garbage_time")]
    output = {
        "meta": {
            "year": 2026,
            "generated": datetime.now().isoformat(),
            "through_week": int(through_week),
            "completed_games": int(completed_games),
            "source": "SportsDataverse cfbfastR ESPN-derived play-by-play",
            "epa_source": "open cfbfastR expected-points model",
            "model_usage": "display_only_not_used_by_model_a",
            "default_view": "non_garbage",
            "minimum_display_sample": MIN_SAMPLE,
            "definitions": {
                "early_downs": "First and second down",
                "late_downs": "Third and fourth down",
                "standard_downs": "First down, second-and-7 or less, third/fourth-and-4 or less",
                "passing_downs": "All other scrimmage-down situations",
                "stuff_rate": "Share of rushes gaining zero or fewer yards",
                "line_yards": "120% of losses, 100% through 4 yards, 50% from 5-10, capped after 10",
                "red_zone": "Scrimmage plays at the opponent 20-yard line or closer",
                "garbage_time": "Fourth quarter at 28+ points or third quarter at 38+ points",
            },
        },
        "teams": {},
    }

    for team in sorted(teams):
        output["teams"][team] = {
            "non_garbage": {
                "offense": _side_metrics(_team_view(non_garbage, team, "offense"), team, "offense"),
                "defense": _side_metrics(_team_view(non_garbage, team, "defense"), team, "defense"),
            },
            "all_plays": {
                "offense": _side_metrics(_team_view(plays, team, "offense"), team, "offense"),
                "defense": _side_metrics(_team_view(plays, team, "defense"), team, "defense"),
            },
        }

    return output


def write_advanced_metrics(plays, teams, through_week, completed_games, output_path=OUTPUT_PATH):
    output = build_advanced_metrics(plays, teams, through_week, completed_games)
    if len(output["teams"]) < 100:
        raise ValueError("Advanced metrics safety check failed: fewer than 100 teams")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    temp_path = output_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(output, file, indent=2, ensure_ascii=False, allow_nan=False)
    os.replace(temp_path, output_path)

    populated = sum(
        data["non_garbage"]["offense"].get("n_plays", 0) > 0
        for data in output["teams"].values()
    )
    print(f"✅ Advanced metrics written: {output_path}")
    print(f"   Teams with offensive samples: {populated}")
    return output
