#!/usr/bin/env python3
"""Research-only historical Ridge audit for a first-half situational model.

No point-equivalent rating is published by this script. 2025 was inspected
during prototype development; it is an out-of-sample diagnostic, not a fresh
sealed test. Use future 2026 prospective snapshots for a new untouched test.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HISTORY = ROOT / "data/training/historical_games.csv"
DEFAULT_ADVANCED = ROOT / "data/advanced_metrics.json"
DEFAULT_OUTPUT = ROOT / "data/reports/thi_situational_calibration.json"
FEATURES = ("script_epa", "leverage_epa", "red_zone_epa", "iso_ppp", "competitive_epa")
ALPHAS = (0.0, 10.0, 50.0, 200.0, 500.0, 1000.0)
VALIDATION_YEARS = (2022, 2023, 2024)
MIN_HOLDOUT_GAMES = 500


def make_features(frame):
    columns = []
    for name in FEATURES:
        off, defense = f"off_{name}", f"def_{name}_allowed"
        home = frame[f"home_pregame_{off}"] - frame[f"away_pregame_{defense}"]
        away = frame[f"away_pregame_{off}"] - frame[f"home_pregame_{defense}"]
        columns.append((home - away).to_numpy(dtype=float))
    return np.column_stack(columns)


def score(x, target, train, test, alpha):
    train_x = x[train]
    center, scale = train_x.mean(axis=0), train_x.std(axis=0)
    scale[scale < 1e-3] = 1.0
    design = np.column_stack((np.ones(int(train.sum())), (train_x - center) / scale))
    # Cap only the training target, never the evaluation outcomes.
    fit_y = np.clip(target[train], -40, 40)
    penalty = np.eye(design.shape[1])
    penalty[0, 0] = 0.0  # Home intercept is not shrunk.
    coefficient = np.linalg.solve(
        design.T @ design + alpha * penalty, design.T @ fit_y
    )
    prediction = coefficient[0] + ((x[test] - center) / scale) @ coefficient[1:]
    # Both methods are judged on the same real, uncapped margins.
    return {
        "games": int(test.sum()),
        "mae": round(float(np.mean(np.abs(target[test] - prediction))), 4),
        "constant_baseline_mae": round(float(np.mean(np.abs(target[test] - fit_y.mean()))), 4),
        "coefficient_by_feature": {
            name: round(float(value), 4)
            for name, value in zip(("home_intercept", *FEATURES), coefficient)
        },
    }


def run(history, advanced):
    frame = pd.read_csv(history, low_memory=False)
    if set(range(2019, 2026)) - set(frame.season.unique()):
        raise RuntimeError("Historical training seasons 2019–2025 are required")
    if not frame.season_type.eq(2).all():
        raise RuntimeError("Postseason rows entered the first-half calibration")
    x = make_features(frame)
    target = pd.to_numeric(frame.actual_first_half_margin, errors="coerce").to_numpy()
    years = frame.season.to_numpy()
    valid = np.isfinite(x).all(axis=1) & np.isfinite(target)
    candidates = []
    for alpha in ALPHAS:
        folds = []
        for year in VALIDATION_YEARS:
            train, test = valid & (years < year), valid & (years == year)
            folds.append({"year": year, **score(x, target, train, test, alpha)})
        weighted_mae = sum(f["games"] * f["mae"] for f in folds) / sum(f["games"] for f in folds)
        candidates.append((weighted_mae, alpha, folds))
    _, selected_alpha, selected_folds = min(candidates, key=lambda c: (c[0], c[1]))
    holdout_train = valid & (years < 2025)
    holdout_test = valid & (years == 2025)
    if holdout_test.sum() < MIN_HOLDOUT_GAMES:
        raise RuntimeError("Too few historical 2025 games to audit")
    holdout = score(x, target, holdout_train, holdout_test, selected_alpha)

    live = json.loads(Path(advanced).read_text(encoding="utf-8"))
    team_metrics = [t.get("non_garbage", {}).get("offense", {}) for t in live.get("teams", {}).values()]
    coverage = {
        "teams": len(team_metrics),
        "at_least_30_script_plays": sum(t.get("script_early_plays", 0) >= 30 for t in team_metrics),
        "at_least_30_leverage_plays": sum(t.get("leverage_plays", 0) >= 30 for t in team_metrics),
        "at_least_30_red_zone_plays": sum(t.get("situational_red_zone_plays", 0) >= 30 for t in team_metrics),
    }
    # Never publish a point-scale rating on a failure or incomplete sample.
    release_ready = (
        holdout["mae"] + 0.1 < holdout["constant_baseline_mae"]
        and coverage["at_least_30_script_plays"] >= 80
        and coverage["at_least_30_leverage_plays"] >= 80
        and coverage["at_least_30_red_zone_plays"] >= 80
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "RESEARCH_ONLY_HOLD" if not release_ready else "RESEARCH_ONLY_REVIEW",
        "point_equivalent_published": False,
        "reason": "Model must beat a predeclared baseline and meet sample thresholds; a future prospective test is still required.",
        "data": "2019–2025 regular-season ESPN-derived SportsDataverse plays; pregame features use prior weeks only",
        "target": "actual first-half home margin in points",
        "features": list(FEATURES),
        "fit": "Ridge with training-only standardization and a nonpenalized home intercept",
        "selected_alpha_on_2022_2024": selected_alpha,
        "validation": selected_folds,
        "historical_2025_audit": holdout,
        "holdout_integrity": "2025 was inspected in prototype development; future 2026 prospective data must provide an untouched test.",
        "live_2026": {"through_week": live.get("meta", {}).get("through_week"), **coverage},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--advanced", type=Path, default=DEFAULT_ADVANCED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run(args.history, args.advanced)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"{report['status']}: 2025 MAE={report['historical_2025_audit']['mae']}, "
          f"baseline={report['historical_2025_audit']['constant_baseline_mae']}")


if __name__ == "__main__":
    main()
