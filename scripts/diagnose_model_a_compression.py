#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

FROZEN = DATA / "frozen" / "2026_week1_modelA_frozen.json"
COMPOSITE = DATA / "composite_backtest_report.json"
HFA = DATA / "hfa_2026.json"

REPORT_DIR = DATA / "reports"
REPORT_JSON = REPORT_DIR / "model_a_compression_diagnostic.json"
REPORT_TXT = REPORT_DIR / "model_a_compression_diagnostic.txt"

PRODUCTION_SCALE = 10.4245
INPUT_COMPRESSION_THRESHOLD = 0.85

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
    if isinstance(obj, dict) and isinstance(obj.get("projections"), list):
        raw = obj["projections"]
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


def historical_oos_rows():
    obj = load_json(COMPOSITE)
    games = obj.get("games", []) if isinstance(obj, dict) else []
    rows = []

    for g in games:
        market_spread = num(g.get("market_home_spread"))
        actual_home_margin = num(g.get("actual_home_margin"))
        projected_home_margin = num(g.get("projected_home_margin"))
        rating_diff = num(g.get("rating_diff"))

        if None in (market_spread, actual_home_margin, projected_home_margin, rating_diff) or market_spread == 0:
            continue

        if market_spread < 0:
            favorite = "home"
            market_fav = -market_spread
            actual_fav = actual_home_margin
            model_fav = projected_home_margin
            rating_fav = rating_diff
        else:
            favorite = "away"
            market_fav = market_spread
            actual_fav = -actual_home_margin
            model_fav = -projected_home_margin
            rating_fav = -rating_diff

        rows.append({
            "game_id": g.get("game_id"),
            "year": g.get("year"),
            "week": g.get("week"),
            "home": g.get("home"),
            "away": g.get("away"),
            "favorite": favorite,
            "market_favorite_margin": market_fav,
            "actual_favorite_margin": actual_fav,
            "model_favorite_margin": model_fav,
            "rating_favorite_difference": rating_fav,
            "signed_model_residual_actual_minus_model": actual_fav - model_fav,
            "signed_market_residual_actual_minus_market": actual_fav - market_fav,
        })
    return rows


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

    current_model = [abs(r["model_home_spread"]) for r in current]
    current_market = [abs(r["market_home_spread"]) for r in current]
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
    tail_worsening = (
        len(large_residuals) >= 3
        and avg(large_residuals) > 0.0
        and large_residuals[-1] > large_residuals[0] + 2.0
    )

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
        "diagnostic_version": "model-a-compression-audit-v2-schema-corrected",
        "production_scale": PRODUCTION_SCALE,
        "production_untouched": True,
        "frozen_baseline": str(FROZEN.relative_to(ROOT)),
        "historical_oos_source": str(COMPOSITE.relative_to(ROOT)),
        "current_week1_variance": {
            "all_projection_rows_detected": len(current_all),
            "lined_games_detected": len(current),
            "model_favorite_margin_sd": model_sd,
            "market_favorite_margin_sd": market_sd,
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
            "tail_worsening_flag": tail_worsening,
        },
        "hfa_sanity": hfa_sanity,
        "week1_focus_game_anatomy": anatomy,
        "classification": classification,
        "classification_protocol": {
            "outcome_1": "Current model/market SD ratio < 0.85, without historical worsening large-favorite residual pattern.",
            "outcome_2": "Current SD ratio healthy, historical signed residuals worsen materially in large-favorite buckets.",
            "outcome_3": "Both current input compression and historical tail worsening are present.",
            "outcome_4": "Neither condition is proven.",
            "quadratic_note": "Quadratic significance is supporting evidence of nonlinearity only; it does not automatically justify an exponential challenger.",
        },
    }

    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "MODEL A COMPRESSION DIAGNOSTIC — V2",
        "=" * 42,
        f"Classification: {classification}",
        "",
        "CURRENT WEEK 1 VARIANCE AUDIT",
        f"Projection rows detected: {len(current_all)}",
        f"Lined games detected: {len(current)}",
        f"Model favorite-margin SD: {model_sd}",
        f"Market favorite-margin SD: {market_sd}",
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
        f"Tail worsening flag: {tail_worsening}",
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
