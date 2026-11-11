#!/usr/bin/env python3
"""Build a public, leakage-safe CBB model comparison scorecard."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-model-lab-v1.0"


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def metric(rows: list[dict[str, Any]], projection_key: str, actual_key: str) -> dict[str, Any]:
    errors = []
    for row in rows:
        projection = finite(row.get(projection_key))
        actual = finite(row.get(actual_key))
        if projection is not None and actual is not None:
            errors.append(projection - actual)
    return {
        "games": len(errors),
        "mae": round(statistics.fmean(abs(error) for error in errors), 4) if errors else None,
        "rmse": round(math.sqrt(statistics.fmean(error * error for error in errors)), 4) if errors else None,
        "bias": round(statistics.fmean(errors), 4) if errors else None,
    }


def market_metric(rows: list[dict[str, Any]], market_key: str, actual_key: str, invert: bool = False) -> dict[str, Any]:
    copied = []
    for row in rows:
        value = finite(row.get(market_key))
        if value is None:
            continue
        copied.append({**row, "market_projection": -value if invert else value})
    return metric(copied, "market_projection", actual_key)


def build(predictions: dict[str, Any], card: dict[str, Any], challenger: dict[str, Any]) -> dict[str, Any]:
    games = predictions.get("games") or []
    splits = {}
    for split, label in (("train", "Training"), ("validation", "Validation"), ("test", "Out-of-time test")):
        rows = [row for row in games if row.get("split") == split]
        raw_margin_rows = [{**row, "raw_margin_value": (row.get("features") or {}).get("raw_margin")} for row in rows]
        raw_total_rows = [{**row, "raw_total_value": (row.get("features") or {}).get("raw_total")} for row in rows]
        splits[split] = {
            "label": label,
            "incumbent_margin": metric(rows, "projected_home_margin", "actual_home_margin"),
            "raw_efficiency_margin": metric(raw_margin_rows, "raw_margin_value", "actual_home_margin"),
            "market_margin": market_metric(rows, "market_home_spread", "actual_home_margin", invert=True),
            "incumbent_total": metric(rows, "projected_total", "actual_total"),
            "raw_efficiency_total": metric(raw_total_rows, "raw_total_value", "actual_total"),
            "market_total": market_metric(rows, "market_total", "actual_total"),
        }

    selected = challenger.get("selected_candidate") or {}
    comparison = challenger.get("post_selection_comparison") or {}
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "published_model_version": (card.get("meta") or {}).get("model_version"),
            "published_model_state": (card.get("meta") or {}).get("activation_state"),
            "policy": "Every comparison is chronological. Market prices are evaluation benchmarks, never model inputs. No challenger is promoted without clearing every frozen gate.",
        },
        "splits": splits,
        "challenger": {
            "name": selected.get("name"),
            "ridge": selected.get("ridge"),
            "inner_fold_margin_mae": selected.get("mean_margin_mae"),
            "inner_fold_improvement": challenger.get("inner_fold_mae_improvement"),
            "validation": (comparison.get("validation_2025") or {}).get("challenger"),
            "out_of_time_audit": (comparison.get("audit_2026") or {}).get("challenger"),
            "promotion_recommended": (challenger.get("promotion") or {}).get("recommended", False),
            "promotion_checks": (challenger.get("promotion") or {}).get("checks") or {},
        },
        "feature_readiness": [
            {"feature": "Rest and back-to-back", "state": "challenger_tested", "model_status": "not_promoted", "reason": "Chronological challenger testing exists; frozen promotion gates did not clear."},
            {"feature": "Shot profile and transition", "state": "display_only", "model_status": "not_tested_historically", "reason": "Current play-by-play coverage is useful for matchup context but not yet a multi-season training sample."},
            {"feature": "Travel and venue", "state": "display_only", "model_status": "not_promoted", "reason": "Verified context is shown separately until a historical holdout clears."},
            {"feature": "Player availability", "state": "source_limited", "model_status": "not_priced", "reason": "Only verified, timestamped availability can qualify; no synthetic injury adjustment is made."},
            {"feature": "Ball-screen and action type", "state": "paid_data_required", "model_status": "unavailable", "reason": "Ordinary play-by-play cannot reliably identify screens, handoffs or detailed half-court actions."},
        ],
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, default=ROOT / "data/cbb/model/walk_forward_predictions.json.gz")
    parser.add_argument("--model-card", type=Path, default=ROOT / "data/cbb/model/model_card.json")
    parser.add_argument("--challenger", type=Path, default=ROOT / "data/cbb/research/model_v02_challenger.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/cbb/model/model_lab.json")
    args = parser.parse_args()
    with gzip.open(args.predictions, "rt", encoding="utf-8") as handle:
        predictions = json.load(handle)
    payload = build(predictions, json.loads(args.model_card.read_text()), json.loads(args.challenger.read_text()))
    atomic_write(args.output, payload)
    print(f"{VERSION}: {len(payload['splits'])} chronological splits")


if __name__ == "__main__":
    main()
