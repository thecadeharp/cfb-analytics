#!/usr/bin/env python3
"""Build the public, resume-aware THI CFB Index.

This display ranking is intentionally separate from Model A and the experimental
THI Power research rating. It uses only completed-season results, current
performance, schedule quality, and the production predictive rating. Roster
contribution is never an input.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WEIGHTS = {
    "results": 0.35,
    "record": 0.20,
    "predictive": 0.20,
    "observed_performance": 0.15,
    "schedule_strength": 0.10,
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def average_tie_percentiles(values: dict[str, float]) -> dict[str, float]:
    """Return 0-100 percentiles where larger values are better."""
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    count = len(ordered)
    if count <= 1:
        return {team: 50.0 for team in values}

    output: dict[str, float] = {}
    cursor = 0
    while cursor < count:
        end = cursor + 1
        while end < count and ordered[end][1] == ordered[cursor][1]:
            end += 1
        average_position = (cursor + end - 1) / 2
        percentile = 100.0 * average_position / (count - 1)
        for index in range(cursor, end):
            output[ordered[index][0]] = percentile
        cursor = end
    return output


def build_index(
    metrics: dict[str, Any],
    power: dict[str, Any],
    observed: dict[str, Any],
    schedule: dict[str, Any],
) -> dict[str, Any]:
    metrics_week = int(metrics["meta"]["through_week"])
    power_week = int(power["meta"]["through_week"])
    observed_week = int(observed["meta"]["through_week"])
    if len({metrics_week, power_week, observed_week}) != 1:
        raise ValueError(
            "Index inputs must share a completed-week cutoff: "
            f"metrics={metrics_week}, power={power_week}, observed={observed_week}"
        )

    teams = metrics["teams"]
    power_by_team = {row["team"]: row for row in power["teams"]}
    observed_by_team = observed["teams"]
    eligible = sorted(set(teams) & set(power_by_team) & set(observed_by_team))
    if len(eligible) < 100:
        raise ValueError(f"Expected a complete FBS field, found {len(eligible)} teams")

    result_values = {
        team: float(power_by_team[team]["result_elo_contribution"])
        for team in eligible
    }
    record_values = {
        team: float(teams[team]["record"]["wins"])
        - 1.35 * float(teams[team]["record"]["losses"])
        for team in eligible
    }
    predictive_values = {
        team: float(teams[team]["power_rating"])
        for team in eligible
    }
    observed_values = {
        team: float(observed_by_team[team]["ratings"]["net"]["value"])
        for team in eligible
    }

    opponents: dict[str, list[str]] = {team: [] for team in eligible}
    for game in schedule.get("games", []):
        if game.get("status") != "completed":
            continue
        if game.get("opponent_type") != "FBS":
            continue
        if int(game.get("week") or 0) > metrics_week:
            continue
        home = game.get("home_team")
        away = game.get("away_team")
        if home in opponents and away in teams:
            opponents[home].append(away)
        if away in opponents and home in teams:
            opponents[away].append(home)

    schedule_values = {
        team: (
            sum(float(teams[opponent]["power_rating"]) for opponent in team_opponents)
            / len(team_opponents)
            if team_opponents
            else 0.0
        )
        for team, team_opponents in opponents.items()
    }

    percentiles = {
        "results": average_tie_percentiles(result_values),
        "record": average_tie_percentiles(record_values),
        "predictive": average_tie_percentiles(predictive_values),
        "observed_performance": average_tie_percentiles(observed_values),
        "schedule_strength": average_tie_percentiles(schedule_values),
    }

    rows = []
    for team in eligible:
        score = sum(
            WEIGHTS[component] * percentiles[component][team]
            for component in WEIGHTS
        )
        record = teams[team]["record"]
        rows.append(
            {
                "team": team,
                "conference": teams[team].get("conference"),
                "wins": int(record["wins"]),
                "losses": int(record["losses"]),
                "score": round(score, 3),
                "components": {
                    "results": round(percentiles["results"][team], 1),
                    "record": round(percentiles["record"][team], 1),
                    "predictive": round(percentiles["predictive"][team], 1),
                    "observed_performance": round(
                        percentiles["observed_performance"][team], 1
                    ),
                    "schedule_strength": round(
                        percentiles["schedule_strength"][team], 1
                    ),
                },
                "raw": {
                    "result_elo_contribution": round(result_values[team], 3),
                    "record_score": round(record_values[team], 3),
                    "predictive_rating": round(predictive_values[team], 3),
                    "observed_net_rating": round(observed_values[team], 2),
                    "average_opponent_predictive_rating": round(
                        schedule_values[team], 3
                    ),
                    "completed_fbs_opponents": len(opponents[team]),
                },
            }
        )

    rows.sort(key=lambda row: (-row["score"], row["team"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank

    return {
        "meta": {
            "version": "thi_cfb_index_v1.0",
            "status": "RESUME_AWARE_BETA",
            "season": int(metrics["meta"]["year"]),
            "through_week": metrics_week,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scope": "FBS",
            "model_usage": "display_and_resume_context_only",
            "model_a_touched": False,
            "market_inputs": False,
            "roster_inputs": False,
            "description": (
                "A resume-aware weekly order combining completed-game results, "
                "record, production predictive strength, opponent-adjusted observed "
                "performance, and schedule strength."
            ),
            "weights": WEIGHTS,
            "record_score": "wins - 1.35 * losses",
            "schedule_strength": (
                "Average current production predictive rating of completed FBS opponents"
            ),
            "separation": (
                "The Index is not the experimental THI Power rating and does not use "
                "its roster contribution."
            ),
        },
        "top_25": rows[:25],
        "teams": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", type=Path, default=Path("data/cfb_metrics.json"))
    parser.add_argument("--power", type=Path, default=Path("data/thi_power_ratings.json"))
    parser.add_argument("--observed", type=Path, default=Path("data/thi_observed_ratings.json"))
    parser.add_argument("--schedule", type=Path, default=Path("data/schedule.json"))
    parser.add_argument("--output", type=Path, default=Path("data/cfb_index_top25.json"))
    args = parser.parse_args()
    payload = build_index(
        load(args.metrics), load(args.power), load(args.observed), load(args.schedule)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    print(
        f"Wrote {args.output} through Week {payload['meta']['through_week']} "
        f"with {len(payload['teams'])} teams"
    )


if __name__ == "__main__":
    main()
