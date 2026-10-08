#!/usr/bin/env python3
"""Publish a transparent two-season research backtest for both THI boards."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRICE = -110


def grade(wins: int, losses: int, pushes: int) -> dict:
    decisions = wins + losses
    plays = decisions + pushes
    profit = wins * (100 / abs(PRICE)) - losses
    return {
        "games": plays,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "record": f"{wins}-{losses}-{pushes}",
        "hit_rate": round(100 * wins / decisions, 3) if decisions else None,
        "roi_pct": round(100 * profit / plays, 3) if plays else None,
        "profit_units": round(profit, 3),
    }


def cfb_scorecard(path: Path) -> dict:
    source = json.loads(path.read_text())
    rows = [row for row in source["games"] if int(row["year"]) in {2024, 2025}]
    tiers = [
        ("aligned", "Aligned", 0, 2.5),
        ("small_edge", "Small edge", 2.5, 5),
        ("play", "Play", 5, 7),
        ("material_disagreement", "Material disagreement", 7, 10),
        ("outlier", "Outlier", 10, float("inf")),
    ]
    buckets = []
    for key, label, low, high in tiers:
        def in_bucket(row: dict) -> bool:
            edge = abs(float(row["model_edge"]))
            lower_bound = edge >= low if key == "aligned" else edge > low
            return lower_bound and edge <= high

        sample = [row for row in rows if in_bucket(row)]
        counts = {result: sum(row.get("ats_result") == result for row in sample) for result in ("win", "loss", "push")}
        edge_range = f"{low:g} to {high:g}" if key == "aligned" else (f">{low:g} to {high:g}" if high != float("inf") else f">{low:g}")
        buckets.append({"key": key, "label": label, "edge_range": edge_range, **grade(counts["win"], counts["loss"], counts["push"])})
    qualifying = [row for row in rows if abs(float(row["model_edge"])) > 5]
    q = {result: sum(row.get("ats_result") == result for row in qualifying) for result in ("win", "loss", "push")}
    return {
        "status": "historical_research_proxy",
        "seasons": [2024, 2025],
        "model": "Leakage-safe weekly composite predecessor",
        "market": "Historical closing spread",
        "price_assumption": PRICE,
        "selection_policy": "Every frozen edge bucket is published; no favorable bucket is hidden.",
        "validation_note": "Descriptive proxy only. It is not the exact 2026 Model A and lacks per-play two-sided prices for a no-vig probability test.",
        "qualified_5_plus": grade(q["win"], q["loss"], q["push"]),
        "buckets": buckets,
    }


def cbb_scorecard(path: Path) -> dict:
    evaluation = json.loads(path.read_text())["evaluation"]
    seasons = [(2025, "validation"), (2026, "out_of_time_test")]
    yearly = []
    for year, key in seasons:
        row = next(item for item in evaluation[key]["ats_by_edge"] if int(item["minimum_edge"]) == 5)
        yearly.append({"season": year, **grade(int(row["wins"]), int(row["losses"]), int(row["pushes"]))})
    combined = grade(
        sum(row["wins"] for row in yearly),
        sum(row["losses"] for row in yearly),
        sum(row["pushes"] for row in yearly),
    )
    return {
        "status": "strict_walk_forward_research",
        "seasons": [2025, 2026],
        "model": "THI CBB walk-forward v0.7 research",
        "market": "Historical closing spread",
        "price_assumption": PRICE,
        "selection_policy": "All games with an absolute model edge of at least 5 points.",
        "validation_note": "Strict validation and out-of-time test seasons. Combined ROI remains below zero, so current CBB signals stay research-only.",
        "qualified_5_plus": combined,
        "yearly": yearly,
    }


def main() -> None:
    output = ROOT / "data/reports/public_backtest_scorecard.json"
    payload = {
        "meta": {
            "version": "thi-public-backtest-v1.0",
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "staking": "One unit risked per play at -110; pushes return stake.",
            "promotion_rule": "Historical ROI is context. Prospective no-vig, exact-test, multiplicity, outlier and stability gates still control validation labels.",
        },
        "sports": {
            "cfb": cfb_scorecard(ROOT / "data/composite_backtest_report.json"),
            "cbb": cbb_scorecard(ROOT / "data/cbb/model/model_card.json"),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    main()
