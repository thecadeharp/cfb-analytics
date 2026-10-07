#!/usr/bin/env python3
"""Shared statistical validation gates for THI research signals.

The public label ``validated`` is reserved for tests that use the recorded,
de-vigged price for every play, survive family-wise multiple-testing control,
and are not carried by a small number of outlier payouts.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Iterable, Sequence


def american_implied(odds: float) -> float:
    odds = float(odds)
    if odds == 0:
        raise ValueError("American odds cannot be zero")
    return (-odds) / ((-odds) + 100.0) if odds < 0 else 100.0 / (odds + 100.0)


def no_vig_pair(side_odds: float, other_odds: float) -> tuple[float, float]:
    a, b = american_implied(side_odds), american_implied(other_odds)
    total = a + b
    if total <= 0:
        raise ValueError("Market implied probability is invalid")
    return a / total, b / total


def poisson_binomial_tail(probabilities: Sequence[float], wins: int) -> float:
    """Exact P(X >= wins) for independent, non-identical Bernoulli trials."""
    probs = [float(value) for value in probabilities]
    if wins <= 0:
        return 1.0
    if wins > len(probs):
        return 0.0
    distribution = [1.0] + [0.0] * len(probs)
    for index, probability in enumerate(probs, start=1):
        if not 0 <= probability <= 1:
            raise ValueError("Probabilities must be between zero and one")
        for successes in range(index, -1, -1):
            stay = distribution[successes] * (1.0 - probability)
            gain = distribution[successes - 1] * probability if successes else 0.0
            distribution[successes] = stay + gain
    return min(1.0, max(0.0, sum(distribution[wins:])))


def exact_binomial_tail(trials: int, wins: int, probability: float) -> float:
    trials, wins, probability = int(trials), int(wins), float(probability)
    if wins <= 0:return 1.0
    if wins > trials:return 0.0
    if probability <= 0:return 0.0
    if probability >= 1:return 1.0
    log_term = (
        math.lgamma(trials + 1) - math.lgamma(wins + 1) - math.lgamma(trials - wins + 1)
        + wins * math.log(probability) + (trials - wins) * math.log1p(-probability)
    )
    term = math.exp(log_term)
    total = term
    for successes in range(wins, trials):
        term *= ((trials - successes) / (successes + 1)) * (probability / (1 - probability))
        total += term
    return min(1.0, max(0.0, total))


def holm_bonferroni(p_values: Sequence[float]) -> list[float]:
    """Return Holm-adjusted p-values in original order."""
    count = len(p_values)
    ordered = sorted(enumerate(float(value) for value in p_values), key=lambda row: row[1])
    adjusted = [1.0] * count
    running = 0.0
    for rank, (index, value) in enumerate(ordered):
        running = max(running, min(1.0, (count - rank) * value))
        adjusted[index] = running
    return adjusted


def bomb_dependency(profits: Sequence[float], remove_count: int | None = None) -> dict:
    values = [float(value) for value in profits]
    if not values:
        return {"passed": False, "removed": 0, "remaining_profit": 0.0}
    remove = remove_count if remove_count is not None else max(1, math.ceil(len(values) * 0.02))
    remove = min(remove, max(0, len(values) - 1))
    remaining = sorted(values, reverse=True)[remove:]
    remaining_profit = sum(remaining)
    return {
        "passed": remaining_profit > 0,
        "removed": remove,
        "remaining_profit": round(remaining_profit, 4),
        "original_profit": round(sum(values), 4),
    }


def monthly_results(rows: Iterable[dict]) -> list[dict]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        raw = row.get("date") or row.get("start_date")
        if not raw:
            continue
        try:
            month = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).strftime("%Y-%m")
        except ValueError:
            continue
        grouped[month].append(str(row.get("result")))
    return [
        {
            "month": month,
            "wins": results.count("W"),
            "losses": results.count("L"),
            "pushes": results.count("P"),
        }
        for month, results in sorted(grouped.items())
    ]


def validation_gate(
    *,
    outcomes: Sequence[str],
    no_vig_probabilities: Sequence[float] | None,
    adjusted_p: float | None,
    profits: Sequence[float],
    alpha: float = 0.05,
) -> dict:
    priced = no_vig_probabilities is not None and len(no_vig_probabilities) == len(outcomes)
    bomb = bomb_dependency(profits)
    checks = {
        "recorded_no_vig_baseline": priced,
        "exact_test": priced and adjusted_p is not None,
        "multiple_comparison_control": adjusted_p is not None and adjusted_p < alpha,
        "bomb_dependency": bomb["passed"],
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "adjusted_p_value": round(adjusted_p, 6) if adjusted_p is not None else None,
        "bomb_dependency": bomb,
        "label_rule": "All four checks must pass before THI displays Validated.",
    }
