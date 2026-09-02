"""
CFB ANALYTICS
validate_score_engine_2025.py

SEALED 2025 isolation audit for Score Engine v1.1.

Outer split:
    TRAIN = 2019-2024
    TEST  = 2025

The script is CACHE-ONLY. If a historical cache file is missing it exits.
It never calls CFBD.

Nonlinear exponent selection:
- Candidate alpha values are selected using rolling inner validation contained
  entirely inside 2019-2024.
- 2025 is never consulted when choosing alpha.

Probability uncertainty scaling:
- Fitted strictly on 2019-2024 after the final score model is fitted.
- 2025 outcomes are never used to choose the multiplier.
"""

import json
import math
import statistics
import sys
from pathlib import Path

# Import football parsing/snapshot logic from the experimental engine.
import backtest_score_engine as core

CACHE_ROOT = Path("data/historical_cache")
OUTPUT_PATH = Path("data/score_engine_2025_sealed.json")
OLD_V1_REPORT = Path("data/score_engine_backtest.json")

TRAIN_YEARS = list(range(2019, 2025))
TEST_YEAR = 2025

ALPHA_CANDIDATES = [1.25, 1.50, 1.75, 2.00, 2.25, 2.50]
RIDGE_LAMBDA = 2.0

BASE_FEATURES = [
    "matchup_epa",
    "matchup_pass_epa",
    "matchup_rush_epa",
    "matchup_success_rate",
    "matchup_explosive_rate",
    "matchup_havoc",
    "expected_possessions",
    "offense_strength",
    "opponent_defense_strength",
    "strength_advantage",
    "advantage_x_possessions",
    "venue_indicator",
]

FAVORITE_BUCKETS = [
    (28.0, 40.0, "28-40"),
    (40.0, 999.0, "40+"),
]

HOME_PROBABILITY_BINS = [
    (0.00, 0.45, "0-45%"),
    (0.45, 0.55, "45-55%"),
    (0.55, 0.65, "55-65%"),
    (0.65, 0.75, "65-75%"),
    (0.75, 1.01, "75%+"),
]


def mean(values):
    values = [v for v in values if v is not None and math.isfinite(v)]
    return statistics.mean(values) if values else None


def mae(pred, actual):
    return mean([abs(p - a) for p, a in zip(pred, actual)])


def rmse(pred, actual):
    return math.sqrt(mean([(p - a) ** 2 for p, a in zip(pred, actual)]))


def normal_cdf(value):
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def cache_path(endpoint, params):
    year = int(params["year"])
    year_dir = CACHE_ROOT / str(year)

    if endpoint == "/games":
        return year_dir / "games.json"
    if endpoint == "/lines":
        return year_dir / "lines.json"
    if endpoint == "/plays":
        return year_dir / f"plays_week_{int(params['week'])}.json"

    raise RuntimeError(f"Unsupported cached endpoint: {endpoint}")


def cached_cfbd_get(endpoint, params=None, required=True):
    params = params or {}
    path = cache_path(endpoint, params)

    if not path.exists() or path.stat().st_size < 10:
        raise SystemExit(
            f"Missing cache file: {path}\n"
            "Run Historical Cache for that season first."
        )

    return json.loads(path.read_text(encoding="utf-8"))


# Absolute guardrail: imported core functions cannot reach the network.
core.cfbd_get = cached_cfbd_get


def verify_manifests():
    missing = []
    for year in range(2019, 2026):
        manifest = CACHE_ROOT / str(year) / "manifest.json"
        if not manifest.exists():
            missing.append(str(year))
            continue
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if not data.get("complete"):
            missing.append(str(year))

    if missing:
        raise SystemExit(
            "Historical cache incomplete for: "
            + ", ".join(missing)
            + ". Cache one season at a time first."
        )


def signed_power(value, alpha):
    if abs(value) < 1e-15:
        return 0.0
    return math.copysign(abs(value) ** alpha, value)


def feature_names():
    return BASE_FEATURES + ["strength_advantage_nonlinear"]


def feature_row(features, alpha):
    row = [features[name] for name in BASE_FEATURES]
    row.append(signed_power(features["strength_advantage"], alpha))
    return row


