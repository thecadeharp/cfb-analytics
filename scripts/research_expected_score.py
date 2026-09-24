#!/usr/bin/env python3
"""Offline retrospective expected-score baseline; never feeds published projections.

Fits only earlier seasons, evaluates on 2025, and writes research metrics, not
per-game public predictions. Realized drive/opportunity counts are known AFTER
each game. They must never be used in a pregame model.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/training/historical_games.csv"
OUTPUT = ROOT / "data/research/expected_score_holdout_2025.json"
FEATURES = (
    "home_actual_drives",
    "away_actual_drives",
    "home_actual_scoring_opportunities",
    "away_actual_scoring_opportunities",
)
TARGETS = ("home_score", "away_score")
TRAIN_END = 2024
TEST_YEAR = 2025
RIDGE_LAMBDA = 30.0


def numeric(value: str) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def load_rows(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = set((*FEATURES, *TARGETS, "season", "completed")) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Historical dataset missing columns: {sorted(missing)}")
        seasons, features, targets = [], [], []
        for row in reader:
            if row["completed"].strip().lower() not in ("true", "1"):
                continue
            values = [numeric(row.get(name)) for name in (*FEATURES, *TARGETS)]
            season = numeric(row.get("season"))
            if season is None or any(value is None for value in values):
                continue
            x, y = values[:len(FEATURES)], values[len(FEATURES):]
            if min(x) < 0 or min(y) < 0 or x[2] > x[0] or x[3] > x[1]:
                continue
            seasons.append(int(season))
            features.append(x)
            targets.append(y)
    return np.asarray(seasons), np.asarray(features), np.asarray(targets)


def main() -> None:
    seasons, x, y = load_rows(INPUT)
    train, test = seasons <= TRAIN_END, seasons == TEST_YEAR
    if train.sum() < 1000 or test.sum() < 500:
        raise RuntimeError("Too few historical games for sealed 2025 evaluation")

    # Standardize on training data ONLY. Penalize slopes but never intercept.
    center = x[train].mean(axis=0)
    scale = np.where(x[train].std(axis=0) > 0, x[train].std(axis=0), 1.0)
    z_train = np.column_stack((np.ones(train.sum()), (x[train] - center) / scale))
    z_test = np.column_stack((np.ones(test.sum()), (x[test] - center) / scale))
    penalty = np.diag([0.0] + [RIDGE_LAMBDA] * len(FEATURES))
    coefficients = np.linalg.solve(z_train.T @ z_train + penalty, z_train.T @ y[train])
    train_pred = np.maximum(0.0, z_train @ coefficients)
    prediction = np.maximum(0.0, z_test @ coefficients)

    # Empirical *paired* margin residuals preserve game-level shared noise.
    train_margin_residual = ((y[train, 0] - y[train, 1])
                             - (train_pred[:, 0] - train_pred[:, 1]))
    predicted_margin = prediction[:, 0] - prediction[:, 1]
    home_win_probability = (
        np.count_nonzero(predicted_margin[:, None] + train_margin_residual[None, :] > 0, axis=1)
        + 0.5 * np.count_nonzero(predicted_margin[:, None] + train_margin_residual[None, :] == 0, axis=1)
        + 1.0
    ) / (len(train_margin_residual) + 2.0)
    actual_margin = y[test, 0] - y[test, 1]
    decisive = actual_margin != 0
    observed = (actual_margin[decisive] > 0).astype(float)
    probabilities = np.clip(home_win_probability[decisive], 1e-6, 1 - 1e-6)
    score_error = np.abs(y[test] - prediction)
    baseline_score = np.broadcast_to(y[train].mean(axis=0), y[test].shape)
    baseline_margin = baseline_score[:, 0] - baseline_score[:, 1]
    train_decisive = y[train, 0] != y[train, 1]
    baseline_home_win = float(np.mean(y[train, 0][train_decisive] > y[train, 1][train_decisive]))

    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "research_only_not_for_public_scores_or_model_a",
            "dataset": str(INPUT.relative_to(ROOT)),
            "train_seasons": sorted(set(int(v) for v in seasons[train])),
            "sealed_test_season": TEST_YEAR,
            "training_games": int(train.sum()),
            "test_games": int(test.sum()),
            "features": list(FEATURES),
            "target": "Actual final team points. Non-offensive scores are not modeled separately.",
            "method": "Ridge game-level baseline; empirical training margin residual CDF, no Monte Carlo.",
            "limitation": "Uses completed-game drive and scoring-opportunity counts, not a possession ledger or play-level quality. Game-script dependence and defense/special-teams scores remain. Do not publish as calibrated expected scores or a pregame forecast.",
        },
        "holdout": {
            "team_score_mae": round(float(score_error.mean()), 3),
            "league_average_team_score_mae": round(float(np.abs(y[test] - baseline_score).mean()), 3),
            "home_score_mae": round(float(score_error[:, 0].mean()), 3),
            "away_score_mae": round(float(score_error[:, 1].mean()), 3),
            "margin_mae": round(float(np.abs(actual_margin - predicted_margin).mean()), 3),
            "league_average_margin_mae": round(float(np.abs(actual_margin - baseline_margin).mean()), 3),
            "win_probability_brier": round(float(np.mean((probabilities - observed) ** 2)), 4),
            "historical_home_win_rate_brier": round(float(np.mean((baseline_home_win - observed) ** 2)), 4),
            "win_probability_log_loss": round(float(np.mean(-observed * np.log(probabilities) - (1 - observed) * np.log(1 - probabilities))), 4),
            "non_tied_games_for_probability": int(decisive.sum()),
            "calibration_bins": [
                {"from": round(float(low), 1), "to": round(float(low + 0.2), 1),
                 "count": int(mask.sum()),
                 "mean_prediction": round(float(probabilities[mask].mean()), 3) if mask.any() else None,
                 "actual_home_win_rate": round(float(observed[mask].mean()), 3) if mask.any() else None}
                for low in np.arange(0, 1, 0.2)
                for mask in [((probabilities >= low) &
                             (probabilities < low + 0.2 if low < 0.8 else probabilities <= 1.0))]
            ],
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["holdout"], indent=2))


if __name__ == "__main__":
    main()
