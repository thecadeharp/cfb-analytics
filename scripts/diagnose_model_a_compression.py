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

FROZEN = DATA / "frozen" / "2026_week1_modelA_frozen.json"
HISTORICAL = DATA / "training" / "historical_games.csv"
HFA = DATA / "hfa_2026.json"

REPORT_DIR = DATA / "reports"
REPORT_JSON = REPORT_DIR / "model_a_compression_diagnostic.json"
REPORT_TXT = REPORT_DIR / "model_a_compression_diagnostic.txt"

PRODUCTION_SCALE = 10.4245
INPUT_COMPRESSION_THRESHOLD = 0.85
FIRST_TEST_YEAR = 2022

WEIGHTS = {
    "net_epa": 0.30,
    "net_epa_pass": 0.15,
    "net_epa_rush": 0.15,
    "net_sr": 0.10,
    "def_havoc_created": 0.20,
    "off_havoc_allowed": 0.10,
}

FAVORITE_BUCKETS = [
    (0.0, 7.0, "0-7"),
    (7.0, 14.0, "7-14"),
    (14.0, 21.0, "14-21"),
    (21.0, 28.0, "21-28"),
    (28.0, 40.0, "28-40"),
    (40.0, float("inf"), "40+"),
]

RATING_BUCKETS = [
    (0.0, 1.0, "0-1.0"),
    (1.0, 1.5, "1.0-1.5"),
    (1.5, 2.0, "1.5-2.0"),
    (2.0, 2.5, "2.0-2.5"),
    (2.5, 3.0, "2.5-3.0"),
    (3.0, float("inf"), "3.0+"),
]

FOCUS_GAMES = [
    ("Alabama", "East Carolina"),
    ("Oklahoma", "UTEP"),
    ("Texas", "Texas State"),
    ("Indiana", "North Texas"),
    ("USC", "Fresno State"),
    ("Miami", "Stanford"),
    ("West Virginia", "Coastal Carolina"),
    ("Houston", "Oregon State"),
]


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def num(v):
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def avg(values):
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return statistics.fmean(vals) if vals else None


def sd(values):
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return statistics.pstdev(vals) if len(vals) >= 2 else None


def mae(errors):
    return avg([abs(e) for e in errors if e is not None])


def rmse(errors):
    vals = [e * e for e in errors if e is not None]
    return math.sqrt(avg(vals)) if vals else None



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