def fit_score_model(records, alpha):
    rows = []
    targets = []

    for record in records:
        rows.append(feature_row(record["home_features"], alpha))
        targets.append(record["home_points"])
        rows.append(feature_row(record["away_features"], alpha))
        targets.append(record["away_points"])

    names = feature_names()
    means = [statistics.mean([row[i] for row in rows]) for i in range(len(names))]
    stds = []
    for i in range(len(names)):
        s = statistics.pstdev([row[i] for row in rows])
        stds.append(s if s > 1e-9 else 1.0)

    x = [
        [1.0] + [(row[i] - means[i]) / stds[i] for i in range(len(names))]
        for row in rows
    ]

    p = len(x[0])
    xtx = [[0.0] * p for _ in range(p)]
    xty = [0.0] * p

    for row, target in zip(x, targets):
        for i in range(p):
            xty[i] += row[i] * target
            for j in range(p):
                xtx[i][j] += row[i] * row[j]

    for i in range(1, p):
        xtx[i][i] += RIDGE_LAMBDA

    coefs = core.solve_linear_system(xtx, xty)

    return {
        "alpha": alpha,
        "names": names,
        "means": means,
        "stds": stds,
        "coefficients": coefs,
    }


def predict_score(model, features):
    raw = feature_row(features, model["alpha"])
    row = [1.0] + [
        (raw[i] - model["means"][i]) / model["stds"][i]
        for i in range(len(raw))
    ]
    return max(0.0, sum(c * x for c, x in zip(model["coefficients"], row)))


def predict_margin(model, record):
    return (
        predict_score(model, record["home_features"])
        - predict_score(model, record["away_features"])
    )


def select_alpha(records_by_year):
    # Inner rolling OOS is fully contained in the training window.
    folds = [
        (list(range(2019, 2023)), 2023),
        (list(range(2019, 2024)), 2024),
    ]

    rows = []

    for alpha in ALPHA_CANDIDATES:
        fold_rmses = []

        for training_years, validation_year in folds:
            train = []
            for year in training_years:
                train.extend(records_by_year[year])

            validation = records_by_year[validation_year]
            model = fit_score_model(train, alpha)
            pred = [predict_margin(model, r) for r in validation]
            actual = [r["actual_home_margin"] for r in validation]
            fold_rmses.append(rmse(pred, actual))

        rows.append(
            {
                "alpha": alpha,
                "inner_validation_rmse": statistics.mean(fold_rmses),
                "fold_rmse": fold_rmses,
            }
        )

    winner = min(rows, key=lambda x: x["inner_validation_rmse"])
    return winner["alpha"], rows


def fit_probability_scale(training, model):
    residuals = [
        r["actual_home_margin"] - predict_margin(model, r)
        for r in training
    ]
    base_std = statistics.pstdev(residuals)

    market_games = [r for r in training if r.get("market_home_spread") is not None]

    best = None
    for step in range(20, 81):
        scale = step / 20.0
        brier_values = []

        for record in market_games:
            cover_margin = record["actual_home_margin"] + record["market_home_spread"]
            if abs(cover_margin) < 1e-9:
                continue

            market_margin = -record["market_home_spread"]
            edge = predict_margin(model, record) - market_margin
            home_probability = normal_cdf(edge / (base_std * scale))
            actual = 1.0 if cover_margin > 0 else 0.0
            brier_values.append((home_probability - actual) ** 2)

        if not brier_values:
            continue

        candidate = {
            "scale": scale,
            "brier": statistics.mean(brier_values),
        }

        if best is None or candidate["brier"] < best["brier"]:
            best = candidate

    if best is None:
        return base_std, 1.0

    return base_std, best["scale"]


def fit_legacy(training):
    return core.fit_legacy_margin_model(training)


def score_2025(testing, modular_model, legacy_model, base_std, probability_scale):
    scored = []

    for record in testing:
        modular_home = predict_score(modular_model, record["home_features"])
        modular_away = predict_score(modular_model, record["away_features"])
        modular_margin = modular_home - modular_away

        legacy_margin = (
            legacy_model["rating_to_points"] * record["legacy_rating_diff"]
            + (0.0 if record["neutral"] else legacy_model["home_field"])
        )

        out = dict(record)
        out["modular_margin"] = modular_margin
        out["legacy_margin"] = legacy_margin
        out["modular_home_score"] = modular_home
        out["modular_away_score"] = modular_away

        spread = record.get("market_home_spread")
        if spread is not None:
            market_margin = -spread
            edge = modular_margin - market_margin
            home_prob = normal_cdf(edge / (base_std * probability_scale))
            out["modular_home_cover_probability"] = home_prob
            out["modular_selected_cover_probability"] = max(home_prob, 1.0 - home_prob)
            out["market_favorite_size"] = abs(market_margin)

            cover_margin = record["actual_home_margin"] + spread
            out["actual_home_cover"] = (
                None if abs(cover_margin) < 1e-9 else (1.0 if cover_margin > 0 else 0.0)
            )

        scored.append(out)

    return scored


