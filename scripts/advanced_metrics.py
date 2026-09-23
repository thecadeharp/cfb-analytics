"""Build display-only advanced team metrics from normalized play-by-play.

This module is intentionally isolated from Model A. It receives normalized
scrimmage plays and writes a separate public data file. Nothing here changes
ratings or projections.
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


def _ratio(numerator, denominator, digits=1):
    denominator_number = _number(denominator)
    if denominator_number is None or denominator_number <= 0:
        return None
    return round(float(numerator) * 100 / denominator_number, digits)


def _description(play):
    return f"{play.get('play_type', '')} {play.get('play_text', '')}".lower()


def _is_sack(play):
    return bool(play.get("sack")) or "sack" in _description(play)


def _is_spike_or_throwaway(play):
    text = _description(play)
    return any(term in text for term in ("spike", "spiked", "throwaway", "thrown away"))


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


def _is_fumble(play):
    return bool(play.get("fumble")) or "fumble" in _description(play)


def _is_fumble_lost(play):
    if not _is_fumble(play):
        return False
    return bool(play.get("fumble_lost")) or _is_turnover(play)


def _is_havoc(play):
    if play.get("havoc"):
        return True
    text = _description(play)
    return any(
        (
            _is_sack(play),
            _is_turnover(play),
            bool(play.get("tfl")),
            bool(play.get("pass_breakup")),
            "tackle for loss" in text,
            "broken up" in text,
            "pass breakup" in text,
        )
    )


def _is_front_seven_havoc(play):
    text = _description(play)
    return any(
        (
            _is_sack(play),
            bool(play.get("tfl")),
            bool(play.get("forced_fumble")),
            "tackle for loss" in text,
            "forced fumble" in text,
        )
    )


def _is_secondary_havoc(play):
    text = _description(play)
    return any(
        (
            "interception" in text,
            bool(play.get("pass_breakup")),
            "broken up" in text,
            "pass breakup" in text,
        )
    )


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


def _drive_metrics(plays):
    """Aggregate drive/territory measures only when a stable drive id exists."""
    grouped = {}
    for play in plays:
        drive_id = play.get("drive_id")
        game_id = play.get("game_id")
        if drive_id in (None, "") or game_id in (None, ""):
            continue
        grouped.setdefault((str(game_id), str(drive_id)), []).append(play)

    available_yards = []
    scoring_drives = 0
    opportunities = 0
    opportunity_points = 0.0
    red_zone_trips = 0
    red_zone_touchdowns = 0
    red_zone_scores = 0

    for drive in grouped.values():
        start_yards_to_goal = next(
            (
                _number(play.get("yards_to_goal"))
                for play in drive
                if _number(play.get("yards_to_goal")) is not None
            ),
            None,
        )
        net_yards = sum(_number(play.get("yards_gained")) or 0.0 for play in drive)
        if start_yards_to_goal and start_yards_to_goal > 0:
            available_yards.append(
                max(0.0, min(1.0, net_yards / start_yards_to_goal))
            )

        start_score = next(
            (
                _number(play.get("offense_score"))
                for play in drive
                if _number(play.get("offense_score")) is not None
            ),
            0.0,
        ) or 0.0
        end_scores = [
            _number(play.get("offense_score_after"))
            for play in drive
            if _number(play.get("offense_score_after")) is not None
        ]
        points = max(0.0, (max(end_scores) if end_scores else start_score) - start_score)
        if not points and any(play.get("touchdown") for play in drive):
            points = 7.0
        if points > 0:
            scoring_drives += 1

        yards_to_goal = [
            _number(play.get("yards_to_goal"))
            for play in drive
            if _number(play.get("yards_to_goal")) is not None
        ]
        if yards_to_goal and min(yards_to_goal) <= 40:
            opportunities += 1
            opportunity_points += points
        if yards_to_goal and min(yards_to_goal) <= 20:
            red_zone_trips += 1
            if points > 0:
                red_zone_scores += 1
            if any(play.get("touchdown") for play in drive):
                red_zone_touchdowns += 1

    drive_count = len(grouped)
    return {
        "drives": drive_count,
        "available_yards_pct": (
            round(sum(available_yards) * 100 / len(available_yards), 1)
            if available_yards
            else None
        ),
        "drive_scoring_rate": _ratio(scoring_drives, drive_count),
        "scoring_opportunities": opportunities,
        "points_per_opportunity": (
            round(opportunity_points / opportunities, 2)
            if opportunities
            else None
        ),
        "red_zone_trips": red_zone_trips,
        "red_zone_scoring_rate": _ratio(red_zone_scores, red_zone_trips),
        "red_zone_td_rate": _ratio(red_zone_touchdowns, red_zone_trips),
    }


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
    successful = [play for play in plays if play.get("success")]
    third_downs = [
        play for play in plays
        if int(_number(play.get("down")) or 0) == 3
    ]
    eligible_dropbacks = [play for play in pass_plays if not _is_spike_or_throwaway(play)]
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

    fumbles = sum(_is_fumble(play) for play in plays)
    fumbles_lost = sum(_is_fumble_lost(play) for play in plays)
    team_fumble_recoveries = (
        fumbles - fumbles_lost
        if side == "offense"
        else fumbles_lost
    )
    drive_metrics = _drive_metrics(plays)

    metrics = {
        "n_plays": len(plays),
        "yards_per_play": _mean((play.get("yards_gained") for play in plays), 2),
        "yards_per_rush": _mean((play.get("yards_gained") for play in rush_plays), 2),
        "yards_per_pass_play": _mean((play.get("yards_gained") for play in pass_plays), 2),
        "epa_play": _mean(play.get("epa") for play in plays),
        "success_rate": _rate(play.get("success") for play in plays),
        "iso_ppp": _mean(play.get("epa") for play in successful),
        "explosive_rate": _rate(play.get("explosive") for play in plays),
        "early_down_epa": _mean(play.get("epa") for play in early),
        "early_down_success_rate": _rate(play.get("success") for play in early),
        "early_down_plays": len(early),
        "late_down_epa": _mean(play.get("epa") for play in late),
        "late_down_plays": len(late),
        "standard_down_epa": _mean(play.get("epa") for play in standard),
        "standard_down_success_rate": _rate(play.get("success") for play in standard),
        "standard_down_plays": len(standard),
        "passing_down_epa": _mean(play.get("epa") for play in passing),
        "passing_down_success_rate": _rate(play.get("success") for play in passing),
        "passing_down_plays": len(passing),
        "third_down_conversion_rate": _rate(play.get("success") for play in third_downs),
        "expected_third_down_conversion_rate": None,
        "third_down_conversion_delta": None,
        "third_down_attempts": len(third_downs),
        "stuff_rate": _rate((_number(play.get("yards_gained")) or 0) <= 0 for play in rush_plays),
        "opportunity_rate": _rate((_number(play.get("yards_gained")) or 0) >= 4 for play in rush_plays),
        "rush_attempts": len(rush_plays),
        "sack_rate": _rate(_is_sack(play) for play in pass_plays),
        "adjusted_sack_rate": _rate(_is_sack(play) for play in eligible_dropbacks),
        "pass_plays": len(pass_plays),
        "tfl_rate": _rate((_number(play.get("yards_gained")) or 0) < 0 for play in plays),
        "havoc_rate": _rate(_is_havoc(play) for play in plays),
        "front_seven_havoc_rate": _rate(_is_front_seven_havoc(play) for play in plays),
        "secondary_havoc_rate": _rate(_is_secondary_havoc(play) for play in pass_plays),
        "power_success_rate": _rate(play.get("success") for play in power),
        "power_attempts": len(power),
        "turnovers": sum(_is_turnover(play) for play in plays),
        "turnover_rate": _rate(_is_turnover(play) for play in plays),
        "fumbles": fumbles,
        "fumbles_lost": fumbles_lost,
        "fumble_recovery_delta": (
            round(team_fumble_recoveries - 0.5 * fumbles, 1)
            if fumbles
            else 0.0
        ),
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
    metrics.update(drive_metrics)
    return metrics


def _add_third_down_deltas(output):
    """Use the current FBS cross-section to estimate third-down expectation.

    This is intentionally a transparent regression residual rather than a
    hand-picked threshold: third-down conversion rate is regressed on each
    team's early-down success rate, separately for offense and defense.
    """
    for sample in ("non_garbage", "all_plays"):
        for side in ("offense", "defense"):
            rows = []
            for team in output["teams"].values():
                metrics = team[sample][side]
                x = _number(metrics.get("early_down_success_rate"))
                y = _number(metrics.get("third_down_conversion_rate"))
                attempts = int(metrics.get("third_down_attempts") or 0)
                if x is not None and y is not None and attempts >= MIN_SAMPLE:
                    rows.append((x, y))

            if len(rows) < 2:
                continue
            x_mean = sum(x for x, _ in rows) / len(rows)
            y_mean = sum(y for _, y in rows) / len(rows)
            denominator = sum((x - x_mean) ** 2 for x, _ in rows)
            slope = (
                sum((x - x_mean) * (y - y_mean) for x, y in rows) / denominator
                if denominator
                else 0.0
            )
            intercept = y_mean - slope * x_mean

            for team in output["teams"].values():
                metrics = team[sample][side]
                x = _number(metrics.get("early_down_success_rate"))
                y = _number(metrics.get("third_down_conversion_rate"))
                if x is None or y is None:
                    metrics["expected_third_down_conversion_rate"] = None
                    metrics["third_down_conversion_delta"] = None
                    continue
                expected = max(0.0, min(100.0, intercept + slope * x))
                metrics["expected_third_down_conversion_rate"] = round(expected, 1)
                metrics["third_down_conversion_delta"] = round(y - expected, 1)


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
            "game_ids": sorted(
                {
                    str(play.get("game_id"))
                    for play in plays
                    if play.get("game_id") not in (None, "")
                }
            ),
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
                "iso_ppp": "Mean EPA on successful plays",
                "stuff_rate": "Share of rushes gaining zero or fewer yards",
                "opportunity_rate": "Share of rushes gaining at least four yards",
                "line_yards": "120% of losses, 100% through 4 yards, 50% from 5-10, capped after 10",
                "red_zone": "Scrimmage plays at the opponent 20-yard line or closer",
                "red_zone_scoring_rate": "Share of red-zone drives producing any points",
                "adjusted_sack_rate": "Sacks per qualifying dropback after removing spikes and throwaways",
                "available_yards": "Share of starting drive field space gained, capped from 0% to 100%",
                "scoring_opportunity": "Drive reaching the opponent 40-yard line",
                "third_down_delta": "Actual third-down conversion rate minus the FBS expectation regressed from early-down success",
                "fumble_recovery_delta": "Team fumble recoveries minus a 50/50 recovery expectation",
                "garbage_time": "First half at 38+ points, third quarter at 28+ points, or fourth quarter at 22+ points",
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

    _add_third_down_deltas(output)
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
