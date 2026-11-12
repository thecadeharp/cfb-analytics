#!/usr/bin/env python3
"""Derive compact live and postgame CBB flow intelligence from CBBD plays.

Raw play-by-play is never written by this module. Every output is a game or
team aggregate and remains display-only until separately validated.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from statistics import NormalDist
from typing import Any

try:
    from scripts.build_cbb_play_style import as_plays, shot_zone, team_id_for_play
except ModuleNotFoundError:
    from build_cbb_play_style import as_plays, shot_zone, team_id_for_play


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def text_value(value: Any) -> str:
    if isinstance(value, dict):
        return str(first_value(value, "displayValue", "display", "value") or "")
    return str(value or "")


def clock_minutes(value: Any) -> float | None:
    text = text_value(value).strip()
    match = re.search(r"(\d+):(\d{1,2})", text)
    if match:
        return int(match.group(1)) + int(match.group(2)) / 60
    number = finite(value)
    return number / 60 if number is not None and number > 40 else number


def period_number(play: dict[str, Any]) -> int:
    value = first_value(play, "period", "periodNumber", "period_number", "half")
    if isinstance(value, dict):
        value = first_value(value, "number", "value")
    return max(1, int(finite(value) or 1))


def elapsed_minutes(play: dict[str, Any]) -> float | None:
    period = period_number(play)
    remaining = clock_minutes(first_value(play, "clock", "displayClock", "clockDisplay"))
    if remaining is None:
        return None
    if period <= 2:
        return max(0.0, min(40.0, (period - 1) * 20 + (20 - remaining)))
    return max(40.0, 40 + (period - 3) * 5 + (5 - remaining))


def description(play: dict[str, Any]) -> str:
    return str(first_value(play, "playText", "text", "description", "shortText") or "")


def play_type(play: dict[str, Any]) -> str:
    return " ".join((str(first_value(play, "playType", "type", "typeText") or ""), description(play))).casefold()


def score_pair(play: dict[str, Any]) -> tuple[int | None, int | None]:
    scores = play.get("score") or play.get("scores") or {}
    home = first_value(play, "homeScore", "home_score")
    away = first_value(play, "awayScore", "away_score")
    if isinstance(scores, dict):
        home = home if home is not None else first_value(scores, "home", "homeScore")
        away = away if away is not None else first_value(scores, "away", "awayScore")
    h, a = finite(home), finite(away)
    return (int(h) if h is not None else None, int(a) if a is not None else None)


def actor_name(play: dict[str, Any]) -> str | None:
    for key in ("athlete", "player", "shooter"):
        value = play.get(key)
        if isinstance(value, dict):
            name = first_value(value, "name", "displayName", "fullName")
            if name:
                return str(name)
    value = first_value(play, "athleteName", "playerName")
    if value:
        return str(value)
    match = re.match(r"([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+)+)", description(play))
    return match.group(1) if match else None


def profile_expected_efg(profiles: dict[str, Any] | None, team_id: str) -> float | None:
    if not profiles:
        return None
    for team in profiles.get("teams") or []:
        if str(team.get("team_id")) != team_id:
            continue
        offense = (team.get("four_factors") or {}).get("offense") or {}
        value = finite(first_value(offense, "effective_fg_pct", "effectiveFieldGoalPct"))
        if value is not None:
            return round(value * 100 if abs(value) <= 1.5 else value, 1)
    return None


def is_garbage(elapsed: float, margin: int) -> bool:
    remaining = max(0.0, 40 - elapsed)
    lead = abs(margin)
    return (remaining <= 8 and lead >= 20) or (remaining <= 4 and lead >= 15) or (remaining <= 2 and lead >= 10)


def game_flow(game: dict[str, Any], payload: Any, profiles: dict[str, Any] | None = None) -> dict[str, Any]:
    teams = {
        str((game.get("away") or {}).get("team_id")): {"side": "away", "team": (game.get("away") or {}).get("team")},
        str((game.get("home") or {}).get("team_id")): {"side": "home", "team": (game.get("home") or {}).get("team")},
    }
    counters: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(int))
    player_fouls: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    fouls_by_period: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    score_events: list[dict[str, Any]] = []
    possession_events: list[dict[str, Any]] = []
    current_score = {"home": 0, "away": 0}
    current_elapsed = 0.0
    latest_on_floor: dict[str, Any] = {}

    ordered = sorted(as_plays(payload), key=lambda play: (elapsed_minutes(play) is None, elapsed_minutes(play) or 0))
    for play in ordered:
        elapsed = elapsed_minutes(play)
        if elapsed is None:
            continue
        current_elapsed = max(current_elapsed, elapsed)
        home_score, away_score = score_pair(play)
        if home_score is not None and away_score is not None:
            current_score = {"home": home_score, "away": away_score}
            score_events.append({"elapsed": round(elapsed, 3), "home": home_score, "away": away_score})
        team_id = team_id_for_play(play)
        if team_id not in teams:
            continue
        side = teams[team_id]["side"]
        row = counters[team_id]
        kind = play_type(play)
        shot = play.get("shotInfo") or play.get("shot")
        made = False
        if isinstance(shot, dict):
            row["fga"] += 1
            zone = shot_zone(shot)
            if zone == "three":
                row["three_a"] += 1
            made = bool(first_value(shot, "made", "isMade"))
            if made:
                row["fgm"] += 1
                if zone == "three":
                    row["three_m"] += 1
        free_throw = "free throw" in kind or "freethrow" in kind
        if free_throw and "lane violation" not in kind:
            row["fta"] += 1
            if "makes" in kind or "made" in kind or bool(play.get("made")):
                row["ftm"] += 1
        turnover = "turnover" in kind
        if turnover:
            row["turnovers"] += 1
        if "offensive rebound" in kind:
            row["off_reb"] += 1
        elif "defensive rebound" in kind:
            row["def_reb"] += 1
        foul = "foul" in kind and "drawn" not in kind
        if foul:
            row["team_fouls"] += 1
            fouls_by_period[team_id][period_number(play)] += 1
            player = actor_name(play)
            if player:
                player_fouls[team_id][player] += 1
        on_floor = play.get("onFloor")
        if on_floor:
            latest_on_floor[team_id] = on_floor
        if isinstance(shot, dict) or free_throw or turnover:
            possession_events.append({
                "elapsed": elapsed, "team_id": team_id, "side": side,
                "garbage": is_garbage(elapsed, current_score["home"] - current_score["away"]),
                "turnover": turnover, "free_throw": free_throw, "free_throw_made": bool(free_throw and ("makes" in kind or "made" in kind or play.get("made"))),
            })

    if not score_events:
        current_score = {
            "home": int(finite((game.get("home") or {}).get("score")) or 0),
            "away": int(finite((game.get("away") or {}).get("score")) or 0),
        }
    total_points = current_score["home"] + current_score["away"]
    latest_margin = current_score["home"] - current_score["away"]
    def score_at(minute: float) -> dict[str, Any]:
        prior = [row for row in score_events if row["elapsed"] <= minute + .01]
        return prior[-1] if prior else {"home": 0, "away": 0, "elapsed": 0}
    checkpoint_specs = [("10:00 1H", 10), ("Halftime", 20), ("10:00 2H", 30), ("5:00 2H", 35), ("Final / current", current_elapsed)]
    checkpoints = [{"label": label, **{key: row[key] for key in ("home", "away")}} for label, minute in checkpoint_specs if current_elapsed + .05 >= minute for row in [score_at(minute)]]
    margins = [row["home"] - row["away"] for row in score_events] or [latest_margin]
    final_winner = "home" if latest_margin > 0 else "away" if latest_margin < 0 else None
    comeback = max(0, -min(margins)) if final_winner == "home" else max(0, max(margins)) if final_winner == "away" else 0
    cutoff = max(0.0, current_elapsed - 4)
    start_last = score_at(cutoff)
    last_four = {
        "window_minutes": round(min(4.0, current_elapsed), 1),
        "away_points": max(0, current_score["away"] - int(start_last.get("away") or 0)),
        "home_points": max(0, current_score["home"] - int(start_last.get("home") or 0)),
    }
    for team_id, meta in teams.items():
        last_four[f"{meta['side']}_turnovers"] = sum(event["turnover"] and event["team_id"] == team_id and event["elapsed"] >= cutoff for event in possession_events)
    scoring_times = {"home": [0.0], "away": [0.0]}
    prior_score = {"home": 0, "away": 0}
    for event in score_events:
        for side in ("home", "away"):
            if event[side] > prior_score[side]: scoring_times[side].append(event["elapsed"])
            prior_score[side] = event[side]
    droughts = {}
    for side in ("home", "away"):
        intervals = [b-a for a,b in zip(scoring_times[side], scoring_times[side][1:] + [current_elapsed])]
        droughts[side] = round(max(intervals or [0]), 2)

    team_output = []
    for team_id, meta in teams.items():
        row = counters[team_id]
        opponent_id = next((value for value in teams if value != team_id), None)
        opponent = counters[opponent_id] if opponent_id else {}
        possessions = row["fga"] - row["off_reb"] + row["turnovers"] + .44 * row["fta"]
        efg = 100 * (row["fgm"] + .5 * row["three_m"]) / row["fga"] if row["fga"] else None
        tov = 100 * row["turnovers"] / possessions if possessions else None
        orb_den = row["off_reb"] + opponent.get("def_reb", 0)
        orb = 100 * row["off_reb"] / orb_den if orb_den else None
        ft_rate = 100 * row["fta"] / row["fga"] if row["fga"] else None
        expected_efg = profile_expected_efg(profiles, team_id)
        current_period = 1 if current_elapsed < 20 else 2 if current_elapsed <= 40 else max(3, int((current_elapsed - 40) // 5) + 3)
        fouls = int(fouls_by_period[team_id][current_period])
        bonus = "DOUBLE BONUS" if fouls >= 10 else "BONUS" if fouls >= 7 else f"{max(0, 7-fouls)} to bonus"
        trouble = [{"player": name, "fouls": count} for name, count in player_fouls[team_id].items() if count >= (4 if current_elapsed >= 20 else 3)]
        trouble.sort(key=lambda item: (-item["fouls"], item["player"]))
        team_output.append({
            "team_id": int(team_id) if team_id.isdigit() else team_id, "team": meta["team"], "side": meta["side"],
            "estimated_possessions": round(possessions, 1),
            "four_factors": {"effective_fg_pct": round(efg, 1) if efg is not None else None, "turnover_pct": round(tov, 1) if tov is not None else None, "offensive_rebound_pct": round(orb, 1) if orb is not None else None, "free_throw_rate": round(ft_rate, 1) if ft_rate is not None else None},
            "shooting_vs_expected": {"actual_efg_pct": round(efg, 1) if efg is not None else None, "expected_efg_pct": expected_efg, "difference": round(efg - expected_efg, 1) if efg is not None and expected_efg is not None else None},
            "team_fouls": fouls, "game_fouls": int(row["team_fouls"]), "bonus_state": bonus, "foul_trouble": trouble[:5], "on_floor": latest_on_floor.get(team_id),
        })

    average_possessions = sum(row["estimated_possessions"] for row in team_output) / max(1, len(team_output))
    projected_pace = round(average_possessions * 40 / current_elapsed, 1) if current_elapsed >= 4 else None
    projection = game.get("projection") or {}
    pregame_total = finite(projection.get("total"))
    pregame_possessions = finite(projection.get("projected_possessions")) or 68.0
    live_ppp = total_points / max(1.0, 2 * average_possessions)
    pregame_ppp = pregame_total / max(1.0, 2 * pregame_possessions) if pregame_total is not None else live_ppp
    weight = min(.75, average_possessions / (average_possessions + 25))
    blended_ppp = weight * live_ppp + (1 - weight) * pregame_ppp
    final_possessions = projected_pace or pregame_possessions
    remaining_possessions = max(0.0, final_possessions - average_possessions)
    live_total = round(total_points + 2 * remaining_possessions * blended_ppp, 1) if pregame_total is not None else None
    pregame_margin = finite(projection.get("home_margin")) or 0.0
    remaining_fraction = max(0.0, (40 - min(40, current_elapsed)) / 40)
    expected_final_margin = latest_margin + remaining_fraction * pregame_margin
    sigma = max(2.0, 11.0 * math.sqrt(remaining_fraction))
    home_win_probability = round(100 * (1 - NormalDist(mu=expected_final_margin, sigma=sigma).cdf(0)), 1)
    competitive = sum(not event["garbage"] for event in possession_events)
    garbage = len(possession_events) - competitive
    late_cutoff = max(0.0, current_elapsed - 2)
    late_fts = sum(event["free_throw"] and event["elapsed"] >= late_cutoff for event in possession_events)
    late_ft_points = sum(event["free_throw_made"] and event["elapsed"] >= late_cutoff for event in possession_events)
    return {
        "elapsed_minutes": round(current_elapsed, 2), "score": current_score,
        "estimated_game_possessions": round(average_possessions, 1), "projected_40_minute_pace": projected_pace,
        "thi_live_total_estimate": live_total, "live_home_win_probability": home_win_probability,
        "teams": team_output, "last_four_minutes": {**last_four, "longest_scoring_drought_minutes": droughts}, "score_checkpoints": checkpoints,
        "largest_lead": {"home": max(0, max(margins)), "away": max(0, -min(margins))},
        "biggest_comeback": {"side": final_winner, "points": comeback},
        "possession_context": {"competitive_events": competitive, "garbage_time_events": garbage, "garbage_time_share_pct": round(100 * garbage / len(possession_events), 1) if possession_events else None},
        "late_free_throw_attempt_events": late_fts, "late_free_throw_points": late_ft_points,
        "methodology": "Display-only estimates derived from compact CBBD play aggregates. Live values never alter the frozen pregame projection.",
    }