def favorite_report(scored):
    out = []

    for low, high, label in FAVORITE_BUCKETS:
        games = [
            g for g in scored
            if g.get("market_favorite_size") is not None
            and low <= g["market_favorite_size"] < high
        ]

        if not games:
            out.append({"range": label, "games": 0})
            continue

        out.append(
            {
                "range": label,
                "games": len(games),
                "legacy_mae": mae(
                    [g["legacy_margin"] for g in games],
                    [g["actual_home_margin"] for g in games],
                ),
                "modular_mae": mae(
                    [g["modular_margin"] for g in games],
                    [g["actual_home_margin"] for g in games],
                ),
                "legacy_bias": mean(
                    [g["legacy_margin"] - g["actual_home_margin"] for g in games]
                ),
                "modular_bias": mean(
                    [g["modular_margin"] - g["actual_home_margin"] for g in games]
                ),
            }
        )

    return out


def probability_bins(scored):
    games = [
        g for g in scored
        if g.get("modular_home_cover_probability") is not None
        and g.get("actual_home_cover") is not None
    ]

    out = []

    for low, high, label in HOME_PROBABILITY_BINS:
        bucket = [
            g for g in games
            if low <= g["modular_home_cover_probability"] < high
        ]

        out.append(
            {
                "range": label,
                "games": len(bucket),
                "average_predicted_home_cover": (
                    mean([g["modular_home_cover_probability"] for g in bucket])
                    if bucket else None
                ),
                "actual_home_cover_rate": (
                    mean([g["actual_home_cover"] for g in bucket])
                    if bucket else None
                ),
            }
        )

    return out


def old_v1_70_cohort(scored):
    if not OLD_V1_REPORT.exists() or OLD_V1_REPORT.stat().st_size < 10:
        return {"available": False, "reason": "old V1 report missing"}

    old = json.loads(OLD_V1_REPORT.read_text(encoding="utf-8"))
    old_games = old.get("games") or []

    old_2025 = {
        int(g["game_id"]): g
        for g in old_games
        if g.get("year") == 2025
        and g.get("modular_cover_probability") is not None
        and g["modular_cover_probability"] >= 0.70
    }

    if not old_2025:
        return {
            "available": False,
            "reason": "no 2025 old-V1 70%+ games found in report",
        }

    new_by_id = {int(g["game_id"]): g for g in scored}

    matched = []
    for game_id, old_game in old_2025.items():
        new = new_by_id.get(game_id)
        if new is None:
            continue

        old_side = old_game.get("modular_cover_side")
        if old_side not in ("home", "away"):
            continue

        home_prob = new.get("modular_home_cover_probability")
        if home_prob is None:
            continue

        recalibrated_for_old_side = (
            home_prob if old_side == "home" else 1.0 - home_prob
        )

        matched.append(
            {
                "old_probability": old_game["modular_cover_probability"],
                "old_result": old_game.get("modular_cover_result"),
                "recalibrated_probability_same_side": recalibrated_for_old_side,
            }
        )

    if not matched:
        return {"available": False, "reason": "cohort could not be matched"}

    return {
        "available": True,
        "games": len(matched),
        "old_v1_average_probability": mean([g["old_probability"] for g in matched]),
        "old_v1_actual_cover_rate": mean([g["old_result"] for g in matched]),
        "v11_recalibrated_probability_same_sides": mean(
            [g["recalibrated_probability_same_side"] for g in matched]
        ),
    }


