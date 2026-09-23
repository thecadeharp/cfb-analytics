#!/usr/bin/env python3
"""Build THI Observed Ratings v0.1 from the display-only metrics layer.

This engine is intentionally isolated from Model A. It converts current-season,
non-garbage-time FBS-vs-FBS performance into opponent-adjusted offensive,
defensive and net ratings. The output is descriptive and is never read by the
projection engine.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ADVANCED_PATH = DATA / "advanced_metrics.json"
SCHEDULE_PATH = DATA / "schedule.json"
OUTPUT_PATH = DATA / "thi_observed_ratings.json"
SNAPSHOT_DIR = DATA / "ratings_snapshots"

VERSION = "0.1.0"
MIN_PLAYS = 35
SHRINKAGE_PLAYS = 140
OPPONENT_ADJUSTMENT_STRENGTH = 0.70
ITERATIONS = 24
DAMPING = 0.45

METRICS = {
    "epa_play": {
        "label": "EPA / Play",
        "format": "epa",
        "sample": "n_plays",
        "cap": 0.18,
    },
    "yards_per_play": {
        "label": "Yards / Play",
        "format": "decimal",
        "sample": "n_plays",
        "cap": 2.00,
    },
    "success_rate": {
        "label": "Success Rate",
        "format": "percent",
        "sample": "n_plays",
        "cap": 12.00,
    },
    "yards_per_rush": {
        "label": "Yards / Carry",
        "format": "decimal",
        "sample": "rush_attempts",
        "cap": 2.00,
    },
    "yards_per_pass_play": {
        "label": "Yards / Pass Play",
        "format": "decimal",
        "sample": "pass_plays",
        "cap": 2.50,
    },
    "red_zone_scoring_rate": {
        "label": "Red-Zone Scoring Rate",
        "format": "percent",
        "sample": "red_zone_trips",
        "cap": 20.00,
    },
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def weighted_mean(values: dict[str, float], weights: dict[str, float]) -> float:
    total_weight = sum(max(0.0, weights.get(team, 0.0)) for team in values)
    if total_weight <= 0:
        return sum(values.values()) / len(values) if values else 0.0
    return sum(values[team] * max(0.0, weights.get(team, 0.0)) for team in values) / total_weight


def average(values: list[float]) -> float | None:
    clean = [float(value) for value in values if finite(value)]
    return sum(clean) / len(clean) if clean else None


def color_band(percentile: float | None) -> str:
    if percentile is None:
        return "missing"
    if percentile >= 85:
        return "elite"
    if percentile >= 70:
        return "strong"
    if percentile >= 55:
        return "above"
    if percentile >= 45:
        return "average"
    if percentile >= 30:
        return "below"
    if percentile >= 15:
        return "poor"
    return "critical"


def ranked(values: dict[str, float], higher_is_better: bool) -> dict[str, dict[str, Any]]:
    ordered = sorted(
        values.items(),
        key=lambda item: (-item[1] if higher_is_better else item[1], item[0]),
    )
    count = len(ordered)
    output: dict[str, dict[str, Any]] = {}
    for index, (team, value) in enumerate(ordered, start=1):
        if count <= 1:
            percentile = 50.0
        else:
            percentile = 100.0 * (count - index) / (count - 1)
        output[team] = {
            "value": round(value, 2),
            "rank": index,
            "percentile": round(percentile, 1),
            "band": color_band(percentile),
        }
    return output


def sample_games(
    advanced: dict[str, Any], schedule: dict[str, Any], team_names: set[str]
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    game_ids = {str(value) for value in advanced.get("meta", {}).get("game_ids", [])}
    through_week = int(advanced.get("meta", {}).get("through_week") or 0)
    games: list[dict[str, Any]] = []
    opponents = {team: [] for team in team_names}

    for game in schedule.get("games", []):
        home = game.get("home_team")
        away = game.get("away_team")
        if home not in team_names or away not in team_names:
            continue
        if str(game.get("opponent_type") or "FBS").upper() != "FBS":
            continue
        if game_ids:
            if str(game.get("id")) not in game_ids:
                continue
        else:
            if int(game.get("week") or 0) > through_week:
                continue
            if str(game.get("status") or "").lower() != "completed":
                continue
        games.append(game)
        opponents[home].append(away)
        opponents[away].append(home)

    return games, opponents


def reliability(plays: int, games: int) -> dict[str, Any]:
    weight = plays / (plays + SHRINKAGE_PLAYS) if plays > 0 else 0.0
    if plays < 70 or games < 2:
        label = "LIMITED"
    elif plays < 140:
        label = "DEVELOPING"
    elif plays < 240:
        label = "STABILIZING"
    else:
        label = "STRONG"
    return {
        "label": label,
        "weight": round(weight, 3),
        "qualifying_plays": plays,
        "games": games,
    }


def adjust_metric(
    team_rows: dict[str, Any],
    opponents: dict[str, list[str]],
    field: str,
    sample_field: str,
    adjustment_cap: float,
) -> dict[str, Any]:
    raw_off: dict[str, float] = {}
    raw_def: dict[str, float] = {}
    off_weights: dict[str, float] = {}
    def_weights: dict[str, float] = {}

    for team, row in team_rows.items():
        offense = row.get("non_garbage", {}).get("offense", {})
        defense = row.get("non_garbage", {}).get("defense", {})
        if finite(offense.get(field)):
            raw_off[team] = float(offense[field])
            off_weights[team] = float(offense.get(sample_field) or 0)
        if finite(defense.get(field)):
            raw_def[team] = float(defense[field])
            def_weights[team] = float(defense.get(sample_field) or 0)

    combined = {f"o:{team}": value for team, value in raw_off.items()}
    combined.update({f"d:{team}": value for team, value in raw_def.items()})
    combined_weights = {f"o:{team}": off_weights[team] for team in raw_off}
    combined_weights.update({f"d:{team}": def_weights[team] for team in raw_def})
    baseline = weighted_mean(combined, combined_weights)

    off = {
        team: baseline + (value - baseline) * (off_weights[team] / (off_weights[team] + SHRINKAGE_PLAYS))
        for team, value in raw_off.items()
    }
    defense = {
        team: baseline + (value - baseline) * (def_weights[team] / (def_weights[team] + SHRINKAGE_PLAYS))
        for team, value in raw_def.items()
    }

    for _ in range(ITERATIONS):
        new_off: dict[str, float] = {}
        new_def: dict[str, float] = {}
        for team, current in off.items():
            faced = [defense[opp] for opp in opponents.get(team, []) if opp in defense]
            opponent_mean = average(faced)
            raw_adjustment = (
                OPPONENT_ADJUSTMENT_STRENGTH * (baseline - opponent_mean)
                if opponent_mean is not None
                else 0.0
            )
            adjustment = max(-adjustment_cap, min(adjustment_cap, raw_adjustment))
            target = baseline + (raw_off[team] + adjustment - baseline) * (
                off_weights[team] / (off_weights[team] + SHRINKAGE_PLAYS)
            )
            new_off[team] = current * (1.0 - DAMPING) + target * DAMPING

        for team, current in defense.items():
            faced = [off[opp] for opp in opponents.get(team, []) if opp in off]
            opponent_mean = average(faced)
            raw_adjustment = (
                -OPPONENT_ADJUSTMENT_STRENGTH * (opponent_mean - baseline)
                if opponent_mean is not None
                else 0.0
            )
            adjustment = max(-adjustment_cap, min(adjustment_cap, raw_adjustment))
            target = baseline + (raw_def[team] + adjustment - baseline) * (
                def_weights[team] / (def_weights[team] + SHRINKAGE_PLAYS)
            )
            new_def[team] = current * (1.0 - DAMPING) + target * DAMPING

        off, defense = new_off, new_def

    return {
        "baseline": baseline,
        "raw_offense": raw_off,
        "raw_defense": raw_def,
        "adjusted_offense": off,
        "adjusted_defense": defense,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-snapshot", action="store_true")
    args = parser.parse_args()

    advanced = load_json(ADVANCED_PATH)
    schedule = load_json(SCHEDULE_PATH)
    team_rows = advanced.get("teams", {})
    team_names = set(team_rows)
    if len(advanced.get("meta", {}).get("game_ids", [])) < 50:
        raise RuntimeError(
            "Refresh Advanced Metrics v2 first: exact completed-game IDs are required"
        )
    enriched = sum(
        all(
            finite(row.get("non_garbage", {}).get(side, {}).get(field))
            for side in ("offense", "defense")
            for field in ("yards_per_play", "yards_per_rush", "yards_per_pass_play")
        )
        for row in team_rows.values()
    )
    if enriched < 80:
        raise RuntimeError(
            f"Refresh Advanced Metrics v2 first: complete yardage for {enriched} teams"
        )
    games, opponents = sample_games(advanced, schedule, team_names)

    metric_results = {
        field: adjust_metric(
            team_rows,
            opponents,
            field,
            definition["sample"],
            definition["cap"],
        )
        for field, definition in METRICS.items()
    }

    epa = metric_results["epa_play"]
    game_points = [
        float(points)
        for game in games
        for points in (game.get("home_points"), game.get("away_points"))
        if finite(points)
    ]
    national_points = average(game_points) or 28.0

    total_all_plays = sum(
        float(row.get("all_plays", {}).get("offense", {}).get("n_plays") or 0)
        for row in team_rows.values()
    )
    total_team_games = sum(len(value) for value in opponents.values())
    national_plays = total_all_plays / total_team_games if total_team_games else 68.0

    eligible = {
        team
        for team, row in team_rows.items()
        if int(row.get("non_garbage", {}).get("offense", {}).get("n_plays") or 0) >= MIN_PLAYS
        and int(row.get("non_garbage", {}).get("defense", {}).get("n_plays") or 0) >= MIN_PLAYS
        and len(opponents.get(team, [])) > 0
        and team in epa["adjusted_offense"]
        and team in epa["adjusted_defense"]
    }

    offense_values = {
        team: national_points
        + (epa["adjusted_offense"][team] - epa["baseline"]) * national_plays
        for team in eligible
    }
    defense_values = {
        team: national_points
        + (epa["adjusted_defense"][team] - epa["baseline"]) * national_plays
        for team in eligible
    }
    net_values = {team: offense_values[team] - defense_values[team] for team in eligible}

    pace_values: dict[str, float] = {}
    for team in eligible:
        games_played = len(opponents.get(team, []))
        all_plays = float(
            team_rows[team].get("all_plays", {}).get("offense", {}).get("n_plays") or 0
        )
        if games_played and national_plays > 0:
            pace_values[team] = (all_plays / games_played) / national_plays

    ranked_offense = ranked(offense_values, True)
    ranked_defense = ranked(defense_values, False)
    ranked_net = ranked(net_values, True)
    ranked_pace = ranked(pace_values, True)

    adjusted_rankings: dict[str, dict[str, dict[str, Any]]] = {}
    for field, result in metric_results.items():
        adjusted_rankings[field] = {
            "offense": ranked(
                {team: value for team, value in result["adjusted_offense"].items() if team in eligible},
                True,
            ),
            "defense": ranked(
                {team: value for team, value in result["adjusted_defense"].items() if team in eligible},
                False,
            ),
        }

    output_teams: dict[str, Any] = {}
    for team in sorted(team_names):
        row = team_rows[team]
        offense_plays = int(row.get("non_garbage", {}).get("offense", {}).get("n_plays") or 0)
        defense_plays = int(row.get("non_garbage", {}).get("defense", {}).get("n_plays") or 0)
        qualifying_plays = min(offense_plays, defense_plays)
        games_played = len(opponents.get(team, []))
        team_output: dict[str, Any] = {
            "team": team,
            "eligible": team in eligible,
            "reliability": reliability(qualifying_plays, games_played),
            "ratings": {},
            "metrics": {},
        }
        if team in eligible:
            team_output["ratings"] = {
                "offense": ranked_offense[team],
                "defense": ranked_defense[team],
                "net": ranked_net[team],
                "pace": ranked_pace.get(team),
            }
            for field, definition in METRICS.items():
                result = metric_results[field]
                team_output["metrics"][field] = {
                    "label": definition["label"],
                    "format": definition["format"],
                    "offense": adjusted_rankings[field]["offense"].get(team),
                    "defense": adjusted_rankings[field]["defense"].get(team),
                    "raw_offense": round(result["raw_offense"].get(team), 3)
                    if team in result["raw_offense"]
                    else None,
                    "raw_defense": round(result["raw_defense"].get(team), 3)
                    if team in result["raw_defense"]
                    else None,
                }
        output_teams[team] = team_output

    through_week = int(advanced.get("meta", {}).get("through_week") or 0)
    payload = {
        "meta": {
            "season": int(advanced.get("meta", {}).get("year") or 2026),
            "through_week": through_week,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "version": VERSION,
            "status": "PUBLIC_BETA",
            "name": "THI Observed Ratings",
            "model_usage": "display_only_not_used_by_model_a",
            "sample": "completed FBS-vs-FBS scrimmage plays with garbage time excluded",
            "source_contract": "advanced_metrics.json plus schedule.json",
            "upstream_play_by_play": advanced.get("meta", {}).get("source"),
            "upstream_epa_model": advanced.get("meta", {}).get("epa_source"),
            "methodology": {
                "description": "Current-season performance adjusted iteratively for opponents faced and regressed toward the FBS average according to sample size.",
                "offense_rating": "Scoring-scale index: national FBS points per game plus opponent-adjusted offensive EPA deviation times national average plays. Descriptive, not a game score forecast.",
                "defense_rating": "Scoring-scale index: national FBS points per game plus opponent-adjusted defensive EPA allowed deviation times national average plays; lower is better.",
                "net_rating": "Offensive rating minus defensive rating.",
                "pace_rating": "Unadjusted scrimmage plays per game indexed to the FBS average of 1.00; affected by opponent tempo and game script.",
                "opponent_adjustment": "Iterative adjustment from each FBS opponent's season-wide efficiency; one opponent contributes once per game. Aggregate approximation, not a play-level opponent model.",
                "minimum_plays": MIN_PLAYS,
                "shrinkage_plays": SHRINKAGE_PLAYS,
                "opponent_adjustment_strength": OPPONENT_ADJUSTMENT_STRENGTH,
                "iterations": ITERATIONS,
                "market_inputs": False,
                "preseason_inputs": False,
            },
            "national_baselines": {
                "points_per_team_game": round(national_points, 2),
                "scrimmage_plays_per_team_game": round(national_plays, 2),
                "epa_per_play": round(epa["baseline"], 4),
            },
            "qualifying_games": len(games),
            "eligible_teams": len(eligible),
            "metrics": METRICS,
        },
        "teams": output_teams,
    }

    if len(output_teams) < 100 or len(eligible) < 80 or len(games) < 50:
        raise RuntimeError(
            f"THI Ratings safety check failed: {len(output_teams)} teams, {len(eligible)} eligible"
        )
    if payload["meta"]["model_usage"] != "display_only_not_used_by_model_a":
        raise RuntimeError("THI Ratings must remain isolated from Model A")

    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if not args.no_snapshot:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        version_slug = VERSION.replace(".", "_")
        snapshot_path = SNAPSHOT_DIR / f"{payload['meta']['season']}_week_{through_week}_v{version_slug}.json"
        if not snapshot_path.exists():
            snapshot_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            print(f"Wrote frozen snapshot: {snapshot_path.relative_to(ROOT)}")
        else:
            print(f"Preserved existing snapshot: {snapshot_path.relative_to(ROOT)}")

    print(f"Wrote {OUTPUT_PATH.relative_to(ROOT)}")
    print(f"Eligible teams: {len(eligible)}")
    print(f"Qualifying games: {len(games)}")
    print("Model A files were not read or modified")


if __name__ == "__main__":
    main()
