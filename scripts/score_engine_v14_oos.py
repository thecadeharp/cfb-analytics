"""
CFB ANALYTICS
score_engine_v14_oos.py

Score Engine V1.4 — REALIZED possession/scoring mechanism model.

Purpose
-------
Use the audited V4 historical training table to model actual football outcomes:

    expected drives
      * expected SportsDataverse scoring-opportunity rate
      * expected points per SportsDataverse scoring opportunity
      = projected team points

IMPORTANT
---------
- 2025 is NEVER used in this experiment.
- Current-game realized targets are used only as TRAINING LABELS.
- Prediction inputs are leakage-safe pregame_* / prev_season_* features.
- Market spread is evaluation-only and NEVER predictive.
- "Scoring opportunity" means the SportsDataverse scoring_opp drive flag as
  preserved by our V4 builder. We do not redefine it as a traditional
  inside-the-40 scoring-opportunity concept.

Rolling OOS folds
-----------------
train 2019-2021 -> validate 2022
train 2019-2022 -> validate 2023
train 2019-2023 -> validate 2024

Output
------
data/training/score_engine_v14_oos.json
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
OUT = ROOT / "data" / "training" / "score_engine_v14_oos.json"

FOLDS = [
    ([2019, 2020, 2021], 2022),
    ([2019, 2020, 2021, 2022], 2023),
    ([2019, 2020, 2021, 2022, 2023], 2024),
]

RIDGE_LAMBDAS = [0.5, 1.0, 2.0, 4.0, 8.0]

# Prediction inputs. Every item is pulled from pregame_* first, then
# prev_season_* as fallback.
BASE_METRICS = [
    "off_epa",
    "off_success_rate",
    "off_explosive_rate",
    "off_pass_epa",
    "off_rush_epa",
    "havoc_allowed_rate",
    "line_yards_per_rush",
    "scoring_opp_rate",
    "avg_start_yards_to_endzone",
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

    # V4 historical realized mechanism priors.
    "actual_drives",
    "actual_scoring_opportunities",
    "actual_scoring_opportunity_rate",
    "actual_points_on_scoring_opportunities",
    "actual_points_per_scoring_opportunity",
    "actual_scoring_opportunity_conversion_rate",
    "def_actual_drives_faced",
    "def_actual_scoring_opportunities_allowed",
    "def_actual_scoring_opportunity_rate_allowed",
    "def_actual_points_on_scoring_opportunities_allowed",
    "def_actual_points_per_scoring_opportunity_allowed",
    "def_actual_scoring_opportunity_conversion_rate_allowed",
]

CONTROL_METRICS = [
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


def get_matchup(row, offense_side, defense_side):
    data = {}

    for metric in BASE_METRICS:
        off = blended(row, offense_side, metric)
        data[f"off_{metric}"] = off

    # Opponent defensive-side features are already stored on the opposing team.
    needed = [
        "def_epa_allowed",
        "def_success_allowed",
        "def_explosive_allowed",
        "def_pass_epa_allowed",
        "def_rush_epa_allowed",
        "def_havoc_created_rate",
        "def_line_yards_allowed",
        "def_scoring_opp_allowed",
        "def_actual_drives_faced",
        "def_actual_scoring_opportunities_allowed",
        "def_actual_scoring_opportunity_rate_allowed",
        "def_actual_points_on_scoring_opportunities_allowed",
        "def_actual_points_per_scoring_opportunity_allowed",
        "def_actual_scoring_opportunity_conversion_rate_allowed",
    ]

    for metric in needed:
        val = blended(row, defense_side, metric)
        data[f"opp_{metric}"] = val

    required = [
        data["off_off_epa"],
        data["off_off_success_rate"],
        data["off_off_explosive_rate"],
        data["off_off_pass_epa"],
        data["off_off_rush_epa"],
        data["off_havoc_allowed_rate"],
        data["off_line_yards_per_rush"],
        data["off_scoring_opp_rate"],
        data["off_avg_start_yards_to_endzone"],
        data["off_drives"],
        data["off_plays_per_drive"],
        data["off_actual_drives"],
        data["off_actual_scoring_opportunity_rate"],
        data["off_actual_points_per_scoring_opportunity"],
        data["off_actual_scoring_opportunity_conversion_rate"],

        data["opp_def_epa_allowed"],
        data["opp_def_success_allowed"],
        data["opp_def_explosive_allowed"],
        data["opp_def_pass_epa_allowed"],
        data["opp_def_rush_epa_allowed"],
        data["opp_def_havoc_created_rate"],
        data["opp_def_line_yards_allowed"],
        data["opp_def_scoring_opp_allowed"],
        data["opp_def_actual_drives_faced"],
        data["opp_def_actual_scoring_opportunity_rate_allowed"],
        data["opp_def_actual_points_per_scoring_opportunity_allowed"],
        data["opp_def_actual_scoring_opportunity_conversion_rate_allowed"],
    ]

    if not all(finite(v) for v in required):
        return None

    return data


def drive_vector(row, offense_side, defense_side, is_home):
    m = get_matchup(row, offense_side, defense_side)
    if m is None:
        return None

    return [
        m["off_drives"],
        m["off_actual_drives"],
        m["off_plays_per_drive"],
        m["off_off_success_rate"],
        m["opp_def_success_allowed"],
        m["off_havoc_allowed_rate"],
        m["opp_def_havoc_created_rate"],
        m["off_off_epa"],
        m["opp_def_epa_allowed"],
        m["off_avg_start_yards_to_endzone"],
        1.0 if is_home else -1.0,
    ]


def scoring_rate_vector(row, offense_side, defense_side, is_home):
    m = get_matchup(row, offense_side, defense_side)
    if m is None:
        return None

    return [
        m["off_actual_scoring_opportunity_rate"],
        m["opp_def_actual_scoring_opportunity_rate_allowed"],
        m["off_scoring_opp_rate"],
        m["opp_def_scoring_opp_allowed"],
        m["off_off_epa"],
        m["opp_def_epa_allowed"],
        m["off_off_success_rate"],
        m["opp_def_success_allowed"],
        m["off_off_explosive_rate"],
        m["opp_def_explosive_allowed"],
        m["off_havoc_allowed_rate"],
        m["opp_def_havoc_created_rate"],
        m["off_line_yards_per_rush"],
        m["opp_def_line_yards_allowed"],
        m["off_avg_start_yards_to_endzone"],
        1.0 if is_home else -1.0,
    ]


def ppso_vector(row, offense_side, defense_side, is_home):
    m = get_matchup(row, offense_side, defense_side)
    if m is None:
        return None

    return [
        m["off_actual_points_per_scoring_opportunity"],
        m["opp_def_actual_points_per_scoring_opportunity_allowed"],
        m["off_actual_scoring_opportunity_conversion_rate"],
        m["opp_def_actual_scoring_opportunity_conversion_rate_allowed"],
        m["off_off_epa"],
        m["opp_def_epa_allowed"],
        m["off_off_pass_epa"],
        m["opp_def_pass_epa_allowed"],
        m["off_off_rush_epa"],
        m["opp_def_rush_epa_allowed"],
        m["off_off_success_rate"],
        m["opp_def_success_allowed"],
        m["off_off_explosive_rate"],
        m["opp_def_explosive_allowed"],
        m["off_havoc_allowed_rate"],
        m["opp_def_havoc_created_rate"],
        1.0 if is_home else -1.0,
    ]


def control_vector(row):
    values = []
    for metric in CONTROL_METRICS:
        h = blended(row, "home", metric)
        a = blended(row, "away", metric)
        if not finite(h) or not finite(a):
            return None
        values.append(h - a)
    values.append(1.0)
    return values


def fit_components(training, ridge_lambda):
    x_drive, y_drive = [], []
    x_rate, y_rate = [], []
    x_ppso, y_ppso = [], []

    for _, row in training.iterrows():
        for side, opp, is_home in [
            ("home", "away", True),
            ("away", "home", False),
        ]:
            dv = drive_vector(row, side, opp, is_home)
            rv = scoring_rate_vector(row, side, opp, is_home)
            pv = ppso_vector(row, side, opp, is_home)

            drive_target = row.get(f"{side}_actual_drives")
            rate_target = row.get(f"{side}_actual_scoring_opportunity_rate")
            ppso_target = row.get(
                f"{side}_actual_points_per_scoring_opportunity"
            )

            if (
                dv is None or rv is None or pv is None
                or not finite(drive_target)
                or not finite(rate_target)
                or not finite(ppso_target)
            ):
                continue

            x_drive.append(dv)
            y_drive.append(float(drive_target))

            x_rate.append(rv)
            y_rate.append(float(rate_target))

            x_ppso.append(pv)
            y_ppso.append(float(ppso_target))

    if len(x_drive) < 500:
        raise RuntimeError(
            f"Too few V1.4 component training rows: {len(x_drive)}"
        )

    return {
        "drive": ridge_fit(x_drive, y_drive, ridge_lambda),
        "rate": ridge_fit(x_rate, y_rate, ridge_lambda),
        "ppso": ridge_fit(x_ppso, y_ppso, ridge_lambda),
        "team_training_rows": len(x_drive),
    }


def predict_team(models, row, offense_side, defense_side, is_home):
    dv = drive_vector(row, offense_side, defense_side, is_home)
    rv = scoring_rate_vector(row, offense_side, defense_side, is_home)
    pv = ppso_vector(row, offense_side, defense_side, is_home)

    if dv is None or rv is None or pv is None:
        return None

    expected_drives = ridge_predict(models["drive"], dv)
    scoring_rate = ridge_predict(models["rate"], rv)
    ppso = ridge_predict(models["ppso"], pv)

    # Fixed football-plausibility bounds based on the audited source's actual
    # observed variable meanings, not on any market line or 2025 result.
    expected_drives = float(np.clip(expected_drives, 4.0, 23.0))
    scoring_rate = float(np.clip(scoring_rate, 0.0, 1.0))
    ppso = float(np.clip(ppso, 0.0, 7.0))

    expected_opportunities = expected_drives * scoring_rate
    points = expected_opportunities * ppso

    return {
        "points": max(0.0, points),
        "expected_drives": expected_drives,
        "expected_scoring_opportunity_rate": scoring_rate,
        "expected_scoring_opportunities": expected_opportunities,
        "expected_points_per_scoring_opportunity": ppso,
    }


def fit_control(training, ridge_lambda=2.0):
    x, y = [], []
    for _, row in training.iterrows():
        vector = control_vector(row)
        if vector is None:
            continue
        x.append(vector)
        y.append(float(row["actual_home_margin"]))

    if len(x) < 500:
        raise RuntimeError("Too few control training rows.")

    return ridge_fit(x, y, ridge_lambda)


def evaluate_fold(train, val, ridge_lambda):
    components = fit_components(train, ridge_lambda)
    control = fit_control(train)

    v14_margin_pred = []
    control_margin_pred = []
    actual_margin = []

    total_pred = []
    total_actual = []
    team_score_errors = []

    drive_pred, drive_actual = [], []
    rate_pred, rate_actual = [], []
    ppso_pred, ppso_actual = [], []

    market_rows = []

    for _, row in val.iterrows():
        home = predict_team(components, row, "home", "away", True)
        away = predict_team(components, row, "away", "home", False)
        cv = control_vector(row)

        if home is None or away is None or cv is None:
            continue

        control_margin = ridge_predict(control, cv)
        v14_margin = home["points"] - away["points"]
        actual = float(row["actual_home_margin"])

        v14_margin_pred.append(v14_margin)
        control_margin_pred.append(control_margin)
        actual_margin.append(actual)

        team_score_errors.extend([
            abs(home["points"] - float(row["home_score"])),
            abs(away["points"] - float(row["away_score"])),
        ])
        total_pred.append(home["points"] + away["points"])
        total_actual.append(float(row["actual_total"]))

        for side, pred in [("home", home), ("away", away)]:
            ad = row.get(f"{side}_actual_drives")
            ar = row.get(f"{side}_actual_scoring_opportunity_rate")
            ap = row.get(f"{side}_actual_points_per_scoring_opportunity")

            if finite(ad):
                drive_pred.append(pred["expected_drives"])
                drive_actual.append(float(ad))
            if finite(ar):
                rate_pred.append(pred["expected_scoring_opportunity_rate"])
                rate_actual.append(float(ar))
            if finite(ap):
                ppso_pred.append(
                    pred["expected_points_per_scoring_opportunity"]
                )
                ppso_actual.append(float(ap))

        spread = row.get("market_home_spread")
        market_rows.append({
            "market_home_spread": (
                float(spread) if finite(spread) else None
            ),
            "actual_home_margin": actual,
            "control_margin": control_margin,
            "v14_margin": v14_margin,
        })

    return {
        "n": len(actual_margin),
        "team_training_rows": components["team_training_rows"],
        "control_margin_mae": mae(control_margin_pred, actual_margin),
        "control_margin_rmse": rmse(control_margin_pred, actual_margin),
        "v14_margin_mae": mae(v14_margin_pred, actual_margin),
        "v14_margin_rmse": rmse(v14_margin_pred, actual_margin),
        "v14_team_score_mae": mean(team_score_errors),
        "v14_total_mae": mae(total_pred, total_actual),
        "v14_total_rmse": rmse(total_pred, total_actual),
        "component_accuracy": {
            "drives_mae": mae(drive_pred, drive_actual),
            "drives_rmse": rmse(drive_pred, drive_actual),
            "scoring_opportunity_rate_mae": mae(rate_pred, rate_actual),
            "scoring_opportunity_rate_rmse": rmse(rate_pred, rate_actual),
            "points_per_scoring_opportunity_mae": mae(ppso_pred, ppso_actual),
            "points_per_scoring_opportunity_rmse": rmse(ppso_pred, ppso_actual),
        },
        "tail": tail_report(market_rows),
    }


def tail_report(rows):
    output = []

    for low, high, label in [
        (0, 3, "0-3"),
        (3, 7, "3-7"),
        (7, 14, "7-14"),
        (14, 21, "14-21"),
        (21, 28, "21-28"),
        (28, 40, "28-40"),
        (40, 999, "40+"),
    ]:
        bucket = [
            g for g in rows
            if g["market_home_spread"] is not None
            and low <= abs(g["market_home_spread"]) < high
        ]

        if not bucket:
            output.append({"range": label, "games": 0})
            continue

        control_errors = []
        v14_errors = []

        for g in bucket:
            # Orient everything from market favorite perspective.
            sign = 1.0 if g["market_home_spread"] < 0 else -1.0
            actual = sign * g["actual_home_margin"]
            control = sign * g["control_margin"]
            v14 = sign * g["v14_margin"]

            control_errors.append(control - actual)
            v14_errors.append(v14 - actual)

        output.append({
            "range": label,
            "games": len(bucket),
            "control_bias": mean(control_errors),
            "v14_bias": mean(v14_errors),
            "control_mae": mean([abs(x) for x in control_errors]),
            "v14_mae": mean([abs(x) for x in v14_errors]),
        })

    return output


def aggregate(folds):
    def weighted(key):
        good = [f for f in folds if finite(f.get(key))]
        denom = sum(f["n"] for f in good)
        if not denom:
            return None
        return sum(f[key] * f["n"] for f in good) / denom

    component_keys = [
        "drives_mae",
        "drives_rmse",
        "scoring_opportunity_rate_mae",
        "scoring_opportunity_rate_rmse",
        "points_per_scoring_opportunity_mae",
        "points_per_scoring_opportunity_rmse",
    ]

    components = {}
    for key in component_keys:
        denom = sum(f["n"] for f in folds)
        components[key] = (
            sum(
                f["component_accuracy"][key] * f["n"]
                for f in folds
            ) / denom
            if denom else None
        )

    tail = []
    labels = ["0-3", "3-7", "7-14", "14-21", "21-28", "28-40", "40+"]

    for label in labels:
        pieces = []
        for fold in folds:
            for item in fold["tail"]:
                if item["range"] == label and item.get("games", 0) > 0:
                    pieces.append(item)

        n = sum(x["games"] for x in pieces)
        if not n:
            tail.append({"range": label, "games": 0})
            continue

        tail.append({
            "range": label,
            "games": n,
            "control_bias": sum(
                x["control_bias"] * x["games"] for x in pieces
            ) / n,
            "v14_bias": sum(
                x["v14_bias"] * x["games"] for x in pieces
            ) / n,
            "control_mae": sum(
                x["control_mae"] * x["games"] for x in pieces
            ) / n,
            "v14_mae": sum(
                x["v14_mae"] * x["games"] for x in pieces
            ) / n,
        })

    return {
        "n": sum(f["n"] for f in folds),
        "control_margin_mae": weighted("control_margin_mae"),
        "control_margin_rmse": weighted("control_margin_rmse"),
        "v14_margin_mae": weighted("v14_margin_mae"),
        "v14_margin_rmse": weighted("v14_margin_rmse"),
        "v14_team_score_mae": weighted("v14_team_score_mae"),
        "v14_total_mae": weighted("v14_total_mae"),
        "v14_total_rmse": weighted("v14_total_rmse"),
        "component_accuracy": components,
        "tail": tail,
    }


def run_config(df, ridge_lambda):
    folds = []

    for train_years, validation_year in FOLDS:
        train = df[df["season"].isin(train_years)]
        val = df[df["season"] == validation_year]

        result = evaluate_fold(
            train,
            val,
            ridge_lambda,
        )
        result["train_years"] = train_years
        result["validation_year"] = validation_year
        folds.append(result)

    return {
        "ridge_lambda": ridge_lambda,
        "folds": folds,
        "aggregate": aggregate(folds),
    }


def round_tree(value):
    if isinstance(value, dict):
        return {k: round_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [round_tree(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else round(float(value), 6)
    if isinstance(value, np.integer):
        return int(value)
    return value


def main():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))

    if audit.get("status") != "PASS":
        raise SystemExit("Historical V4 training audit must PASS first.")

    if audit.get("builder_version") != "historical_training_v4_realized_drives":
        raise SystemExit(
            "V1.4 requires historical_training_v4_realized_drives."
        )

    df = pd.read_csv(DATA)

    # HARD SEAL: 2025 is dropped before model selection/evaluation.
    df = df[df["season"].between(2019, 2024)].copy()

    configs = []

    for lam in RIDGE_LAMBDAS:
        print(
            f"Running V1.4 rolling OOS with lambda={lam}...",
            flush=True,
        )
        configs.append(run_config(df, lam))

    winner = min(
        configs,
        key=lambda x: x["aggregate"]["v14_margin_rmse"],
    )

    a = winner["aggregate"]

    large = [
        item for item in a["tail"]
        if item["range"] in {"21-28", "28-40", "40+"}
        and item.get("games", 0) > 0
    ]

    decision = {
        "v14_beats_control_margin_mae": (
            a["v14_margin_mae"] < a["control_margin_mae"]
        ),
        "v14_beats_control_margin_rmse": (
            a["v14_margin_rmse"] < a["control_margin_rmse"]
        ),
        "v14_improves_large_favorite_bias_all_available_21plus": (
            all(
                abs(x["v14_bias"]) < abs(x["control_bias"])
                for x in large
            )
            if large else None
        ),
    }

    decision["status"] = (
        "ADVANCE_TO_FROZEN_2025_COMPARISON"
        if (
            decision["v14_beats_control_margin_mae"]
            and decision["v14_beats_control_margin_rmse"]
        )
        else "HOLD_V14"
    )

    report = {
        "status": "OOS_COMPLETE",
        "model": "score_engine_v1.4_realized_possession_scoring",
        "dataset": "historical_training_v4_realized_drives",
        "years_used": [2019, 2020, 2021, 2022, 2023, 2024],
        "years_excluded": [2025],
        "leakage_guard": {
            "audit_status": audit.get("status"),
            "2025_read_for_model_selection": False,
            "market_spread_used_as_predictive_feature": False,
            "current_game_actual_drive_targets_used_as_predictive_features": False,
            "rolling_oos_folds": FOLDS,
        },
        "architecture": {
            "equation": (
                "expected_drives * expected_sdv_scoring_opportunity_rate "
                "* expected_points_per_sdv_scoring_opportunity "
                "= expected_points"
            ),
            "scoring_opportunity_definition": (
                "SportsDataverse scoring_opp flag aggregated once per drive, "
                "exactly as preserved by historical training V4."
            ),
            "note": (
                "V1.4 uses REALIZED drive/scoring targets from V4 for training "
                "labels. Pregame prediction inputs use only shifted historical "
                "pregame_* and prev_season_* features."
            ),
            "fixed_prediction_bounds": {
                "expected_drives": [4.0, 23.0],
                "expected_scoring_opportunity_rate": [0.0, 1.0],
                "expected_points_per_scoring_opportunity": [0.0, 7.0],
            },
        },
        "search_space": {
            "ridge_lambdas": RIDGE_LAMBDAS,
            "config_count": len(configs),
        },
        "all_configs": configs,
        "winner": winner,
        "decision": decision,
    }

    OUT.write_text(
        json.dumps(round_tree(report), indent=2),
        encoding="utf-8",
    )

    print("")
    print("=" * 78)
    print("SCORE ENGINE V1.4 OOS COMPLETE")
    print("=" * 78)
    print("Winner lambda:", winner["ridge_lambda"])
    print(
        "Control margin MAE/RMSE:",
        round(a["control_margin_mae"], 4),
        "/",
        round(a["control_margin_rmse"], 4),
    )
    print(
        "V1.4 margin MAE/RMSE:",
        round(a["v14_margin_mae"], 4),
        "/",
        round(a["v14_margin_rmse"], 4),
    )
    print("Team score MAE:", round(a["v14_team_score_mae"], 4))
    print("Total MAE:", round(a["v14_total_mae"], 4))
    print("Decision:", decision["status"])
    print("Wrote:", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
