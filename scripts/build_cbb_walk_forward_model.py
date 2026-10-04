#!/usr/bin/env python3
"""Build THI CBB walk-forward projections without same-season future leakage."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import statistics
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = ROOT / "data" / "cbb" / "history"
OUTPUT_DIR = ROOT / "data" / "cbb" / "model"
MODEL_VERSION = "thi-cbb-walk-forward-v0.3-research"
TRAIN_SEASONS = set(range(2019, 2025))
VALIDATION_SEASONS = {2025}
TEST_SEASONS = {2026}
MARGIN_FEATURES = (
    "raw_margin", "raw_margin_curve", "home_court", "experience_diff", "experience_sum",
    "early_strength_margin", "early_home", "nonconference_home", "efg_edge", "turnover_edge",
    "rebound_edge", "free_throw_edge",
)
TOTAL_FEATURES = (
    "raw_total", "projected_pace", "experience_sum", "combined_efg", "combined_turnover",
)


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def median(values: list[float], fallback: float) -> float:
    return statistics.median(values) if values else fallback


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class TeamState:
    offense: float
    defense: float
    tempo: float
    weight: float
    efg_for: float = 50.0
    efg_allowed: float = 50.0
    turnover_for: float = 20.0
    turnover_forced: float = 20.0
    rebound_for: float = 30.0
    rebound_allowed: float = 30.0
    free_throw_for: float = 30.0
    free_throw_allowed: float = 30.0
    games: int = 0
    last_game: datetime | None = None

    def update(self, field: str, observation: float | None) -> None:
        if observation is None:
            return
        alpha = 1.0 / (self.weight + 1.0)
        setattr(self, field, getattr(self, field) + alpha * (observation - getattr(self, field)))

    def finish_game(self, when: datetime) -> None:
        self.games += 1
        self.weight = min(10.0, self.weight + 1.0)
        self.last_game = when


def load_seasons(history_dir: Path) -> dict[int, dict[str, Any]]:
    payloads = {}
    for path in sorted(history_dir.glob("season_*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("meta", {}).get("builder_version") != "cbb-history-v1.1":
            raise RuntimeError(f"{path} is not a clean cbb-history-v1.1 archive")
        payloads[int(payload["meta"]["season"])] = payload
    if not payloads:
        raise RuntimeError(f"no historical seasons found in {history_dir}")
    return payloads


def league_context(previous_teams: list[dict[str, Any]]) -> tuple[float, float]:
    offense = [value for row in previous_teams if (value := finite(row.get("adjusted_offense"))) is not None]
    defense = [value for row in previous_teams if (value := finite(row.get("adjusted_defense"))) is not None]
    tempo = [value for row in previous_teams if (value := finite(row.get("pace"))) is not None]
    efficiencies = offense + defense
    return median(efficiencies, 100.0), median(tempo, 68.0)


def initial_states(
    current_teams: list[dict[str, Any]],
    previous_teams: list[dict[str, Any]],
    league_efficiency: float,
    league_tempo: float,
) -> dict[str, TeamState]:
    prior = {str(row.get("team_id")): row for row in previous_teams}
    states = {}
    for current in current_teams:
        team_id = str(current.get("team_id"))
        previous = prior.get(team_id) or {}
        continuity = current.get("continuity_from_prior") or {}
        returning = finite(continuity.get("returning_minutes_pct"))
        carry = 0.25 + 0.50 * clip((returning or 0.0) / 100.0, 0.0, 1.0)
        prior_offense = finite(previous.get("adjusted_offense"))
        prior_defense = finite(previous.get("adjusted_defense"))
        prior_tempo = finite(previous.get("pace"))
        weight = 3.0 + 4.0 * clip((returning or 0.0) / 100.0, 0.0, 1.0)
        states[team_id] = TeamState(
            offense=league_efficiency + carry * ((prior_offense or league_efficiency) - league_efficiency),
            defense=league_efficiency + carry * ((prior_defense or league_efficiency) - league_efficiency),
            tempo=league_tempo + (0.50 + 0.25 * carry) * ((prior_tempo or league_tempo) - league_tempo),
            weight=weight,
        )
    return states


def get_state(states: dict[str, TeamState], team_id: Any, league_efficiency: float, league_tempo: float) -> TeamState:
    key = str(team_id)
    if key not in states:
        states[key] = TeamState(league_efficiency, league_efficiency, league_tempo, 3.0)
    return states[key]


def rest_days(state: TeamState, when: datetime) -> int | None:
    if state.last_game is None:
        return None
    return max(0, min(30, (when.date() - state.last_game.date()).days))


def projection_features(game: dict[str, Any], home: TeamState, away: TeamState, league_efficiency: float) -> dict[str, float]:
    pace = 2.0 / ((1.0 / max(home.tempo, 1.0)) + (1.0 / max(away.tempo, 1.0)))
    home_eff = clip(home.offense + away.defense - league_efficiency, 70.0, 145.0)
    away_eff = clip(away.offense + home.defense - league_efficiency, 70.0, 145.0)
    raw_home = pace * home_eff / 100.0
    raw_away = pace * away_eff / 100.0
    home_efg = home.efg_for + away.efg_allowed - 50.0
    away_efg = away.efg_for + home.efg_allowed - 50.0
    home_tov = home.turnover_for + away.turnover_forced - 20.0
    away_tov = away.turnover_for + home.turnover_forced - 20.0
    home_orb = home.rebound_for + away.rebound_allowed - 30.0
    away_orb = away.rebound_for + home.rebound_allowed - 30.0
    home_ftr = home.free_throw_for + away.free_throw_allowed - 30.0
    away_ftr = away.free_throw_for + home.free_throw_allowed - 30.0
    minimum_games = min(home.games, away.games)
    early_weight = 1.0 / (1.0 + minimum_games)
    home_court = 0.0 if game.get("neutral_site") else 1.0
    raw_margin = raw_home - raw_away
    return {
        "raw_margin": raw_margin,
        "raw_margin_curve": raw_margin * abs(raw_margin),
        "raw_total": raw_home + raw_away,
        "home_court": home_court,
        "early_strength_margin": raw_margin * early_weight,
        "early_home": home_court * early_weight,
        "nonconference_home": home_court * (0.0 if game.get("conference_game") else 1.0),
        "projected_pace": pace,
        "experience_diff": math.log1p(home.games) - math.log1p(away.games),
        "experience_sum": math.log1p(home.games) + math.log1p(away.games),
        "efg_edge": home_efg - away_efg,
        "turnover_edge": away_tov - home_tov,
        "rebound_edge": home_orb - away_orb,
        "free_throw_edge": home_ftr - away_ftr,
        "combined_efg": home_efg + away_efg,
        "combined_turnover": home_tov + away_tov,
    }


def update_states(game: dict[str, Any], home: TeamState, away: TeamState, league_efficiency: float, when: datetime) -> None:
    home_box = game.get("home") or {}
    away_box = game.get("away") or {}
    home_eff = finite(home_box.get("efficiency"))
    away_eff = finite(away_box.get("efficiency"))
    if home_eff is not None and away_eff is not None:
        observations = (
            (home, "offense", home_eff - (away.defense - league_efficiency)),
            (home, "defense", away_eff - (away.offense - league_efficiency)),
            (away, "offense", away_eff - (home.defense - league_efficiency)),
            (away, "defense", home_eff - (home.offense - league_efficiency)),
        )
        for state, field, value in observations:
            state.update(field, clip(value, 65.0, 150.0))
    pace = finite(game.get("pace"))
    home.update("tempo", pace)
    away.update("tempo", pace)
    factor_pairs = (
        ("effective_fg_pct", "efg_for", "efg_allowed"),
        ("turnover_pct", "turnover_for", "turnover_forced"),
        ("offensive_rebound_pct", "rebound_for", "rebound_allowed"),
        ("free_throw_rate", "free_throw_for", "free_throw_allowed"),
    )
    for source, offense_field, defense_field in factor_pairs:
        home_value = finite(home_box.get(source))
        away_value = finite(away_box.get(source))
        home.update(offense_field, home_value)
        away.update(defense_field, home_value)
        away.update(offense_field, away_value)
        home.update(defense_field, away_value)
    home.finish_game(when)
    away.finish_game(when)


def generate_rows(seasons: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    prior_teams: list[dict[str, Any]] = []
    for season in sorted(seasons):
        payload = seasons[season]
        current_teams = payload.get("season_end_teams") or []
        league_efficiency, league_tempo = league_context(prior_teams)
        states = initial_states(current_teams, prior_teams, league_efficiency, league_tempo)
        observed_efficiencies: list[float] = []
        for game in payload.get("games") or []:
            outcome = game.get("outcome") or {}
            if (finite(outcome.get("total_points")) or 0.0) < 40:
                raise RuntimeError(f"season {season} contains an unplayed/zero-score game: {game.get('game_id')}")
            when = parse_time(game["start_date"])
            home = get_state(states, game.get("home_team_id"), league_efficiency, league_tempo)
            away = get_state(states, game.get("away_team_id"), league_efficiency, league_tempo)
            features = projection_features(game, home, away, league_efficiency)
            market = game.get("market") or {}
            rows.append({
                "season": season,
                "game_id": game.get("game_id"),
                "start_date": game.get("start_date"),
                "home_team_id": game.get("home_team_id"),
                "home_team": game.get("home_team"),
                "away_team_id": game.get("away_team_id"),
                "away_team": game.get("away_team"),
                "neutral_site": bool(game.get("neutral_site")),
                "conference_game": bool(game.get("conference_game")),
                "home_games_before": home.games,
                "away_games_before": away.games,
                "home_rest_days": rest_days(home, when),
                "away_rest_days": rest_days(away, when),
                "pregame_home_offense": round(home.offense, 4),
                "pregame_home_defense": round(home.defense, 4),
                "pregame_away_offense": round(away.offense, 4),
                "pregame_away_defense": round(away.defense, 4),
                "features": {key: round(value, 5) for key, value in features.items()},
                "actual_home_margin": finite(outcome.get("home_margin")),
                "actual_total": finite(outcome.get("total_points")),
                "market_home_spread": finite(market.get("home_spread_close")),
                "market_total": finite(market.get("total_close")),
                "book_count": int(market.get("book_count") or 0),
            })
            update_states(game, home, away, league_efficiency, when)
            for box in (game.get("home") or {}, game.get("away") or {}):
                if (value := finite(box.get("efficiency"))) is not None:
                    observed_efficiencies.append(value)
            if observed_efficiencies:
                league_efficiency += 0.01 * (statistics.fmean(observed_efficiencies[-40:]) - league_efficiency)
        prior_teams = current_teams
    return rows


def solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [matrix[i][:] + [vector[i]] for i in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-10:
            raise RuntimeError("singular regression system")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [a - factor * b for a, b in zip(augmented[row], augmented[column])]
    return [augmented[row][-1] for row in range(size)]


def fit_ridge(rows: list[dict[str, Any]], feature_names: tuple[str, ...], target: str, ridge: float = 4.0) -> dict[str, Any]:
    samples = [row for row in rows if row.get(target) is not None]
    means = {name: statistics.fmean(row["features"][name] for row in samples) for name in feature_names}
    scales = {}
    for name in feature_names:
        variance = statistics.fmean((row["features"][name] - means[name]) ** 2 for row in samples)
        scales[name] = math.sqrt(variance) or 1.0
    width = len(feature_names) + 1
    xtx = [[0.0] * width for _ in range(width)]
    xty = [0.0] * width
    for row in samples:
        x = [1.0] + [(row["features"][name] - means[name]) / scales[name] for name in feature_names]
        y = float(row[target])
        for i in range(width):
            xty[i] += x[i] * y
            for j in range(width):
                xtx[i][j] += x[i] * x[j]
    for i in range(1, width):
        xtx[i][i] += ridge
    coefficients = solve(xtx, xty)
    return {
        "feature_names": list(feature_names),
        "means": {key: round(value, 8) for key, value in means.items()},
        "scales": {key: round(value, 8) for key, value in scales.items()},
        "coefficients": [round(value, 8) for value in coefficients],
        "ridge": ridge,
        "sample_count": len(samples),
    }


def predict(row: dict[str, Any], model: dict[str, Any]) -> float:
    values = [1.0]
    for name in model["feature_names"]:
        values.append((row["features"][name] - model["means"][name]) / model["scales"][name])
    return sum(coefficient * value for coefficient, value in zip(model["coefficients"], values))


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    margin = [row for row in rows if row.get("actual_home_margin") is not None]
    total = [row for row in rows if row.get("actual_total") is not None]
    result: dict[str, Any] = {
        "games": len(rows),
        "margin_mae": round(statistics.fmean(abs(row["projected_home_margin"] - row["actual_home_margin"]) for row in margin), 4),
        "margin_rmse": round(math.sqrt(statistics.fmean((row["projected_home_margin"] - row["actual_home_margin"]) ** 2 for row in margin)), 4),
        "total_mae": round(statistics.fmean(abs(row["projected_total"] - row["actual_total"]) for row in total), 4),
        "total_rmse": round(math.sqrt(statistics.fmean((row["projected_total"] - row["actual_total"]) ** 2 for row in total)), 4),
        "winner_accuracy": round(100 * statistics.fmean((row["projected_home_margin"] > 0) == (row["actual_home_margin"] > 0) for row in margin), 3),
        "win_probability_brier": round(statistics.fmean((row["home_win_probability"] - float(row["actual_home_margin"] > 0)) ** 2 for row in margin), 6),
    }
    market_margin = [row for row in margin if row.get("market_home_spread") is not None]
    market_total = [row for row in total if row.get("market_total") is not None]
    result["market_margin_games"] = len(market_margin)
    result["market_margin_mae"] = round(statistics.fmean(abs(-row["market_home_spread"] - row["actual_home_margin"]) for row in market_margin), 4) if market_margin else None
    result["market_total_games"] = len(market_total)
    result["market_total_mae"] = round(statistics.fmean(abs(row["market_total"] - row["actual_total"]) for row in market_total), 4) if market_total else None
    result["ats_by_edge"] = edge_metrics(market_margin, "spread")
    result["totals_by_edge"] = edge_metrics(market_total, "total")
    return result


def edge_metrics(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    output = []
    for threshold in (0, 1, 2, 3, 4, 5):
        wins = losses = pushes = 0
        for row in rows:
            if kind == "spread":
                edge = row["projected_home_margin"] + row["market_home_spread"]
                result = row["actual_home_margin"] + row["market_home_spread"]
            else:
                edge = row["projected_total"] - row["market_total"]
                result = row["actual_total"] - row["market_total"]
            if abs(edge) < threshold:
                continue
            if abs(result) < 0.01:
                pushes += 1
            elif edge * result > 0:
                wins += 1
            else:
                losses += 1
        decisions = wins + losses
        output.append({
            "minimum_edge": threshold,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "hit_rate": round(100 * wins / decisions, 3) if decisions else None,
        })
    return output


def current_priors(profile_path: Path, previous_teams: list[dict[str, Any]]) -> dict[str, Any]:
    profiles = json.loads(profile_path.read_text()) if profile_path.exists() else {"meta": {}, "teams": []}
    league_efficiency, league_tempo = league_context(previous_teams)
    rows = []
    for profile in profiles.get("teams") or []:
        prior = profile.get("preseason_prior") or {}
        adjusted = prior.get("adjusted") or {}
        returning = finite(prior.get("returning_minutes_pct"))
        carry = 0.25 + 0.50 * clip((returning or 0.0) / 100.0, 0.0, 1.0)
        offense = finite(adjusted.get("offense")) or league_efficiency
        defense = finite(adjusted.get("defense")) or league_efficiency
        rows.append({
            "team_id": profile.get("team_id"),
            "team": profile.get("team"),
            "conference": profile.get("conference"),
            "prior_offense": round(league_efficiency + carry * (offense - league_efficiency), 4),
            "prior_defense": round(league_efficiency + carry * (defense - league_efficiency), 4),
            "prior_net": round(carry * (offense - defense), 4),
            "returning_minutes_pct": returning,
            "continuity_known": returning is not None,
        })
    rows.sort(key=lambda row: (-row["prior_net"], str(row.get("team") or "")))
    return {
        "meta": {
            "model_version": MODEL_VERSION,
            "season": profiles.get("meta", {}).get("season"),
            "team_count": len(rows),
            "continuity_known_count": sum(row["continuity_known"] for row in rows),
            "positive_continuity_count": sum((row["returning_minutes_pct"] or 0) > 0 for row in rows),
            "status": "preseason_prior; not a current-season adjusted rating",
        },
        "teams": rows,
    }


def atomic_json(path: Path, payload: Any, compressed: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, separators=(",", ":") if compressed else None, indent=None if compressed else 2, allow_nan=False) + "\n").encode()
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    if compressed:
        with temporary.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            zipped.write(encoded)
    else:
        temporary.write_bytes(encoded)
    temporary.replace(path)


def build(history_dir: Path, profile_path: Path, output_dir: Path) -> dict[str, Any]:
    seasons = load_seasons(history_dir)
    rows = generate_rows(seasons)
    training = [row for row in rows if row["season"] in TRAIN_SEASONS]
    margin_model = fit_ridge(training, MARGIN_FEATURES, "actual_home_margin")
    total_model = fit_ridge(training, TOTAL_FEATURES, "actual_total")
    for row in rows:
        row["projected_home_margin"] = round(predict(row, margin_model), 4)
        row["projected_total"] = round(predict(row, total_model), 4)
    residual_sd = statistics.pstdev(row["actual_home_margin"] - row["projected_home_margin"] for row in training)
    for row in rows:
        z = row["projected_home_margin"] / max(residual_sd, 1.0)
        row["home_win_probability"] = round(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))), 6)
        row["projected_home_points"] = round((row["projected_total"] + row["projected_home_margin"]) / 2.0, 3)
        row["projected_away_points"] = round((row["projected_total"] - row["projected_home_margin"]) / 2.0, 3)
        row["split"] = "train" if row["season"] in TRAIN_SEASONS else "validation" if row["season"] in VALIDATION_SEASONS else "test" if row["season"] in TEST_SEASONS else "burn_in"
    evaluated = [row for row in rows if row["split"] != "burn_in"]
    evaluation = {
        "train": metrics([row for row in evaluated if row["split"] == "train"]),
        "validation": metrics([row for row in evaluated if row["split"] == "validation"]),
        "out_of_time_test": metrics([row for row in evaluated if row["split"] == "test"]),
    }
    latest = seasons[max(seasons)]["season_end_teams"]
    priors = current_priors(profile_path, latest)
    validation = evaluation["validation"]
    test = evaluation["out_of_time_test"]
    gate_checks = {
        "validation_margin_mae_within_one_point_of_market": validation["margin_mae"] <= validation["market_margin_mae"] + 1.0,
        "test_margin_mae_within_one_point_of_market": test["margin_mae"] <= test["market_margin_mae"] + 1.0,
        "validation_large_spread_edge_above_52_38_pct": validation["ats_by_edge"][5]["hit_rate"] >= 52.38,
        "test_large_spread_edge_above_52_38_pct": test["ats_by_edge"][5]["hit_rate"] >= 52.38,
        "validation_totals_edge_above_52_38_pct": validation["totals_by_edge"][5]["hit_rate"] >= 52.38,
        "usable_roster_continuity_for_300_teams": priors["meta"]["positive_continuity_count"] >= 300,
    }
    card = {
        "meta": {
            "model_version": MODEL_VERSION,
            "activation_state": "research_only",
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "strict_walk_forward": True,
            "training_seasons": sorted(TRAIN_SEASONS),
            "validation_seasons": sorted(VALIDATION_SEASONS),
            "out_of_time_test_seasons": sorted(TEST_SEASONS),
            "burn_in_seasons": sorted(set(seasons) - TRAIN_SEASONS - VALIDATION_SEASONS - TEST_SEASONS),
            "same_season_end_ratings_used_as_pregame_features": False,
            "description": "Pregame team states update only after each completed game. Current-season end ratings never initialize that same season. Market prices are evaluation fields only.",
        },
        "models": {"margin": margin_model, "total": total_model, "margin_residual_sd": round(residual_sd, 6)},
        "evaluation": evaluation,
        "promotion_gate": {
            "eligible_for_public_projection_engine": all(gate_checks.values()),
            "checks": gate_checks,
        },
        "limitations": [
            "Roster continuity is used only where CBBD supplies matched player IDs and minutes.",
            "Injuries, travel, altitude, coaching, officials and player-level availability are not active inputs in this research version.",
            "Market results are evaluation context and are not model inputs.",
            "The 2027 CBBD roster feed currently has no positive returning-minutes values, so continuity cannot yet differentiate teams.",
            "This research model does not guarantee betting profit.",
        ],
    }
    predictions = {"meta": card["meta"], "games": evaluated}
    atomic_json(output_dir / "model_card.json", card)
    atomic_json(output_dir / "walk_forward_predictions.json.gz", predictions, compressed=True)
    atomic_json(output_dir / "current_priors.json", priors)
    return card


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-dir", type=Path, default=HISTORY_DIR)
    parser.add_argument("--team-profiles", type=Path, default=ROOT / "data" / "cbb" / "team_profiles.json")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    card = build(args.history_dir, args.team_profiles, args.output_dir)
    test = card["evaluation"]["out_of_time_test"]
    print(f"{MODEL_VERSION}: test margin MAE {test['margin_mae']}, total MAE {test['total_mae']}")


if __name__ == "__main__":
    main()
