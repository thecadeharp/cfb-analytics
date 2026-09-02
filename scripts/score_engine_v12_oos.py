"""
CFB ANALYTICS
score_engine_v12_oos.py

Score Engine V1.2 mechanism experiment.

Purpose
-------
Test richer football-mechanism features using ONLY 2019-2024.
2025 is never read for model selection or evaluation in this experiment.

Design
------
- Uses the audited canonical SportsDataverse training table.
- Builds matchup interactions rather than favorite-size corrections.
- Uses rolling out-of-sample folds:
    train 2019-2021 -> validate 2022
    train 2019-2022 -> validate 2023
    train 2019-2023 -> validate 2024
- Compares:
    A) same-dataset linear margin control
    B) V1.1-style score engine baseline
    C) V1.2 mechanism score engine
- No market spread is used as a predictive feature.
- Market favorite buckets are evaluation-only.

Writes:
    data/training/score_engine_v12_oos.json
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "training" / "historical_games.csv"
AUDIT = ROOT / "data" / "training" / "historical_training_audit.json"
OUT = ROOT / "data" / "training" / "score_engine_v12_oos.json"

RIDGE_LAMBDAS = [0.5, 1.0, 2.0, 4.0, 8.0]
ALPHAS = [1.0, 1.25, 1.5, 1.75, 2.0]

FOLDS = [
    ([2019, 2020, 2021], 2022),
    ([2019, 2020, 2021, 2022], 2023),
    ([2019, 2020, 2021, 2022, 2023], 2024),
]

BASE_METRICS = [
    "off_epa",
    "off_success_rate",
    "off_explosive_rate",
    "off_pass_epa",
    "off_rush_epa",
    "havoc_allowed_rate",
    "line_yards_per_rush",
    "scoring_opp_rate",
    "drives",
    "plays_per_drive",
    "def_epa_allowed",
    "def_success_allowed",
    "def_explosive_allowed",
    "def_pass_epa_allowed",
    "def_rush_epa_allowed",
    "def_havoc_created_rate",
    "def_line_yards_allowed",
    "def_scoring_opp_allowed",
]


def finite(x):
    return x is not None and np.isfinite(x)


def mean(values):
    vals = [float(v) for v in values if finite(v)]
    return float(np.mean(vals)) if vals else None


def mae(pred, actual):
    vals = [abs(p - a) for p, a in zip(pred, actual) if finite(p) and finite(a)]
    return float(np.mean(vals)) if vals else None


def rmse(pred, actual):
    vals = [(p - a) ** 2 for p, a in zip(pred, actual) if finite(p) and finite(a)]
    return float(math.sqrt(np.mean(vals))) if vals else None


def signed_power(value, alpha):
    if abs(value) < 1e-15:
        return 0.0
    return math.copysign(abs(value) ** alpha, value)


def blended(row, side, metric):
    current = row.get(f"{side}_pregame_{metric}")
    previous = row.get(f"{side}_prev_season_{metric}")
    if finite(current):
        return float(current)
    if finite(previous):
        return float(previous)
    return None


def ridge_fit(x, y, ridge_lambda):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)

    means = x.mean(axis=0)
    stds = x.std(axis=0)
    stds[stds < 1e-9] = 1.0

    z = (x - means) / stds
    design = np.column_stack([np.ones(len(z)), z])

    penalty = np.eye(design.shape[1]) * ridge_lambda
    penalty[0, 0] = 0.0

    coefs = np.linalg.solve(
        design.T @ design + penalty,
        design.T @ y,
    )

    return {
        "means": means,
        "stds": stds,
        "coefs": coefs,
        "ridge_lambda": ridge_lambda,
    }


def ridge_predict(model, x):
    x = np.asarray(x, dtype=float)
    z = (x - model["means"]) / model["stds"]
    design = np.concatenate([[1.0], z])
    return float(design @ model["coefs"])


def matchup_pair(row, offense_side, defense_side):
    """
    Returns interpretable offense-vs-defense matchup mechanisms.

    Positive values generally favor the offense.
    """
    off_epa = blended(row, offense_side, "off_epa")
    def_epa = blended(row, defense_side, "def_epa_allowed")

    off_pass = blended(row, offense_side, "off_pass_epa")
    def_pass = blended(row, defense_side, "def_pass_epa_allowed")

    off_rush = blended(row, offense_side, "off_rush_epa")
    def_rush = blended(row, defense_side, "def_rush_epa_allowed")

    off_success = blended(row, offense_side, "off_success_rate")
    def_success = blended(row, defense_side, "def_success_allowed")

    off_explosive = blended(row, offense_side, "off_explosive_rate")
    def_explosive = blended(row, defense_side, "def_explosive_allowed")

    havoc_allowed = blended(row, offense_side, "havoc_allowed_rate")
    havoc_created = blended(row, defense_side, "def_havoc_created_rate")

    line_yards = blended(row, offense_side, "line_yards_per_rush")
    line_yards_allowed = blended(row, defense_side, "def_line_yards_allowed")

    scoring_opp = blended(row, offense_side, "scoring_opp_rate")
    scoring_opp_allowed = blended(row, defense_side, "def_scoring_opp_allowed")

    drives = blended(row, offense_side, "drives")
    plays_per_drive = blended(row, offense_side, "plays_per_drive")

    values = [
        off_epa, def_epa,
        off_pass, def_pass,
        off_rush, def_rush,
        off_success, def_success,
        off_explosive, def_explosive,
        havoc_allowed, havoc_created,
        line_yards, line_yards_allowed,
        scoring_opp, scoring_opp_allowed,
        drives, plays_per_drive,
    ]
    if not all(finite(v) for v in values):
        return None

    epa_mismatch = off_epa - def_epa
    pass_mismatch = off_pass - def_pass
    rush_mismatch = off_rush - def_rush
    success_mismatch = off_success - def_success
    explosive_mismatch = off_explosive - def_explosive

    # Lower offensive havoc allowed is good; higher defensive havoc created is good.
    havoc_mismatch = havoc_created - havoc_allowed

    line_yards_mismatch = line_yards - line_yards_allowed
    scoring_opp_mismatch = scoring_opp - scoring_opp_allowed

    # Mechanism interactions. These are football-variable interactions, not
    # market-line or favorite-size adjustments.
    pass_explosive_interaction = pass_mismatch * explosive_mismatch
    rush_success_interaction = rush_mismatch * success_mismatch
    havoc_explosive_interaction = havoc_mismatch * explosive_mismatch
    scoring_epa_interaction = scoring_opp_mismatch * epa_mismatch

    return {
        "off_epa": off_epa,
        "def_epa_allowed": def_epa,
        "off_pass_epa": off_pass,
        "def_pass_epa_allowed": def_pass,
        "off_rush_epa": off_rush,
        "def_rush_epa_allowed": def_rush,
        "off_success_rate": off_success,
        "def_success_allowed": def_success,
        "off_explosive_rate": off_explosive,
        "def_explosive_allowed": def_explosive,
        "havoc_allowed_rate": havoc_allowed,
        "def_havoc_created_rate": havoc_created,
        "line_yards_per_rush": line_yards,
        "def_line_yards_allowed": line_yards_allowed,
        "scoring_opp_rate": scoring_opp,
        "def_scoring_opp_allowed": scoring_opp_allowed,
        "drives": drives,
        "plays_per_drive": plays_per_drive,
        "epa_mismatch": epa_mismatch,
        "pass_mismatch": pass_mismatch,
        "rush_mismatch": rush_mismatch,
        "success_mismatch": success_mismatch,
        "explosive_mismatch": explosive_mismatch,
        "havoc_mismatch": havoc_mismatch,
        "line_yards_mismatch": line_yards_mismatch,
        "scoring_opp_mismatch": scoring_opp_mismatch,
        "pass_x_explosive": pass_explosive_interaction,
        "rush_x_success": rush_success_interaction,
        "havoc_x_explosive": havoc_explosive_interaction,
        "scoring_x_epa": scoring_epa_interaction,
    }


def v11_vector(row, offense_side, defense_side, is_home, alpha):
    m = matchup_pair(row, offense_side, defense_side)
    if m is None:
        return None

    offense_strength = (
        m["off_epa"]
        + 0.75 * m["off_success_rate"]
        + 0.50 * m["off_explosive_rate"]
    )
    defense_strength = -(
        m["def_epa_allowed"]
        + 0.75 * m["def_success_allowed"]
        + 0.50 * m["def_explosive_allowed"]
    )
    advantage = offense_strength - defense_strength

    return [
        m["epa_mismatch"],
        m["pass_mismatch"],
        m["rush_mismatch"],
        m["success_mismatch"],
        m["explosive_mismatch"],
        m["havoc_mismatch"],
        m["drives"],
        offense_strength,
        defense_strength,
        advantage,
        signed_power(advantage, alpha),
        advantage * m["drives"],
        1.0 if is_home else -1.0,
    ]


def v12_vector(row, offense_side, defense_side, is_home, alpha):
    m = matchup_pair(row, offense_side, defense_side)
    if m is None:
        return None

    # Composite matchup strength is built from actual football mismatches.
    matchup_strength = (
        1.00 * m["epa_mismatch"]
        + 0.70 * m["pass_mismatch"]
        + 0.55 * m["rush_mismatch"]
        + 0.80 * m["success_mismatch"]
        + 0.60 * m["explosive_mismatch"]
        + 0.45 * m["havoc_mismatch"]
        + 0.20 * m["line_yards_mismatch"]
        + 0.55 * m["scoring_opp_mismatch"]
    )

    # Possession-weighted scoring opportunity advantage.
    possession_pressure = matchup_strength * m["drives"]

    # Nonlinearity is applied to the football matchup strength, not market size.
    nonlinear_strength = signed_power(matchup_strength, alpha)

    return [
        # Raw offense and opponent defense states
        m["off_epa"],
        m["def_epa_allowed"],
        m["off_pass_epa"],
        m["def_pass_epa_allowed"],
        m["off_rush_epa"],
        m["def_rush_epa_allowed"],
        m["off_success_rate"],
        m["def_success_allowed"],
        m["off_explosive_rate"],
        m["def_explosive_allowed"],
        m["havoc_allowed_rate"],
        m["def_havoc_created_rate"],
        m["line_yards_per_rush"],
        m["def_line_yards_allowed"],
        m["scoring_opp_rate"],
        m["def_scoring_opp_allowed"],
        m["drives"],
        m["plays_per_drive"],

        # Explicit matchup mismatches
        m["epa_mismatch"],
        m["pass_mismatch"],
        m["rush_mismatch"],
        m["success_mismatch"],
        m["explosive_mismatch"],
        m["havoc_mismatch"],
        m["line_yards_mismatch"],
        m["scoring_opp_mismatch"],

        # Mechanism interactions
        m["pass_x_explosive"],
        m["rush_x_success"],
        m["havoc_x_explosive"],
        m["scoring_x_epa"],

        # Game-environment / nonlinear terms
        matchup_strength,
        nonlinear_strength,
        possession_pressure,
        1.0 if is_home else -1.0,
    ]


def control_vector(row):
    values = []
    for metric in BASE_METRICS:
        h = blended(row, "home", metric)
        a = blended(row, "away", metric)
        if not finite(h) or not finite(a):
            return None
        values.append(h - a)
    values.append(1.0)
    return values


def fit_score_model(training, vector_fn, alpha, ridge_lambda):
    x, y = [], []

    for _, row in training.iterrows():
        h = vector_fn(row, "home", "away", True, alpha)
        a = vector_fn(row, "away", "home", False, alpha)
        if h is None or a is None:
            continue

        x.append(h)
        y.append(float(row["home_score"]))
        x.append(a)
        y.append(float(row["away_score"]))

    if len(x) < 100:
        raise RuntimeError("Too few score-model rows.")

    model = ridge_fit(x, y, ridge_lambda)
    model["alpha"] = alpha
    return model


def predict_scores(model, row, vector_fn):
    h = vector_fn(row, "home", "away", True, model["alpha"])
    a = vector_fn(row, "away", "home", False, model["alpha"])
    if h is None or a is None:
        return None

    return (
        max(0.0, ridge_predict(model, h)),
        max(0.0, ridge_predict(model, a)),
    )


def fit_control(training, ridge_lambda=2.0):
    x, y = [], []
    for _, row in training.iterrows():
        vec = control_vector(row)
        if vec is None:
            continue
        x.append(vec)
        y.append(float(row["actual_home_margin"]))

    return ridge_fit(x, y, ridge_lambda)


def predict_control(model, row):
    vec = control_vector(row)
    return None if vec is None else ridge_predict(model, vec)


def evaluate_fold(train, val, vector_fn, alpha, ridge_lambda):
    score_model = fit_score_model(train, vector_fn, alpha, ridge_lambda)
    control_model = fit_control(train)

    score_margin_pred = []
    control_margin_pred = []
    actual_margin = []

    team_score_errors = []
    total_pred = []
    total_actual = []

    scored_rows = []

    for _, row in val.iterrows():
        scores = predict_scores(score_model, row, vector_fn)
        control_margin = predict_control(control_model, row)

        if scores is None or control_margin is None:
            continue

        hp, ap = scores
        margin = hp - ap
        actual = float(row["actual_home_margin"])

        score_margin_pred.append(margin)
        control_margin_pred.append(control_margin)
        actual_margin.append(actual)

        team_score_errors.extend([
            abs(hp - float(row["home_score"])),
            abs(ap - float(row["away_score"])),
        ])
        total_pred.append(hp + ap)
        total_actual.append(float(row["actual_total"]))

        scored_rows.append({
            "market_home_spread": (
                float(row["market_home_spread"])
                if pd.notna(row["market_home_spread"])
                else None
            ),
            "actual_home_margin": actual,
            "score_margin": margin,
            "control_margin": control_margin,
        })

    return {
        "n": len(actual_margin),
        "control_margin_mae": mae(control_margin_pred, actual_margin),
        "control_margin_rmse": rmse(control_margin_pred, actual_margin),
        "score_margin_mae": mae(score_margin_pred, actual_margin),
        "score_margin_rmse": rmse(score_margin_pred, actual_margin),
        "team_score_mae": mean(team_score_errors),
        "total_mae": mae(total_pred, total_actual),
        "tail": tail_report(scored_rows),
    }


def tail_report(rows):
    buckets = [
        (21, 28, "21-28"),
        (28, 40, "28-40"),
        (40, 999, "40+"),
    ]
    out = []

    for low, high, label in buckets:
        bucket = []
        for g in rows:
            spread = g["market_home_spread"]
            if spread is None:
                continue
            size = abs(spread)
            if low <= size < high:
                bucket.append(g)

        if not bucket:
            out.append({"range": label, "games": 0})
            continue

        control_bias = []
        score_bias = []

        for g in bucket:
            home_fav = g["market_home_spread"] < 0
            sign = 1.0 if home_fav else -1.0
            actual = sign * g["actual_home_margin"]
            control = sign * g["control_margin"]
            score = sign * g["score_margin"]
            control_bias.append(control - actual)
            score_bias.append(score - actual)

        out.append({
            "range": label,
            "games": len(bucket),
            "control_bias": mean(control_bias),
            "score_bias": mean(score_bias),
        })

    return out


def aggregate_folds(folds):
    weights = [f["n"] for f in folds]
    total = sum(weights)

    def weighted(key):
        vals = [
            f[key] * f["n"]
            for f in folds
            if finite(f.get(key))
        ]
        denom = sum(
            f["n"]
            for f in folds
            if finite(f.get(key))
        )
        return sum(vals) / denom if denom else None

    tail_labels = ["21-28", "28-40", "40+"]
    tail = []
    for label in tail_labels:
        rows = []
        for fold in folds:
            for item in fold["tail"]:
                if item["range"] == label and item.get("games", 0) > 0:
                    rows.append(item)

        n = sum(r["games"] for r in rows)
        if not n:
            tail.append({"range": label, "games": 0})
            continue

        tail.append({
            "range": label,
            "games": n,
            "control_bias": sum(r["control_bias"] * r["games"] for r in rows) / n,
            "score_bias": sum(r["score_bias"] * r["games"] for r in rows) / n,
        })

    return {
        "n": total,
        "control_margin_mae": weighted("control_margin_mae"),
        "control_margin_rmse": weighted("control_margin_rmse"),
        "score_margin_mae": weighted("score_margin_mae"),
        "score_margin_rmse": weighted("score_margin_rmse"),
        "team_score_mae": weighted("team_score_mae"),
        "total_mae": weighted("total_mae"),
        "tail": tail,
    }


def run_config(df, vector_fn, alpha, ridge_lambda):
    fold_results = []

    for train_years, val_year in FOLDS:
        train = df[df["season"].isin(train_years)]
        val = df[df["season"] == val_year]

        result = evaluate_fold(
            train,
            val,
            vector_fn,
            alpha,
            ridge_lambda,
        )
        result["train_years"] = train_years
        result["validation_year"] = val_year
        fold_results.append(result)

    return {
        "alpha": alpha,
        "ridge_lambda": ridge_lambda,
        "folds": fold_results,
        "aggregate": aggregate_folds(fold_results),
    }


def round_tree(value):
    if isinstance(value, dict):
        return {k: round_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [round_tree(v) for v in value]
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(value):
            return None
        return round(float(value), 6)
    if isinstance(value, (np.integer,)):
        return int(value)
    return value


def main():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    if audit.get("status") != "PASS":
        raise SystemExit("Historical training audit must PASS first.")

    df = pd.read_csv(DATA)

    # Absolute guard: never even include 2025 rows in this experiment.
    df = df[df["season"].between(2019, 2024)].copy()

    print("Running V1.1 rolling OOS baseline...")
    v11 = run_config(
        df,
        v11_vector,
        alpha=1.25,
        ridge_lambda=2.0,
    )

    print("Searching V1.2 mechanism configs using 2019-2024 OOS only...")
    configs = []

    for alpha in ALPHAS:
        for ridge_lambda in RIDGE_LAMBDAS:
            print(
                f"  alpha={alpha:.2f} lambda={ridge_lambda:.2f}",
                flush=True,
            )
            result = run_config(
                df,
                v12_vector,
                alpha=alpha,
                ridge_lambda=ridge_lambda,
            )
            configs.append(result)

    winner = min(
        configs,
        key=lambda r: r["aggregate"]["score_margin_rmse"],
    )

    control = {
        "margin_mae": winner["aggregate"]["control_margin_mae"],
        "margin_rmse": winner["aggregate"]["control_margin_rmse"],
    }

    v11_agg = v11["aggregate"]
    v12_agg = winner["aggregate"]

    # Promotion gate is based only on 2019-2024 OOS.
    v12_beats_v11_mae = v12_agg["score_margin_mae"] < v11_agg["score_margin_mae"]
    v12_beats_v11_rmse = v12_agg["score_margin_rmse"] < v11_agg["score_margin_rmse"]
    v12_beats_control_mae = v12_agg["score_margin_mae"] < control["margin_mae"]
    v12_beats_control_rmse = v12_agg["score_margin_rmse"] < control["margin_rmse"]

    available_tail = [
        r for r in v12_agg["tail"]
        if r.get("games", 0) > 0
    ]
    tail_better_than_control = (
        all(
            abs(r["score_bias"]) < abs(r["control_bias"])
            for r in available_tail
        )
        if available_tail else None
    )

    report = {
        "status": "OOS_COMPLETE",
        "dataset": "historical_training_v3_sportsdataverse_espn",
        "years_used": list(range(2019, 2025)),
        "years_excluded": [2025],
        "leakage_guard": {
            "2025_read_for_model_selection": False,
            "market_spread_used_as_predictive_feature": False,
            "rolling_oos_folds": FOLDS,
        },
        "v11_baseline": v11,
        "v12_search_space": {
            "alphas": ALPHAS,
            "ridge_lambdas": RIDGE_LAMBDAS,
            "config_count": len(configs),
        },
        "v12_all_configs": configs,
        "v12_winner": winner,
        "decision": {
            "v12_beats_v11_margin_mae": v12_beats_v11_mae,
            "v12_beats_v11_margin_rmse": v12_beats_v11_rmse,
            "v12_beats_linear_control_margin_mae": v12_beats_control_mae,
            "v12_beats_linear_control_margin_rmse": v12_beats_control_rmse,
            "v12_large_favorite_bias_better_than_control_all_available_21plus": (
                tail_better_than_control
            ),
            "status": (
                "ADVANCE_TO_FROZEN_2025_COMPARISON"
                if (
                    v12_beats_v11_mae
                    and v12_beats_v11_rmse
                    and v12_beats_control_mae
                    and v12_beats_control_rmse
                )
                else "HOLD_V12"
            ),
        },
        "mechanism_notes": [
            "No favorite-size feature or market-line correction is used.",
            "Pass/explosiveness, rush/success, havoc/explosiveness, and scoring-opportunity/EPA interactions are explicit.",
            "Possession pressure is matchup strength multiplied by estimated drives.",
            "The nonlinear term is applied to football matchup strength, not market favorite size.",
            "2025 remains untouched by this experiment.",
        ],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(round_tree(report), indent=2),
        encoding="utf-8",
    )

    print("=" * 78)
    print("SCORE ENGINE V1.2 OOS COMPLETE")
    print("=" * 78)
    print(
        "V1.1 OOS margin MAE/RMSE:",
        round(v11_agg["score_margin_mae"], 4),
        "/",
        round(v11_agg["score_margin_rmse"], 4),
    )
    print(
        "V1.2 OOS margin MAE/RMSE:",
        round(v12_agg["score_margin_mae"], 4),
        "/",
        round(v12_agg["score_margin_rmse"], 4),
    )
    print(
        "Linear control MAE/RMSE:",
        round(control["margin_mae"], 4),
        "/",
        round(control["margin_rmse"], 4),
    )
    print(
        "Winner alpha/lambda:",
        winner["alpha"],
        "/",
        winner["ridge_lambda"],
    )
    print("Decision:", report["decision"]["status"])
    print("Wrote:", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
