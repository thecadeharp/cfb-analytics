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
TRAINING = DATA / "training"
FROZEN = DATA / "frozen" / "2026_week1_modelA_frozen.json"
METRICS = DATA / "cfb_metrics.json"
HFA = DATA / "hfa_2026.json"
HIST = TRAINING / "historical_games.csv"
REPORT_DIR = DATA / "reports"
REPORT_JSON = REPORT_DIR / "model_a_compression_diagnostic.json"
REPORT_TXT = REPORT_DIR / "model_a_compression_diagnostic.txt"

SCALE = 10.4245

FAVORITE_BUCKETS = [
    (0.0, 7.0, "0-7"),
    (7.0, 14.0, "7-14"),
    (14.0, 21.0, "14-21"),
    (21.0, 28.0, "21-28"),
    (28.0, 40.0, "28-40"),
    (40.0, float("inf"), "40+"),
]

TAIL_RATING_BUCKETS = [
    (0.0, 1.0, "0-1.0"),
    (1.0, 1.5, "1.0-1.5"),
    (1.5, 2.0, "1.5-2.0"),
    (2.0, 2.5, "2.0-2.5"),
    (2.5, 3.0, "2.5-3.0"),
    (3.0, float("inf"), "3.0+"),
]


def fnum(v):
    if v is None:
        return None
    try:
        if isinstance(v, str):
            t = v.strip()
            if not t:
                return None
            return float(t)
        return float(v)
    except Exception:
        return None


def first_numeric(row, candidates):
    for c in candidates:
        if c in row:
            v = fnum(row.get(c))
            if v is not None:
                return v
    return None


def first_text(row, candidates):
    for c in candidates:
        if c in row:
            v = row.get(c)
            if v is not None and str(v).strip():
                return str(v).strip()
    return None


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def population_sd(vals):
    vals = [x for x in vals if x is not None and math.isfinite(x)]
    return statistics.pstdev(vals) if len(vals) >= 2 else None


def mean(vals):
    vals = [x for x in vals if x is not None and math.isfinite(x)]
    return statistics.fmean(vals) if vals else None


def mae(errors):
    return mean([abs(x) for x in errors])


def rmse(errors):
    vals = [x * x for x in errors if x is not None and math.isfinite(x)]
    return math.sqrt(mean(vals)) if vals else None


def corr(x, y):
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None and math.isfinite(a) and math.isfinite(b)]
    if len(pairs) < 3:
        return None
    xs, ys = zip(*pairs)
    mx, my = mean(xs), mean(ys)
    num = sum((a - mx) * (b - my) for a, b in pairs)
    denx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    deny = math.sqrt(sum((b - my) ** 2 for b in ys))
    if denx == 0 or deny == 0:
        return None
    return num / (denx * deny)


