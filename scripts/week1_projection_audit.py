"""
CFB ANALYTICS
week1_projection_audit.py

WEEK 1 PROJECTION AUDIT — V2

Offline descriptive audit of the current production projection file.

This audit intentionally does NOT:
- call CFBD
- call an odds API
- alter model coefficients
- alter projections
- alter status labels
- treat the betting market as ground truth
- claim that market disagreement is predictive error

Purpose:
Measure how the current production model differs from the current Week 1
market, with particular attention to favorite magnitude.

The important distinction:

    MODEL vs MARKET = disagreement
    MODEL vs ACTUAL RESULT = prediction error

This file only performs the first comparison.

Reads:
    data/projections.json

Writes:
    data/week1_projection_audit.json
"""

import json
import math
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECTIONS_PATH = ROOT / "data" / "projections.json"
OUTPUT_PATH = ROOT / "data" / "week1_projection_audit.json"

TARGET_WEEK = 1

BUCKET_ORDER = (
    "0-3",
    "3-7",
    "7-14",
    "14-21",
    "21-28",
    "28-40",
    "40+",
)

EPSILON = 1e-9


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def round1(value):
    if value is None:
        return None
    return round(float(value), 1)


def round3(value):
    if value is None:
        return None
    return round(float(value), 3)


def round4(value):
    if value is None:
        return None
    return round(float(value), 4)


def safe_mean(values):
    values = [float(v) for v in values if v is not None]
    if not values:
        return None
    return sum(values) / len(values)


def safe_median(values):
    values = [float(v) for v in values if v is not None]
    if not values:
        return None
    return statistics.median(values)


def pct(numerator, denominator):
    if not denominator:
        return None
    return 100.0 * numerator / denominator


def favorite_from_home_spread(home_spread, home_team, away_team):
    """
    Convert a home-team spread into favorite identity and favorite size.

    Examples:
        home_spread = -7.5  -> home team favored by 7.5
        home_spread = +7.5  -> away team favored by 7.5
        home_spread =  0.0  -> pick'em
    """
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

    size = float(size)

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
    """
    Convert betting spread to projected signed HOME margin.

    home spread -7.5 -> home margin +7.5
    home spread +7.5 -> home margin -7.5
    """
    if home_spread is None:
        return None

    return -float(home_spread)


def model_margin_from_market_favorite_perspective(
    market_favorite,
    home_team,
    away_team,
    model_home_margin,
):
    """
    Orient the model margin around the MARKET favorite.

    Positive:
        model also has the market favorite winning.

    Negative:
        model has the market favorite losing.

    This lets every game be compared on one consistent axis:

        market favorite size
        vs
        model-implied margin for that same market favorite
    """
    if (
        market_favorite in (None, "PICKEM")
        or model_home_margin is None
    ):
        return None

    if market_favorite == home_team:
        return float(model_home_margin)

    if market_favorite == away_team:
        return -float(model_home_margin)

    return None


def classify_market_favorite_difference(
    market_favorite_size,
    model_margin_for_market_favorite,
):
    """
    Classify whether the model prices the MARKET favorite:

    SHORTER:
        model margin for market favorite < market favorite size

    LARGER:
        model margin for market favorite > market favorite size

    EQUAL:
        same magnitude to floating-point tolerance

    A favorite flip naturally becomes SHORTER because the model-oriented
    margin will be negative.
    """
    if (
        market_favorite_size is None
        or model_margin_for_market_favorite is None
    ):
        return None

    difference = (
        float(model_margin_for_market_favorite)
        - float(market_favorite_size)
    )

    if difference < -EPSILON:
        return "SHORTER"

    if difference > EPSILON:
        return "LARGER"

    return "EQUAL"


