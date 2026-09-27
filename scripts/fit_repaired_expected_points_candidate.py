#!/usr/bin/env python3
"""Freeze a research-only expected-points candidate after repaired-sample gates."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import research_expected_points_score_margin as base
from evaluate_repaired_score_margin import build_repaired_table

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/repaired_expected_points_candidate.json"
FEATURES = ["intercept", "yards_to_endzone_0_1", "yards_to_endzone_squared",
            "period_2", "period_3", "period_4", "possession_score_margin_div_28"]


def fit(train):
    x = np.column_stack([base.design(train), train.start_score_margin.to_numpy(float) / 28.0])
    penalty = np.eye(x.shape[1]); penalty[0, 0] = 0
    return np.linalg.solve(x.T @ x + 10.0 * penalty,
                           x.T @ train.target_offensive_points.to_numpy(float))


def predict(frame, coefficients):
    x = np.column_stack([base.design(frame), frame.start_score_margin.to_numpy(float) / 28.0])
    return np.clip(x @ coefficients, 0, 8)


def calibration(frame, prediction, column, bins):
    bucket = pd.cut(frame[column], bins, include_lowest=True)
    work = frame.assign(prediction=prediction, bucket=bucket)
    return [{"bucket": str(name), "rows": len(group),
             "actual_mean": float(group.target_offensive_points.mean()),
             "predicted_mean": float(group.prediction.mean()),
             "bias": float((group.prediction - group.target_offensive_points).mean())}
            for name, group in work.groupby("bucket", observed=False) if len(group)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    args = parser.parse_args()
    table, coverage = build_repaired_table(args.source_dir)
    predictions = []
    for train_end, test_year in base.FOLDS:
        test = table.loc[table.season.eq(test_year)].copy()
        test["prediction"] = predict(test, fit(table.loc[table.season.le(train_end)]))
        predictions.append(test)
    oos = pd.concat(predictions, ignore_index=True)
    coefficients = fit(table)
    actual = oos.target_offensive_points.to_numpy(float)
    pred = oos.prediction.to_numpy(float)
    report = {"meta": {"generated_at": datetime.now(timezone.utc).isoformat(),
                        "status": "research_only_repaired_expected_points_candidate_v1",
                        "training_ready": False,
                        "production_use": "none; no Model A, projections, site, or 2025 access",
                        "scope": "2019-2024 strict plus fully corroborated repaired games; rolling OOS calibration uses 2022-2024",
                        "ridge_penalty": 10.0,
                        "prediction_range": [0, 8]},
              "features": FEATURES,
              "coefficients_fit_on_all_approved_2019_2024_rows": coefficients.tolist(),
              "approved_sample": {"games": int(table.game_id.nunique()), "possessions": len(table),
                                  "coverage": coverage},
              "rolling_oos": {"games": int(oos.game_id.nunique()), "possessions": len(oos),
                              "metrics": base.score(actual, pred),
                              "field_position_calibration": calibration(oos, pred, "start_yards_to_endzone", [0,20,40,60,80,100]),
                              "score_margin_calibration": calibration(oos, pred, "start_score_margin", [-100,-15,-8,-1,0,7,14,100])}}
    OUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
