#!/usr/bin/env python3
"""Build display-only CFB player performance forecasts for each team's next game.

This is intentionally isolated from Model A. It converts verified season workload
into matchup-aware statistical expectations and does not ingest or retain player
market data, prices, lines, picks, or wager records.
"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
VERSION = "thi-cfb-player-projections-v0.1-research"
POSITIONS = {"QB", "RB", "WR", "TE"}
STAT_FIELDS = {
    "QB": ("pass_attempts", "completions", "pass_yards", "pass_tds", "interceptions", "rush_attempts", "rush_yards"),
    "RB": ("rush_attempts", "rush_yards", "targets", "receptions", "receiving_yards"),
    "WR": ("targets", "receptions", "receiving_yards"),
    "TE": ("targets", "receptions", "receiving_yards"),
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def number(value, default=0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def mean(values: list[float], default=0.0) -> float:
    usable = [number(value) for value in values if number(value) > 0]
    return sum(usable) / len(usable) if usable else default


def round_stat(field: str, value: float) -> float:
    digits = 2 if field in {"pass_tds", "interceptions"} else 1
    return round(max(0.0, value), digits)


def team_game_count(players: dict, team: str) -> int:
    games = [int(number(row.get("games"))) for row in players.values() if row.get("team") == team]
    return max(games, default=1)


def team_metrics(metrics: dict, team: str) -> tuple[dict, dict]:
    row = (metrics.get("teams") or {}).get(team) or {}
    profile = row.get("non_garbage") or row.get("all_plays") or {}
    return profile.get("offense") or {}, profile.get("defense") or {}


def upcoming_games(board: dict) -> dict[str, dict]:
    result = {}
    games = sorted(
        [game for game in board.get("games") or [] if game.get("status") not in {"completed", "final"}],
        key=lambda game: (str(game.get("start_date") or ""), int(number(game.get("game_id")))),
    )
    for game in games:
        for side, other in (("home", "away"), ("away", "home")):
            team = (game.get(side) or {}).get("team")
            opponent = (game.get(other) or {}).get("team")
            if not team or team in result:
                continue
            home_spread = number((game.get("projection") or {}).get("home_spread"))
            total = number((game.get("projection") or {}).get("total"))
            team_spread = home_spread if side == "home" else -home_spread
            implied_points = total / 2 - team_spread / 2 if total else None
            result[team] = {
                "game_id": game.get("game_id"),
                "week": game.get("week"),
                "start_date": game.get("start_date"),
                "venue": game.get("venue"),
                "network": game.get("network"),
                "home_away": side,
                "opponent": opponent,
                "team_spread": round(team_spread, 1),
                "game_total": round(total, 1) if total else None,
                "implied_team_points": round(implied_points, 1) if implied_points is not None else None,
            }
    return result


def availability_index(notes: dict) -> dict[tuple[str, str], dict]:
    index = {}
    for team, entries in (notes.get("teams") or {}).items():
        for note in entries or []:
            player = str(note.get("player") or note.get("player_name") or "").strip().casefold()
            if player:
                index[(team, player)] = note
    return index


def established_role(player: dict) -> bool:
    """Keep the public board to materially observed offensive roles."""
    position = player.get("position_group")
    workload = player.get("workload") or {}
    if player.get("rating") is None:
        return False
    if position == "QB":
        return number(workload.get("pass_attempt_share")) >= 25
    if position == "RB":
        return max(number(workload.get("rush_attempt_share")), number(workload.get("target_share"))) >= 8
    if position in {"WR", "TE"}:
        return number(workload.get("target_share")) >= 5
    return False


def build(players_payload: dict, board: dict, metrics: dict, notes: dict) -> dict:
    players = players_payload.get("players") or {}
    next_games = upcoming_games(board)
    availability = availability_index(notes)
    groups = {
        position: [row for row in players.values() if row.get("position_group") == position and number(row.get("games")) >= 3]
        for position in POSITIONS
    }
    baselines = {
        position: {
            field: mean([number((row.get("traditional") or {}).get(field)) / max(number(row.get("games")), 1) for row in rows])
            for field in STAT_FIELDS[position]
        }
        for position, rows in groups.items()
    }
    all_team_games = {team: team_game_count(players, team) for team in next_games}
    plays_per_game = {}
    for team, games in all_team_games.items():
        offense, _ = team_metrics(metrics, team)
        plays_per_game[team] = number(offense.get("n_plays")) / max(games, 1)
    national_plays = mean(list(plays_per_game.values()), 68.0)
    national_pass_ypp = mean([team_metrics(metrics, team)[0].get("yards_per_pass_play") for team in next_games], 7.0)
    national_rush_ypp = mean([team_metrics(metrics, team)[0].get("yards_per_rush") for team in next_games], 4.5)

    output = []
    for player in players.values():
        position = player.get("position_group")
        team = player.get("team")
        game = next_games.get(team)
        if position not in POSITIONS or not game or number(player.get("games")) < 3 or player.get("status") not in {None, "active"} or not established_role(player):
            continue
        traditional = player.get("traditional") or {}
        games = max(number(player.get("games")), 1)
        prior_games = 2.0
        projected = {}
        for field in STAT_FIELDS[position]:
            observed = number(traditional.get(field)) / games
            baseline = baselines[position].get(field, 0.0)
            projected[field] = (observed * games + baseline * prior_games) / (games + prior_games)

        opponent = game["opponent"]
        offense, _ = team_metrics(metrics, team)
        _, opponent_defense = team_metrics(metrics, opponent)
        opponent_games = max(all_team_games.get(opponent, team_game_count(players, opponent)), 1)
        opponent_def_plays = number(opponent_defense.get("n_plays")) / opponent_games
        pace_factor = clamp(((plays_per_game.get(team, national_plays) + opponent_def_plays) / 2) / max(national_plays, 1), 0.88, 1.12)
        spread = number(game.get("team_spread"))
        pass_script = clamp(1 + spread * 0.008, 0.90, 1.10)
        rush_script = clamp(1 - spread * 0.006, 0.91, 1.09)
        points = game.get("implied_team_points")
        scoring_factor = clamp(number(points, 27.0) / 27.0, 0.85, 1.15)
        pass_matchup = clamp(
            (number(offense.get("yards_per_pass_play"), national_pass_ypp) + number(opponent_defense.get("yards_per_pass_play"), national_pass_ypp))
            / (2 * max(national_pass_ypp, 0.1)), 0.84, 1.16,
        )
        rush_matchup = clamp(
            (number(offense.get("yards_per_rush"), national_rush_ypp) + number(opponent_defense.get("yards_per_rush"), national_rush_ypp))
            / (2 * max(national_rush_ypp, 0.1)), 0.84, 1.16,
        )

        for field in list(projected):
            factor = pace_factor
            if field.startswith("pass_") or field in {"completions", "interceptions", "targets", "receptions", "receiving_yards"}:
                factor *= pass_script
            if field.startswith("rush_"):
                factor *= rush_script
            if field in {"pass_yards", "receiving_yards"}:
                factor *= pass_matchup
            if field == "rush_yards":
                factor *= rush_matchup
            if field in {"pass_tds"}:
                factor *= scoring_factor
            projected[field] = round_stat(field, projected[field] * factor)

        note = availability.get((team, str(player.get("name") or "").strip().casefold()))
        reliability = number(player.get("reliability"))
        confidence = "established" if games >= 6 and reliability >= 75 else "developing"
        if note:
            confidence = "availability_watch"
        output.append({
            "athlete_id": str(player.get("athlete_id") or ""),
            "name": player.get("name"),
            "team": team,
            "conference": player.get("conference"),
            "position": player.get("position"),
            "position_group": position,
            "thi_production_rating": player.get("rating"),
            "national_position_rank": player.get("national_position_rank"),
            "season_games": int(games),
            "sample_reliability": reliability,
            "confidence": confidence,
            "availability": ({
                "status": note.get("status"),
                "note": note.get("text"),
                "source_url": note.get("source_url"),
                "verified_at_utc": note.get("verified_at_utc"),
            } if note else None),
            "matchup": game,
            "projection": projected,
            "adjustments": {
                "pace_factor": round(pace_factor, 3),
                "pass_script_factor": round(pass_script, 3),
                "rush_script_factor": round(rush_script, 3),
                "pass_matchup_factor": round(pass_matchup, 3),
                "rush_matchup_factor": round(rush_matchup, 3),
                "scoring_factor": round(scoring_factor, 3),
            },
        })

    output.sort(key=lambda row: (str(row["matchup"].get("start_date") or ""), row["team"], row["position_group"], -(number(row.get("thi_production_rating")))))
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "season": players_payload.get("meta", {}).get("season"),
            "through_week": players_payload.get("meta", {}).get("through_week"),
            "projection_count": len(output),
            "game_count": len({row["matchup"]["game_id"] for row in output}),
            "status": "research_only",
            "model_usage": "display_only_not_used_by_model_a",
            "intended_use": "player_performance_forecasting_for_matchup_analysis_fantasy_research_broadcast_preparation_and_player_evaluation",
            "market_data_usage": "none_ingested_retained_or_displayed",
            "method": "Two-game empirical-Bayes shrinkage of observed per-game production, adjusted for projected pace, game script, opponent efficiency and implied team scoring.",
            "limitations": [
                "Current build uses season aggregates rather than a complete frozen player-game variance ledger.",
                "Point estimates remain research forecasts until prospective error calibration is complete.",
                "Availability context is shown only when a current source-linked report exists.",
                "The board contains no player market lines, odds, prices, picks, or wager tracking.",
            ],
        },
        "projections": output,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players", type=Path, default=DATA / "player_intelligence.json")
    parser.add_argument("--games", type=Path, default=DATA / "projections.json")
    parser.add_argument("--metrics", type=Path, default=DATA / "advanced_metrics.json")
    parser.add_argument("--availability", type=Path, default=DATA / "roster_notes.json")
    parser.add_argument("--output", type=Path, default=DATA / "player_projections.json")
    args = parser.parse_args()
    payload = build(load(args.players), load(args.games), load(args.metrics), load(args.availability))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.output.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(args.output)
    print(f"Built {payload['meta']['projection_count']} research player projections across {payload['meta']['game_count']} games")
    print("Model A was not changed; no player market data was read or written")


if __name__ == "__main__":
    main()
