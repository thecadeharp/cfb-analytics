"""Shared, non-UI matchup-segment tracking for CFB and CBB ledgers."""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from typing import Any, Iterable


VERSION = "thi-matchup-segments-v1-2026-11-25"
CONFERENCE_TEAM_VERSION = "thi-conference-team-tracking-v1-2026-11-25"
CFB_P4 = {"ACC", "BIG TEN", "BIG 12", "SEC"}
CFB_G6 = {"AAC", "CUSA", "MAC", "MOUNTAIN WEST", "PAC-12", "SUN BELT"}
CBB_P5 = {"ACC", "BIG TEN", "BIG 12", "SEC", "BIG EAST"}


def normalize_conference(value: Any) -> str:
    text = str(value or "").strip().upper()
    aliases = {
        "AMERICAN": "AAC",
        "AMERICAN ATHLETIC": "AAC",
        "AMERICAN ATHLETIC CONFERENCE": "AAC",
        "AM. EAST": "AMERICA EAST",
        "ATLANTIC 10": "A-10",
        "A10": "A-10",
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
        "METRO": "MAAC",
        "METRO ATLANTIC ATHLETIC CONFERENCE": "MAAC",
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


def summarize_forecasts(
    rows: Iterable[dict[str, Any]],
    *,
    margin_error_key: str,
    margin_bias_key: str,
    total_error_key: str,
    total_bias_key: str,
) -> dict[str, Any]:
    materialized = list(rows)
    margin_errors = [_number(row.get(margin_error_key)) for row in materialized]
    margin_errors = [value for value in margin_errors if value is not None]
    margin_biases = [_number(row.get(margin_bias_key)) for row in materialized]
    margin_biases = [value for value in margin_biases if value is not None]
    total_errors = [_number(row.get(total_error_key)) for row in materialized]
    total_errors = [value for value in total_errors if value is not None]
    total_biases = [_number(row.get(total_bias_key)) for row in materialized]
    total_biases = [value for value in total_biases if value is not None]
    return {
        "games": len(materialized),
        "margin_mae": round(sum(abs(value) for value in margin_errors) / len(margin_errors), 3) if margin_errors else None,
        "margin_signed_bias": round(sum(margin_biases) / len(margin_biases), 3) if margin_biases else None,
        "margin_n": len(margin_errors),
        "total_mae": round(sum(abs(value) for value in total_errors) / len(total_errors), 3) if total_errors else None,
        "total_signed_bias": round(sum(total_biases) / len(total_biases), 3) if total_biases else None,
        "total_n": len(total_errors),
        "sample_warning": "n_below_100" if len(materialized) < 100 else None,
    }


def _conference(row: dict[str, Any], side: str) -> str:
    return normalize_conference(row.get(f"{side}_conference"))


def _team(row: dict[str, Any], side: str) -> str:
    return str(row.get(f"{side}_team") or "").strip()


def _pick_team(row: dict[str, Any]) -> str:
    return str(row.get("pick_team") or row.get("preferred_side") or "").strip()


def _involves_conference(row: dict[str, Any], conference: str) -> bool:
    return conference in {_conference(row, "home"), _conference(row, "away")}


def _same_conference(row: dict[str, Any], conference: str) -> bool:
    return _conference(row, "home") == conference == _conference(row, "away")


def _pick_conference(row: dict[str, Any]) -> str:
    pick = _pick_team(row)
    if pick and pick == _team(row, "home"):
        return _conference(row, "home")
    if pick and pick == _team(row, "away"):
        return _conference(row, "away")
    return ""


def _period_market_summary(
    spread_rows: list[dict[str, Any]],
    total_rows: list[dict[str, Any]],
    *,
    spread_result_key: str,
    total_result_key: str,
    spread_clv_key: str,
    total_clv_key: str,
    spread_edge_key: str,
    total_edge_key: str,
) -> dict[str, Any]:
    return {
        "spreads": summarize_rows(
            spread_rows,
            result_key=spread_result_key,
            clv_key=spread_clv_key,
            edge_key=spread_edge_key,
        ),
        "totals": summarize_rows(
            total_rows,
            result_key=total_result_key,
            clv_key=total_clv_key,
            edge_key=total_edge_key,
        ),
    }


def build_conference_team_tracking(
    game_rows: Iterable[dict[str, Any]],
    spread_rows: Iterable[dict[str, Any]],
    total_rows: Iterable[dict[str, Any]],
    *,
    spread_result_key: str,
    total_result_key: str,
    spread_clv_key: str,
    total_clv_key: str,
    margin_error_key: str,
    margin_bias_key: str,
    total_error_key: str,
    total_bias_key: str,
    spread_edge_key: str = "model_edge",
    total_edge_key: str = "model_edge",
) -> dict[str, Any]:
    games = list(game_rows)
    spreads = list(spread_rows)
    totals = list(total_rows)
    all_rows = games + spreads + totals
    conferences = sorted({
        conference
        for row in all_rows
        for conference in (_conference(row, "home"), _conference(row, "away"))
        if conference
    })

    def forecast_summary(rows):
        return summarize_forecasts(
            rows,
            margin_error_key=margin_error_key,
            margin_bias_key=margin_bias_key,
            total_error_key=total_error_key,
            total_bias_key=total_bias_key,
        )

    def spread_summary(rows):
        return summarize_rows(rows, result_key=spread_result_key, clv_key=spread_clv_key, edge_key=spread_edge_key)

    def total_summary(rows):
        return summarize_rows(rows, result_key=total_result_key, clv_key=total_clv_key, edge_key=total_edge_key)

    conference_records: dict[str, Any] = {}
    for conference in conferences:
        conference_games = [row for row in games if _involves_conference(row, conference)]
        intra_games = [row for row in games if _same_conference(row, conference)]
        conference_perspective_games = []
        for row in conference_games:
            copy = dict(row)
            margin_bias = _number(row.get(margin_bias_key))
            home_conference = _conference(row, "home")
            away_conference = _conference(row, "away")
            if home_conference == away_conference == conference:
                copy[margin_bias_key] = None
            elif margin_bias is not None and away_conference == conference:
                copy[margin_bias_key] = -margin_bias
            conference_perspective_games.append(copy)
        intra_forecast_games = []
        for row in intra_games:
            copy = dict(row)
            copy[margin_bias_key] = None
            intra_forecast_games.append(copy)
        intra_spreads = [row for row in spreads if _same_conference(row, conference)]
        involving_spreads = [row for row in spreads if _involves_conference(row, conference)]
        favored_spreads = [row for row in involving_spreads if _pick_conference(row) == conference]
        opposed_spreads = [
            row for row in involving_spreads
            if _pick_conference(row) and _pick_conference(row) != conference
        ]
        intra_totals = [row for row in totals if _same_conference(row, conference)]
        involving_totals = [row for row in totals if _involves_conference(row, conference)]
        conference_records[conference] = {
            "forecasting_all_opponents": forecast_summary(conference_perspective_games),
            "forecasting_intra_conference": forecast_summary(intra_forecast_games),
            "intra_conference_spreads": spread_summary(intra_spreads),
            "intra_conference_spreads_2_5_plus": spread_summary([
                row for row in intra_spreads if (_number(row.get(spread_edge_key)) or 0) >= 2.5
            ]),
            "intra_conference_spreads_5_plus": spread_summary([
                row for row in intra_spreads if (_number(row.get(spread_edge_key)) or 0) >= 5.0
            ]),
            "intra_conference_totals": total_summary(intra_totals),
            "model_favored_conference_team": spread_summary(favored_spreads),
            "model_opposed_conference_team": spread_summary(opposed_spreads),
            "totals_involving_conference": total_summary(involving_totals),
        }

    teams = sorted({
        team
        for row in games
        for team in (_team(row, "home"), _team(row, "away"))
        if team
    })
    team_records: dict[str, Any] = {}
    for team in teams:
        team_games = [row for row in games if team in {_team(row, "home"), _team(row, "away")}]
        perspective_games = []
        conference_counts: Counter[str] = Counter()
        for row in team_games:
            home = team == _team(row, "home")
            conference = _conference(row, "home" if home else "away")
            if conference:
                conference_counts[conference] += 1
            copy = dict(row)
            margin_bias = _number(row.get(margin_bias_key))
            if margin_bias is not None and not home:
                copy[margin_bias_key] = -margin_bias
            perspective_games.append(copy)
        team_spreads = [row for row in spreads if team in {_team(row, "home"), _team(row, "away")}]
        team_totals = [row for row in totals if team in {_team(row, "home"), _team(row, "away")}]
        team_records[team] = {
            "conference_games": dict(sorted(conference_counts.items())),
            "forecasting": forecast_summary(perspective_games),
            "model_favored_team": spread_summary([row for row in team_spreads if _pick_team(row) == team]),
            "model_opposed_team": spread_summary([row for row in team_spreads if _pick_team(row) and _pick_team(row) != team]),
            "totals_involving_team": total_summary(team_totals),
        }

    return {
        "version": CONFERENCE_TEAM_VERSION,
        "visibility": "data_only_not_rendered_in_public_ui",
        "interpretation": {
            "forecasting": "Projection quality; lower MAE and bias nearer zero are better.",
            "model_favored": "ATS/CLV for the side THI preferred when that side belonged to the conference or team.",
            "model_opposed": "ATS/CLV for the THI-preferred opponent when THI opposed the conference or team.",
            "intra_conference": "Both teams belonged to the same frozen conference at game time.",
            "ranking_guardrail": "Do not rank raw hit rates without displaying n and the 95% interval; team samples are descriptive.",
        },
        "conference_count": len(conference_records),
        "team_count": len(team_records),
        "conferences": conference_records,
        "teams": team_records,
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
