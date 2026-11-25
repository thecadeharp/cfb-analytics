"""Shared, non-UI matchup-segment tracking for CFB and CBB ledgers."""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from typing import Any, Iterable


VERSION = "thi-matchup-segments-v1-2026-11-25"
CFB_P4 = {"ACC", "BIG TEN", "BIG 12", "SEC"}
CFB_G6 = {"AAC", "CUSA", "MAC", "MOUNTAIN WEST", "PAC-12", "SUN BELT"}
CBB_P5 = {"ACC", "BIG TEN", "BIG 12", "SEC", "BIG EAST"}


def normalize_conference(value: Any) -> str:
    text = str(value or "").strip().upper()
    aliases = {
        "AMERICAN": "AAC",
        "AMERICAN ATHLETIC": "AAC",
        "AMERICAN ATHLETIC CONFERENCE": "AAC",
        "ATLANTIC COAST CONFERENCE": "ACC",
        "BIG TEN CONFERENCE": "BIG TEN",
        "B1G": "BIG TEN",
        "BIG 12 CONFERENCE": "BIG 12",
        "B12": "BIG 12",
        "BIG EAST CONFERENCE": "BIG EAST",
        "CONFERENCE USA": "CUSA",
        "C-USA": "CUSA",
        "MID-AMERICAN": "MAC",
        "MID-AMERICAN CONFERENCE": "MAC",
        "MOUNTAIN WEST CONFERENCE": "MOUNTAIN WEST",
        "MWC": "MOUNTAIN WEST",
        "PAC 12": "PAC-12",
        "PAC-12 CONFERENCE": "PAC-12",
        "SOUTHEASTERN CONFERENCE": "SEC",
        "SUN BELT CONFERENCE": "SUN BELT",
        "SBC": "SUN BELT",
    }
    return aliases.get(text, text)


def classify_cfb(home_conference: Any, away_conference: Any) -> str:
    home = normalize_conference(home_conference)
    away = normalize_conference(away_conference)
    if not home or not away:
        return "unclassified"
    if home in CFB_P4 and away in CFB_P4:
        return "p4_vs_p4"
    if home in CFB_G6 and away in CFB_G6:
        return "g6_vs_g6"
    return "cross_tier_or_other"


def classify_cbb(home_conference: Any, away_conference: Any) -> str:
    home = normalize_conference(home_conference)
    away = normalize_conference(away_conference)
    if not home or not away:
        return "unclassified"
    if home in CBB_P5 and away in CBB_P5:
        return "p5_vs_p5"
    if home not in CBB_P5 and away not in CBB_P5:
        return "mid_major_vs_mid_major"
    return "mixed_tier"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _outcome(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"w", "win"}:
        return "win"
    if text in {"l", "loss"}:
        return "loss"
    if text in {"p", "push"}:
        return "push"
    return None


def _wilson(wins: int, losses: int) -> dict[str, float] | None:
    n = wins + losses
    if not n:
        return None
    z = 1.96
    p = wins / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    return {
        "low": round(100 * max(0.0, center - margin), 2),
        "high": round(100 * min(1.0, center + margin), 2),
        "method": "wilson_95",
    }


def summarize_rows(
    rows: Iterable[dict[str, Any]],
    *,
    result_key: str,
    clv_key: str,
    edge_key: str,
) -> dict[str, Any]:
    materialized = list(rows)
    outcomes = [_outcome(row.get(result_key)) for row in materialized]
    wins = outcomes.count("win")
    losses = outcomes.count("loss")
    pushes = outcomes.count("push")
    decisions = wins + losses
    clv = [_number(row.get(clv_key)) for row in materialized]
    clv = [value for value in clv if value is not None]
    edges = [_number(row.get(edge_key)) for row in materialized]
    edges = [value for value in edges if value is not None]
    return {
        "games": wins + losses + pushes,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate": round(100 * wins / decisions, 2) if decisions else None,
        "hit_rate_ci_95": _wilson(wins, losses),
        "average_clv": round(sum(clv) / len(clv), 3) if clv else None,
        "beat_close_pct": round(100 * sum(value > 0 for value in clv) / len(clv), 2) if clv else None,
        "clv_games": len(clv),
        "average_model_edge": round(sum(edges) / len(edges), 3) if edges else None,
        "sample_warning": "n_below_100" if decisions < 100 else None,
    }


def _period(row: dict[str, Any], field: str) -> str | None:
    value = row.get(field)
    if value not in (None, ""):
        return str(value)
    if field == "calendar_month_et":
        try:
            return datetime.fromisoformat(str(row.get("start_date") or "").replace("Z", "+00:00")).strftime("%Y-%m")
        except ValueError:
            return None
    return None


def build_segment_tracking(
    spread_rows: Iterable[dict[str, Any]],
    total_rows: Iterable[dict[str, Any]],
    *,
    included_segments: Iterable[str],
    spread_result_key: str,
    total_result_key: str,
    spread_clv_key: str,
    total_clv_key: str,
    spread_edge_key: str = "model_edge",
    total_edge_key: str = "model_edge",
) -> dict[str, Any]:
    spreads = list(spread_rows)
    totals = list(total_rows)
    segments: dict[str, Any] = {}
    for segment in included_segments:
        segment_spreads = [row for row in spreads if row.get("matchup_segment") == segment]
        segment_totals = [row for row in totals if row.get("matchup_segment") == segment]

        def spread_summary(rows):
            return summarize_rows(rows, result_key=spread_result_key, clv_key=spread_clv_key, edge_key=spread_edge_key)

        def total_summary(rows):
            return summarize_rows(rows, result_key=total_result_key, clv_key=total_clv_key, edge_key=total_edge_key)

        weeks = sorted({str(row.get("week")) for row in segment_spreads + segment_totals if row.get("week") is not None}, key=lambda value: int(value))
        months = sorted({month for row in segment_spreads + segment_totals if (month := _period(row, "calendar_month_et"))})
        segments[segment] = {
            "all_spreads": spread_summary(segment_spreads),
            "spread_disagreements_2_5_plus": spread_summary([
                row for row in segment_spreads if (_number(row.get(spread_edge_key)) or 0) >= 2.5
            ]),
            "spread_disagreements_5_plus": spread_summary([
                row for row in segment_spreads if (_number(row.get(spread_edge_key)) or 0) >= 5.0
            ]),
            "tracked_totals_4_plus": total_summary(segment_totals),
            "by_week": {
                week: {
                    "all_spreads": spread_summary([row for row in segment_spreads if str(row.get("week")) == week]),
                    "spread_disagreements_2_5_plus": spread_summary([
                        row for row in segment_spreads if str(row.get("week")) == week and (_number(row.get(spread_edge_key)) or 0) >= 2.5
                    ]),
                    "tracked_totals_4_plus": total_summary([row for row in segment_totals if str(row.get("week")) == week]),
                }
                for week in weeks
            },
            "by_month": {
                month: {
                    "all_spreads": spread_summary([row for row in segment_spreads if _period(row, "calendar_month_et") == month]),
                    "spread_disagreements_2_5_plus": spread_summary([
                        row for row in segment_spreads if _period(row, "calendar_month_et") == month and (_number(row.get(spread_edge_key)) or 0) >= 2.5
                    ]),
                    "tracked_totals_4_plus": total_summary([row for row in segment_totals if _period(row, "calendar_month_et") == month]),
                }
                for month in months
            },
        }

    return {
        "version": VERSION,
        "visibility": "data_only_not_rendered_in_public_ui",
        "classification_counts": dict(sorted(Counter(
            str(row.get("matchup_segment") or "unclassified") for row in spreads
        ).items())),
        "segments": segments,
    }
