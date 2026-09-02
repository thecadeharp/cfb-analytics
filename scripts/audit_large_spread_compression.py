#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

FROZEN = DATA / "frozen" / "2026_week1_modelA_frozen.json"
REPORT_DIR = DATA / "reports"
REPORT_JSON = REPORT_DIR / "large_spread_compression_audit.json"
REPORT_TXT = REPORT_DIR / "large_spread_compression_audit.txt"

BUCKETS = [
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


def median(values):
    vals = [float(v) for v in values if v is not None]
    return statistics.median(vals) if vals else None


def load_rows():
    with FROZEN.open("r", encoding="utf-8") as f:
        obj = json.load(f)

    games = obj.get("games", []) if isinstance(obj, dict) else []
    rows = []

    for game in games:
        projection = game.get("projection") or {}
        market = game.get("market") or {}
        comparison = game.get("comparison") or {}

        model_home_spread = num(projection.get("home_spread"))
        market_home_spread = num(market.get("home_spread"))

        if model_home_spread is None or market_home_spread is None:
            continue
        if abs(market_home_spread) < 1e-9:
            continue

        home = (game.get("home") or {}).get("team")
        away = (game.get("away") or {}).get("team")
        if not home or not away:
            continue

        market_expected_home_margin = -market_home_spread
        model_expected_home_margin = -model_home_spread

        if market_expected_home_margin > 0:
            market_favorite = home
            market_favorite_size = market_expected_home_margin
            model_margin_for_market_favorite = model_expected_home_margin
        else:
            market_favorite = away
            market_favorite_size = -market_expected_home_margin
            model_margin_for_market_favorite = -model_expected_home_margin

        model_same_favorite = model_margin_for_market_favorite > 0
        model_favorite_size_same_side = (
            model_margin_for_market_favorite if model_same_favorite else 0.0
        )

        signed_gap = model_margin_for_market_favorite - market_favorite_size

        rows.append({
            "game_id": game.get("game_id"),
            "week": game.get("week"),
            "home": home,
            "away": away,
            "market_favorite": market_favorite,
            "market_favorite_size": market_favorite_size,
            "model_margin_for_market_favorite": model_margin_for_market_favorite,
            "model_same_favorite": model_same_favorite,
            "favorite_flip": not model_same_favorite,
            "model_shorter_than_market": signed_gap < 0,
            "signed_model_minus_market_favorite_margin": signed_gap,
            "absolute_disagreement": abs(signed_gap),
            "model_home_spread": model_home_spread,
            "market_home_spread": market_home_spread,
            "signal": comparison.get("signal") or comparison.get("status"),
            "preferred_side": comparison.get("preferred_side"),
        })

    return rows


def summarize(rows):
    n = len(rows)
    if not n:
        return {"n": 0}

    shorter = [r for r in rows if r["model_shorter_than_market"]]
    flips = [r for r in rows if r["favorite_flip"]]
    gaps = [r["signed_model_minus_market_favorite_margin"] for r in rows]

    return {
        "n": n,
        "model_shorter_n": len(shorter),
        "model_shorter_pct": round(len(shorter) / n * 100, 2),
        "favorite_flip_n": len(flips),
        "favorite_flip_pct": round(len(flips) / n * 100, 2),
        "mean_signed_model_minus_market_favorite_margin": avg(gaps),
        "median_signed_model_minus_market_favorite_margin": median(gaps),
        "mean_absolute_disagreement": avg([abs(x) for x in gaps]),
        "avg_market_favorite_size": avg([r["market_favorite_size"] for r in rows]),
        "avg_model_margin_for_market_favorite": avg(
            [r["model_margin_for_market_favorite"] for r in rows]
        ),
    }


def bucket_report(rows):
    output = {}
    for lo, hi, label in BUCKETS:
        bucket = [
            r for r in rows
            if lo <= r["market_favorite_size"] < hi
        ]
        output[label] = summarize(bucket)
    return output


def large_game_rows(rows, threshold=14.0):
    return sorted(
        [r for r in rows if r["market_favorite_size"] >= threshold],
        key=lambda r: (-r["market_favorite_size"], r["week"], r["home"], r["away"]),
    )


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_rows()

    if len(rows) < 35:
        raise RuntimeError(
            f"Expected at least 35 lined frozen games; found only {len(rows)}."
        )

    week1 = [r for r in rows if int(r.get("week") or -1) == 1]
    large_all = large_game_rows(rows, 14.0)
    large_week1 = large_game_rows(week1, 14.0)

    report = {
        "audit_version": "large-spread-compression-audit-v1",
        "purpose": (
            "Verify whether Model A is systematically shorter than the market "
            "across all lined large favorites, independent of Signal/Strong Edge labels."
        ),
        "selection_rule": (
            "Every frozen game with both a non-pick'em market spread and Model A spread. "
            "No filtering on signal, preferred side, disagreement, or status."
        ),
        "all_lined": {
            "summary": summarize(rows),
            "market_favorite_buckets": bucket_report(rows),
            "large_favorites_14_plus_summary": summarize(large_all),
            "large_favorites_14_plus_games": large_all,
        },
        "week1_only": {
            "summary": summarize(week1),
            "market_favorite_buckets": bucket_report(week1),
            "large_favorites_14_plus_summary": summarize(large_week1),
            "large_favorites_14_plus_games": large_week1,
        },
        "production_untouched": True,
        "frozen_baseline_untouched": True,
    }

    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "MODEL A LARGE-SPREAD COMPRESSION AUDIT",
        "=" * 46,
        "",
        "SELECTION",
        report["selection_rule"],
        "",
        "ALL LINED FROZEN GAMES",
        str(report["all_lined"]["summary"]),
        "",
        "ALL LINED — MARKET FAVORITE BUCKETS",
    ]

    for _, _, label in BUCKETS:
        lines.append(f"{label}: {report['all_lined']['market_favorite_buckets'][label]}")

    lines += [
        "",
        "ALL LINED — EVERY MARKET FAVORITE 14+",
        str(report["all_lined"]["large_favorites_14_plus_summary"]),
    ]

    for r in large_all:
        lines.append(
            f"W{r['week']} | {r['away']} @ {r['home']} | "
            f"market favorite {r['market_favorite']} {r['market_favorite_size']:.1f} | "
            f"model margin for same market favorite {r['model_margin_for_market_favorite']:.1f} | "
            f"model-market {r['signed_model_minus_market_favorite_margin']:+.1f} | "
            f"flip={r['favorite_flip']} | signal={r['signal']}"
        )

    lines += [
        "",
        "WEEK 1 ONLY",
        str(report["week1_only"]["summary"]),
        "",
        "WEEK 1 — MARKET FAVORITE BUCKETS",
    ]

    for _, _, label in BUCKETS:
        lines.append(f"{label}: {report['week1_only']['market_favorite_buckets'][label]}")

    lines += [
        "",
        "WEEK 1 — EVERY MARKET FAVORITE 14+",
        str(report["week1_only"]["large_favorites_14_plus_summary"]),
    ]

    for r in large_week1:
        lines.append(
            f"{r['away']} @ {r['home']} | "
            f"market favorite {r['market_favorite']} {r['market_favorite_size']:.1f} | "
            f"model margin for same market favorite {r['model_margin_for_market_favorite']:.1f} | "
            f"model-market {r['signed_model_minus_market_favorite_margin']:+.1f} | "
            f"flip={r['favorite_flip']} | signal={r['signal']}"
        )

    lines += [
        "",
        "PRODUCTION STATUS",
        "Model A untouched.",
        "Frozen baseline untouched.",
        "Only audit report files were written.",
    ]

    REPORT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
