#!/usr/bin/env python3
"""Build display-only team splits and luck diagnostics.

This artifact is intentionally isolated from Model A. It summarizes completed
games already present in the canonical postgame feed and never writes a model
input or projection.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "team_intelligence.json"


def finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def rounded(value, digits=2):
    return round(float(value), digits) if finite(value) else None


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def conference_map():
    model = load(DATA / "cfb_metrics.json")
    return {
        name: str(row.get("conference") or "")
        for name, row in (model.get("teams") or {}).items()
    }


def game_type(game, conferences):
    home = game.get("home_team")
    away = game.get("away_team")
    home_conf = conferences.get(home, "")
    away_conf = conferences.get(away, "")
    independents = {"FBS Independents", "Independent", "Independents"}
    if home_conf and home_conf == away_conf and home_conf not in independents:
        return "conference"
    return "nonconference"


def empty_bucket():
    return {
        "games": 0,
        "wins": 0,
        "losses": 0,
        "points_for": 0.0,
        "points_against": 0.0,
        "offensive_plays": 0,
        "defensive_plays": 0,
        "offensive_epa": 0.0,
        "defensive_epa": 0.0,
        "offensive_successes": 0.0,
        "defensive_successes": 0.0,
        "pass_plays": 0,
        "pass_epa": 0.0,
        "rush_plays": 0,
        "rush_epa": 0.0,
        "drives": 0,
        "drive_points": 0.0,
        "turnover_recredit": 0.0,
        "actual_margin": 0.0,
        "deserved_margin": 0.0,
        "offensive_scoreboard_luck": 0.0,
        "opponent_scoreboard_luck": 0.0,
        "points_left_on_field": 0.0,
        "conversion_overperformance": 0.0,
    }


def add_team_game(bucket, own, opp, own_points, opp_points, own_deserved, opp_deserved):
    bucket["games"] += 1
    bucket["wins"] += int(own_points > opp_points)
    bucket["losses"] += int(own_points < opp_points)
    bucket["points_for"] += own_points
    bucket["points_against"] += opp_points

    overall = own.get("overall") or {}
    opp_overall = opp.get("overall") or {}
    plays = int(overall.get("plays") or 0)
    opp_plays = int(opp_overall.get("plays") or 0)
    bucket["offensive_plays"] += plays
    bucket["defensive_plays"] += opp_plays
    bucket["offensive_epa"] += float(overall.get("epa_total") or 0)
    bucket["defensive_epa"] += float(opp_overall.get("epa_total") or 0)
    bucket["offensive_successes"] += plays * float(overall.get("success_rate") or 0) / 100
    bucket["defensive_successes"] += opp_plays * float(opp_overall.get("success_rate") or 0) / 100

    passing = own.get("passing") or {}
    rushing = own.get("rushing") or {}
    bucket["pass_plays"] += int(passing.get("plays") or 0)
    bucket["pass_epa"] += float(passing.get("epa_total") or 0)
    bucket["rush_plays"] += int(rushing.get("plays") or 0)
    bucket["rush_epa"] += float(rushing.get("epa_total") or 0)

    drives = own.get("drives") or {}
    drive_count = int(drives.get("drives") or 0)
    bucket["drives"] += drive_count
    bucket["drive_points"] += drive_count * float(drives.get("points_per_drive") or 0)

    turnover_impact = float((own.get("turnovers") or {}).get("turnover_epa_impact") or 0)
    bucket["turnover_recredit"] += max(0.0, -turnover_impact)
    bucket["actual_margin"] += own_points - opp_points
    bucket["deserved_margin"] += own_deserved - opp_deserved
    bucket["offensive_scoreboard_luck"] += own_points - own_deserved
    bucket["opponent_scoreboard_luck"] += opp_points - opp_deserved
    bucket["points_left_on_field"] += max(0.0, own_deserved - own_points)
    bucket["conversion_overperformance"] += max(0.0, own_points - own_deserved)


def divide(total, count, digits=3):
    return rounded(total / count, digits) if count else None


def finalize(bucket):
    games = bucket["games"]
    return {
        "games": games,
        "record": f'{bucket["wins"]}-{bucket["losses"]}',
        "offensive_plays": bucket["offensive_plays"],
        "defensive_plays": bucket["defensive_plays"],
        "net_epa_per_play": rounded(
            (bucket["offensive_epa"] / bucket["offensive_plays"] if bucket["offensive_plays"] else 0)
            - (bucket["defensive_epa"] / bucket["defensive_plays"] if bucket["defensive_plays"] else 0),
            3,
        ) if bucket["offensive_plays"] and bucket["defensive_plays"] else None,
        "offense_epa_per_play": divide(bucket["offensive_epa"], bucket["offensive_plays"]),
        "defense_epa_per_play": divide(bucket["defensive_epa"], bucket["defensive_plays"]),
        "offense_success_rate": divide(bucket["offensive_successes"] * 100, bucket["offensive_plays"], 1),
        "defense_success_rate": divide(bucket["defensive_successes"] * 100, bucket["defensive_plays"], 1),
        "pass_epa_per_play": divide(bucket["pass_epa"], bucket["pass_plays"]),
        "rush_epa_per_play": divide(bucket["rush_epa"], bucket["rush_plays"]),
        "points_per_drive": divide(bucket["drive_points"], bucket["drives"], 2),
        "scoring_margin_per_game": divide(bucket["actual_margin"], games, 1),
        "luck": {
            "net_scoreboard_luck": rounded(bucket["actual_margin"] - bucket["deserved_margin"], 1),
            "luck_per_game": divide(bucket["actual_margin"] - bucket["deserved_margin"], games, 1),
            "offensive_scoreboard_luck": rounded(bucket["offensive_scoreboard_luck"], 1),
            "opponent_scoreboard_luck": rounded(bucket["opponent_scoreboard_luck"], 1),
            "points_left_on_field": rounded(bucket["points_left_on_field"], 1),
            "conversion_overperformance": rounded(bucket["conversion_overperformance"], 1),
            "turnover_points_recredited": rounded(bucket["turnover_recredit"], 1),
        },
    }


def ranks(teams, split="all"):
    rows = []
    for team, payload in teams.items():
        value = payload["splits"][split]["luck"]["net_scoreboard_luck"]
        if finite(value):
            rows.append((team, float(value)))
    flattered = {team: i + 1 for i, (team, _) in enumerate(sorted(rows, key=lambda row: (-row[1], row[0])))}
    unlucky = {team: i + 1 for i, (team, _) in enumerate(sorted(rows, key=lambda row: (row[1], row[0])))}
    for team, payload in teams.items():
        payload["splits"][split]["luck"]["flattered_rank"] = flattered.get(team)
        payload["splits"][split]["luck"]["unluckiest_rank"] = unlucky.get(team)


def main():
    postgame = load(DATA / "postgame_analytics.json")
    conferences = conference_map()
    buckets = defaultdict(lambda: {name: empty_bucket() for name in ("all", "conference", "nonconference")})

    for game in (postgame.get("games") or {}).values():
        if game.get("analysis_status") != "available" or game.get("analysis_level") != "full":
            continue
        home = game.get("home_team")
        away = game.get("away_team")
        if not home or not away:
            continue
        kind = game_type(game, conferences)
        headline = game.get("headline") or {}
        adjusted = headline.get("adjusted_final_score") or {}
        home_points = float(game.get("home_points") or 0)
        away_points = float(game.get("away_points") or 0)
        home_deserved = float(adjusted.get("home") if finite(adjusted.get("home")) else home_points)
        away_deserved = float(adjusted.get("away") if finite(adjusted.get("away")) else away_points)
        for split in ("all", kind):
            add_team_game(buckets[home][split], game.get("home_metrics") or {}, game.get("away_metrics") or {}, home_points, away_points, home_deserved, away_deserved)
            add_team_game(buckets[away][split], game.get("away_metrics") or {}, game.get("home_metrics") or {}, away_points, home_points, away_deserved, home_deserved)

    teams = {
        team: {
            "team": team,
            "conference": conferences.get(team),
            "splits": {name: finalize(bucket) for name, bucket in team_buckets.items()},
        }
        for team, team_buckets in sorted(buckets.items())
    }
    for split in ("all", "conference", "nonconference"):
        ranks(teams, split)

    output = {
        "meta": {
            "season": postgame.get("meta", {}).get("season", 2026),
            "through_week": max((int(g.get("week") or 0) for g in (postgame.get("games") or {}).values()), default=0),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "THI canonical postgame analytics",
            "model_usage": "display_only_not_used_by_model_a",
            "minimum_split_guidance": "Conference and nonconference ranks are developing until a team has 2 games and 120 offensive and defensive plays.",
            "luck_definition": "Actual scoring margin minus THI beta deserved scoring margin, summed across completed full-analysis games.",
            "turnover_recredit_definition": "The magnitude of negative offensive EPA on recorded turnover plays; diagnostic only.",
            "limitations": "Luck is descriptive and not yet opponent-adjusted. Deserved score remains beta and does not affect Model A.",
        },
        "teams": teams,
    }
    OUTPUT.write_text(json.dumps(output, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT} for {len(teams)} teams")


if __name__ == "__main__":
    main()
