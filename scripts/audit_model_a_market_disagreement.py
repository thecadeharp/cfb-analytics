#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

HISTORICAL = DATA / "training" / "historical_games.csv"
REPORT_DIR = DATA / "reports"
REPORT_JSON = REPORT_DIR / "model_a_market_disagreement_audit.json"
REPORT_TXT = REPORT_DIR / "model_a_market_disagreement_audit.txt"

FIRST_TEST_YEAR = 2022

WEIGHTS = {
    "net_epa": 0.30,
    "net_epa_pass": 0.15,
    "net_epa_rush": 0.15,
    "net_sr": 0.10,
    "def_havoc_created": 0.20,
    "off_havoc_allowed": 0.10,
}

EDGE_BUCKETS = [
    (0.0, 3.0, "0-3"),
    (3.0, 5.0, "3-5"),
    (5.0, 7.0, "5-7"),
    (7.0, 10.0, "7-10"),
    (10.0, float("inf"), "10+"),
]

FAVORITE_BUCKETS = [
    (0.0, 7.0, "0-7"),
    (7.0, 14.0, "7-14"),
    (14.0, 21.0, "14-21"),
    (21.0, 28.0, "21-28"),
    (28.0, 40.0, "28-40"),
    (40.0, float("inf"), "40+"),
]


def num(value):
    try:
        if value is None or value == "":
            return None
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def avg(values):
    vals = [float(v) for v in values if v is not None]
    return statistics.fmean(vals) if vals else None


def z_scores(values_by_team):
    clean = [v for v in values_by_team.values() if v is not None]

    if len(clean) < 2:
        return {team: 0.0 for team in values_by_team}

    mean = statistics.fmean(clean)
    std = statistics.pstdev(clean)

    if std == 0:
        return {team: 0.0 for team in values_by_team}

    return {
        team: ((value - mean) / std if value is not None else 0.0)
        for team, value in values_by_team.items()
    }


def snapshot_from_csv_row(row, side):
    off_epa = num(row.get(f"{side}_pregame_off_epa"))
    def_epa = num(row.get(f"{side}_pregame_def_epa_allowed"))
    off_pass = num(row.get(f"{side}_pregame_off_pass_epa"))
    def_pass = num(row.get(f"{side}_pregame_def_pass_epa_allowed"))
    off_rush = num(row.get(f"{side}_pregame_off_rush_epa"))
    def_rush = num(row.get(f"{side}_pregame_def_rush_epa_allowed"))
    off_sr = num(row.get(f"{side}_pregame_off_success_rate"))
    def_sr = num(row.get(f"{side}_pregame_def_success_allowed"))
    def_havoc = num(row.get(f"{side}_pregame_def_havoc_created_rate"))
    off_havoc_allowed = num(row.get(f"{side}_pregame_havoc_allowed_rate"))

    required = [
        off_epa, def_epa, off_pass, def_pass, off_rush, def_rush,
        off_sr, def_sr, def_havoc, off_havoc_allowed,
    ]

    if any(v is None for v in required):
        return None

    return {
        "net_epa": off_epa - def_epa,
        "net_epa_pass": off_pass - def_pass,
        "net_epa_rush": off_rush - def_rush,
        "net_sr": off_sr - def_sr,
        "def_havoc_created": def_havoc,
        "off_havoc_allowed": off_havoc_allowed,
    }


def load_base():
    games = []
    snapshots = defaultdict(dict)

    with HISTORICAL.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            year = num(row.get("season"))
            week = num(row.get("week"))
            actual_margin = num(row.get("actual_home_margin"))
            market_home_spread = num(row.get("market_home_spread"))
            home = row.get("home_team")
            away = row.get("away_team")

            if None in (year, week, actual_margin) or not home or not away:
                continue

            year = int(year)
            week = int(week)

            home_snapshot = snapshot_from_csv_row(row, "home")
            away_snapshot = snapshot_from_csv_row(row, "away")

            if home_snapshot is not None:
                snapshots[(year, week)][home] = home_snapshot
            if away_snapshot is not None:
                snapshots[(year, week)][away] = away_snapshot

            games.append({
                "game_id": row.get("game_id"),
                "year": year,
                "week": week,
                "home": home,
                "away": away,
                "actual_home_margin": actual_margin,
                "market_home_spread": market_home_spread,
            })

    return games, snapshots