def ordinary_least_squares(xs, ys):
    """
    Simple closed-form OLS regression:

        y = intercept + slope * x

    For this audit:

        x = current market favorite size
        y = model margin from the market favorite's perspective

    This is DESCRIPTIVE ONLY.

    A slope below 1.0 means the model becomes less extreme than the market
    as current market favorite size increases.

    It does NOT prove that the model is wrong.
    """
    pairs = [
        (float(x), float(y))
        for x, y in zip(xs, ys)
        if x is not None and y is not None
    ]

    n = len(pairs)

    if n < 2:
        return {
            "n": n,
            "slope": None,
            "intercept": None,
            "r_squared": None,
        }

    x_values = [p[0] for p in pairs]
    y_values = [p[1] for p in pairs]

    mean_x = sum(x_values) / n
    mean_y = sum(y_values) / n

    ss_x = sum((x - mean_x) ** 2 for x in x_values)

    if abs(ss_x) <= EPSILON:
        return {
            "n": n,
            "slope": None,
            "intercept": None,
            "r_squared": None,
        }

    covariance_numerator = sum(
        (x - mean_x) * (y - mean_y)
        for x, y in pairs
    )

    slope = covariance_numerator / ss_x
    intercept = mean_y - slope * mean_x

    predictions = [
        intercept + slope * x
        for x in x_values
    ]

    ss_res = sum(
        (actual - predicted) ** 2
        for actual, predicted in zip(y_values, predictions)
    )

    ss_tot = sum(
        (actual - mean_y) ** 2
        for actual in y_values
    )

    if abs(ss_tot) <= EPSILON:
        r_squared = None
    else:
        r_squared = 1.0 - (ss_res / ss_tot)

    return {
        "n": n,
        "slope": round4(slope),
        "intercept": round4(intercept),
        "r_squared": round4(r_squared),
    }


def build_row(game):
    home_team = game["home"]["team"]
    away_team = game["away"]["team"]

    projection = game.get("projection", {}) or {}
    market = game.get("market", {}) or {}
    comparison = game.get("comparison", {}) or {}

    model_spread = projection.get("home_spread")
    market_spread = market.get("home_spread")

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

    market_home_margin = signed_home_margin_from_spread(
        market_spread
    )

    model_home_margin = signed_home_margin_from_spread(
        model_spread
    )

    signed_model_minus_market_home_margin = None

    if (
        market_home_margin is not None
        and model_home_margin is not None
    ):
        signed_model_minus_market_home_margin = (
            model_home_margin
            - market_home_margin
        )

    model_margin_for_market_favorite = (
        model_margin_from_market_favorite_perspective(
            market_favorite=market_favorite,
            home_team=home_team,
            away_team=away_team,
            model_home_margin=model_home_margin,
        )
    )

    model_minus_market_favorite_margin = None

    if (
        market_favorite_size is not None
        and model_margin_for_market_favorite is not None
    ):
        model_minus_market_favorite_margin = (
            model_margin_for_market_favorite
            - market_favorite_size
        )

    absolute_market_disagreement = None

    if model_minus_market_favorite_margin is not None:
        absolute_market_disagreement = abs(
            model_minus_market_favorite_margin
        )

    same_favorite = (
        market_favorite not in (None, "PICKEM")
        and market_favorite == model_favorite
    )

    favorite_flip = (
        market_favorite not in (None, "PICKEM")
        and model_favorite != market_favorite
    )

    market_favorite_difference_class = (
        classify_market_favorite_difference(
            market_favorite_size,
            model_margin_for_market_favorite,
        )
    )

    model_to_market_favorite_size_ratio = None

    if (
        market_favorite_size is not None
        and market_favorite_size > EPSILON
        and model_margin_for_market_favorite is not None
    ):
        model_to_market_favorite_size_ratio = (
            model_margin_for_market_favorite
            / market_favorite_size
        )

    return {
        "game_id": game.get("game_id"),
        "week": game.get("week"),
        "start_date": game.get("start_date"),
        "away_team": away_team,
        "home_team": home_team,
        "neutral_site": bool(
            game.get("neutral_site", False)
        ),

        "market_home_spread": round1(
            market_spread
        ),
        "model_home_spread": round1(
            model_spread
        ),

        "market_favorite": market_favorite,
        "market_favorite_size": round1(
            market_favorite_size
        ),
        "market_favorite_bucket": favorite_size_bucket(
            market_favorite_size
        ),

        "model_favorite": model_favorite,
        "model_favorite_size": round1(
            model_favorite_size
        ),

        "same_favorite": same_favorite,
        "favorite_flip": favorite_flip,

        "market_home_margin": round1(
            market_home_margin
        ),
        "model_home_margin": round1(
            model_home_margin
        ),

        "signed_model_minus_market_home_margin": round1(
            signed_model_minus_market_home_margin
        ),

        "model_margin_for_market_favorite": round1(
            model_margin_for_market_favorite
        ),

        "model_minus_market_favorite_margin": round1(
            model_minus_market_favorite_margin
        ),

        "absolute_market_disagreement": round1(
            absolute_market_disagreement
        ),

        "market_favorite_difference_class": (
            market_favorite_difference_class
        ),

        "model_to_market_favorite_size_ratio": round3(
            model_to_market_favorite_size_ratio
        ),

        "disagreement": round1(
            comparison.get("disagreement")
        ),
        "preferred_side": comparison.get(
            "preferred_side"
        ),
        "status": comparison.get(
            "status"
        ),
    }


