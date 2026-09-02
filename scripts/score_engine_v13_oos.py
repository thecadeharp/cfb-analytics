"""
CFB ANALYTICS
score_engine_v13_oos.py

Score Engine V1.3 — possession/scoring-opportunity architecture.

This experiment NEVER reads 2025.

Instead of directly regressing final points from one large feature vector,
V1.3 decomposes team scoring into football mechanisms:

    expected drives
      -> expected scoring opportunities per drive
      -> expected points per scoring opportunity
      -> expected team points
      -> projected margin / total

Rolling out-of-sample validation:
    train 2019-2021 -> validate 2022
    train 2019-2022 -> validate 2023
    train 2019-2023 -> validate 2024

Comparison:
    linear margin control
    V1.1 score baseline
    V1.3 possession/scoring engine

Market spread is evaluation-only and never predictive.

Writes:
    data/training/score_engine_v13_oos.json
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
OUT = ROOT / "data" / "training" / "score_engine_v13_oos.json"

FOLDS = [
    ([2019, 2020, 2021], 2022),
    ([2019, 2020, 2021, 2022], 2023),
    ([2019, 2020, 2021, 2022, 2023], 2024),
]

RIDGE_LAMBDAS = [0.5, 1.0, 2.0, 4.0, 8.0]

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
    vals = [abs(p-a) for p, a in zip(pred, actual) if finite(p) and finite(a)]
    return float(np.mean(vals)) if vals else None


def rmse(pred, actual):
    vals = [(p-a)**2 for p, a in zip(pred, actual) if finite(p) and finite(a)]
    return float(math.sqrt(np.mean(vals))) if vals else None


def blended(row, side, metric):
    cur = row.get(f"{side}_pregame_{metric}")
    prev = row.get(f"{side}_prev_season_{metric}")
    if finite(cur):
        return float(cur)
    if finite(prev):
        return float(prev)
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


def matchup(row, offense_side, defense_side):
    names = {
        "off_epa": ("off_epa", offense_side),
        "off_success": ("off_success_rate", offense_side),
        "off_explosive": ("off_explosive_rate", offense_side),
        "off_pass": ("off_pass_epa", offense_side),
        "off_rush": ("off_rush_epa", offense_side),
        "havoc_allowed": ("havoc_allowed_rate", offense_side),
        "line_yards": ("line_yards_per_rush", offense_side),
        "scoring_rate": ("scoring_opp_rate", offense_side),
        "drives": ("drives", offense_side),
        "plays_per_drive": ("plays_per_drive", offense_side),

        "def_epa": ("def_epa_allowed", defense_side),
        "def_success": ("def_success_allowed", defense_side),
        "def_explosive": ("def_explosive_allowed", defense_side),
        "def_pass": ("def_pass_epa_allowed", defense_side),
        "def_rush": ("def_rush_epa_allowed", defense_side),
        "havoc_created": ("def_havoc_created_rate", defense_side),
        "def_line_yards": ("def_line_yards_allowed", defense_side),
        "def_scoring_rate": ("def_scoring_opp_allowed", defense_side),
    }

    m = {}
    for key, (metric, side) in names.items():
        val = blended(row, side, metric)
        if not finite(val):
            return None
        m[key] = val

    m["epa_mismatch"] = m["off_epa"] - m["def_epa"]
    m["success_mismatch"] = m["off_success"] - m["def_success"]
    m["explosive_mismatch"] = m["off_explosive"] - m["def_explosive"]
    m["pass_mismatch"] = m["off_pass"] - m["def_pass"]
    m["rush_mismatch"] = m["off_rush"] - m["def_rush"]
    m["havoc_mismatch"] = m["havoc_created"] - m["havoc_allowed"]
    m["line_mismatch"] = m["line_yards"] - m["def_line_yards"]
    m["scoring_rate_mismatch"] = m["scoring_rate"] - m["def_scoring_rate"]

    return m


def drive_features(row, offense_side, defense_side, is_home):
    m = matchup(row, offense_side, defense_side)
    if m is None:
        return None

    return [
        m["drives"],
        m["plays_per_drive"],
        m["off_success"],
        m["def_success"],
        m["success_mismatch"],
        m["havoc_allowed"],
        m["havoc_created"],
        m["havoc_mismatch"],
        m["off_epa"],
        m["def_epa"],
        1.0 if is_home else -1.0,
    ]


def scoring_rate_features(row, offense_side, defense_side, is_home):
    m = matchup(row, offense_side, defense_side)
    if m is None:
        return None

    return [
        m["scoring_rate"],
        m["def_scoring_rate"],
        m["scoring_rate_mismatch"],
        m["off_epa"],
        m["def_epa"],
        m["epa_mismatch"],
        m["off_success"],
        m["def_success"],
        m["success_mismatch"],
        m["off_explosive"],
        m["def_explosive"],
        m["explosive_mismatch"],
        m["havoc_allowed"],
        m["havoc_created"],
        m["havoc_mismatch"],
        m["line_yards"],
        m["def_line_yards"],
        m["line_mismatch"],
        1.0 if is_home else -1.0,
    ]


def conversion_features(row, offense_side, defense_side, is_home):
    m = matchup(row, offense_side, defense_side)
    if m is None:
        return None

    # Conversion is driven by efficiency and explosive ability once an offense
    # creates a scoring opportunity. This intentionally differs from the
    # opportunity-creation model.
    return [
        m["off_epa"],
        m["def_epa"],
        m["epa_mismatch"],
        m["off_pass"],
        m["def_pass"],
        m["pass_mismatch"],
        m["off_rush"],
        m["def_rush"],
        m["rush_mismatch"],
        m["off_success"],
        m["def_success"],
        m["success_mismatch"],
        m["off_explosive"],
        m["def_explosive"],
        m["explosive_mismatch"],
        m["havoc_allowed"],
        m["havoc_created"],
        m["havoc_mismatch"],
        1.0 if is_home else -1.0,
    ]


def control_vector(row):
    vals = []
    for metric in CONTROL_METRICS:
        h = blended(row, "home", metric)
        a = blended(row, "away", metric)
        if not finite(h) or not finite(a):
            return None
        vals.append(h-a)
    vals.append(1.0)
    return vals


def infer_game_targets(row, side):
    """
    Historical builder exposes scoring_opp_rate and drives as pregame features,
    but the canonical game row does not necessarily expose direct final
    scoring-opportunity counts. For training the decomposition, infer the
    realized game opportunity count from the team's points using a conservative
    football identity:

      points = scoring opportunities * points per opportunity

    We avoid pretending this inferred count is observed. The decomposition is
    used as a latent mechanism model, and the final evaluation remains on
    actual points/margin.

    The latent opportunity target is anchored by points / 4.5 and bounded by
    plausible drive count. Conversion target then exactly reconciles to points.
    """
    points = float(row[f"{side}_score"])

    # Actual game drive count is not stored directly in the canonical row;
    # use a broad plausible opportunity count derived only from the outcome
    # during TRAINING. It is never available to prediction features.
    opps = max(1.0, points / 4.5) if points > 0 else 0.0
    ppso = (points / opps) if opps > 0 else 0.0

    return opps, ppso


def fit_component_models(training, ridge_lambda):
    x_drive, y_drive = [], []
    x_rate, y_rate = [], []
    x_conv, y_conv = [], []

    for _, row in training.iterrows():
        for side, opp, home_flag in [
            ("home", "away", True),
            ("away", "home", False),
        ]:
            d = drive_features(row, side, opp, home_flag)
            r = scoring_rate_features(row, side, opp, home_flag)
            c = conversion_features(row, side, opp, home_flag)
            if d is None or r is None or c is None:
                continue

            # Pregame expected drive environment target:
            # use realized score-derived latent opportunities only for
            # opportunity/conversion training; drive model learns historical
            # pregame drive tendency as a stabilizing environment component.
            drive_target = blended(row, side, "drives")
            if not finite(drive_target):
                continue

            opps, ppso = infer_game_targets(row, side)

            x_drive.append(d)
            y_drive.append(drive_target)

            # Latent scoring opportunities per expected drive.
            rate_target = opps / max(float(drive_target), 1.0)
            x_rate.append(r)
            y_rate.append(rate_target)

            x_conv.append(c)
            y_conv.append(ppso)

    if len(x_drive) < 100:
        raise RuntimeError("Too few V1.3 component rows.")

    return {
        "drive": ridge_fit(x_drive, y_drive, ridge_lambda),
        "rate": ridge_fit(x_rate, y_rate, ridge_lambda),
        "conversion": ridge_fit(x_conv, y_conv, ridge_lambda),
    }


def predict_team_points(models, row, offense_side, defense_side, is_home):
    d = drive_features(row, offense_side, defense_side, is_home)
    r = scoring_rate_features(row, offense_side, defense_side, is_home)
    c = conversion_features(row, offense_side, defense_side, is_home)

    if d is None or r is None or c is None:
        return None

    expected_drives = ridge_predict(models["drive"], d)
    scoring_rate = ridge_predict(models["rate"], r)
    points_per_opp = ridge_predict(models["conversion"], c)

    # Football-plausibility bounds, fixed before any 2025 evaluation.
    expected_drives = float(np.clip(expected_drives, 6.0, 18.0))
    scoring_rate = float(np.clip(scoring_rate, 0.0, 0.85))
    points_per_opp = float(np.clip(points_per_opp, 2.0, 7.0))

    expected_opps = expected_drives * scoring_rate
    points = expected_opps * points_per_opp

    return {
        "points": max(0.0, points),
        "expected_drives": expected_drives,
        "scoring_rate": scoring_rate,
        "expected_scoring_opportunities": expected_opps,
        "points_per_scoring_opportunity": points_per_opp,
    }


def fit_control(training, ridge_lambda=2.0):
    x, y = [], []
    for _, row in training.iterrows():
        vec = control_vector(row)
        if vec is None:
            continue
        x.append(vec)
        y.append(float(row["actual_home_margin"]))
    return ridge_fit(x, y, ridge_lambda)


def evaluate_fold(train, val, ridge_lambda):
    models = fit_component_models(train, ridge_lambda)
    control = fit_control(train)

    margins, actual_margins, control_margins = [], [], []
    team_errors, total_pred, total_actual = [], [], []
    rows = []

    for _, row in val.iterrows():
        home = predict_team_points(models, row, "home", "away", True)
        away = predict_team_points(models, row, "away", "home", False)
        cv = control_vector(row)

        if home is None or away is None or cv is None:
            continue

        control_margin = ridge_predict(control, cv)
        margin = home["points"] - away["points"]
        actual_margin = float(row["actual_home_margin"])

        margins.append(margin)
        actual_margins.append(actual_margin)
        control_margins.append(control_margin)

        team_errors.extend([
            abs(home["points"] - float(row["home_score"])),
            abs(away["points"] - float(row["away_score"])),
        ])
        total_pred.append(home["points"] + away["points"])
        total_actual.append(float(row["actual_total"]))

        rows.append({
            "market_home_spread": (
                float(row["market_home_spread"])
                if pd.notna(row["market_home_spread"])
                else None
            ),
            "actual_home_margin": actual_margin,
            "control_margin": control_margin,
            "v13_margin": margin,
        })

    return {
        "n": len(margins),
        "control_margin_mae": mae(control_margins, actual_margins),
        "control_margin_rmse": rmse(control_margins, actual_margins),
        "v13_margin_mae": mae(margins, actual_margins),
        "v13_margin_rmse": rmse(margins, actual_margins),
        "v13_team_score_mae": mean(team_errors),
        "v13_total_mae": mae(total_pred, total_actual),
        "tail": tail_report(rows),
    }


def tail_report(rows):
    out = []
    for low, high, label in [
        (21, 28, "21-28"),
        (28, 40, "28-40"),
        (40, 999, "40+"),
    ]:
        bucket = []
        for g in rows:
            spread = g["market_home_spread"]
            if spread is None:
                continue
            if low <= abs(spread) < high:
                bucket.append(g)

        if not bucket:
            out.append({"range": label, "games": 0})
            continue

        cb, vb = [], []
        for g in bucket:
            sign = 1.0 if g["market_home_spread"] < 0 else -1.0
            actual = sign * g["actual_home_margin"]
            cb.append(sign * g["control_margin"] - actual)
            vb.append(sign * g["v13_margin"] - actual)

        out.append({
            "range": label,
            "games": len(bucket),
            "control_bias": mean(cb),
            "v13_bias": mean(vb),
        })
    return out


def aggregate(folds):
    def weighted(key):
        good = [f for f in folds if finite(f.get(key))]
        n = sum(f["n"] for f in good)
        return sum(f[key] * f["n"] for f in good) / n if n else None

    tails = []
    for label in ["21-28", "28-40", "40+"]:
        items = []
        for f in folds:
            for t in f["tail"]:
                if t["range"] == label and t.get("games", 0):
                    items.append(t)
        n = sum(t["games"] for t in items)
        if not n:
            tails.append({"range": label, "games": 0})
        else:
            tails.append({
                "range": label,
                "games": n,
                "control_bias": sum(t["control_bias"]*t["games"] for t in items)/n,
                "v13_bias": sum(t["v13_bias"]*t["games"] for t in items)/n,
            })

    return {
        "n": sum(f["n"] for f in folds),
        "control_margin_mae": weighted("control_margin_mae"),
        "control_margin_rmse": weighted("control_margin_rmse"),
        "v13_margin_mae": weighted("v13_margin_mae"),
        "v13_margin_rmse": weighted("v13_margin_rmse"),
        "v13_team_score_mae": weighted("v13_team_score_mae"),
        "v13_total_mae": weighted("v13_total_mae"),
        "tail": tails,
    }


def run_config(df, ridge_lambda):
    folds = []
    for train_years, val_year in FOLDS:
        train = df[df["season"].isin(train_years)]
        val = df[df["season"] == val_year]
        result = evaluate_fold(train, val, ridge_lambda)
        result["train_years"] = train_years
        result["validation_year"] = val_year
        folds.append(result)

    return {
        "ridge_lambda": ridge_lambda,
        "folds": folds,
        "aggregate": aggregate(folds),
    }


def round_tree(v):
    if isinstance(v, dict):
        return {k: round_tree(x) for k, x in v.items()}
    if isinstance(v, list):
        return [round_tree(x) for x in v]
    if isinstance(v, (float, np.floating)):
        return None if not np.isfinite(v) else round(float(v), 6)
    if isinstance(v, np.integer):
        return int(v)
    return v


def main():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    if audit.get("status") != "PASS":
        raise SystemExit("Historical training audit must PASS.")

    df = pd.read_csv(DATA)

    # Hard seal. 2025 is discarded before any modeling.
    df = df[df["season"].between(2019, 2024)].copy()

    configs = []
    for lam in RIDGE_LAMBDAS:
        print(f"Running V1.3 rolling OOS lambda={lam}...", flush=True)
        configs.append(run_config(df, lam))

    winner = min(
        configs,
        key=lambda x: x["aggregate"]["v13_margin_rmse"],
    )

    a = winner["aggregate"]

    tail_ok = []
    for t in a["tail"]:
        if t.get("games", 0):
            tail_ok.append(abs(t["v13_bias"]) < abs(t["control_bias"]))

    decision = {
        "v13_beats_control_margin_mae":
            a["v13_margin_mae"] < a["control_margin_mae"],
        "v13_beats_control_margin_rmse":
            a["v13_margin_rmse"] < a["control_margin_rmse"],
        "v13_improves_control_large_favorite_bias_all_available_21plus":
            all(tail_ok) if tail_ok else None,
    }

    decision["status"] = (
        "ADVANCE_TO_FROZEN_2025_COMPARISON"
        if (
            decision["v13_beats_control_margin_mae"]
            and decision["v13_beats_control_margin_rmse"]
        )
        else "HOLD_V13"
    )

    report = {
        "status": "OOS_COMPLETE",
        "model": "score_engine_v1.3_possession_scoring_opportunity",
        "dataset": "historical_training_v3_sportsdataverse_espn",
        "years_used": [2019, 2020, 2021, 2022, 2023, 2024],
        "years_excluded": [2025],
        "leakage_guard": {
            "2025_read_for_model_selection": False,
            "market_spread_used_as_predictive_feature": False,
            "rolling_oos_folds": FOLDS,
        },
        "architecture": {
            "equation": (
                "expected_drives * scoring_opportunity_rate * "
                "points_per_scoring_opportunity = expected_points"
            ),
            "note": (
                "Scoring opportunities are latent training targets inferred "
                "from final points because direct realized opportunity counts "
                "are not currently preserved in the canonical game table. "
                "They are never prediction inputs."
            ),
            "fixed_bounds": {
                "expected_drives": [6.0, 18.0],
                "scoring_opportunity_rate": [0.0, 0.85],
                "points_per_scoring_opportunity": [2.0, 7.0],
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

    print("="*78)
    print("SCORE ENGINE V1.3 OOS COMPLETE")
    print("="*78)
    print("Winner lambda:", winner["ridge_lambda"])
    print(
        "Control MAE/RMSE:",
        round(a["control_margin_mae"], 4),
        "/",
        round(a["control_margin_rmse"], 4),
    )
    print(
        "V1.3 MAE/RMSE:",
        round(a["v13_margin_mae"], 4),
        "/",
        round(a["v13_margin_rmse"], 4),
    )
    print("V1.3 team score MAE:", round(a["v13_team_score_mae"], 4))
    print("V1.3 total MAE:", round(a["v13_total_mae"], 4))
    print("Decision:", decision["status"])
    print("Wrote:", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