def build_week_ratings(snapshot_map):
    if len(snapshot_map) < 20:
        return {}

    component_z = {}

    for component in WEIGHTS:
        component_z[component] = z_scores({
            team: snapshot.get(component)
            for team, snapshot in snapshot_map.items()
        })

    ratings = {}

    for team in snapshot_map:
        rating = 0.0

        for component, weight in WEIGHTS.items():
            z = component_z[component].get(team, 0.0)

            if component == "off_havoc_allowed":
                z *= -1.0

            rating += z * weight

        ratings[team] = rating

    return ratings


def build_records():
    games, snapshots = load_base()

    weekly_ratings = {
        key: build_week_ratings(value)
        for key, value in snapshots.items()
    }

    records = []

    for game in games:
        ratings = weekly_ratings.get((game["year"], game["week"]), {})
        home_rating = ratings.get(game["home"])
        away_rating = ratings.get(game["away"])

        if home_rating is None or away_rating is None:
            continue

        records.append({
            **game,
            "rating_diff": home_rating - away_rating,
        })

    return records


def fit_model(records):
    if len(records) < 100:
        raise RuntimeError("Insufficient historical records for calibration.")

    sum_xx = sum_xh = sum_hh = sum_xy = sum_hy = 0.0

    # historical_training_v4 does not retain neutral-site status.
    # Use the same fitted global home intercept as the previous offline audits.
    for record in records:
        x = record["rating_diff"]
        h = 1.0
        y = record["actual_home_margin"]

        sum_xx += x * x
        sum_xh += x * h
        sum_hh += h * h
        sum_xy += x * y
        sum_hy += h * y

    determinant = sum_xx * sum_hh - sum_xh * sum_xh

    if abs(determinant) < 1e-12:
        raise RuntimeError("Historical calibration matrix is singular.")

    scale = (sum_xy * sum_hh - sum_hy * sum_xh) / determinant
    hfa = (sum_hy * sum_xx - sum_xy * sum_xh) / determinant

    return {"scale": scale, "hfa": hfa}


def ats_result(actual_home_margin, market_home_spread, model_edge):
    home_cover_margin = actual_home_margin + market_home_spread

    if abs(model_edge) < 1e-12:
        return "no_edge"

    if model_edge > 0:
        cover_margin = home_cover_margin
    else:
        cover_margin = -home_cover_margin

    if cover_margin > 0:
        return "win"
    if cover_margin < 0:
        return "loss"
    return "push"