def summarize_rows(rows):
    """
    Summarize ALL supplied rows.

    There is no conditioning on "compressed" games.

    This is the central methodological correction from Audit V1.
    """
    n = len(rows)

    if not n:
        return {
            "games": 0,
            "same_favorite_games": 0,
            "favorite_flip_games": 0,
            "model_shorter_games": 0,
            "model_larger_games": 0,
            "equal_magnitude_games": 0,
            "same_favorite_rate_pct": None,
            "favorite_flip_rate_pct": None,
            "model_shorter_rate_pct": None,
            "model_larger_rate_pct": None,
            "mean_signed_model_minus_market_favorite_margin": None,
            "median_signed_model_minus_market_favorite_margin": None,
            "mean_absolute_market_disagreement": None,
            "median_absolute_market_disagreement": None,
            "mean_model_to_market_favorite_size_ratio": None,
            "median_model_to_market_favorite_size_ratio": None,
        }

    market_favorite_rows = [
        row for row in rows
        if row["market_favorite"] not in (None, "PICKEM")
    ]

    comparable_n = len(market_favorite_rows)

    same_favorite_games = sum(
        1 for row in market_favorite_rows
        if row["same_favorite"]
    )

    favorite_flip_games = sum(
        1 for row in market_favorite_rows
        if row["favorite_flip"]
    )

    model_shorter_games = sum(
        1 for row in market_favorite_rows
        if row["market_favorite_difference_class"] == "SHORTER"
    )

    model_larger_games = sum(
        1 for row in market_favorite_rows
        if row["market_favorite_difference_class"] == "LARGER"
    )

    equal_magnitude_games = sum(
        1 for row in market_favorite_rows
        if row["market_favorite_difference_class"] == "EQUAL"
    )

    signed_differences = [
        row["model_minus_market_favorite_margin"]
        for row in market_favorite_rows
        if row["model_minus_market_favorite_margin"] is not None
    ]

    absolute_differences = [
        row["absolute_market_disagreement"]
        for row in market_favorite_rows
        if row["absolute_market_disagreement"] is not None
    ]

    ratios = [
        row["model_to_market_favorite_size_ratio"]
        for row in market_favorite_rows
        if row["model_to_market_favorite_size_ratio"] is not None
    ]

    shorter_same_favorite_games = sum(
        1 for row in market_favorite_rows
        if (
            row["same_favorite"]
            and row["market_favorite_difference_class"] == "SHORTER"
        )
    )

    return {
        "games": n,
        "market_favorite_games": comparable_n,

        "same_favorite_games": same_favorite_games,
        "favorite_flip_games": favorite_flip_games,

        "model_shorter_games": model_shorter_games,
        "model_larger_games": model_larger_games,
        "equal_magnitude_games": equal_magnitude_games,

        "same_favorite_rate_pct": round1(
            pct(
                same_favorite_games,
                comparable_n,
            )
        ),

        "favorite_flip_rate_pct": round1(
            pct(
                favorite_flip_games,
                comparable_n,
            )
        ),

        "model_shorter_rate_pct": round1(
            pct(
                model_shorter_games,
                comparable_n,
            )
        ),

        "model_larger_rate_pct": round1(
            pct(
                model_larger_games,
                comparable_n,
            )
        ),

        "model_shorter_rate_among_same_favorite_pct": round1(
            pct(
                shorter_same_favorite_games,
                same_favorite_games,
            )
        ),

        "mean_signed_model_minus_market_favorite_margin": round1(
            safe_mean(signed_differences)
        ),

        "median_signed_model_minus_market_favorite_margin": round1(
            safe_median(signed_differences)
        ),

        "mean_absolute_market_disagreement": round1(
            safe_mean(absolute_differences)
        ),

        "median_absolute_market_disagreement": round1(
            safe_median(absolute_differences)
        ),

        "mean_model_to_market_favorite_size_ratio": round3(
            safe_mean(ratios)
        ),

        "median_model_to_market_favorite_size_ratio": round3(
            safe_median(ratios)
        ),
    }


