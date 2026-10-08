#!/usr/bin/env python3
"""Build a conservative, reproducible audit of THI's historical research models."""
from __future__ import annotations

import gzip
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
PRICE = -110
BREAK_EVEN = abs(PRICE) / (100 + abs(PRICE))


def exact_binomial_upper_tail(wins: int, decisions: int, baseline: float = BREAK_EVEN) -> float | None:
    """P(X >= wins) under a fixed binomial baseline, evaluated in log space."""
    if decisions <= 0:
        return None
    logs = [
        math.lgamma(decisions + 1) - math.lgamma(k + 1) - math.lgamma(decisions - k + 1)
        + k * math.log(baseline) + (decisions - k) * math.log1p(-baseline)
        for k in range(wins, decisions + 1)
    ]
    peak = max(logs)
    return min(1.0, math.exp(peak) * sum(math.exp(value - peak) for value in logs))


def wilson_interval(wins: int, decisions: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if decisions <= 0:
        return None, None
    rate = wins / decisions
    denominator = 1 + z * z / decisions
    midpoint = (rate + z * z / (2 * decisions)) / denominator
    radius = z * math.sqrt(rate * (1 - rate) / decisions + z * z / (4 * decisions * decisions)) / denominator
    return 100 * (midpoint - radius), 100 * (midpoint + radius)


def grade(wins: int, losses: int, pushes: int) -> dict:
    decisions = wins + losses
    plays = decisions + pushes
    profit = wins * (100 / abs(PRICE)) - losses
    low, high = wilson_interval(wins, decisions)
    return {
        "games": plays, "decisions": decisions, "wins": wins, "losses": losses, "pushes": pushes,
        "record": f"{wins}-{losses}-{pushes}",
        "hit_rate": round(100 * wins / decisions, 3) if decisions else None,
        "hit_rate_ci_95": [round(low, 3), round(high, 3)] if low is not None else None,
        "hypothetical_return_pct": round(100 * profit / plays, 3) if plays else None,
        "hypothetical_units": round(profit, 3),
        "p_value_vs_flat_minus_110": round(exact_binomial_upper_tail(wins, decisions), 6) if decisions else None,
    }


def holm_adjust(rows: list[dict]) -> None:
    """Attach Holm-adjusted p-values for the complete displayed comparison family."""
    ordered = sorted(enumerate(rows), key=lambda item: item[1]["p_value_vs_flat_minus_110"])
    running = 0.0
    total = len(rows)
    for rank, (index, row) in enumerate(ordered):
        adjusted = min(1.0, (total - rank) * row["p_value_vs_flat_minus_110"])
        running = max(running, adjusted)
        rows[index]["holm_adjusted_p"] = round(running, 6)


TIERS: list[tuple[str, str, str, Callable[[float], bool]]] = [
    ("aligned", "Aligned", "0 to 2.5", lambda edge: edge <= 2.5),
    ("small_edge", "Small edge", ">2.5 to 5", lambda edge: 2.5 < edge <= 5),
    ("play", "Play", ">5 to 7", lambda edge: 5 < edge <= 7),
    ("material_disagreement", "Material disagreement", ">7 to 10", lambda edge: 7 < edge <= 10),
    ("outlier", "Outlier", ">10", lambda edge: edge > 10),
]


def summarize(rows: list[dict], selector: Callable[[dict], bool], result: Callable[[dict], str]) -> dict:
    selected = [row for row in rows if selector(row)]
    return grade(
        sum(result(row) == "win" for row in selected),
        sum(result(row) == "loss" for row in selected),
        sum(result(row) == "push" for row in selected),
    )


def cfb_scorecard(path: Path) -> dict:
    source = json.loads(path.read_text())
    rows = [row for row in source["games"] if int(row["year"]) in {2024, 2025}]
    edge = lambda row: abs(float(row["model_edge"]))
    result = lambda row: row["ats_result"]
    buckets = [
        {"key": key, "label": label, "edge_range": edge_range, **summarize(rows, lambda row, test=test: test(edge(row)), result)}
        for key, label, edge_range, test in TIERS
    ]
    actionable = summarize(rows, lambda row: edge(row) > 5, result)
    holm_adjust([actionable, *buckets])
    yearly = [
        {"season": year, **summarize([row for row in rows if int(row["year"]) == year], lambda row: edge(row) > 5, result)}
        for year in (2024, 2025)
    ]
    identities = [(int(row["year"]), int(row["week"]), str(row["game_id"])) for row in rows]
    return {
        "status": "not_validated", "verdict": "Historical pattern did not validate", "seasons": [2024, 2025],
        "model": "Time-safe weekly composite predecessor; not the live 2026 Model A",
        "market": "Archived provider spread snapshot; closing time and two-sided price are not verified",
        "price_assumption": PRICE,
        "selection_policy": "All five predeclared signal tiers plus the combined >5-point group are shown.",
        "validation_note": "The combined result is positive under a hypothetical flat -110 price, but it is not statistically significant, turns negative in 2025, and cannot validate live Model A.",
        "actionable_over_5": actionable, "yearly": yearly, "buckets": buckets,
        "data_integrity": {"source_rows": len(rows), "duplicate_game_keys": len(identities) - len(set(identities))},
        "robustness": {
            "without_outlier_tier": summarize(rows, lambda row: 5 < edge(row) <= 10, result),
            "interpretation": "Removing >10-point outliers does not make the combined result statistically significant.",
        },
    }


def cbb_result(row: dict) -> str:
    edge = float(row["projected_home_margin"]) + float(row["market_home_spread"])
    outcome = float(row["actual_home_margin"]) + float(row["market_home_spread"])
    if abs(outcome) < 0.01:
        return "push"
    return "win" if edge * outcome > 0 else "loss"


def cbb_scorecard(predictions_path: Path, card_path: Path) -> dict:
    with gzip.open(predictions_path, "rt") as handle:
        rows = [row for row in json.load(handle)["games"] if row.get("split") in {"validation", "test"} and row.get("market_home_spread") is not None]
    card = json.loads(card_path.read_text())
    edge = lambda row: abs(float(row["projected_home_margin"]) + float(row["market_home_spread"]))
    buckets = [
        {"key": key, "label": label, "edge_range": edge_range, **summarize(rows, lambda row, test=test: test(edge(row)), cbb_result)}
        for key, label, edge_range, test in TIERS
    ]
    actionable = summarize(rows, lambda row: edge(row) > 5, cbb_result)
    holm_adjust([actionable, *buckets])
    yearly = [
        {"season": year, **summarize([row for row in rows if int(row["season"]) == year], lambda row: edge(row) > 5, cbb_result)}
        for year in (2025, 2026)
    ]
    evaluation = card["evaluation"]
    accuracy = [
        {"season": year, "thi_margin_mae": evaluation[key]["margin_mae"], "market_margin_mae": evaluation[key]["market_margin_mae"],
         "market_advantage_points": round(evaluation[key]["margin_mae"] - evaluation[key]["market_margin_mae"], 4)}
        for year, key in ((2025, "validation"), (2026, "out_of_time_test"))
    ]
    identities = [(int(row["season"]), str(row["game_id"])) for row in rows]
    return {
        "status": "not_validated", "verdict": "Research model did not validate", "seasons": [2025, 2026],
        "model": "THI CBB walk-forward v0.7 research",
        "market": "Archived closing-spread field; two-sided prices are unavailable",
        "price_assumption": PRICE,
        "selection_policy": "All five predeclared signal tiers plus the combined >5-point group are shown.",
        "validation_note": "The combined >5-point sample loses at a hypothetical flat -110 price, no displayed tier clears the corrected significance test, and the market has lower margin error in both held-out seasons.",
        "actionable_over_5": actionable, "yearly": yearly, "buckets": buckets, "market_accuracy": accuracy,
        "data_integrity": {"source_rows": len(rows), "duplicate_game_keys": len(identities) - len(set(identities))},
        "robustness": {
            "without_outlier_tier": summarize(rows, lambda row: 5 < edge(row) <= 10, cbb_result),
            "interpretation": "Removing >10-point outliers leaves the combined sample negative.",
        },
    }


def main() -> None:
    output = ROOT / "data/reports/public_backtest_scorecard.json"
    payload = {
        "meta": {
            "version": "thi-public-backtest-v2.0",
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "audit_standard": "Exact one-sided binomial test against the 52.381% break-even rate implied by a hypothetical flat -110 price; Holm correction across the six displayed comparisons; 95% Wilson hit-rate intervals; season and outlier sensitivity checks.",
            "financial_claim": False,
            "price_policy": "Historical per-play prices and no-vig probabilities are unavailable. Return figures are hypothetical flat -110 arithmetic, not realized ROI.",
            "promotion_rule": "These archived studies cannot validate the live models. Prospective frozen projections, verified prices, no-vig baselines, multiplicity control, outlier checks and stability checks govern any future validation label.",
        },
        "sports": {
            "cfb": cfb_scorecard(ROOT / "data/composite_backtest_report.json"),
            "cbb": cbb_scorecard(ROOT / "data/cbb/model/walk_forward_predictions.json.gz", ROOT / "data/cbb/model/model_card.json"),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    main()