def score_oos(records):
    years = sorted({r["year"] for r in records})
    scored = []

    for test_year in years:
        if test_year < FIRST_TEST_YEAR:
            continue

        training = [r for r in records if r["year"] < test_year]
        testing = [r for r in records if r["year"] == test_year]

        if len(training) < 100 or len(testing) < 25:
            continue

        model = fit_model(training)

        for record in testing:
            market_spread = record.get("market_home_spread")

            if market_spread is None:
                continue

            projected_home_margin = (
                model["scale"] * record["rating_diff"] + model["hfa"]
            )
            market_expected_home_margin = -market_spread
            actual_home_margin = record["actual_home_margin"]

            model_edge = projected_home_margin - market_expected_home_margin
            absolute_edge = abs(model_edge)

            market_favorite_size = abs(market_spread)

            if market_spread < 0:
                market_favorite = "home"
                market_dog = "away"
            elif market_spread > 0:
                market_favorite = "away"
                market_dog = "home"
            else:
                market_favorite = "pickem"
                market_dog = "pickem"

            if model_edge > 0:
                model_side = "home"
            elif model_edge < 0:
                model_side = "away"
            else:
                model_side = "none"

            model_takes_dog = model_side == market_dog and market_dog != "pickem"
            model_takes_favorite = (
                model_side == market_favorite and market_favorite != "pickem"
            )

            model_abs_error = abs(
                projected_home_margin - actual_home_margin
            )
            market_abs_error = abs(
                market_expected_home_margin - actual_home_margin
            )

            result = ats_result(
                actual_home_margin,
                market_spread,
                model_edge,
            )

            scored.append({
                **record,
                "oos_scale": model["scale"],
                "oos_hfa": model["hfa"],
                "projected_home_margin": projected_home_margin,
                "market_expected_home_margin": market_expected_home_margin,
                "model_edge": model_edge,
                "absolute_edge": absolute_edge,
                "market_favorite_size": market_favorite_size,
                "market_favorite": market_favorite,
                "model_side": model_side,
                "model_takes_dog": model_takes_dog,
                "model_takes_favorite": model_takes_favorite,
                "ats_result": result,
                "model_abs_error": model_abs_error,
                "market_abs_error": market_abs_error,
                "model_better_than_market_margin": model_abs_error < market_abs_error,
                "market_better_than_model_margin": market_abs_error < model_abs_error,
                "error_tie": abs(model_abs_error - market_abs_error) < 1e-12,
            })

    return scored


def summarize(rows):
    if not rows:
        return {"n": 0}

    wins = sum(r["ats_result"] == "win" for r in rows)
    losses = sum(r["ats_result"] == "loss" for r in rows)
    pushes = sum(r["ats_result"] == "push" for r in rows)
    decisions = wins + losses

    model_better = sum(r["model_better_than_market_margin"] for r in rows)
    market_better = sum(r["market_better_than_model_margin"] for r in rows)
    ties = sum(r["error_tie"] for r in rows)

    return {
        "n": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "ats_win_rate": round(wins / decisions * 100, 2) if decisions else None,
        "avg_absolute_edge": avg([r["absolute_edge"] for r in rows]),
        "avg_model_abs_margin_error": avg([r["model_abs_error"] for r in rows]),
        "avg_market_abs_margin_error": avg([r["market_abs_error"] for r in rows]),
        "model_better_margin_n": model_better,
        "market_better_margin_n": market_better,
        "error_ties_n": ties,
        "model_better_margin_pct": round(
            model_better / len(rows) * 100, 2
        ),
        "avg_market_favorite_size": avg(
            [r["market_favorite_size"] for r in rows]
        ),
    }


def edge_buckets(rows):
    output = {}

    for lo, hi, label in EDGE_BUCKETS:
        bucket = [
            r for r in rows
            if lo <= r["absolute_edge"] < hi
        ]
        output[label] = summarize(bucket)

    return output


def favorite_buckets(rows):
    output = {}

    for lo, hi, label in FAVORITE_BUCKETS:
        bucket = [
            r for r in rows
            if lo <= r["market_favorite_size"] < hi
        ]
        output[label] = summarize(bucket)

    return output