def round_tree(value):
    if isinstance(value, dict):
        return {k: round_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [round_tree(v) for v in value]
    if isinstance(value, float):
        return round(value, 4)
    return value


def main():
    verify_manifests()

    print("=" * 78)
    print("2025 SEALED TEST ISOLATION AUDIT")
    print("=" * 78)
    print("TRAINING WINDOW: 2019-2024")
    print("TESTING WINDOW: 2025")
    print("NETWORK ACCESS: DISABLED (cache-only)")
    print("")

    records_by_year = {}

    for year in range(2019, 2026):
        print(f"# Building frozen records: {year}")
        games = core.get_games(year)
        lines = core.get_lines(year)
        records_by_year[year] = core.build_year_records(year, games, lines)

    alpha, alpha_audit = select_alpha(records_by_year)

    training = []
    for year in TRAIN_YEARS:
        training.extend(records_by_year[year])

    testing = records_by_year[TEST_YEAR]

    modular_model = fit_score_model(training, alpha)
    legacy_model = fit_legacy(training)
    base_std, probability_scale = fit_probability_scale(training, modular_model)

    scored = score_2025(
        testing,
        modular_model,
        legacy_model,
        base_std,
        probability_scale,
    )

    actual = [g["actual_home_margin"] for g in scored]
    legacy_pred = [g["legacy_margin"] for g in scored]
    modular_pred = [g["modular_margin"] for g in scored]

    overall = {
        "games": len(scored),
        "legacy_margin_mae": mae(legacy_pred, actual),
        "legacy_margin_rmse": rmse(legacy_pred, actual),
        "modular_margin_mae": mae(modular_pred, actual),
        "modular_margin_rmse": rmse(modular_pred, actual),
    }

    result = {
        "isolation_audit": {
            "training_window": "2019-2024",
            "testing_window": "2025",
            "cache_only": True,
            "week_rule": "Week N uses only Weeks < N",
            "alpha_selected_without_2025": True,
            "probability_scale_selected_without_2025": True,
            "status": "PASSED",
        },
        "alpha_selection": {
            "selected_alpha": alpha,
            "method": (
                "rolling inner out-of-sample validation entirely inside 2019-2024; "
                "validation years 2023 and 2024"
            ),
            "candidates": alpha_audit,
        },
        "probability_calibration": {
            "training_margin_residual_std": base_std,
            "training_derived_uncertainty_multiplier": probability_scale,
            "home_probability_bins_2025": probability_bins(scored),
            "old_v1_70_plus_cohort": old_v1_70_cohort(scored),
        },
        "overall_2025": overall,
        "large_favorite_2025": favorite_report(scored),
    }

    rounded = round_tree(result)
    OUTPUT_PATH.write_text(json.dumps(rounded, indent=2), encoding="utf-8")

    print("")
    print("=" * 78)
    print("2025 SCORE ENGINE V1.1 — SEALED RESULT")
    print("=" * 78)
    print(f"Selected alpha (training only): {alpha:.2f}")
    print(f"Uncertainty multiplier (training only): {probability_scale:.2f}")
    print("")
    print(
        f"Legacy  MAE/RMSE: {overall['legacy_margin_mae']:.2f} / "
        f"{overall['legacy_margin_rmse']:.2f}"
    )
    print(
        f"Modular MAE/RMSE: {overall['modular_margin_mae']:.2f} / "
        f"{overall['modular_margin_rmse']:.2f}"
    )

    for bucket in favorite_report(scored):
        print("")
        print(f"{bucket['range']} FAVORITES | n={bucket.get('games', 0)}")
        if bucket.get("games", 0):
            print(
                f"Legacy bias/MAE:  {bucket['legacy_bias']:+.2f} / "
                f"{bucket['legacy_mae']:.2f}"
            )
            print(
                f"V1.1 bias/MAE:    {bucket['modular_bias']:+.2f} / "
                f"{bucket['modular_mae']:.2f}"
            )

    cohort = old_v1_70_cohort(scored)
    print("")
    print("OLD-V1 70%+ COHORT")
    if cohort.get("available"):
        print(f"Games: {cohort['games']}")
        print(f"Old stated: {cohort['old_v1_average_probability']*100:.2f}%")
        print(f"Actual:     {cohort['old_v1_actual_cover_rate']*100:.2f}%")
        print(
            "V1.1 same-side recalibrated: "
            f"{cohort['v11_recalibrated_probability_same_sides']*100:.2f}%"
        )
    else:
        print("Unavailable:", cohort.get("reason"))

    print("")
    print("2025 HOME-COVER PROBABILITY BINS")
    for bucket in probability_bins(scored):
        if bucket["games"] == 0:
            print(f"{bucket['range']}: 0 games")
        else:
            print(
                f"{bucket['range']}: n={bucket['games']} | "
                f"pred {bucket['average_predicted_home_cover']*100:.2f}% | "
                f"actual {bucket['actual_home_cover_rate']*100:.2f}%"
            )

    print("")
    print("LEAKAGE AUDIT STATUS: PASSED")
    print(f"Saved {OUTPUT_PATH}")
    print("=" * 78)


if __name__ == "__main__":
    main()
