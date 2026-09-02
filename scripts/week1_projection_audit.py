"""
CFB ANALYTICS
week1_projection_audit.py

Offline diagnostic for the current production projection file.

Purpose:
- No CFBD calls
- No Odds API calls
- No coefficient tuning
- No model changes
- Snapshot Week 1 model-vs-market disagreement before Score Engine v1.1 is promoted

Reads:
    data/projections.json

Writes:
    data/week1_projection_audit.json
"""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECTIONS_PATH = ROOT / "data" / "projections.json"
OUTPUT_PATH = ROOT / "data" / "week1_projection_audit.json"

TARGET_WEEK = 1


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def round1(value):
    return None if value is None else round(float(value), 1)


def favorite_from_home_spread(home_spread, home_team, away_team):
    if home_spread is None:
        return None, None

    spread = float(home_spread)

    if spread < 0:
        return home_team, abs(spread)
    if spread > 0:
        return away_team, abs(spread)

    return "PICKEM", 0.0


def favorite_size_bucket(size):
    if size is None:
        return "NO MARKET"
    if size < 3:
        return "0-3"
    if size < 7:
        return "3-7"
    if size < 14:
        return "7-14"
    if size < 21:
        return "14-21"
    if size < 28:
        return "21-28"
    if size < 40:
        return "28-40"
    return "40+"


def signed_home_margin_from_spread(home_spread):
    if home_spread is None:
        return None
    return -float(home_spread)


def build_row(game):
    home_team = game["home"]["team"]
    away_team = game["away"]["team"]

    model_spread = game.get("projection", {}).get("home_spread")
    market_spread = game.get("market", {}).get("home_spread")
    comparison = game.get("comparison", {}) or {}

    market_favorite, market_favorite_size = favorite_from_home_spread(
        market_spread,
        home_team,
        away_team,
    )
    model_favorite, model_favorite_size = favorite_from_home_spread(
        model_spread,
        home_team,
        away_team,
    )

    market_margin = signed_home_margin_from_spread(market_spread)
    model_margin = signed_home_margin_from_spread(model_spread)

    signed_model_minus_market_margin = None
    if market_margin is not None and model_margin is not None:
        signed_model_minus_market_margin = model_margin - market_margin

    same_favorite = (
        market_favorite not in (None, "PICKEM")
        and market_favorite == model_favorite
    )

    compressed_same_favorite = (
        same_favorite
        and model_favorite_size is not None
        and market_favorite_size is not None
        and model_favorite_size < market_favorite_size
    )

    compression_points = None
    if compressed_same_favorite:
        compression_points = market_favorite_size - model_favorite_size

    large_favorite_compression_flag = (
        compressed_same_favorite
        and market_favorite_size is not None
        and market_favorite_size >= 21.0
        and compression_points is not None
        and compression_points >= 3.0
    )

    return {
        "game_id": game.get("game_id"),
        "week": game.get("week"),
        "start_date": game.get("start_date"),
        "away_team": away_team,
        "home_team": home_team,
        "neutral_site": bool(game.get("neutral_site", False)),
        "market_home_spread": round1(market_spread),
        "model_home_spread": round1(model_spread),
        "market_favorite": market_favorite,
        "market_favorite_size": round1(market_favorite_size),
        "market_favorite_bucket": favorite_size_bucket(market_favorite_size),
        "model_favorite": model_favorite,
        "model_favorite_size": round1(model_favorite_size),
        "same_favorite": same_favorite,
        "signed_model_minus_market_margin": round1(
            signed_model_minus_market_margin
        ),
        "disagreement": round1(comparison.get("disagreement")),
        "preferred_side": comparison.get("preferred_side"),
        "status": comparison.get("status"),
        "compressed_same_favorite": compressed_same_favorite,
        "compression_points": round1(compression_points),
        "large_favorite_compression_flag": large_favorite_compression_flag,
    }


def main():
    payload = load_json(PROJECTIONS_PATH)
    games = payload.get("games") or payload.get("projections") or []

    week_games = [
        game for game in games
        if game.get("week") == TARGET_WEEK
    ]

    rows = [build_row(game) for game in week_games]

    lined = [
        row for row in rows
        if row["market_home_spread"] is not None
    ]

    lined.sort(
        key=lambda row: (
            -(row["disagreement"] or 0.0),
            row["start_date"] or "",
            row["away_team"],
        )
    )

    status_counts = Counter(
        row["status"] for row in lined
    )

    bucket_summary = {}
    for bucket in ("0-3", "3-7", "7-14", "14-21", "21-28", "28-40", "40+"):
        bucket_rows = [
            row for row in lined
            if row["market_favorite_bucket"] == bucket
        ]

        compressed = [
            row for row in bucket_rows
            if row["compressed_same_favorite"]
        ]

        avg_compression = None
        if compressed:
            avg_compression = sum(
                row["compression_points"] for row in compressed
            ) / len(compressed)

        bucket_summary[bucket] = {
            "games": len(bucket_rows),
            "same_favorite_games": sum(
                1 for row in bucket_rows if row["same_favorite"]
            ),
            "compressed_same_favorite_games": len(compressed),
            "average_compression_points_when_compressed": round1(
                avg_compression
            ),
        }

    flagged = [
        row for row in lined
        if row["large_favorite_compression_flag"]
    ]

    report = {
        "meta": {
            "generated": datetime.now().isoformat(),
            "source": "data/projections.json",
            "week": TARGET_WEEK,
            "purpose": (
                "offline production-model audit; diagnostic only; "
                "does not alter model coefficients or recommendations"
            ),
        },
        "summary": {
            "week_games": len(rows),
            "lined_games": len(lined),
            "status_counts": dict(status_counts),
            "large_favorite_compression_flags": len(flagged),
        },
        "favorite_size_buckets": bucket_summary,
        "flagged_large_favorite_compression": flagged,
        "games_sorted_by_disagreement": lined,
    }

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("=" * 78)
    print("WEEK 1 PROJECTION AUDIT")
    print("Offline diagnostic only — no API calls, no model tuning")
    print("=" * 78)
    print(f"Week 1 games: {len(rows)}")
    print(f"Lined games:  {len(lined)}")
    print(f"Status counts: {dict(status_counts)}")
    print(
        "Large-favorite compression flags: "
        f"{len(flagged)}"
    )
    print("")
    print("TOP MODEL / MARKET DISAGREEMENTS")
    print("-" * 78)

    for row in lined[:15]:
        matchup = f"{row['away_team']} @ {row['home_team']}"
        print(
            f"{matchup[:34]:34} "
            f"MKT {row['market_home_spread']:>6.1f}  "
            f"MOD {row['model_home_spread']:>6.1f}  "
            f"DIFF {row['disagreement']:>4.1f}  "
            f"{row['status']}"
        )

    if flagged:
        print("")
        print("LARGE-FAVORITE COMPRESSION FLAGS")
        print("-" * 78)

        for row in flagged:
            matchup = f"{row['away_team']} @ {row['home_team']}"
            print(
                f"{matchup[:34]:34} "
                f"{row['market_favorite']} "
                f"{row['market_favorite_size']:.1f} -> "
                f"{row['model_favorite_size']:.1f} "
                f"(compression {row['compression_points']:.1f})"
            )

    print("")
    print(f"Wrote: {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
