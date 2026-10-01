#!/usr/bin/env python3
"""Build display-only THI season and conference outlooks.

This script derives presentation data from existing production projections. It
does not import or mutate Model A, and it never changes a game probability.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def probability_distribution(probabilities):
    distribution = [1.0]
    for probability in probabilities:
        p = max(0.0, min(1.0, float(probability)))
        updated = [0.0] * (len(distribution) + 1)
        for wins, value in enumerate(distribution):
            updated[wins] += value * (1.0 - p)
            updated[wins + 1] += value * p
        distribution = updated
    return distribution


def central_range(distribution, mass):
    if not distribution:
        return None
    lower_target = (1.0 - mass) / 2.0
    upper_target = 1.0 - lower_target
    cumulative = 0.0
    lower = 0
    upper = len(distribution) - 1
    for wins, probability in enumerate(distribution):
        cumulative += probability
        if cumulative >= lower_target:
            lower = wins
            break
    cumulative = 0.0
    for wins, probability in enumerate(distribution):
        cumulative += probability
        if cumulative >= upper_target:
            upper = wins
            break
    return [lower, upper]


def distribution_from_percentages(values):
    if not isinstance(values, dict):
        return []
    largest = max((int(key) for key in values), default=-1)
    if largest < 0:
        return []
    return [float(values.get(str(wins), 0.0)) / 100.0 for wins in range(largest + 1)]


def result_from_probability(probability):
    if probability >= 0.999999:
        return "win"
    if probability <= 0.000001:
        return "loss"
    return None


def team_outlook(name, season, conference, conferences):
    conference_probabilities = []
    conference_schedule = []
    actual_wins = 0
    actual_losses = 0

    for game in season.get("schedule", []):
        opponent = game.get("opponent")
        opponent_conference = conferences.get(opponent)
        is_conference = bool(
            conference
            and conference not in {"FBS Independents", "Independent"}
            and opponent_conference == conference
            and game.get("opponent_type") == "FBS"
        )
        if not is_conference:
            continue
        probability = float(game.get("win_probability", 0.0)) / 100.0
        conference_probabilities.append(probability)
        result = result_from_probability(probability)
        actual_wins += int(result == "win")
        actual_losses += int(result == "loss")
        conference_schedule.append({
            "game_id": game.get("game_id"),
            "week": game.get("week"),
            "opponent": opponent,
            "location": game.get("location"),
            "status": game.get("status"),
            "win_probability": game.get("win_probability"),
            "team_line": game.get("team_line"),
            "probability_source": game.get("probability_source"),
        })

    conference_distribution = probability_distribution(conference_probabilities)
    expected_conference_wins = sum(conference_probabilities)
    conference_games = len(conference_probabilities)
    most_likely_conference_wins = (
        max(range(len(conference_distribution)), key=conference_distribution.__getitem__)
        if conference_distribution else 0
    )

    overall_distribution = distribution_from_percentages(
        season.get("exact_win_distribution", {})
    )
    overall_actual_wins = int(season.get("actual_wins", 0))

    return {
        "team": name,
        "conference": conference,
        "overall": {
            "games": int(season.get("games", 0)),
            "actual_wins": overall_actual_wins,
            "actual_losses": int(season.get("actual_losses", 0)),
            "expected_wins": float(season.get("expected_wins", 0.0)),
            "expected_remaining_wins": round(
                float(season.get("expected_wins", 0.0)) - overall_actual_wins, 2
            ),
            "most_likely_record": season.get("most_likely_record"),
            "range_50": central_range(overall_distribution, 0.50),
            "range_80": central_range(overall_distribution, 0.80),
            "exact_win_distribution": season.get("exact_win_distribution", {}),
            "bowl_eligible_probability": season.get("bowl_eligible_probability"),
            "at_least": season.get("at_least", {}),
        },
        "conference_outlook": {
            "applicable": conference_games > 0,
            "games": conference_games,
            "actual_wins": actual_wins,
            "actual_losses": actual_losses,
            "expected_wins": round(expected_conference_wins, 2),
            "expected_remaining_wins": round(expected_conference_wins - actual_wins, 2),
            "most_likely_record": (
                f"{most_likely_conference_wins}-{conference_games - most_likely_conference_wins}"
                if conference_games else None
            ),
            "range_50": central_range(conference_distribution, 0.50),
            "range_80": central_range(conference_distribution, 0.80),
            "exact_win_distribution": {
                str(wins): round(probability * 100.0, 1)
                for wins, probability in enumerate(conference_distribution)
            },
            "schedule": conference_schedule,
        },
        "schedule": season.get("schedule", []),
    }


def build_report(projections, metrics, previous=None):
    season_projections = projections.get("season_projections", {})
    metrics_teams = metrics.get("teams", {})
    conferences = {
        name: row.get("conference") or "FBS Independents"
        for name, row in metrics_teams.items()
    }
    teams = {
        name: team_outlook(
            name,
            season,
            conferences.get(name, "FBS Independents"),
            conferences,
        )
        for name, season in season_projections.items()
    }

    week = int(
        projections.get("meta", {}).get("metrics_through_week")
        or metrics.get("meta", {}).get("through_week")
        or 0
    )
    generated = datetime.now(timezone.utc).isoformat()
    history = []
    if isinstance(previous, dict) and previous.get("meta", {}).get("season") == 2026:
        history = [
            item for item in previous.get("history", [])
            if int(item.get("through_week", -1)) != week
        ]
    history.append({
        "through_week": week,
        "generated_at": generated,
        "teams": {
            name: {
                "overall_expected_wins": row["overall"]["expected_wins"],
                "conference_expected_wins": row["conference_outlook"]["expected_wins"],
            }
            for name, row in teams.items()
        },
    })
    history.sort(key=lambda item: int(item.get("through_week", 0)))

    return {
        "meta": {
            "version": "thi_season_outlook_v1",
            "status": "DISPLAY_ONLY",
            "season": 2026,
            "through_week": week,
            "generated_at": generated,
            "source": "existing THI production game probabilities",
            "model_a_touched": False,
            "method": "Exact Poisson-binomial distributions over fixed THI game win probabilities",
        },
        "teams": teams,
        "history": history,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--projections", type=Path, default=Path("data/projections.json"))
    parser.add_argument("--metrics", type=Path, default=Path("data/cfb_metrics.json"))
    parser.add_argument("--output", type=Path, default=Path("data/thi_season_outlook.json"))
    args = parser.parse_args()
    projections = json.loads(args.projections.read_text())
    metrics = json.loads(args.metrics.read_text())
    previous = json.loads(args.output.read_text()) if args.output.exists() else None
    report = build_report(projections, metrics, previous)
    if len(report["teams"]) < 100:
        raise ValueError("Season outlook coverage is incomplete")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"meta": report["meta"], "teams": len(report["teams"])}, indent=2))


if __name__ == "__main__":
    main()