def main():
    payload = load_json(
        PROJECTIONS_PATH
    )

    games = (
        payload.get("games")
        or payload.get("projections")
        or []
    )

    week_games = [
        game
        for game in games
        if game.get("week") == TARGET_WEEK
    ]

    rows = [
        build_row(game)
        for game in week_games
    ]

    lined = [
        row
        for row in rows
        if (
            row["market_home_spread"] is not None
            and row["model_home_spread"] is not None
        )
    ]

    lined.sort(
        key=lambda row: (
            -(row["absolute_market_disagreement"] or 0.0),
            row["start_date"] or "",
            row["away_team"],
        )
    )

    status_counts = Counter(
        row["status"]
        for row in lined
    )

    overall_summary = summarize_rows(
        lined
    )

    bucket_summary = {}

    for bucket in BUCKET_ORDER:
        bucket_rows = [
            row
            for row in lined
            if row["market_favorite_bucket"] == bucket
        ]

        bucket_summary[bucket] = summarize_rows(
            bucket_rows
        )

    favorites_14_plus = [
        row
        for row in lined
        if (
            row["market_favorite_size"] is not None
            and row["market_favorite_size"] >= 14.0
        )
    ]

    favorites_21_plus = [
        row
        for row in lined
        if (
            row["market_favorite_size"] is not None
            and row["market_favorite_size"] >= 21.0
        )
    ]

    regression_rows = [
        row
        for row in lined
        if (
            row["market_favorite"] not in (None, "PICKEM")
            and row["market_favorite_size"] is not None
            and row["model_margin_for_market_favorite"] is not None
        )
    ]

    regression = ordinary_least_squares(
        [
            row["market_favorite_size"]
            for row in regression_rows
        ],
        [
            row["model_margin_for_market_favorite"]
            for row in regression_rows
        ],
    )

    model_shorter_games = [
        row
        for row in lined
        if row["market_favorite_difference_class"] == "SHORTER"
    ]

    model_larger_games = [
        row
        for row in lined
        if row["market_favorite_difference_class"] == "LARGER"
    ]

    favorite_flips = [
        row
        for row in lined
        if row["favorite_flip"]
    ]

    report = {
        "meta": {
            "generated": datetime.now().isoformat(),
            "source": "data/projections.json",
            "week": TARGET_WEEK,
            "version": "2.0",
            "purpose": (
                "offline descriptive audit of current Week 1 "
                "production-model disagreement with the current market"
            ),
        },

        "methodology_notes": [
            (
                "The current betting market is used as a comparison "
                "benchmark, not as ground truth."
            ),
            (
                "Model-vs-market differences are disagreement, not "
                "prediction error."
            ),
            (
                "Prediction error can only be measured against actual "
                "game outcomes."
            ),
            (
                "All lined games are included in bucket summaries. "
                "Audit V2 does not condition averages on games where "
                "the model is shorter than the market."
            ),
            (
                "model_minus_market_favorite_margin is oriented around "
                "the current market favorite. Negative values mean the "
                "model prices that favorite shorter than the market; "
                "positive values mean the model prices that favorite "
                "larger."
            ),
            (
                "If the model flips the favorite, "
                "model_margin_for_market_favorite becomes negative and "
                "the game remains included in the analysis."
            ),
            (
                "The model-vs-market regression is descriptive only. "
                "A slope below 1.0 shows that the model is less extreme "
                "than the current market as favorite size increases; "
                "it does not establish which side is more accurate."
            ),
            (
                "No model coefficients, projection outputs, or status "
                "labels are changed by this audit."
            ),
        ],

        "summary": {
            "week_games": len(rows),
            "lined_games": len(lined),
            "status_counts": dict(status_counts),
            **overall_summary,
        },

        "large_favorite_summaries": {
            "market_favorites_14_plus": summarize_rows(
                favorites_14_plus
            ),
            "market_favorites_21_plus": summarize_rows(
                favorites_21_plus
            ),
        },

        "favorite_size_buckets": bucket_summary,

        "model_vs_market_regression": {
            "x": "market_favorite_size",
            "y": "model_margin_for_market_favorite",
            "interpretation": (
                "descriptive comparison only; market is not ground truth"
            ),
            **regression,
        },

        "model_shorter_than_market": model_shorter_games,
        "model_larger_than_market": model_larger_games,
        "favorite_flips": favorite_flips,

        "games_sorted_by_absolute_market_disagreement": lined,
    }

    with OUTPUT_PATH.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            report,
            f,
            indent=2,
        )

    print("=" * 82)
    print("WEEK 1 PROJECTION AUDIT — V2")
    print(
        "DESCRIPTIVE MODEL-vs-MARKET ANALYSIS ONLY — "
        "MARKET IS NOT GROUND TRUTH"
    )
    print("=" * 82)

    print(
        f"Week 1 games: {len(rows)}"
    )
    print(
        f"Lined games:  {len(lined)}"
    )
    print(
        f"Status counts: {dict(status_counts)}"
    )

    print("")
    print("OVERALL MODEL / MARKET RELATIONSHIP")
    print("-" * 82)

    print(
        "Same favorite: "
        f"{overall_summary['same_favorite_games']}/"
        f"{overall_summary['market_favorite_games']} "
        f"({overall_summary['same_favorite_rate_pct']}%)"
    )

    print(
        "Favorite flips: "
        f"{overall_summary['favorite_flip_games']}/"
        f"{overall_summary['market_favorite_games']} "
        f"({overall_summary['favorite_flip_rate_pct']}%)"
    )

    print(
        "Model shorter than market favorite: "
        f"{overall_summary['model_shorter_games']}/"
        f"{overall_summary['market_favorite_games']} "
        f"({overall_summary['model_shorter_rate_pct']}%)"
    )

    print(
        "Model larger than market favorite: "
        f"{overall_summary['model_larger_games']}/"
        f"{overall_summary['market_favorite_games']} "
        f"({overall_summary['model_larger_rate_pct']}%)"
    )

    print(
        "Mean signed difference: "
        f"{overall_summary['mean_signed_model_minus_market_favorite_margin']}"
    )

    print(
        "Median signed difference: "
        f"{overall_summary['median_signed_model_minus_market_favorite_margin']}"
    )

    print(
        "Mean absolute disagreement: "
        f"{overall_summary['mean_absolute_market_disagreement']}"
    )

    print("")
    print("MARKET FAVORITES 14+")
    print("-" * 82)

    summary_14 = report[
        "large_favorite_summaries"
    ]["market_favorites_14_plus"]

    print(
        "Games: "
        f"{summary_14['games']}"
    )

    print(
        "Model shorter: "
        f"{summary_14['model_shorter_games']}/"
        f"{summary_14['market_favorite_games']} "
        f"({summary_14['model_shorter_rate_pct']}%)"
    )

    print(
        "Mean signed difference: "
        f"{summary_14['mean_signed_model_minus_market_favorite_margin']}"
    )

    print("")
    print("MARKET FAVORITES 21+")
    print("-" * 82)

    summary_21 = report[
        "large_favorite_summaries"
    ]["market_favorites_21_plus"]

    print(
        "Games: "
        f"{summary_21['games']}"
    )

    print(
        "Model shorter: "
        f"{summary_21['model_shorter_games']}/"
        f"{summary_21['market_favorite_games']} "
        f"({summary_21['model_shorter_rate_pct']}%)"
    )

    print(
        "Mean signed difference: "
        f"{summary_21['mean_signed_model_minus_market_favorite_margin']}"
    )

    print("")
    print("FAVORITE-SIZE BUCKETS")
    print("-" * 82)

    for bucket in BUCKET_ORDER:
        summary = bucket_summary[bucket]

        print(
            f"{bucket:>6}  "
            f"n={summary['games']:>2}  "
            f"shorter={summary['model_shorter_games']:>2}  "
            f"larger={summary['model_larger_games']:>2}  "
            f"flips={summary['favorite_flip_games']:>2}  "
            f"mean_diff="
            f"{summary['mean_signed_model_minus_market_favorite_margin']}"
        )

    print("")
    print("DESCRIPTIVE REGRESSION")
    print("-" * 82)

    print(
        "Model market-favorite margin = "
        f"{regression['intercept']} + "
        f"{regression['slope']} × market favorite size"
    )

    print(
        f"R²: {regression['r_squared']}"
    )

    print("")
    print("TOP MODEL / MARKET DISAGREEMENTS")
    print("-" * 82)

    for row in lined[:15]:
        matchup = (
            f"{row['away_team']} @ "
            f"{row['home_team']}"
        )

        print(
            f"{matchup[:34]:34} "
            f"MKT {row['market_home_spread']:>6.1f}  "
            f"MOD {row['model_home_spread']:>6.1f}  "
            f"DIFF {row['absolute_market_disagreement']:>4.1f}  "
            f"{row['status']}"
        )

    print("")
    print(
        "IMPORTANT: This audit measures disagreement with the market."
    )
    print(
        "It does NOT determine whether the model or market is correct."
    )

    print("")
    print(
        f"Wrote: {OUTPUT_PATH.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