def dog_large_favorite_matrix(rows):
    output = {}

    for favorite_threshold in (14.0, 21.0, 28.0, 40.0):
        threshold_key = f"favorite_{favorite_threshold:g}_plus"

        subset = [
            r for r in rows
            if r["market_favorite_size"] >= favorite_threshold
            and r["model_takes_dog"]
        ]

        output[threshold_key] = {
            "all_edges": summarize(subset),
            "edge_5_plus": summarize(
                [r for r in subset if r["absolute_edge"] >= 5.0]
            ),
            "edge_7_plus": summarize(
                [r for r in subset if r["absolute_edge"] >= 7.0]
            ),
            "edge_10_plus": summarize(
                [r for r in subset if r["absolute_edge"] >= 10.0]
            ),
        }

    return output


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    records = build_records()
    scored = score_oos(records)

    if len(scored) < 2500:
        raise RuntimeError(
            f"Expected a large historical lined OOS sample; found only {len(scored)}."
        )

    dogs = [r for r in scored if r["model_takes_dog"]]
    favorites = [r for r in scored if r["model_takes_favorite"]]

    report = {
        "audit_version": "model-a-market-disagreement-audit-v1",
        "historical_source": str(HISTORICAL.relative_to(ROOT)),
        "historical_method": (
            "Rebuild the same six-component time-safe composite from prior-week "
            "historical_training_v4 pregame fields, calibrate rating->margin only "
            "on prior seasons, then compare OOS Model A margin to the stored market spread."
        ),
        "important_limitations": [
            (
                "Historical market_home_spread is evaluation-only. Its exact capture timing "
                "is not guaranteed to be the closing line."
            ),
            (
                "Neutral-site status is unavailable in historical_training_v4, so the "
                "offline OOS rebuild uses one fitted global home intercept."
            ),
            (
                "This audit evaluates historical disagreement behavior. It does not prove "
                "the current 2026 preseason prior layer is identical to historical in-season ratings."
            ),
        ],
        "sample": {
            "lined_oos_games": len(scored),
            "years": sorted({r["year"] for r in scored}),
        },
        "all_disagreements": {
            "overall": summarize(scored),
            "by_absolute_edge": edge_buckets(scored),
            "by_market_favorite_size": favorite_buckets(scored),
        },
        "model_takes_market_dog": {
            "overall": summarize(dogs),
            "by_absolute_edge": edge_buckets(dogs),
            "by_market_favorite_size": favorite_buckets(dogs),
            "large_favorite_matrix": dog_large_favorite_matrix(scored),
        },
        "model_takes_market_favorite": {
            "overall": summarize(favorites),
            "by_absolute_edge": edge_buckets(favorites),
            "by_market_favorite_size": favorite_buckets(favorites),
        },
        "production_untouched": True,
        "recommendation_rule": (
            "If large-favorite dog disagreements are historically poor, fix the Signal/"
            "confidence layer first rather than forcing the fair line toward market. "
            "If they are historically strong, retain fair-line independence and continue "
            "prospective CLV tracking."
        ),
    }

    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "MODEL A HISTORICAL MARKET DISAGREEMENT AUDIT",
        "=" * 52,
        "",
        f"OOS lined games: {len(scored)}",
        "",
        "ALL DISAGREEMENTS — EDGE BUCKETS",
    ]

    for _, _, label in EDGE_BUCKETS:
        lines.append(
            f"{label}: {report['all_disagreements']['by_absolute_edge'][label]}"
        )

    lines += [
        "",
        "MODEL TAKES MARKET DOG — EDGE BUCKETS",
    ]

    for _, _, label in EDGE_BUCKETS:
        lines.append(
            f"{label}: {report['model_takes_market_dog']['by_absolute_edge'][label]}"
        )

    lines += [
        "",
        "MODEL TAKES MARKET DOG — FAVORITE SIZE BUCKETS",
    ]

    for _, _, label in FAVORITE_BUCKETS:
        lines.append(
            f"{label}: {report['model_takes_market_dog']['by_market_favorite_size'][label]}"
        )

    lines += [
        "",
        "LARGE-FAVORITE DOG DISAGREEMENT MATRIX",
    ]

    for key, value in report[
        "model_takes_market_dog"
    ]["large_favorite_matrix"].items():
        lines.append(f"{key}: {value}")

    lines += [
        "",
        "MODEL TAKES MARKET FAVORITE — EDGE BUCKETS",
    ]

    for _, _, label in EDGE_BUCKETS:
        lines.append(
            f"{label}: {report['model_takes_market_favorite']['by_absolute_edge'][label]}"
        )

    lines += [
        "",
        "PRODUCTION STATUS",
        "Model A untouched.",
        "Current 2026 projections untouched.",
        "Website untouched.",
        "Only audit report files were written.",
    ]

    REPORT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
