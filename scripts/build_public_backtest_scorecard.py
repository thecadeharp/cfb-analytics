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



def short_favorite_summary(rows: list[dict], spread_key: str = "market_home_spread", margin_key: str = "actual_home_margin") -> dict:
    """Describe -1 through -4.5 market favorites, comparing straight-up and ATS results."""
    selected = []
    for row in rows:
        try:
            spread = float(row[spread_key])
            margin = float(row[margin_key])
        except (KeyError, TypeError, ValueError):
            continue
        if not 1.0 <= abs(spread) <= 4.5:
            continue
        home_favorite = spread < 0
        favorite_margin = margin if home_favorite else -margin
        ats_margin = margin + spread
        favorite_ats_margin = ats_margin if home_favorite else -ats_margin
        selected.append((favorite_margin, favorite_ats_margin))

    su_wins = sum(margin > 0.01 for margin, _ in selected)
    su_losses = sum(margin < -0.01 for margin, _ in selected)
    su_ties = len(selected) - su_wins - su_losses
    ats_wins = sum(margin > 0.01 for _, margin in selected)
    ats_losses = sum(margin < -0.01 for _, margin in selected)
    ats_pushes = len(selected) - ats_wins - ats_losses
    su_decisions = su_wins + su_losses
    ats_decisions = ats_wins + ats_losses
    return {
        "definition": "Market favorites priced from -1 through -4.5 points",
        "games": len(selected),
        "su_record": f"{su_wins}-{su_losses}-{su_ties}",
        "su_win_rate": round(100 * su_wins / su_decisions, 3) if su_decisions else None,
        "ats_record": f"{ats_wins}-{ats_losses}-{ats_pushes}",
        "ats_cover_rate": round(100 * ats_wins / ats_decisions, 3) if ats_decisions else None,
        "note": "Descriptive market behavior only. This is not a THI signal and moneyline ROI cannot be calculated without historical prices.",
    }

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
        "short_favorites": short_favorite_summary(rows),
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


def prior_season_rankings(history_dir: Path, seasons: set[int]) -> dict[int, dict[str, int]]:
    """Load only ratings that were available before each evaluated season began."""
    rankings: dict[int, dict[str, int]] = {}
    for season in sorted(seasons):
        path = history_dir / f"season_{season - 1}.json.gz"
        if not path.exists():
            rankings[season] = {}
            continue
        with gzip.open(path, "rt") as handle:
            payload = json.load(handle)
        rankings[season] = {
            str(team["team_id"]): int(team["adjusted_net_rank"])
            for team in payload.get("season_end_teams", [])
            if team.get("team_id") is not None and team.get("adjusted_net_rank") is not None
        }
    return rankings


def cbb_quality_sensitivity(rows: list[dict], history_dir: Path) -> dict:
    """Test whether excluding weaker teams improves the predeclared >5-point tier."""
    rankings = prior_season_rankings(history_dir, {int(row["season"]) for row in rows})
    edge = lambda row: abs(float(row["projected_home_margin"]) + float(row["market_home_spread"]))

    def prior_rank(row: dict, side: str) -> int | None:
        return rankings.get(int(row["season"]), {}).get(str(row.get(f"{side}_team_id")))

    def cohort(max_rank: int) -> list[dict]:
        selected = []
        for row in rows:
            home_rank = prior_rank(row, "home")
            away_rank = prior_rank(row, "away")
            if home_rank is not None and away_rank is not None and max(home_rank, away_rank) <= max_rank:
                selected.append(row)
        return selected

    comparisons = []
    for max_rank in (300, 200, 100):
        selected = cohort(max_rank)
        overall = summarize(selected, lambda row: edge(row) > 5, cbb_result)
        yearly = [
            {
                "season": season,
                **summarize(
                    [row for row in selected if int(row["season"]) == season],
                    lambda row: edge(row) > 5,
                    cbb_result,
                ),
            }
            for season in (2025, 2026)
        ]
        comparisons.append({
            "cohort": f"Both teams prior-season top {max_rank}",
            "maximum_prior_season_rank": max_rank,
            "eligible_market_games": len(selected),
            "actionable_over_5": overall,
            "yearly": yearly,
        })
    return {
        "status": "filter_rejected",
        "definition": (
            "A team is excluded when its prior-season adjusted-net rank is below the cohort cutoff "
            "or it has no prior-season rating. Same-season final ratings are never used."
        ),
        "primary_cutoff": 300,
        "comparisons": comparisons,
        "interpretation": (
            "The predeclared top-300 sensitivity performs worse than the full Division-I sample. "
            "Narrower cutoffs are exploratory, fail corrected significance, and are unstable by season, "
            "so team-quality exclusion is not adopted as a selection rule."
        ),
    }


def cbb_scorecard(predictions_path: Path, card_path: Path, history_dir: Path | None = None) -> dict:
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
    quality_sensitivity = cbb_quality_sensitivity(rows, history_dir or ROOT / "data/cbb/history")
    holm_adjust([
        actionable,
        *buckets,
        *(comparison["actionable_over_5"] for comparison in quality_sensitivity["comparisons"]),
    ])
    return {
        "status": "not_validated", "verdict": "Research model did not validate", "seasons": [2025, 2026],
        "model": "THI CBB walk-forward v0.6 selected research model",
        "market": "Archived closing-spread field; two-sided prices are unavailable",
        "price_assumption": PRICE,
        "selection_policy": "All five predeclared signal tiers, the combined >5-point group and three team-quality sensitivity cohorts are shown and corrected as one nine-test family.",
        "validation_note": "The combined >5-point sample is positive at a hypothetical flat -110 price, but it does not clear the corrected significance test and the market has lower margin error in both held-out seasons.",
        "actionable_over_5": actionable, "yearly": yearly, "buckets": buckets, "market_accuracy": accuracy,
        "short_favorites": short_favorite_summary(rows),
        "data_integrity": {"source_rows": len(rows), "duplicate_game_keys": len(identities) - len(set(identities))},
        "robustness": {
            "without_outlier_tier": summarize(rows, lambda row: 5 < edge(row) <= 10, cbb_result),
            "interpretation": "Removing >10-point outliers tests whether the result depends on the largest model disagreements; the displayed result remains descriptive until prospective validation clears every gate.",
        },
        "team_quality_sensitivity": quality_sensitivity,
    }


def main() -> None:
    output = ROOT / "data/reports/public_backtest_scorecard.json"
    payload = {
        "meta": {
            "version": "thi-public-backtest-v2.1",
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "audit_standard": "Exact one-sided binomial test against the 52.381% break-even rate implied by a hypothetical flat -110 price; Holm correction across each sport's complete displayed comparison family; 95% Wilson hit-rate intervals; season, outlier and CBB team-quality sensitivity checks.",
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
