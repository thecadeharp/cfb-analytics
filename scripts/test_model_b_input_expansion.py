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
REPORT_JSON = REPORT_DIR / "model_b_input_expansion_challenger.json"
REPORT_TXT = REPORT_DIR / "model_b_input_expansion_challenger.txt"

FIRST_TEST_YEAR = 2022

WEIGHTS = {
    "net_epa": 0.30,
    "net_epa_pass": 0.15,
    "net_epa_rush": 0.15,
    "net_sr": 0.10,
    "def_havoc_created": 0.20,
    "off_havoc_allowed": 0.10,
}

MARKET_BUCKETS = [
    (0.0, 7.0, "0-7"),
    (7.0, 14.0, "7-14"),
    (14.0, 21.0, "14-21"),
    (21.0, 28.0, "21-28"),
    (28.0, 40.0, "28-40"),
    (40.0, float("inf"), "40+"),
]

# Candidate strength is chosen from training data only.
# Thresholds are DATA-DERIVED training quantiles.
EXPANSION_GAMMAS = [0.10, 0.20, 0.30, 0.40, 0.50, 0.65, 0.80, 1.00]
THRESHOLD_QUANTILES = [0.60, 0.70, 0.80, 0.90]


def num(value):
    try:
        if value is None or value == "":
            return None
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def mean(values):
    vals = [float(v) for v in values if v is not None]
    return statistics.fmean(vals) if vals else None


def mae(predictions, actuals):
    if not predictions:
        return None
    return statistics.fmean(abs(p - a) for p, a in zip(predictions, actuals))


def rmse(predictions, actuals):
    if not predictions:
        return None
    return math.sqrt(
        statistics.fmean((p - a) ** 2 for p, a in zip(predictions, actuals))
    )


def quantile(values, q):
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    position = (len(vals) - 1) * q
    lo = int(math.floor(position))
    hi = int(math.ceil(position))
    if lo == hi:
        return vals[lo]
    weight = position - lo
    return vals[lo] * (1 - weight) + vals[hi] * weight


def z_scores(values_by_team):
    clean = [v for v in values_by_team.values() if v is not None]
    if len(clean) < 2:
        return {team: 0.0 for team in values_by_team}

    avg = statistics.fmean(clean)
    std = statistics.pstdev(clean)
    if std == 0:
        return {team: 0.0 for team in values_by_team}

    return {
        team: ((value - avg) / std if value is not None else 0.0)
        for team, value in values_by_team.items()
    }


def snapshot_from_csv_row(row, side):
    fields = {
        "off_epa": num(row.get(f"{side}_pregame_off_epa")),
        "def_epa": num(row.get(f"{side}_pregame_def_epa_allowed")),
        "off_pass": num(row.get(f"{side}_pregame_off_pass_epa")),
        "def_pass": num(row.get(f"{side}_pregame_def_pass_epa_allowed")),
        "off_rush": num(row.get(f"{side}_pregame_off_rush_epa")),
        "def_rush": num(row.get(f"{side}_pregame_def_rush_epa_allowed")),
        "off_sr": num(row.get(f"{side}_pregame_off_success_rate")),
        "def_sr": num(row.get(f"{side}_pregame_def_success_allowed")),
        "def_havoc": num(row.get(f"{side}_pregame_def_havoc_created_rate")),
        "off_havoc_allowed": num(row.get(f"{side}_pregame_havoc_allowed_rate")),
    }

    if any(v is None for v in fields.values()):
        return None

    return {
        "net_epa": fields["off_epa"] - fields["def_epa"],
        "net_epa_pass": fields["off_pass"] - fields["def_pass"],
        "net_epa_rush": fields["off_rush"] - fields["def_rush"],
        "net_sr": fields["off_sr"] - fields["def_sr"],
        "def_havoc_created": fields["def_havoc"],
        "off_havoc_allowed": fields["off_havoc_allowed"],
    }


