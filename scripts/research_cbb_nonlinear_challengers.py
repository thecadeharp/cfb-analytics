#!/usr/bin/env python3
"""Chronologically evaluate a compact boosted residual CBB margin challenger."""
from __future__ import annotations

import argparse
import gzip
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-nonlinear-challengers-v1.0"
FEATURES = ("raw_margin", "raw_margin_curve", "home_court", "projected_pace", "efg_edge", "turnover_edge", "rebound_edge", "free_throw_edge", "experience_diff", "personnel_recruit_rating", "personnel_transfer_minutes", "personnel_transfer_rating")


def finite(value: Any) -> float | None:
    try:
        number = float(value); return number if math.isfinite(number) else None
    except (TypeError, ValueError): return None


def values(row: dict[str, Any]) -> dict[str, float]:
    source = row.get("features") or {}
    return {key: finite(source.get(key)) or 0.0 for key in FEATURES}


def metrics(rows: list[dict[str, Any]], corrections: dict[int, float], weight: float = 1.0) -> dict[str, Any]:
    errors = []
    for row in rows:
        actual, base = finite(row.get("actual_home_margin")), finite(row.get("projected_home_margin"))
        if actual is not None and base is not None: errors.append(base + weight * corrections.get(id(row), 0.0) - actual)
    return {"games": len(errors), "mae": round(statistics.fmean(abs(x) for x in errors), 4), "rmse": round(math.sqrt(statistics.fmean(x*x for x in errors)), 4), "bias": round(statistics.fmean(errors), 4)} if errors else {"games": 0, "mae": None, "rmse": None, "bias": None}


def build(predictions: dict[str, Any], rounds: int = 12, learning_rate: float = .12) -> dict[str, Any]:
    rows = [row for row in predictions.get("games") or [] if finite(row.get("actual_home_margin")) is not None and finite(row.get("projected_home_margin")) is not None]
    training = [row for row in rows if row.get("split") == "train"]
    training_ids = {id(row) for row in training}
    feature_rows = {id(row): values(row) for row in rows}
    residual = {id(row): float(row["actual_home_margin"]) - float(row["projected_home_margin"]) for row in training}
    correction = {id(row): 0.0 for row in rows}
    stumps = []
    thresholds = {}
    for feature in FEATURES:
        ordered = sorted(feature_rows[id(row)][feature] for row in training)
        thresholds[feature] = sorted(set(ordered[int((len(ordered)-1)*q)] for q in (.2,.4,.6,.8))) if ordered else []
    for _ in range(rounds):
        best = None
        for feature in FEATURES:
            for threshold in thresholds[feature]:
                left = [residual[id(row)] for row in training if feature_rows[id(row)][feature] <= threshold]
                right = [residual[id(row)] for row in training if feature_rows[id(row)][feature] > threshold]
                if not left or not right: continue
                lv, rv = statistics.fmean(left), statistics.fmean(right)
                loss = sum((value-lv)**2 for value in left) + sum((value-rv)**2 for value in right)
                if best is None or loss < best[0]: best = (loss, feature, threshold, lv, rv)
        if best is None: break
        _, feature, threshold, left_value, right_value = best
        stumps.append({"feature":feature,"threshold":round(threshold,6),"left":round(left_value,6),"right":round(right_value,6)})
        for row in rows:
            step = left_value if feature_rows[id(row)][feature] <= threshold else right_value
            correction[id(row)] += learning_rate * step
            if id(row) in training_ids: residual[id(row)] -= learning_rate * step
    validation = [row for row in rows if row.get("split") == "validation"]
    test = [row for row in rows if row.get("split") == "test"]
    weights = [0,.25,.5,.75,1]
    selected_weight = min(weights, key=lambda weight: metrics(validation, correction, weight)["mae"] or 999)
    return {"meta":{"version":VERSION,"generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"policy":"Stumps are fit on the training split only. Ensemble weight is selected on validation only; the test split remains an out-of-time audit. Published model unchanged."},"gradient_boosting":{"rounds":len(stumps),"learning_rate":learning_rate,"features":list(FEATURES),"validation":metrics(validation,correction,1),"out_of_time_audit":metrics(test,correction,1),"stumps":stumps},"selected_ensemble":{"boosted_weight":selected_weight,"incumbent_weight":1-selected_weight,"validation":metrics(validation,correction,selected_weight),"out_of_time_audit":metrics(test,correction,selected_weight),"promotion_recommended":False}}


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--predictions",type=Path,default=ROOT/"data/cbb/model/walk_forward_predictions.json.gz"); parser.add_argument("--output",type=Path,default=ROOT/"data/cbb/research/nonlinear_challengers.json"); args=parser.parse_args()
    with gzip.open(args.predictions,"rt",encoding="utf-8") as handle: predictions=json.load(handle)
    payload=build(predictions); args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(payload,indent=2,allow_nan=False)+"\n"); print(f"{VERSION}: {payload['gradient_boosting']['rounds']} stumps, ensemble weight {payload['selected_ensemble']['boosted_weight']}")


if __name__ == "__main__": main()
