#!/usr/bin/env python3
"""Build an isolated, retrospective postgame analytics layer.

Inputs are frozen prospective settlements plus CFBD completed-game advanced box
scores and play-by-play. The script never imports or rewrites Model A. Existing
postgame rows are preserved when CFBD is unavailable, and unavailable metrics
remain null rather than being inferred from the final score.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
SETTLED_PATH = ROOT / "data" / "reports" / "settled_results.json"
OUTPUT_PATH = ROOT / "data" / "postgame_analytics.json"
CFBD_BASE = "https://api.collegefootballdata.com"
VERSION = "postgame-analytics-v1"


def number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def rounded(value: Any, digits: int = 3) -> float | None:
    value = number(value)
    return round(value, digits) if value is not None else None


def canonical(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def first_snapshot_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    earliest: dict[str, dict[str, Any]] = {}
    for row in payload.get("rows") or []:
        if not row.get("result_settled"):
            continue
        game_id = str(row.get("game_key") or "").strip()
        if not game_id:
            continue
        current = earliest.get(game_id)
        stamp = str(row.get("captured_at_utc") or "")
        if current is None or stamp < str(current.get("captured_at_utc") or ""):
            earliest[game_id] = row
    return list(earliest.values())


class CfbdClient:
    def __init__(self, api_key: str):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    def get(self, endpoint: str, params: dict[str, Any]) -> Any:
        waits = (0, 5, 15, 30)
        last_error = "unknown error"
        for wait in waits:
            if wait:
                time.sleep(wait)
            try:
                response = self.session.get(
                    f"{CFBD_BASE}{endpoint}", params=params, timeout=35
                )
            except requests.RequestException as error:
                last_error = str(error)
                continue
            if response.status_code == 429:
                last_error = "HTTP 429 rate limit"
                continue
            if response.status_code in (401, 403):
                raise RuntimeError(f"CFBD authentication failed: HTTP {response.status_code}")
            if not response.ok:
                last_error = f"HTTP {response.status_code}: {response.text[:160]}"
                continue
            return response.json()
        raise RuntimeError(f"CFBD {endpoint} failed after retries: {last_error}")


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    output: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            output.update(flatten(child, name))
    else:
        output[canonical(prefix)] = value
    return output


def section_rows(payload: dict[str, Any], section: str) -> list[dict[str, Any]]:
    candidates = [
        payload.get(section),
        (payload.get("teams") or {}).get(section)
        if isinstance(payload.get("teams"), dict)
        else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            return [row for row in candidate if isinstance(row, dict)]
    return []


def team_row(payload: dict[str, Any], section: str, team: str) -> dict[str, Any]:
    wanted = canonical(team)
    for row in section_rows(payload, section):
        label = row.get("team") or row.get("school") or row.get("teamName")
        if canonical(label) == wanted:
            return row
    return {}


def find_metric(row: dict[str, Any], *keys: str) -> float | None:
    values = flatten(row)
    for key in keys:
        wanted = canonical(key)
        if wanted in values:
            result = number(values[wanted])
            if result is not None:
                return result
    for key in keys:
        wanted = canonical(key)
        for path, raw in values.items():
            if path.endswith(wanted):
                result = number(raw)
                if result is not None:
                    return result
    return None


def percentage(value: Any) -> float | None:
    value = number(value)
    if value is None:
        return None
    return rounded(value * 100.0 if abs(value) <= 1.0 else value, 1)


def team_advanced(payload: dict[str, Any], team: str) -> dict[str, Any]:
    ppa = team_row(payload, "ppa", team)
    success = team_row(payload, "successRates", team)
    explosive = team_row(payload, "explosiveness", team)
    scoring = team_row(payload, "scoringOpportunities", team)
    field = team_row(payload, "fieldPosition", team)
    havoc = team_row(payload, "havoc", team)
    return {
        "plays": rounded(find_metric(ppa, "plays"), 0),
        "epa_per_play": rounded(find_metric(ppa, "overall.total", "overall", "total")),
        "success_rate": percentage(find_metric(success, "overall.total", "overall", "total")),
        "standard_down_success_rate": percentage(
            find_metric(success, "standardDowns.total", "standardDowns")
        ),
        "passing_down_success_rate": percentage(
            find_metric(success, "passingDowns.total", "passingDowns")
        ),
        "explosiveness": rounded(
            find_metric(explosive, "overall.total", "overall", "total")
        ),
        "scoring_opportunities": rounded(
            find_metric(scoring, "opportunities", "scoringOpportunities"), 0
        ),
        "points_per_opportunity": rounded(
            find_metric(scoring, "pointsPerOpportunity", "pointsPerScoringOpportunity")
        ),
        "average_start": rounded(find_metric(field, "averageStart", "avgStart"), 1),
        "average_start_ep": rounded(
            find_metric(field, "averagePredictedPoints", "averageStartPredictedPoints")
        ),
        "havoc_rate": percentage(find_metric(havoc, "total", "havoc.total")),
    }


def play_team(play: dict[str, Any]) -> str:
    return str(play.get("offense") or play.get("offenseTeam") or "").strip()


def play_epa(play: dict[str, Any]) -> float | None:
    return number(play.get("ppa") if play.get("ppa") is not None else play.get("epa"))


def is_garbage(play: dict[str, Any]) -> bool:
    period = int(number(play.get("period")) or 0)
    home = number(play.get("homeScore"))
    away = number(play.get("awayScore"))
    if home is None or away is None:
        return False
    margin = abs(home - away)
    return (period == 3 and margin >= 28) or (period >= 4 and margin >= 21)


def is_explosive(play: dict[str, Any]) -> bool:
    yards = number(play.get("yardsGained"))
    if yards is None:
        return False
    kind = canonical(play.get("playType") or play.get("playTypeText") or play.get("type"))
    return yards >= (20 if "pass" in kind else 10 if "rush" in kind else 20)


def play_splits(plays: list[dict[str, Any]], team: str) -> dict[str, Any]:
    rows = [play for play in plays if canonical(play_team(play)) == canonical(team)]
    competitive = [play for play in rows if not is_garbage(play)]

    def average_epa(subset: list[dict[str, Any]]) -> float | None:
        values = [play_epa(play) for play in subset]
        values = [value for value in values if value is not None]
        return rounded(sum(values) / len(values)) if values else None

    early = [play for play in competitive if int(number(play.get("down")) or 0) in (1, 2)]
    late = [play for play in competitive if int(number(play.get("down")) or 0) in (3, 4)]
    explosive = [play for play in competitive if is_explosive(play)]
    all_epa = [play_epa(play) for play in competitive]
    positive = sum(max(value or 0.0, 0.0) for value in all_epa)
    explosive_positive = sum(max(play_epa(play) or 0.0, 0.0) for play in explosive)
    dependency = 100.0 * explosive_positive / positive if positive > 0 else None
    garbage_share = 100.0 * (len(rows) - len(competitive)) / len(rows) if rows else None

    variance_values = [value for value in all_epa if value is not None]
    if len(variance_values) >= 2:
        mean = sum(variance_values) / len(variance_values)
        variance = sum((value - mean) ** 2 for value in variance_values) / len(variance_values)
        volatility = math.sqrt(variance)
    else:
        volatility = None

    return {
        "competitive_plays": len(competitive),
        "early_down_epa": average_epa(early),
        "late_down_epa": average_epa(late),
        "explosive_play_count": len(explosive),
        "explosive_epa_dependency_pct": rounded(dependency, 1),
        "garbage_time_play_share_pct": rounded(garbage_share, 1),
        "play_epa_volatility": rounded(volatility),
    }


def home_win_expectancy(payload: dict[str, Any]) -> float | None:
    info = payload.get("gameInfo") or payload.get("game_info") or {}
    value = find_metric(info, "homeWinProb", "homeWinProbability", "homePostgameWinProbability")
    if value is None:
        return None
    if value > 1:
        value /= 100.0
    return min(max(value, 0.001), 0.999)


def adjusted_score(row: dict[str, Any], home_probability: float | None) -> dict[str, Any] | None:
    if home_probability is None:
        return None
    baseline_total = number(row.get("public_total"))
    if baseline_total is None:
        baseline_total = number(row.get("model_total"))
    if baseline_total is None:
        return None
    adjusted_margin = max(-35.0, min(35.0, 7.0 * math.log(home_probability / (1-home_probability))))
    home = max(0.0, (baseline_total + adjusted_margin) / 2.0)
    away = max(0.0, baseline_total - home)
    return {
        "home_points": round(home),
        "away_points": round(away),
        "home_margin": rounded(adjusted_margin, 1),
        "total_baseline": rounded(baseline_total, 1),
        "method": "CFBD postgame win expectancy mapped to margin with a fixed log-odds scale; frozen THI total anchors scoring environment.",
    }


def reality_check(row: dict[str, Any], score: dict[str, Any] | None) -> str | None:
    if not score:
        return None
    actual = number(row.get("actual_home_margin"))
    adjusted = number(score.get("home_margin"))
    if actual is None or adjusted is None:
        return None
    if (actual > 0) != (adjusted > 0):
        return "RESULT DEFIED THE UNDERLYING PLAY"
    gap = abs(actual) - abs(adjusted)
    if gap >= 9:
        return "CLOSER THAN THE SCORE"
    if gap <= -9:
        return "MORE CONTROL THAN THE SCORE"
    return "SCORE MATCHED PERFORMANCE"


def difference(a: Any, b: Any, digits: int = 3) -> float | None:
    a, b = number(a), number(b)
    return rounded(a - b, digits) if a is not None and b is not None else None


def build_game(row: dict[str, Any], advanced: dict[str, Any], plays: list[dict[str, Any]]) -> dict[str, Any]:
    home_name = str(row.get("home_team") or "Home")
    away_name = str(row.get("away_team") or "Away")
    home = team_advanced(advanced, home_name)
    away = team_advanced(advanced, away_name)
    home_splits = play_splits(plays, home_name)
    away_splits = play_splits(plays, away_name)
    probability = home_win_expectancy(advanced)
    score = adjusted_score(row, probability)

    return {
        "game_id": str(row.get("game_key")),
        "week": row.get("week"),
        "away_team": away_name,
        "home_team": home_name,
        "availability": "available" if any(value is not None for value in home.values()) else "partial",
        "source": "CFBD completed-game advanced box score and play-by-play",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "headline": {
            "home_win_expectancy_pct": rounded((probability or 0) * 100, 1) if probability is not None else None,
            "away_win_expectancy_pct": rounded((1-probability) * 100, 1) if probability is not None else None,
            "adjusted_score": score,
            "reality_check": reality_check(row, score),
        },
        "teams": {"away": {**away, **away_splits}, "home": {**home, **home_splits}},
        "comparisons": {
            "epa_margin_home": difference(home.get("epa_per_play"), away.get("epa_per_play")),
            "success_rate_margin_home": difference(home.get("success_rate"), away.get("success_rate")),
            "explosiveness_margin_home": difference(home.get("explosiveness"), away.get("explosiveness")),
            "finishing_drives_margin_home": difference(home.get("points_per_opportunity"), away.get("points_per_opportunity")),
            "field_position_ep_margin_home": difference(home.get("average_start_ep"), away.get("average_start_ep")),
            "early_down_epa_margin_home": difference(home_splits.get("early_down_epa"), away_splits.get("early_down_epa")),
            "late_down_epa_margin_home": difference(home_splits.get("late_down_epa"), away_splits.get("late_down_epa")),
            "garbage_time_share_margin_home": difference(home_splits.get("garbage_time_play_share_pct"), away_splits.get("garbage_time_play_share_pct"), 1),
            "variance_margin_home": difference(home_splits.get("play_epa_volatility"), away_splits.get("play_epa_volatility")),
        },
        "unavailable": {
            "turnover_luck": "Requires a verified turnover-value model; raw turnover margin is not labeled as luck.",
            "red_zone_overperformance": "Held until drive-level red-zone possessions are verified.",
            "hidden_yardage": "Field-position EPA is shown; special-teams hidden yardage requires validated return/punt data.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Rebuild existing game rows.")
    args = parser.parse_args()

    key = os.environ.get("CFBD_API_KEY", "").strip()
    if not key:
        raise SystemExit("CFBD_API_KEY is missing; existing output was not changed.")

    settled = load_json(SETTLED_PATH, {})
    rows = first_snapshot_rows(settled)
    existing = load_json(OUTPUT_PATH, {"meta": {}, "games": {}})
    games = existing.get("games") if isinstance(existing.get("games"), dict) else {}
    client = CfbdClient(key)
    built = skipped = failed = 0

    # One play-by-play request per week, not one per game. This materially
    # reduces CFBD usage while preserving game-level early/late/garbage splits.
    plays_by_game: dict[str, list[dict[str, Any]]] = {}
    weeks_needed = sorted({int(number(row.get("week")) or 0) for row in rows if number(row.get("week"))})
    for week in weeks_needed:
        try:
            week_plays = client.get(
                "/plays",
                {"year": 2026, "week": week, "seasonType": "regular"},
            )
            if isinstance(week_plays, list):
                for play in week_plays:
                    if not isinstance(play, dict):
                        continue
                    play_game = str(play.get("gameId") or play.get("game_id") or "")
                    if play_game:
                        plays_by_game.setdefault(play_game, []).append(play)
        except Exception as error:
            print(f"WARNING: Week {week} play-by-play unavailable: {error}")

    for row in rows:
        game_id = str(row.get("game_key") or "")
        if not args.refresh and game_id in games and games[game_id].get("availability") == "available":
            skipped += 1
            continue
        try:
            advanced = client.get("/game/box/advanced", {"gameId": game_id})
            if not isinstance(advanced, dict):
                raise RuntimeError("advanced box score returned a non-object payload")
            plays = plays_by_game.get(game_id, [])
            games[game_id] = build_game(row, advanced, plays)
            built += 1
            print(f"Built {row.get('away_team')} at {row.get('home_team')}")
        except Exception as error:  # Preserve other completed rows and keep the layer isolated.
            failed += 1
            print(f"WARNING: {game_id} unavailable: {error}")

    output = {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "Retrospective display-only analysis; never a Model A input.",
            "source": "CollegeFootballData completed-game advanced box score and plays endpoints",
            "games_available": len(games),
            "built_this_run": built,
            "preserved_this_run": skipped,
            "failed_this_run": failed,
        },
        "games": games,
    }
    OUTPUT_PATH.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.relative_to(ROOT)} with {len(games)} game(s).")


if __name__ == "__main__":
    main()
