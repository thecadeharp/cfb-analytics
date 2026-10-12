#!/usr/bin/env python3
"""Build independent THI CFB Power, current-form and Resume rankings.

The index deliberately excludes polls and betting markets. Its predictive lens
uses roster/talent and returning-production priors that decay during the season.
It is a public ranking layer; it does not feed Model A projections.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


MARGIN_CAP = 28.0
HOME_EDGE = 2.5
SHRINKAGE_GAMES = 2.5


def percentile_map(values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    count = len(ordered)
    if count <= 1:
        return {team: 50.0 for team, _ in ordered}
    return {team: round(100.0 * index / (count - 1), 3) for index, (team, _) in enumerate(ordered)}


def completed_games(schedule: dict, teams: set[str], through_week: int) -> list[dict]:
    return [
        game for game in schedule.get("games", [])
        if game.get("status") == "completed"
        and int(game.get("week") or 0) <= through_week
        and game.get("home_team") in teams
        and game.get("away_team") in teams
        and game.get("home_points") is not None
        and game.get("away_points") is not None
    ]


def adjusted_home_margin(game: dict) -> float:
    margin = max(-MARGIN_CAP, min(MARGIN_CAP, float(game["home_points"]) - float(game["away_points"])))
    return margin if game.get("neutral_site") else margin - HOME_EDGE


def resume_result_values(
    opponent_strength_for_winner: float,
    opponent_strength_for_loser: float,
    *,
    winner_is_away: bool,
    neutral_site: bool,
    margin: float,
) -> tuple[float, float]:
    location_bonus = 0.18 if winner_is_away else (0.08 if neutral_site else 0.0)
    capped_margin = min(abs(margin), 21.0) / 21.0
    win_credit = 0.35 + 1.15 * opponent_strength_for_winner + location_bonus + 0.12 * capped_margin
    loss_penalty = 0.35 + 1.15 * (1.0 - opponent_strength_for_loser) + 0.12 * capped_margin
    return win_credit, loss_penalty


def solve_srs(team_names: list[str], games: list[dict]) -> tuple[dict[str, float], dict[str, int]]:
    by_team = {team: [] for team in team_names}
    for game in games:
        home, away = game["home_team"], game["away_team"]
        margin = adjusted_home_margin(game)
        by_team[home].append((away, margin))
        by_team[away].append((home, -margin))

    ratings = {team: 0.0 for team in team_names}
    for _ in range(200):
        updated = {}
        for team in team_names:
            rows = by_team[team]
            if not rows:
                updated[team] = 0.0
                continue
            raw = sum(margin + ratings[opponent] for opponent, margin in rows) / len(rows)
            updated[team] = raw * len(rows) / (len(rows) + SHRINKAGE_GAMES)
        center = sum(updated.values()) / max(1, len(updated))
        ratings = {team: value - center for team, value in updated.items()}
    return ratings, {team: len(rows) for team, rows in by_team.items()}


def schedule_strength_map(
    team_names: list[str], games: list[dict], power_percentiles: dict[str, float]
) -> dict[str, float]:
    opponents = {team: [] for team in team_names}
    for game in games:
        home, away = game["home_team"], game["away_team"]
        opponents[home].append(away)
        opponents[away].append(home)
    return {
        team: (
            sum(power_percentiles[opponent] for opponent in opponents[team]) / len(opponents[team])
            if opponents[team] else 0.0
        )
        for team in team_names
    }


def build(metrics: dict, observed: dict, schedule: dict, predictive: dict) -> dict:
    metric_teams = metrics.get("teams", {})
    observed_teams = observed.get("teams", {})
    predictive_teams = {
        row["team"]: row for row in predictive.get("teams", []) if row.get("team")
    }
    team_names = sorted(set(metric_teams) & set(observed_teams) & set(predictive_teams))
    if len(team_names) < 100:
        raise ValueError("THI Index requires a complete FBS metrics and observed-ratings universe")

    metrics_week = int(metrics.get("meta", {}).get("through_week") or 0)
    observed_week = int(observed.get("meta", {}).get("through_week") or 0)
    predictive_week = int(predictive.get("meta", {}).get("through_week") or 0)
    if len({metrics_week, observed_week, predictive_week}) != 1:
        raise ValueError(
            "Input weeks do not match: "
            f"metrics={metrics_week}, observed={observed_week}, predictive={predictive_week}"
        )
    through_week = metrics_week
    games = completed_games(schedule, set(team_names), through_week)
    srs, fbs_games = solve_srs(team_names, games)

    observed_net = {
        team: float(observed_teams[team].get("ratings", {}).get("net", {}).get("value") or 0.0)
        for team in team_names
    }
    predictive_rating = {
        team: float(predictive_teams[team].get("rating") or 0.0)
        for team in team_names
    }
    srs_pct = percentile_map(srs)
    observed_pct = percentile_map(observed_net)
    power_pct = percentile_map(predictive_rating)

    schedule_strength = schedule_strength_map(team_names, games, power_pct)
    schedule_strength_pct = percentile_map(schedule_strength)

    resume = {team: 0.0 for team in team_names}
    fbs_wins = {team: 0 for team in team_names}
    fbs_losses = {team: 0 for team in team_names}
    for game in games:
        home, away = game["home_team"], game["away_team"]
        home_score, away_score = float(game["home_points"]), float(game["away_points"])
        if home_score == away_score:
            continue
        winner, loser = (home, away) if home_score > away_score else (away, home)
        opponent_strength_for_winner = power_pct[loser] / 100.0
        opponent_strength_for_loser = power_pct[winner] / 100.0
        win_credit, loss_penalty = resume_result_values(
            opponent_strength_for_winner,
            opponent_strength_for_loser,
            winner_is_away=winner == away and not game.get("neutral_site"),
            neutral_site=bool(game.get("neutral_site")),
            margin=home_score - away_score,
        )
        resume[winner] += win_credit
        resume[loser] -= loss_penalty
        fbs_wins[winner] += 1
        fbs_losses[loser] += 1

    fcs_wins, fcs_losses = {}, {}
    for team in team_names:
        record = metric_teams[team].get("record", {})
        fcs_wins[team] = max(0, int(record.get("wins") or 0) - fbs_wins[team])
        fcs_losses[team] = max(0, int(record.get("losses") or 0) - fbs_losses[team])
        resume[team] += 0.18 * fcs_wins[team] - 1.50 * fcs_losses[team]

    resume_pct = percentile_map(resume)
    ordered_power = sorted(team_names, key=lambda team: (-predictive_rating[team], team))
    ordered_resume = sorted(team_names, key=lambda team: (-resume[team], team))
    power_ranks = {team: rank for rank, team in enumerate(ordered_power, 1)}
    resume_ranks = {team: rank for rank, team in enumerate(ordered_resume, 1)}
    component_ranks = {}
    for key, values in {
        "resume": resume,
        "predictive_power": predictive_rating,
        "schedule_strength": schedule_strength,
        "game_control": srs,
        "observed_efficiency": observed_net,
    }.items():
        component_ranks[key] = {
            team: rank for rank, team in enumerate(sorted(team_names, key=lambda name: (-values[name], name)), 1)
        }

    rows = []
    for team in ordered_power:
        record = metric_teams[team].get("record", {})
        rows.append({
            "rank": power_ranks[team],
            "power_rank": power_ranks[team],
            "resume_rank": resume_ranks[team],
            "team": team,
            "conference": metric_teams[team].get("conference"),
            "record": f"{int(record.get('wins') or 0)}-{int(record.get('losses') or 0)}",
            "power_score": round(predictive_rating[team], 3),
            "power_percentile": power_pct[team],
            "resume_score": round(resume_pct[team], 3),
            "components": {
                "resume": {"rank": component_ranks["resume"][team], "percentile": resume_pct[team], "value": round(resume[team], 3)},
                "predictive_power": {"rank": component_ranks["predictive_power"][team], "percentile": power_pct[team], "value": round(predictive_rating[team], 3)},
                "schedule_strength": {"rank": component_ranks["schedule_strength"][team], "percentile": schedule_strength_pct[team], "value": round(schedule_strength[team], 3)},
                "game_control": {"rank": component_ranks["game_control"][team], "percentile": srs_pct[team], "value": round(srs[team], 3)},
                "observed_efficiency": {"rank": component_ranks["observed_efficiency"][team], "percentile": observed_pct[team], "value": round(observed_net[team], 3)},
            },
            "sample": {"fbs_games": fbs_games[team], "fbs_wins": fbs_wins[team], "fbs_losses": fbs_losses[team], "fcs_wins": fcs_wins[team], "fcs_losses": fcs_losses[team]},
        })

    return {
        "meta": {
            "version": "thi_cfb_index_v4.0",
            "status": "INDEPENDENT_BETA",
            "season": int(metrics.get("meta", {}).get("year") or schedule.get("meta", {}).get("year")),
            "through_week": through_week,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "poll_inputs": False,
            "market_inputs": False,
            "roster_inputs": True,
            "preseason_inputs": True,
            "poll_based_preseason_inputs": False,
            "model_a_touched": False,
            "model_usage": "power_badges_sorting_and_ratings_display_only",
            "margin_cap_points": MARGIN_CAP,
            "neutral_site_home_adjustment": 0.0,
            "non_neutral_home_adjustment": HOME_EDGE,
            "primary_surface": "power_rank",
            "power_source_version": predictive.get("meta", {}).get("version"),
            "power_source_status": predictive.get("meta", {}).get("status"),
            "power_validation_status": "Independent beta; historical input-timing limitations prevent validated or established labeling.",
            "power_method": "Fitted neutral-field margin rating using current-season result Elo, talent and returning-production priors with weekly decay, plus opponent-adjusted on-field performance.",
            "schedule_strength_usage": "Displayed for context only; the predictive engine already opponent-adjusts performance, so SOS is not added a second time.",
            "resume_method": "Opponent quality from THI Power, result, capped margin and location. FCS wins receive limited credit; FCS losses receive a major penalty.",
            "methodology": "THI Power is the poll-free fitted neutral-field margin rating. Current Form shows opponent-adjusted in-season efficiency, Game Control shows capped location-adjusted SRS, and THI Resume separately ranks accomplishment. Internal SOS is displayed but not added again because the Power, Current Form and Game Control engines already adjust for opponent quality.",
        },
        "teams": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", type=Path, default=Path("data/cfb_metrics.json"))
    parser.add_argument("--observed", type=Path, default=Path("data/thi_observed_ratings.json"))
    parser.add_argument("--schedule", type=Path, default=Path("data/schedule.json"))
    parser.add_argument("--predictive", type=Path, default=Path("data/thi_power_ratings.json"))
    parser.add_argument("--output", type=Path, default=Path("data/cfb_thi_index.json"))
    args = parser.parse_args()
    output = build(
        json.loads(args.metrics.read_text()),
        json.loads(args.observed.read_text()),
        json.loads(args.schedule.read_text()),
        json.loads(args.predictive.read_text()),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, separators=(",", ":")) + "\n")
    print(f"Wrote {args.output}: {len(output['teams'])} teams through Week {output['meta']['through_week']}")


if __name__ == "__main__":
    main()