def solve_3x3(A, b):
    # Gaussian elimination, no external deps.
    M = [list(map(float, A[i])) + [float(b[i])] for i in range(3)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-12:
            raise ValueError("Singular matrix")
        M[col], M[pivot] = M[pivot], M[col]
        div = M[col][col]
        M[col] = [v / div for v in M[col]]
        for r in range(3):
            if r == col:
                continue
            fac = M[r][col]
            M[r] = [M[r][c] - fac * M[col][c] for c in range(4)]
    return [M[i][3] for i in range(3)]


def quadratic_fit(xs, ys):
    pairs = [(float(x), float(y)) for x, y in zip(xs, ys) if x is not None and y is not None and math.isfinite(x) and math.isfinite(y)]
    n = len(pairs)
    if n < 10:
        return None
    sx = sum(x for x, _ in pairs)
    sx2 = sum(x*x for x, _ in pairs)
    sx3 = sum(x*x*x for x, _ in pairs)
    sx4 = sum(x*x*x*x for x, _ in pairs)
    sy = sum(y for _, y in pairs)
    sxy = sum(x*y for x, y in pairs)
    sx2y = sum((x*x)*y for x, y in pairs)
    try:
        c, b, a = solve_3x3(
            [[n, sx, sx2], [sx, sx2, sx3], [sx2, sx3, sx4]],
            [sy, sxy, sx2y],
        )
    except Exception:
        return None
    preds = [a*x*x + b*x + c for x, _ in pairs]
    residuals = [y - p for (_, y), p in zip(pairs, preds)]
    sse = sum(r*r for r in residuals)
    ybar = mean([y for _, y in pairs])
    sst = sum((y - ybar) ** 2 for _, y in pairs)
    r2 = 1 - sse/sst if sst > 0 else None

    # OLS standard error for quadratic coefficient a.
    XTX = [
        [n, sx, sx2],
        [sx, sx2, sx3],
        [sx2, sx3, sx4],
    ]
    # invert 3x3 by solving for basis vectors
    inv_cols = [solve_3x3(XTX, e) for e in ([1,0,0],[0,1,0],[0,0,1])]
    inv = [[inv_cols[j][i] for j in range(3)] for i in range(3)]
    df = n - 3
    sigma2 = sse / df if df > 0 else None
    se_a = math.sqrt(max(0.0, sigma2 * inv[2][2])) if sigma2 is not None else None
    t_a = a / se_a if se_a and se_a > 0 else None
    significant_approx = abs(t_a) >= 1.96 if t_a is not None else None
    return {
        "n": n,
        "quadratic_a": a,
        "linear_b": b,
        "intercept_c": c,
        "r2": r2,
        "se_a": se_a,
        "t_a": t_a,
        "quadratic_significant_approx_95": significant_approx,
    }


def parse_power_ratings(obj):
    out = {}
    if isinstance(obj, dict):
        teams = obj.get("teams")
        if isinstance(teams, list):
            for row in teams:
                name = first_text(row, ["team", "name", "school"])
                pr = first_numeric(row, ["power_rating", "rating"])
                if name and pr is not None:
                    out[name] = pr
        elif isinstance(teams, dict):
            for name, row in teams.items():
                if isinstance(row, dict):
                    pr = first_numeric(row, ["power_rating", "rating"])
                    if pr is not None:
                        out[str(name)] = pr
        # recursive-ish fallback for common shape
        if not out:
            for k, v in obj.items():
                if isinstance(v, dict) and "power_rating" in v:
                    pr = fnum(v.get("power_rating"))
                    if pr is not None:
                        out[str(k)] = pr
    return out


def parse_hfa(obj):
    out = {}
    if isinstance(obj, dict):
        candidates = obj.get("teams", obj)
        if isinstance(candidates, dict):
            for name, v in candidates.items():
                if isinstance(v, dict):
                    h = first_numeric(v, ["hfa", "home_field_advantage", "value"])
                else:
                    h = fnum(v)
                if h is not None:
                    out[str(name)] = h
    return out


def extract_games(proj_obj):
    # Flexible recursive search for matchup dicts.
    found = []
    def rec(x):
        if isinstance(x, dict):
            keys = set(x.keys())
            home = first_text(x, ["home_team", "home", "homeTeam", "home_team_name"])
            away = first_text(x, ["away_team", "away", "awayTeam", "away_team_name"])
            msp = first_numeric(x, ["market_spread", "market_home_spread", "spread", "consensus_spread", "home_spread"])
            mdl = first_numeric(x, ["model_spread", "fair_spread", "projected_spread", "model_home_spread"])
            if home and away and (msp is not None or mdl is not None):
                found.append(x)
            for v in x.values():
                rec(v)
        elif isinstance(x, list):
            for v in x:
                rec(v)
    rec(proj_obj)
    # de-dupe by a useful signature
    uniq = {}
    for g in found:
        sig = (
            first_text(g, ["home_team", "home", "homeTeam", "home_team_name"]),
            first_text(g, ["away_team", "away", "awayTeam", "away_team_name"]),
            first_numeric(g, ["market_spread", "market_home_spread", "spread", "consensus_spread", "home_spread"]),
            first_numeric(g, ["model_spread", "fair_spread", "projected_spread", "model_home_spread"]),
        )
        uniq[sig] = g
    return list(uniq.values())


def historical_rows():
    with open(HIST, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = list(reader)

    candidate_map = {
        "year": ["season", "year"],
        "week": ["week"],
        "market_spread": [
            "market_spread", "closing_spread", "close_spread", "spread",
            "home_spread", "consensus_spread", "line"
        ],
        "model_spread": [
            "model_spread", "predicted_spread", "projected_spread",
            "legacy_spread", "control_spread", "fair_spread"
        ],
        "rating_diff": [
            "rating_difference", "rating_diff", "power_rating_diff",
            "model_rating_difference", "elo_diff", "composite_rating_diff"
        ],
        "home_score": ["home_points", "home_score", "home_points_final"],
        "away_score": ["away_points", "away_score", "away_points_final"],
        "actual_margin": ["actual_margin", "home_margin", "margin"],
        "neutral": ["neutral_site", "neutral", "is_neutral"],
    }
    matched = {}
    header_lower = {h.lower(): h for h in headers}
    for k, candidates in candidate_map.items():
        for c in candidates:
            if c.lower() in header_lower:
                matched[k] = header_lower[c.lower()]
                break

    cooked = []
    for r in rows:
        market = first_numeric(r, [matched["market_spread"]]) if "market_spread" in matched else None
        model = first_numeric(r, [matched["model_spread"]]) if "model_spread" in matched else None
        rating = first_numeric(r, [matched["rating_diff"]]) if "rating_diff" in matched else None
        actual = first_numeric(r, [matched["actual_margin"]]) if "actual_margin" in matched else None
        if actual is None and "home_score" in matched and "away_score" in matched:
            hs = first_numeric(r, [matched["home_score"]])
            a_s = first_numeric(r, [matched["away_score"]])
            if hs is not None and a_s is not None:
                actual = hs - a_s

        # Convert home-centric spreads/margins into favorite-centric magnitudes.
        if market is None or actual is None:
            continue

        # conventional home spread: negative means home favorite
        market_fav_margin = abs(market)
        if market < 0:
            actual_fav_margin = actual
            model_fav_margin = (-model if model is not None else None)
            rating_fav_diff = (rating if rating is not None else None)
        elif market > 0:
            actual_fav_margin = -actual
            model_fav_margin = (model if model is not None else None)
            rating_fav_diff = (-rating if rating is not None else None)
        else:
            actual_fav_margin = abs(actual)
            model_fav_margin = abs(model) if model is not None else None
            rating_fav_diff = abs(rating) if rating is not None else None

        cooked.append({
            "market_favorite_margin": market_fav_margin,
            "actual_favorite_margin": actual_fav_margin,
            "model_favorite_margin": model_fav_margin,
            "rating_favorite_diff": rating_fav_diff,
        })

    return headers, matched, cooked


def bucket_summary(rows, lo, hi):
    rr = [r for r in rows if r["market_favorite_margin"] >= lo and r["market_favorite_margin"] < hi]
    if not rr:
        return {"n": 0}
    model_errs = []
    market_errs = []
    signed_model = []
    for r in rr:
        if r["model_favorite_margin"] is not None:
            e = r["actual_favorite_margin"] - r["model_favorite_margin"]
            model_errs.append(e)
            signed_model.append(e)
        market_errs.append(r["actual_favorite_margin"] - r["market_favorite_margin"])
    return {
        "n": len(rr),
        "avg_market_favorite_margin": mean([r["market_favorite_margin"] for r in rr]),
        "avg_actual_favorite_margin": mean([r["actual_favorite_margin"] for r in rr]),
        "avg_model_favorite_margin": mean([r["model_favorite_margin"] for r in rr if r["model_favorite_margin"] is not None]),
        "mean_signed_model_residual_actual_minus_model": mean(signed_model),
        "model_mae": mae(model_errs),
        "model_rmse": rmse(model_errs),
        "market_mae": mae(market_errs),
        "market_rmse": rmse(market_errs),
    }


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    frozen = load_json(FROZEN)
    metrics = load_json(METRICS)
    hfa_obj = load_json(HFA)
    ratings = parse_power_ratings(metrics)
    hfas = parse_hfa(hfa_obj)
    games = extract_games(frozen)

    current = []
    for g in games:
        home = first_text(g, ["home_team", "home", "homeTeam", "home_team_name"])
        away = first_text(g, ["away_team", "away", "awayTeam", "away_team_name"])
        market = first_numeric(g, ["market_spread", "market_home_spread", "spread", "consensus_spread", "home_spread"])
        model = first_numeric(g, ["model_spread", "fair_spread", "projected_spread", "model_home_spread"])
        if not home or not away or market is None or model is None:
            continue
        current.append({
            "home": home,
            "away": away,
            "market_spread": market,
            "model_spread": model,
            "market_favorite_margin": abs(market),
            "model_favorite_margin": abs(model),
            "rating_diff_home_minus_away": (
                ratings.get(home) - ratings.get(away)
                if home in ratings and away in ratings else None
            ),
            "home_hfa": hfas.get(home),
        })

    current_model_sd = population_sd([r["model_favorite_margin"] for r in current])
    current_market_sd = population_sd([r["market_favorite_margin"] for r in current])
    sd_ratio = current_model_sd / current_market_sd if current_model_sd and current_market_sd else None

    headers, matched_cols, hist = historical_rows()
    favorite_buckets = {
        label: bucket_summary(hist, lo, hi)
        for lo, hi, label in FAVORITE_BUCKETS
    }

    # Tail test uses actual-minus-linear-prediction against absolute rating difference,
    # only when a rating-diff field actually exists in the historical training set.
    tail_rows = []
    for r in hist:
        rd = r["rating_favorite_diff"]
        if rd is None:
            continue
        linear_pred = rd * SCALE
        resid = r["actual_favorite_margin"] - linear_pred
        tail_rows.append((abs(rd), resid))

    tail_bucket_summary = {}
    for lo, hi, label in TAIL_RATING_BUCKETS:
        vals = [(x, y) for x, y in tail_rows if x >= lo and x < hi]
        tail_bucket_summary[label] = {
            "n": len(vals),
            "mean_abs_rating_diff": mean([x for x, _ in vals]),
            "mean_signed_residual_actual_minus_linear": mean([y for _, y in vals]),
            "residual_mae": mae([y for _, y in vals]),
            "residual_rmse": rmse([y for _, y in vals]),
        }

    quad = quadratic_fit([x for x, _ in tail_rows], [y for _, y in tail_rows]) if tail_rows else None

    # HFA sanity
    hfa_vals = list(hfas.values())
    hfa_sanity = {
        "n_team_hfa": len(hfa_vals),
        "min_hfa": min(hfa_vals) if hfa_vals else None,
        "max_hfa": max(hfa_vals) if hfa_vals else None,
        "mean_hfa": mean(hfa_vals),
        "all_nonnegative": all(v >= 0 for v in hfa_vals) if hfa_vals else None,
    }

    focus_pairs = [
        ("Alabama", "East Carolina"),
        ("Oklahoma", "UTEP"),
        ("Texas", "Texas State"),
        ("Indiana", "North Texas"),
        ("USC", "Fresno State"),
        ("Miami", "Stanford"),
        ("West Virginia", "Coastal Carolina"),
        ("Houston", "Oregon State"),
    ]
    anatomy = []
    for a, b in focus_pairs:
        hit = None
        for r in current:
            if {r["home"], r["away"]} == {a, b}:
                hit = r
                break
        if hit:
            anatomy.append(hit)

    # Classification protocol.
    current_input_compressed = (sd_ratio is not None and sd_ratio < 0.85)

    large_labels = ["14-21", "21-28", "28-40", "40+"]
    large_resids = [
        favorite_buckets[l].get("mean_signed_model_residual_actual_minus_model")
        for l in large_labels
        if favorite_buckets[l].get("n", 0) > 0
        and favorite_buckets[l].get("mean_signed_model_residual_actual_minus_model") is not None
    ]
    tail_worsening = False
    if len(large_resids) >= 3:
        # actual - model positive means model underpredicts favorite margin.
        tail_worsening = large_resids[-1] > large_resids[0] + 2.0 and mean(large_resids) > 0.0

    quadratic_sig = bool(quad and quad.get("quadratic_significant_approx_95"))

    if current_input_compressed and tail_worsening:
        outcome = "Outcome 3: Dual-Systemic Compression"
    elif current_input_compressed and not tail_worsening:
        outcome = "Outcome 1: Input Compression Only"
    elif (not current_input_compressed) and tail_worsening:
        outcome = "Outcome 2: Tail Conversion Compression Only"
    else:
        outcome = "Outcome 4: Structural Market Variance / Neither Proven"

    report = {
        "diagnostic_version": "model-a-compression-audit-v1",
        "production_untouched": True,
        "frozen_baseline": str(FROZEN.relative_to(ROOT)),
        "scale": SCALE,
        "current_week1": {
            "lined_games_detected": len(current),
            "model_favorite_margin_sd": current_model_sd,
            "market_favorite_margin_sd": current_market_sd,
            "sd_ratio_model_over_market": sd_ratio,
            "input_compression_threshold": 0.85,
            "input_compression_flag": current_input_compressed,
        },
        "historical_schema": {
            "historical_file": str(HIST.relative_to(ROOT)),
            "headers_count": len(headers),
            "matched_columns": matched_cols,
            "usable_rows": len(hist),
            "has_historical_model_spread": "model_spread" in matched_cols,
            "has_historical_rating_diff": "rating_diff" in matched_cols,
        },
        "historical_market_favorite_buckets": favorite_buckets,
        "historical_rating_tail_buckets": tail_bucket_summary,
        "quadratic_tail_test": quad,
        "tail_worsening_flag": tail_worsening,
        "quadratic_significant_flag": quadratic_sig,
        "hfa_sanity": hfa_sanity,
        "week1_focus_game_anatomy": anatomy,
        "classification": outcome,
        "classification_notes": [
            "Outcome classification is diagnostic only; it does not modify Model A.",
            "A significant quadratic term indicates nonlinearity, not that an exponential form is automatically correct.",
            "Any challenger must beat Model A out of sample before promotion.",
        ],
    }

    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=False)

    lines = []
    lines.append("MODEL A COMPRESSION DIAGNOSTIC")
    lines.append("=" * 34)
    lines.append(f"Classification: {outcome}")
    lines.append("")
    lines.append("CURRENT WEEK 1 VARIANCE AUDIT")
    lines.append(f"Lined games detected: {len(current)}")
    lines.append(f"Model favorite-margin SD: {current_model_sd}")
    lines.append(f"Market favorite-margin SD: {current_market_sd}")
    lines.append(f"SD ratio (model/market): {sd_ratio}")
    lines.append(f"Input compression flag (<0.85): {current_input_compressed}")
    lines.append("")
    lines.append("HISTORICAL FAVORITE-SIZE BUCKETS")
    for label in [b[2] for b in FAVORITE_BUCKETS]:
        lines.append(f"{label}: {favorite_buckets[label]}")
    lines.append("")
    lines.append("RATING-DIFFERENCE TAIL BUCKETS")
    for label in [b[2] for b in TAIL_RATING_BUCKETS]:
        lines.append(f"{label}: {tail_bucket_summary[label]}")
    lines.append("")
    lines.append(f"Quadratic tail test: {quad}")
    lines.append(f"Tail worsening flag: {tail_worsening}")
    lines.append("")
    lines.append("HFA SANITY")
    lines.append(str(hfa_sanity))
    lines.append("")
    lines.append("WEEK 1 FOCUS GAME ANATOMY")
    for row in anatomy:
        lines.append(str(row))
    lines.append("")
    lines.append("SCHEMA")
    lines.append(str(report["historical_schema"]))
    lines.append("")
    lines.append("PRODUCTION STATUS")
    lines.append("Model A untouched. Frozen baseline untouched. No production files modified.")

    REPORT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