def load_base():
    games = []
    snapshots = defaultdict(dict)

    with HISTORICAL.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            year = num(row.get("season"))
            week = num(row.get("week"))
            actual = num(row.get("actual_home_margin"))
            market = num(row.get("market_home_spread"))
            home = row.get("home_team")
            away = row.get("away_team")

            if None in (year, week, actual) or not home or not away:
                continue

            year = int(year)
            week = int(week)

            hs = snapshot_from_csv_row(row, "home")
            aw = snapshot_from_csv_row(row, "away")

            if hs is not None:
                snapshots[(year, week)][home] = hs
            if aw is not None:
                snapshots[(year, week)][away] = aw

            games.append({
                "game_id": row.get("game_id"),
                "year": year,
                "week": week,
                "home": home,
                "away": away,
                "actual_home_margin": actual,
                "market_home_spread": market,
            })

    return games, snapshots


def build_week_ratings(snapshot_map):
    if len(snapshot_map) < 20:
        return {}

    component_z = {}
    for component in WEIGHTS:
        component_z[component] = z_scores({
            team: snap.get(component)
            for team, snap in snapshot_map.items()
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


def transform_rating_diff(x, threshold=None, gamma=0.0):
    if threshold is None or gamma == 0.0:
        return x

    sign = 1.0 if x >= 0 else -1.0
    ax = abs(x)

    if ax <= threshold:
        return x

    expanded = threshold + (ax - threshold) * (1.0 + gamma)
    return sign * expanded


def fit_linear(records, threshold=None, gamma=0.0):
    if len(records) < 100:
        raise RuntimeError("Insufficient records for fit.")

    sum_xx = sum_xh = sum_hh = sum_xy = sum_hy = 0.0

    # historical_training_v4 does not preserve neutral-site status,
    # so this offline challenger uses a single fitted home intercept.
    for record in records:
        x = transform_rating_diff(record["rating_diff"], threshold, gamma)
        h = 1.0
        y = record["actual_home_margin"]

        sum_xx += x * x
        sum_xh += x * h
        sum_hh += h * h
        sum_xy += x * y
        sum_hy += h * y

    determinant = sum_xx * sum_hh - sum_xh * sum_xh
    if abs(determinant) < 1e-12:
        raise RuntimeError("Singular calibration matrix.")

    scale = (sum_xy * sum_hh - sum_hy * sum_xh) / determinant
    hfa = (sum_hy * sum_xx - sum_xy * sum_xh) / determinant

    return {
        "scale": scale,
        "hfa": hfa,
        "threshold": threshold,
        "gamma": gamma,
    }


def predict(record, model):
    x = transform_rating_diff(
        record["rating_diff"],
        model.get("threshold"),
        model.get("gamma", 0.0),
    )
    return model["scale"] * x + model["hfa"]


def score_model(records, model):
    predictions = [predict(r, model) for r in records]
    actuals = [r["actual_home_margin"] for r in records]
    return {
        "n": len(records),
        "mae": mae(predictions, actuals),
        "rmse": rmse(predictions, actuals),
    }


def market_favorite_size(record):
    spread = record.get("market_home_spread")
    if spread is None:
        return None
    return abs(spread)


def bucket_scores(records, model):
    output = {}
    for lo, hi, label in MARKET_BUCKETS:
        bucket = [
            r for r in records
            if r.get("market_home_spread") is not None
            and lo <= market_favorite_size(r) < hi
        ]
        output[label] = score_model(bucket, model) if bucket else {"n": 0}
    return output


def near_pk_score(records, model):
    bucket = [
        r for r in records
        if r.get("market_home_spread") is not None
        and abs(r["market_home_spread"]) <= 3.0
    ]
    return score_model(bucket, model) if bucket else {"n": 0}


def candidate_thresholds(training_records):
    magnitudes = [abs(r["rating_diff"]) for r in training_records]
    values = []
    for q in THRESHOLD_QUANTILES:
        threshold = quantile(magnitudes, q)
        if threshold is not None:
            values.append((q, threshold))
    return values


def choose_challenger(train_records, validation_records):
    baseline = fit_linear(train_records)
    baseline_score = score_model(validation_records, baseline)

    candidates = []

    for q, threshold in candidate_thresholds(train_records):
        for gamma in EXPANSION_GAMMAS:
            model = fit_linear(train_records, threshold=threshold, gamma=gamma)
            score = score_model(validation_records, model)

            candidates.append({
                "quantile": q,
                "threshold": threshold,
                "gamma": gamma,
                "validation_mae": score["mae"],
                "validation_rmse": score["rmse"],
                "mae_improvement_vs_baseline": (
                    baseline_score["mae"] - score["mae"]
                ),
                "rmse_improvement_vs_baseline": (
                    baseline_score["rmse"] - score["rmse"]
                ),
            })

    # Selection is based strictly on validation RMSE, with MAE as tie-breaker.
    candidates.sort(
        key=lambda c: (
            c["validation_rmse"],
            c["validation_mae"],
            c["threshold"],
            c["gamma"],
        )
    )

    winner = candidates[0] if candidates else None

    return {
        "baseline_validation": baseline_score,
        "winner": winner,
        "all_candidates": candidates,
    }


def run_nested_oos(records):
    years = sorted({r["year"] for r in records})
    folds = []

    all_a = []
    all_b = []

    for test_year in years:
        if test_year < FIRST_TEST_YEAR:
            continue

        validation_year = test_year - 1
        train_years = [y for y in years if y < validation_year]

        train_records = [r for r in records if r["year"] in train_years]
        validation_records = [r for r in records if r["year"] == validation_year]
        test_records = [r for r in records if r["year"] == test_year]

        if (
            len(train_records) < 100
            or len(validation_records) < 25
            or len(test_records) < 25
        ):
            continue

        selection = choose_challenger(train_records, validation_records)
        winner = selection["winner"]

        if winner is None:
            continue

        # Refit both A and selected B on ALL information available before test year.
        refit_records = [r for r in records if r["year"] < test_year]

        model_a = fit_linear(refit_records)
        model_b = fit_linear(
            refit_records,
            threshold=winner["threshold"],
            gamma=winner["gamma"],
        )

        fold_a = score_model(test_records, model_a)
        fold_b = score_model(test_records, model_b)

        lined = [r for r in test_records if r.get("market_home_spread") is not None]

        fold = {
            "test_year": test_year,
            "train_years_for_selection": train_years,
            "validation_year": validation_year,
            "refit_years": sorted({r["year"] for r in refit_records}),
            "selected_threshold_quantile": winner["quantile"],
            "selected_threshold": winner["threshold"],
            "selected_gamma": winner["gamma"],
            "model_a": {
                **fold_a,
                "scale": model_a["scale"],
                "hfa": model_a["hfa"],
                "market_buckets": bucket_scores(lined, model_a),
                "near_pk": near_pk_score(lined, model_a),
            },
            "model_b": {
                **fold_b,
                "scale": model_b["scale"],
                "hfa": model_b["hfa"],
                "market_buckets": bucket_scores(lined, model_b),
                "near_pk": near_pk_score(lined, model_b),
            },
            "selection_validation": {
                "baseline": selection["baseline_validation"],
                "winner": winner,
            },
        }

        folds.append(fold)

        for record in test_records:
            all_a.append((record, predict(record, model_a)))
            all_b.append((record, predict(record, model_b)))

    return folds, all_a, all_b


def aggregate_scored(scored):
    records = [r for r, _ in scored]
    predictions = [p for _, p in scored]
    actuals = [r["actual_home_margin"] for r in records]

    overall = {
        "n": len(records),
        "mae": mae(predictions, actuals),
        "rmse": rmse(predictions, actuals),
    }

    market_bucket_results = {}
    for lo, hi, label in MARKET_BUCKETS:
        pairs = [
            (r, p)
            for r, p in scored
            if r.get("market_home_spread") is not None
            and lo <= abs(r["market_home_spread"]) < hi
        ]

        if not pairs:
            market_bucket_results[label] = {"n": 0}
            continue

        preds = [p for _, p in pairs]
        acts = [r["actual_home_margin"] for r, _ in pairs]

        market_bucket_results[label] = {
            "n": len(pairs),
            "mae": mae(preds, acts),
            "rmse": rmse(preds, acts),
            "mean_signed_error_model_minus_actual": mean(
                [p - a for p, a in zip(preds, acts)]
            ),
        }

    near_pk_pairs = [
        (r, p)
        for r, p in scored
        if r.get("market_home_spread") is not None
        and abs(r["market_home_spread"]) <= 3.0
    ]

    if near_pk_pairs:
        near_pk_preds = [p for _, p in near_pk_pairs]
        near_pk_actuals = [r["actual_home_margin"] for r, _ in near_pk_pairs]
        near_pk = {
            "n": len(near_pk_pairs),
            "mae": mae(near_pk_preds, near_pk_actuals),
            "rmse": rmse(near_pk_preds, near_pk_actuals),
        }
    else:
        near_pk = {"n": 0}

    return {
        "overall": overall,
        "market_buckets": market_bucket_results,
        "near_pk_market_3_or_less": near_pk,
    }


def promotion_decision(summary_a, summary_b):
    reasons = []

    overall_mae_better = (
        summary_b["overall"]["mae"] < summary_a["overall"]["mae"]
    )
    overall_rmse_better = (
        summary_b["overall"]["rmse"] < summary_a["overall"]["rmse"]
    )

    if not overall_mae_better:
        reasons.append("Model B did not improve overall MAE.")
    if not overall_rmse_better:
        reasons.append("Model B did not improve overall RMSE.")

    # Protect the small-spread middle. Predefined tolerance: <= 0.25 MAE degradation.
    small_ok = True
    for label in ("0-7", "7-14"):
        a = summary_a["market_buckets"][label]
        b = summary_b["market_buckets"][label]
        if a.get("n", 0) and b.get("n", 0):
            if b["mae"] > a["mae"] + 0.25:
                small_ok = False
                reasons.append(
                    f"Model B degraded {label} MAE by more than 0.25 points."
                )

    # Require improvement in aggregate 14+ favorite games.
    def collect_14_plus(summary):
        labels = ("14-21", "21-28", "28-40", "40+")
        n_total = sum(summary["market_buckets"][l].get("n", 0) for l in labels)
        return n_total

    large_n = collect_14_plus(summary_a)
    large_improvements = []

    for label in ("14-21", "21-28", "28-40", "40+"):
        a = summary_a["market_buckets"][label]
        b = summary_b["market_buckets"][label]
        if a.get("n", 0) >= 20 and b.get("n", 0) >= 20:
            large_improvements.append(b["mae"] < a["mae"])

    large_ok = bool(large_improvements) and sum(large_improvements) >= max(
        1, math.ceil(len(large_improvements) / 2)
    )

    if not large_ok:
        reasons.append(
            "Model B failed to improve MAE in at least half of adequately-sampled 14+ buckets."
        )

    near_a = summary_a["near_pk_market_3_or_less"]
    near_b = summary_b["near_pk_market_3_or_less"]
    near_pk_ok = True
    if near_a.get("n", 0) and near_b.get("n", 0):
        if near_b["mae"] > near_a["mae"] + 0.25:
            near_pk_ok = False
            reasons.append(
                "Model B degraded near-PK (market <=3) MAE by more than 0.25 points."
            )

    passed = (
        overall_mae_better
        and overall_rmse_better
        and small_ok
        and large_ok
        and near_pk_ok
    )

    return {
        "passed_for_shadow_board": passed,
        "overall_mae_better": overall_mae_better,
        "overall_rmse_better": overall_rmse_better,
        "small_spread_protection_pass": small_ok,
        "large_favorite_improvement_pass": large_ok,
        "near_pk_protection_pass": near_pk_ok,
        "large_favorite_oos_n": large_n,
        "reasons": reasons,
    }


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    records = build_records()
    folds, scored_a, scored_b = run_nested_oos(records)

    if len(folds) < 3:
        raise RuntimeError(
            f"Expected at least 3 nested OOS folds; found {len(folds)}."
        )
    if len(scored_a) < 1500 or len(scored_b) < 1500:
        raise RuntimeError(
            f"Insufficient OOS sample: A={len(scored_a)}, B={len(scored_b)}."
        )

    summary_a = aggregate_scored(scored_a)
    summary_b = aggregate_scored(scored_b)
    decision = promotion_decision(summary_a, summary_b)

    report = {
        "challenger_version": "model-b-input-expansion-v1-nested-oos",
        "status": (
            "PASS_FOR_SHADOW_BOARD"
            if decision["passed_for_shadow_board"]
            else "HOLD_MODEL_A"
        ),
        "production_untouched": True,
        "market_used_for_candidate_selection": False,
        "candidate_selection": {
            "method": (
                "For each test year, use years before the prior season as training, "
                "the immediately prior season as validation, select threshold/gamma by "
                "validation RMSE with MAE tie-breaker, then refit on all prior years and "
                "evaluate the untouched test year."
            ),
            "thresholds": "Training-data abs(rating_diff) quantiles 60/70/80/90%",
            "gammas": EXPANSION_GAMMAS,
            "transform": (
                "sign(x) * [threshold + (abs(x)-threshold)*(1+gamma)] "
                "only when abs(x)>threshold; otherwise x unchanged."
            ),
        },
        "historical_source": str(HISTORICAL.relative_to(ROOT)),
        "historical_limitation": (
            "Neutral-site status is unavailable in historical_training_v4, "
            "so both Model A and Model B use the same fitted global home intercept."
        ),
        "oos_folds": folds,
        "aggregate_model_a": summary_a,
        "aggregate_model_b": summary_b,
        "promotion_protocol": {
            "requirements": [
                "Model B overall OOS MAE < Model A.",
                "Model B overall OOS RMSE < Model A.",
                "0-7 and 7-14 MAE may not degrade by more than 0.25 points.",
                "Near-PK market <=3 MAE may not degrade by more than 0.25 points.",
                "Model B must improve MAE in at least half of adequately-sampled 14+ buckets.",
            ],
            "decision": decision,
        },
    }

    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "MODEL B INPUT EXPANSION CHALLENGER — NESTED OOS",
        "=" * 56,
        f"Status: {report['status']}",
        "",
        "AGGREGATE",
        f"Model A: {summary_a['overall']}",
        f"Model B: {summary_b['overall']}",
        "",
        "MARKET FAVORITE BUCKETS",
    ]

    for _, _, label in MARKET_BUCKETS:
        lines.append(
            f"{label} | A={summary_a['market_buckets'][label]} | "
            f"B={summary_b['market_buckets'][label]}"
        )

    lines += [
        "",
        "NEAR-PK SANITY (market <= 3)",
        f"A={summary_a['near_pk_market_3_or_less']}",
        f"B={summary_b['near_pk_market_3_or_less']}",
        "",
        "FOLDS",
    ]

    for fold in folds:
        lines.append(
            f"{fold['test_year']} | threshold={fold['selected_threshold']:.4f} "
            f"(q={fold['selected_threshold_quantile']:.2f}) | "
            f"gamma={fold['selected_gamma']:.2f} | "
            f"A MAE/RMSE={fold['model_a']['mae']:.4f}/{fold['model_a']['rmse']:.4f} | "
            f"B MAE/RMSE={fold['model_b']['mae']:.4f}/{fold['model_b']['rmse']:.4f}"
        )

    lines += [
        "",
        "PROMOTION DECISION",
        json.dumps(decision, indent=2),
        "",
        "PRODUCTION STATUS",
        "Model A untouched.",
        "No website files written.",
        "No current 2026 projections written.",
        "If PASS, next step is a separate shadow-board generator only.",
    ]

    REPORT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
