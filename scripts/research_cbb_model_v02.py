#!/usr/bin/env python3
"""Select a CBB margin challenger on inner chronological folds only."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.build_cbb_walk_forward_model import (
        HISTORY_DIR, MARGIN_FEATURES, fit_ridge, generate_rows, load_personnel, load_seasons, predict,
    )
except ModuleNotFoundError:  # Direct execution adds scripts/, not the repository root, to sys.path.
    from build_cbb_walk_forward_model import (
        HISTORY_DIR, MARGIN_FEATURES, fit_ridge, generate_rows, load_personnel, load_seasons, predict,
    )

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-model-v0.2-challenger-lab"
INNER_FOLDS = (2022, 2023, 2024)
FINAL_TRAIN = set(range(2019, 2025))

FEATURE_SETS = {
    "incumbent_full": MARGIN_FEATURES,
    "efficiency_context": (
        "raw_margin", "raw_margin_curve", "home_court", "experience_diff", "experience_sum",
        "early_strength_margin", "early_home", "nonconference_home",
    ),
    "efficiency_four_factors": (
        "raw_margin", "raw_margin_curve", "home_court", "experience_diff", "experience_sum",
        "early_strength_margin", "early_home", "nonconference_home", "efg_edge",
        "turnover_edge", "rebound_edge", "free_throw_edge",
    ),
    "efficiency_personnel": (
        "raw_margin", "raw_margin_curve", "home_court", "experience_diff", "experience_sum",
        "early_strength_margin", "early_home", "nonconference_home", "personnel_recruit_rating",
        "personnel_transfer_minutes", "personnel_transfer_points", "personnel_transfer_rating",
    ),
    "incumbent_plus_rest": MARGIN_FEATURES + (
        "rest_advantage", "home_back_to_back", "away_back_to_back",
    ),
    "incumbent_plus_schedule_context": MARGIN_FEATURES + (
        "rest_advantage", "home_back_to_back", "away_back_to_back", "conference_game",
    ),
}
RIDGES = (1.0, 4.0, 12.0, 40.0)


def add_challenger_features(rows: list[dict[str, Any]]) -> None:
    """Add only information that is knowable before each game's tipoff."""
    for row in rows:
        home_rest = finite(row.get("home_rest_days"))
        away_rest = finite(row.get("away_rest_days"))
        row["features"].update({
            "rest_advantage": max(-7.0, min(7.0, (home_rest or 0.0) - (away_rest or 0.0))) if home_rest is not None and away_rest is not None else 0.0,
            "home_back_to_back": float(home_rest is not None and home_rest <= 1),
            "away_back_to_back": float(away_rest is not None and away_rest <= 1),
            "conference_game": float(bool(row.get("conference_game"))),
        })


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def score(rows: list[dict[str, Any]], model: dict[str, Any]) -> dict[str, Any]:
    evaluated = []
    for row in rows:
        actual = finite(row.get("actual_home_margin"))
        if actual is None:
            continue
        projection = predict(row, model)
        evaluated.append((row, projection, actual))
    errors = [projection - actual for _row, projection, actual in evaluated]
    market_rows = []
    for row, projection, actual in evaluated:
        spread = finite(row.get("market_home_spread"))
        if spread is None:
            continue
        edge = projection + spread
        if abs(edge) < 5:
            continue
        result = actual + spread
        if abs(result) < .01:
            outcome = "push"
        else:
            outcome = "win" if edge * result > 0 else "loss"
        market_rows.append(outcome)
    wins = market_rows.count("win")
    losses = market_rows.count("loss")
    decisions = wins + losses
    return {
        "games": len(evaluated),
        "margin_mae": round(statistics.fmean(abs(value) for value in errors), 4),
        "margin_rmse": round(math.sqrt(statistics.fmean(value * value for value in errors)), 4),
        "winner_accuracy": round(100 * statistics.fmean((projection > 0) == (actual > 0) for _row, projection, actual in evaluated), 3),
        "margin_bias": round(statistics.fmean(errors), 4),
        "edge_5_games": len(market_rows),
        "edge_5_record": f"{wins}-{losses}-{market_rows.count('push')}",
        "edge_5_hit_rate": round(100 * wins / decisions, 3) if decisions else None,
    }