def solve_3x3(A, b):
    M = [list(map(float, A[i])) + [float(b[i])] for i in range(3)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-12:
            raise ValueError("Singular matrix")
        M[col], M[pivot] = M[pivot], M[col]
        pivot_value = M[col][col]
        M[col] = [x / pivot_value for x in M[col]]
        for r in range(3):
            if r == col:
                continue
            factor = M[r][col]
            M[r] = [M[r][c] - factor * M[col][c] for c in range(4)]
    return [M[i][3] for i in range(3)]


def quadratic_fit(xs, ys):
    pairs = [
        (float(x), float(y))
        for x, y in zip(xs, ys)
        if x is not None and y is not None
        and math.isfinite(float(x)) and math.isfinite(float(y))
    ]
    n = len(pairs)
    if n < 30:
        return None

    sx = sum(x for x, _ in pairs)
    sx2 = sum(x*x for x, _ in pairs)
    sx3 = sum(x*x*x for x, _ in pairs)
    sx4 = sum(x*x*x*x for x, _ in pairs)
    sy = sum(y for _, y in pairs)
    sxy = sum(x*y for x, y in pairs)
    sx2y = sum(x*x*y for x, y in pairs)

    XTX = [[n, sx, sx2], [sx, sx2, sx3], [sx2, sx3, sx4]]
    c, b, a = solve_3x3(XTX, [sy, sxy, sx2y])

    preds = [c + b*x + a*x*x for x, _ in pairs]
    residuals = [y - p for (_, y), p in zip(pairs, preds)]
    sse = sum(r*r for r in residuals)
    ybar = avg([y for _, y in pairs])
    sst = sum((y-ybar)**2 for _, y in pairs)
    r2 = 1.0 - sse/sst if sst > 0 else None

    inv_cols = [
        solve_3x3(XTX, [1,0,0]),
        solve_3x3(XTX, [0,1,0]),
        solve_3x3(XTX, [0,0,1]),
    ]
    inv = [[inv_cols[j][i] for j in range(3)] for i in range(3)]
    sigma2 = sse / (n - 3)
    se_a = math.sqrt(max(0.0, sigma2 * inv[2][2]))
    t_a = a / se_a if se_a > 0 else None

    return {
        "n": n,
        "quadratic_a": a,
        "linear_b": b,
        "intercept_c": c,
        "r2": r2,
        "se_a": se_a,
        "t_a": t_a,
        "quadratic_significant_approx_95": abs(t_a) >= 1.96 if t_a is not None else None,
    }


def parse_hfa():
    obj = load_json(HFA)
    source = obj.get("teams", obj) if isinstance(obj, dict) else {}
    out = {}
    if isinstance(source, dict):
        for team, value in source.items():
            if isinstance(value, dict):
                h = num(value.get("hfa", value.get("home_field_advantage", value.get("value"))))
            else:
                h = num(value)
            if h is not None:
                out[str(team)] = h
    return out


def current_projection_rows():
    obj = load_json(FROZEN)
    if isinstance(obj, dict) and isinstance(obj.get("games"), list):
        raw = obj["games"]
    elif isinstance(obj, list):
        raw = obj
    else:
        raw = []

    rows, seen = [], set()
    for g in raw:
        if not isinstance(g, dict):
            continue
        home_obj = g.get("home") or {}
        away_obj = g.get("away") or {}
        proj = g.get("projection") or {}
        market = g.get("market") or {}
        comp = proj.get("components") or {}
        matchup = proj.get("matchup_adjustment") or comp.get("matchup_adjustment") or {}

        home = home_obj.get("team")
        away = away_obj.get("team")
        model_spread = num(proj.get("home_spread"))
        market_spread = num(market.get("home_spread"))
        if not home or not away or model_spread is None:
            continue

        signature = (str(g.get("game_id")), home, away)
        if signature in seen:
            continue
        seen.add(signature)

        home_rating = num(home_obj.get("power_rating"))
        away_rating = num(away_obj.get("power_rating"))
        rating_diff = num(comp.get("rating_difference"))
        if rating_diff is None and home_rating is not None and away_rating is not None:
            rating_diff = home_rating - away_rating

        rows.append({
            "game_id": g.get("game_id"),
            "week": g.get("week"),
            "home": home,
            "away": away,
            "neutral_site": bool(g.get("neutral_site", False)),
            "home_rating": home_rating,
            "away_rating": away_rating,
            "rating_difference_home_minus_away": rating_diff,
            "rating_points_home_edge": num(comp.get("rating_points_home_edge")),
            "home_field_advantage": num(comp.get("home_field_advantage", proj.get("home_field_advantage"))),
            "matchup_adjustment": num(matchup.get("total")) if isinstance(matchup, dict) else None,
            "model_home_spread": model_spread,
            "market_home_spread": market_spread,
            "signal": (g.get("comparison") or {}).get("signal"),
            "disagreement": num((g.get("comparison") or {}).get("disagreement")),
        })
    return rows


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


def load_historical_base():
    games = []
    snapshots_by_year_week = defaultdict(dict)

    with HISTORICAL.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required_cols = {
            "game_id", "season", "week", "home_team", "away_team",
            "actual_home_margin", "market_home_spread",
            "home_pregame_off_epa", "home_pregame_def_epa_allowed",
            "away_pregame_off_epa", "away_pregame_def_epa_allowed",
        }
        missing = required_cols - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(
                f"Historical CSV missing required columns: {sorted(missing)}"
            )

        for row in reader:
            year = num(row.get("season"))
            week = num(row.get("week"))
            actual_margin = num(row.get("actual_home_margin"))
            market_spread = num(row.get("market_home_spread"))
            home = row.get("home_team")
            away = row.get("away_team")

            if None in (year, week, actual_margin) or not home or not away:
                continue

            year = int(year)
            week = int(week)

            home_snap = snapshot_from_csv_row(row, "home")
            away_snap = snapshot_from_csv_row(row, "away")
            if home_snap is not None:
                snapshots_by_year_week[(year, week)][home] = home_snap
            if away_snap is not None:
                snapshots_by_year_week[(year, week)][away] = away_snap

            games.append({
                "game_id": row.get("game_id"),
                "year": year,
                "week": week,
                "home": home,
                "away": away,
                "actual_home_margin": actual_margin,
                "market_home_spread": market_spread,
            })

    return games, snapshots_by_year_week


def build_week_ratings(snapshots):
    if len(snapshots) < 20:
        return {}

    component_z = {}
    for component in WEIGHTS:
        component_z[component] = z_scores({
            team: snap.get(component)
            for team, snap in snapshots.items()
        })

    ratings = {}
    for team in snapshots:
        rating = 0.0
        for component, weight in WEIGHTS.items():
            z = component_z[component].get(team, 0.0)
            if component == "off_havoc_allowed":
                z *= -1.0
            rating += z * weight
        ratings[team] = rating
    return ratings


def build_historical_rating_records():
    games, snapshots_by_year_week = load_historical_base()
    ratings_by_year_week = {
        key: build_week_ratings(snaps)
        for key, snaps in snapshots_by_year_week.items()
    }

    records = []
    for g in games:
        ratings = ratings_by_year_week.get((g["year"], g["week"]), {})
        home_rating = ratings.get(g["home"])
        away_rating = ratings.get(g["away"])
        if home_rating is None or away_rating is None:
            continue
        records.append({
            **g,
            "rating_diff": home_rating - away_rating,
        })
    return records


def fit_scale_hfa(records):
    if len(records) < 100:
        raise RuntimeError("Insufficient training records for OOS calibration.")

    sum_xx = sum_xh = sum_hh = sum_xy = sum_hy = 0.0
    for r in records:
        x = r["rating_diff"]
        h = 1.0
        y = r["actual_home_margin"]
        sum_xx += x*x
        sum_xh += x*h
        sum_hh += h*h
        sum_xy += x*y
        sum_hy += h*y

    determinant = sum_xx*sum_hh - sum_xh*sum_xh
    if abs(determinant) < 1e-9:
        raise RuntimeError("Historical calibration matrix is singular.")

    scale = (sum_xy*sum_hh - sum_hy*sum_xh) / determinant
    hfa = (sum_hy*sum_xx - sum_xy*sum_xh) / determinant
    return scale, hfa


def historical_oos_rows():
    records = build_historical_rating_records()
    years = sorted({r["year"] for r in records})
    out = []

    for test_year in years:
        if test_year < FIRST_TEST_YEAR:
            continue

        training = [r for r in records if r["year"] < test_year]
        testing = [r for r in records if r["year"] == test_year]
        if len(training) < 100 or len(testing) < 25:
            continue

        scale, hfa = fit_scale_hfa(training)

        for r in testing:
            market_spread = r["market_home_spread"]
            if market_spread is None or market_spread == 0:
                continue

            projected_home_margin = scale * r["rating_diff"] + hfa
            actual_home_margin = r["actual_home_margin"]

            if market_spread < 0:
                favorite = "home"
                market_fav = -market_spread
                actual_fav = actual_home_margin
                model_fav = projected_home_margin
                rating_fav = r["rating_diff"]
            else:
                favorite = "away"
                market_fav = market_spread
                actual_fav = -actual_home_margin
                model_fav = -projected_home_margin
                rating_fav = -r["rating_diff"]

            out.append({
                "game_id": r["game_id"],
                "year": r["year"],
                "week": r["week"],
                "home": r["home"],
                "away": r["away"],
                "favorite": favorite,
                "oos_scale": scale,
                "oos_hfa": hfa,
                "market_favorite_margin": market_fav,
                "actual_favorite_margin": actual_fav,
                "model_favorite_margin": model_fav,
                "rating_favorite_difference": rating_fav,
                "signed_model_residual_actual_minus_model": actual_fav - model_fav,
                "signed_market_residual_actual_minus_market": actual_fav - market_fav,
            })

    return out


def favorite_bucket_summary(rows, lo, hi):
    rr = [r for r in rows if lo <= r["market_favorite_margin"] < hi]
    if not rr:
        return {"n": 0}
    model_err = [r["signed_model_residual_actual_minus_model"] for r in rr]
    market_err = [r["signed_market_residual_actual_minus_market"] for r in rr]
    return {
        "n": len(rr),
        "avg_market_favorite_margin": avg([r["market_favorite_margin"] for r in rr]),
        "avg_model_favorite_margin": avg([r["model_favorite_margin"] for r in rr]),
        "avg_actual_favorite_margin": avg([r["actual_favorite_margin"] for r in rr]),
        "mean_signed_model_residual_actual_minus_model": avg(model_err),
        "model_mae": mae(model_err),
        "model_rmse": rmse(model_err),
        "mean_signed_market_residual_actual_minus_market": avg(market_err),
        "market_mae": mae(market_err),
        "market_rmse": rmse(market_err),
    }


def rating_bucket_summary(rows, lo, hi):
    rr = [
        r for r in rows
        if lo <= abs(r["rating_favorite_difference"]) < hi
    ]
    if not rr:
        return {"n": 0}
    residuals = [r["signed_model_residual_actual_minus_model"] for r in rr]
    return {
        "n": len(rr),
        "avg_abs_rating_difference": avg([abs(r["rating_favorite_difference"]) for r in rr]),
        "mean_signed_model_residual_actual_minus_model": avg(residuals),
        "residual_mae": mae(residuals),
        "residual_rmse": rmse(residuals),
    }


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    current_all = current_projection_rows()
    current = [r for r in current_all if r["market_home_spread"] is not None]
    historical = historical_oos_rows()
    hfas = parse_hfa()

    if len(current_all) < 40:
        raise RuntimeError(f"Expected a full frozen Week 1 board; found only {len(current_all)} projection rows.")
    if len(current) < 35:
        raise RuntimeError(f"Expected at least 35 lined Week 1 games; found only {len(current)}.")
    if len(historical) < 1500:
        raise RuntimeError(f"Historical OOS source parsed only {len(historical)} usable games; refusing to classify.")

    current_model = [r["model_home_spread"] for r in current]
    current_market = [r["market_home_spread"] for r in current]
    model_sd = sd(current_model)
    market_sd = sd(current_market)
    sd_ratio = model_sd / market_sd if market_sd else None
    input_compression = sd_ratio is not None and sd_ratio < INPUT_COMPRESSION_THRESHOLD

    favorite_buckets = {
        label: favorite_bucket_summary(historical, lo, hi)
        for lo, hi, label in FAVORITE_BUCKETS
    }
    rating_buckets = {
        label: rating_bucket_summary(historical, lo, hi)
        for lo, hi, label in RATING_BUCKETS
    }

    quad = quadratic_fit(
        [abs(r["rating_favorite_difference"]) for r in historical],
        [r["signed_model_residual_actual_minus_model"] for r in historical],
    )
    quadratic_sig = bool(quad and quad.get("quadratic_significant_approx_95"))

    ordered_large = ["14-21", "21-28", "28-40", "40+"]
    large_residuals = [
        favorite_buckets[label]["mean_signed_model_residual_actual_minus_model"]
        for label in ordered_large
        if favorite_buckets[label].get("n", 0) >= 20
        and favorite_buckets[label].get("mean_signed_model_residual_actual_minus_model") is not None
    ]
    residual_shape_worsens = (
        len(large_residuals) >= 3
        and avg(large_residuals) > 0.0
        and large_residuals[-1] > large_residuals[0] + 2.0
    )
    tail_worsening = residual_shape_worsens and quadratic_sig

    if input_compression and tail_worsening:
        classification = "Outcome 3: Dual-Systemic Compression"
    elif input_compression:
        classification = "Outcome 1: Input Compression Only"
    elif tail_worsening:
        classification = "Outcome 2: Tail Conversion Compression Only"
    else:
        classification = "Outcome 4: Structural Market Variance / Neither Proven"

    anatomy = []
    for a, b in FOCUS_GAMES:
        hit = next((r for r in current_all if {r["home"], r["away"]} == {a, b}), None)
        if hit:
            anatomy.append(hit)

    hfa_vals = list(hfas.values())
    hfa_sanity = {
        "teams": len(hfa_vals),
        "min": min(hfa_vals) if hfa_vals else None,
        "max": max(hfa_vals) if hfa_vals else None,
        "mean": avg(hfa_vals),
        "all_nonnegative": all(v >= 0 for v in hfa_vals) if hfa_vals else None,
    }

    report = {
        "diagnostic_version": "model-a-compression-audit-v4-offline-oos-rebuild",
        "production_scale": PRODUCTION_SCALE,
        "production_untouched": True,
        "frozen_baseline": str(FROZEN.relative_to(ROOT)),
        "historical_oos_source": str(HISTORICAL.relative_to(ROOT)),
        "historical_method": "Offline rebuild of the six-component time-safe composite from historical_training_v4 pregame_* fields; prior-season-only OOS scale fitting for 2022-2025.",
        "historical_limitations": "Neutral-site status is not preserved in historical_training_v4, so the offline rebuild fits a single global home intercept. Use this for tail-shape diagnosis, not exact old-report reproduction.",
        "current_week1_variance": {
            "all_projection_rows_detected": len(current_all),
            "lined_games_detected": len(current),
            "model_signed_home_spread_sd": model_sd,
            "market_signed_home_spread_sd": market_sd,
            "sd_ratio_model_over_market": sd_ratio,
            "compression_threshold": INPUT_COMPRESSION_THRESHOLD,
            "input_compression_flag": input_compression,
        },
        "historical_oos": {
            "usable_games": len(historical),
            "favorite_size_buckets": favorite_buckets,
            "rating_difference_buckets": rating_buckets,
            "quadratic_residual_test": quad,
            "quadratic_significant_flag": quadratic_sig,
            "residual_shape_worsens_flag": residual_shape_worsens,
            "tail_worsening_flag": tail_worsening,
        },
        "hfa_sanity": hfa_sanity,
        "week1_focus_game_anatomy": anatomy,
        "classification": classification,
        "classification_protocol": {
            "outcome_1": "Current model/market SD ratio < 0.85, without historical worsening large-favorite residual pattern.",
            "outcome_2": "Current SD ratio healthy, historical signed residuals worsen materially in large-favorite buckets AND the quadratic term is significant.",
            "outcome_3": "Both current input compression and statistically-supported historical tail worsening are present.",
            "outcome_4": "Neither condition is proven.",
            "quadratic_note": "Quadratic significance is supporting evidence of nonlinearity only; it does not automatically justify an exponential challenger.",
        },
    }

    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "MODEL A COMPRESSION DIAGNOSTIC — V4",
        "=" * 42,
        f"Classification: {classification}",
        "",
        "CURRENT WEEK 1 GLOBAL SIGNED-SPREAD VARIANCE AUDIT",
        f"Projection rows detected: {len(current_all)}",
        f"Lined games detected: {len(current)}",
        f"Model signed home-spread SD: {model_sd}",
        f"Market signed home-spread SD: {market_sd}",
        f"SD ratio (model/market): {sd_ratio}",
        f"Input compression flag (<{INPUT_COMPRESSION_THRESHOLD}): {input_compression}",
        "",
        "HISTORICAL OOS SAMPLE",
        f"Usable games: {len(historical)}",
        "",
        "HISTORICAL FAVORITE-SIZE BUCKETS",
    ]
    for _, _, label in FAVORITE_BUCKETS:
        lines.append(f"{label}: {favorite_buckets[label]}")
    lines += ["", "HISTORICAL RATING-DIFFERENCE BUCKETS"]
    for _, _, label in RATING_BUCKETS:
        lines.append(f"{label}: {rating_buckets[label]}")
    lines += [
        "",
        f"Quadratic residual test: {quad}",
        f"Quadratic significant: {quadratic_sig}",
        f"Residual shape worsens: {residual_shape_worsens}",
        f"Tail worsening flag (shape + significant quadratic): {tail_worsening}",
        "",
        "HFA SANITY",
        str(hfa_sanity),
        "",
        "WEEK 1 FOCUS GAME ANATOMY",
    ]
    for row in anatomy:
        lines.append(str(row))
    lines += [
        "",
        "PRODUCTION STATUS",
        "Model A untouched.",
        "Frozen Week 1 baseline untouched.",
        "Only diagnostic report files were written.",
    ]

    REPORT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