def candidate_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for name, features in FEATURE_SETS.items():
        for ridge in RIDGES:
            folds = []
            for validation_season in INNER_FOLDS:
                training = [row for row in rows if 2019 <= row["season"] < validation_season]
                validation = [row for row in rows if row["season"] == validation_season]
                model = fit_ridge(training, features, "actual_home_margin", ridge)
                folds.append({"season": validation_season, **score(validation, model)})
            output.append({
                "name": name,
                "ridge": ridge,
                "feature_names": list(features),
                "folds": folds,
                "mean_margin_mae": round(statistics.fmean(row["margin_mae"] for row in folds), 4),
                "worst_margin_mae": round(max(row["margin_mae"] for row in folds), 4),
            })
    output.sort(key=lambda row: (row["mean_margin_mae"], row["worst_margin_mae"], len(row["feature_names"]), row["ridge"]))
    return output


def build(history_dir: Path, personnel_dir: Path) -> dict[str, Any]:
    seasons = load_seasons(history_dir)
    personnel = load_personnel(personnel_dir)
    rows = generate_rows(seasons, personnel)
    add_challenger_features(rows)
    candidates = candidate_table(rows)
    selected = candidates[0]
    incumbent_inner = next(row for row in candidates if row["name"] == "incumbent_full" and row["ridge"] == 4.0)
    full_training = [row for row in rows if row["season"] in FINAL_TRAIN]
    challenger_model = fit_ridge(full_training, tuple(selected["feature_names"]), "actual_home_margin", selected["ridge"])
    incumbent_model = fit_ridge(full_training, MARGIN_FEATURES, "actual_home_margin", 4.0)
    comparisons = {}
    for label, season in (("validation_2025", 2025), ("audit_2026", 2026)):
        sample = [row for row in rows if row["season"] == season]
        comparisons[label] = {
            "incumbent": score(sample, incumbent_model),
            "challenger": score(sample, challenger_model),
        }
    inner_improvement = incumbent_inner["mean_margin_mae"] - selected["mean_margin_mae"]
    validation = comparisons["validation_2025"]
    audit = comparisons["audit_2026"]
    promotion_checks = {
        "selected_without_2025_or_2026_results": True,
        "inner_fold_mae_improves_by_0_05": inner_improvement >= .05,
        "challenger_improves_2025_margin_mae": validation["challenger"]["margin_mae"] < validation["incumbent"]["margin_mae"],
        "challenger_does_not_regress_2026_margin_mae": audit["challenger"]["margin_mae"] <= audit["incumbent"]["margin_mae"],
        "challenger_2025_edge_5_at_least_incumbent": (validation["challenger"]["edge_5_hit_rate"] or 0) >= (validation["incumbent"]["edge_5_hit_rate"] or 0),
    }
    promote = all(promotion_checks.values()) and selected["name"] != "incumbent_full"
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "eligible_for_engineering_review" if promote else "research_only_no_promotion",
            "selection_policy": "Candidate family and ridge are selected only on rolling 2022-2024 inner folds. The 2025 validation and previously exposed 2026 audit are post-selection gates, never selection inputs.",
            "published_model_unchanged": True,
        },
        "selected_candidate": {key: selected[key] for key in ("name", "ridge", "feature_names", "mean_margin_mae", "worst_margin_mae", "folds")},
        "incumbent_inner_folds": {key: incumbent_inner[key] for key in ("name", "ridge", "mean_margin_mae", "worst_margin_mae", "folds")},
        "inner_fold_mae_improvement": round(inner_improvement, 4),
        "post_selection_comparison": comparisons,
        "promotion": {"recommended": promote, "checks": promotion_checks, "required_next_evidence": "2027 frozen prospective results remain the clean next unseen evidence."},
        "candidate_count": len(candidates),
        "leaderboard": candidates[:8],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-dir", type=Path, default=HISTORY_DIR)
    parser.add_argument("--personnel-dir", type=Path, default=ROOT / "data" / "cbb" / "personnel")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "cbb" / "research" / "model_v02_challenger.json")
    args = parser.parse_args()
    payload = build(args.history_dir, args.personnel_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(f"{VERSION}: {payload['selected_candidate']['name']} ridge={payload['selected_candidate']['ridge']} promote={payload['promotion']['recommended']}")


if __name__ == "__main__":
    main()
