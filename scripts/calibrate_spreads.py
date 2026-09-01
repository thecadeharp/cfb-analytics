"""
CFB ANALYTICS
calibrate_spreads.py

Historical spread calibration audit.

Purpose:
- Measure how strongly team-rating differences translate to actual scoring margin
- Estimate historical home-field advantage
- Test whether extreme projected margins need compression
- Compare model-style projections against actual results
- Keep the LIVE 2026 projection engine untouched until the audit is reviewed

This script is diagnostic only.
It does NOT modify data/projections.json.
"""

import json
import math
import os
import statistics
import sys

import requests


# =============================================================================
# CONFIG
# =============================================================================

CFBD_BASE = "https://api.collegefootballdata.com"

START_YEAR = 2019
END_YEAR = 2025

OUTPUT_PATH = "data/calibration_report.json"

# Exclude games where rating information is missing.
MIN_GAMES = 500

# Current live model number, for comparison only.
CURRENT_HFA = 2.0

# Buckets let us see whether large favorite projections become too aggressive.
MARGIN_BUCKETS = [
    (0, 7),
    (7, 14),
    (14, 21),
    (21, 28),
    (28, 35),
    (35, 999),
]


# =============================================================================
# HELPERS
# =============================================================================

def clean_api_key(raw):

    if raw is None:
        return ""

    key = str(raw).strip()

    if (
        len(key) >= 2
        and key[0] == key[-1]
        and key[0] in ("'", '"')
    ):
        key = key[1:-1].strip()

    if key.lower().startswith("bearer "):
        key = key[7:].strip()

    return (
        key
        .replace("\r", "")
        .replace("\n", "")
        .replace("\t", "")
        .strip()
    )


CFBD_API_KEY = clean_api_key(
    os.environ.get(
        "CFBD_API_KEY",
        ""
    )
)


def safe_number(value):

    try:

        if value is None:
            return None

        return float(value)

    except (
        TypeError,
        ValueError
    ):

        return None


def mean(values):

    values = [
        value
        for value in values
        if value is not None
    ]

    if not values:
        return None

    return statistics.mean(values)


def mae(predictions, actuals):

    return statistics.mean(
        abs(pred - actual)
        for pred, actual
        in zip(predictions, actuals)
    )


def rmse(predictions, actuals):

    return math.sqrt(
        statistics.mean(
            (pred - actual) ** 2
            for pred, actual
            in zip(predictions, actuals)
        )
    )


def regression(x_values, y_values):

    if len(x_values) != len(y_values):

        raise ValueError(
            "Regression arrays must have equal length."
        )

    if len(x_values) < 2:

        return {
            "slope": 0.0,
            "intercept": 0.0,
            "r_squared": 0.0,
        }

    x_mean = statistics.mean(x_values)
    y_mean = statistics.mean(y_values)

    numerator = sum(
        (x - x_mean) * (y - y_mean)
        for x, y
        in zip(x_values, y_values)
    )

    denominator = sum(
        (x - x_mean) ** 2
        for x in x_values
    )

    slope = (
        numerator / denominator
        if denominator
        else 0.0
    )

    intercept = (
        y_mean
        - slope * x_mean
    )

    predictions = [
        intercept + slope * x
        for x in x_values
    ]

    total_variance = sum(
        (y - y_mean) ** 2
        for y in y_values
    )

    residual_variance = sum(
        (y - pred) ** 2
        for y, pred
        in zip(y_values, predictions)
    )

    r_squared = (
        1.0
        - residual_variance / total_variance
        if total_variance
        else 0.0
    )

    return {
        "slope": slope,
        "intercept": intercept,
        "r_squared": r_squared,
    }


# =============================================================================
# API
# =============================================================================

def cfbd_get(
    endpoint,
    params=None
):

    if not CFBD_API_KEY:

        print(
            "❌ CFBD_API_KEY missing."
        )

        sys.exit(1)

    try:

        response = requests.get(
            f"{CFBD_BASE}{endpoint}",
            headers={
                "Authorization":
                    f"Bearer {CFBD_API_KEY}",
                "Accept":
                    "application/json",
            },
            params=params,
            timeout=60
        )

    except requests.RequestException as error:

        print(
            f"❌ CFBD request failed: {error}"
        )

        sys.exit(1)

    if response.status_code in (
        401,
        403
    ):

        print(
            "❌ CFBD authentication failed."
        )

        sys.exit(1)

    if not response.ok:

        print(
            f"❌ CFBD {endpoint}: "
            f"HTTP {response.status_code}"
        )

        print(
            response.text[:500]
        )

        sys.exit(1)

    try:

        return response.json()

    except ValueError:

        print(
            "❌ CFBD returned invalid JSON."
        )

        sys.exit(1)


# =============================================================================
# DATA COLLECTION
# =============================================================================

def get_sp_ratings(year):

    print(
        f"   Loading {year} SP+..."
    )

    raw = cfbd_get(
        "/ratings/sp",
        {
            "year": year
        }
    )

    ratings = {}

    for row in raw:

        team = row.get("team")

        rating = safe_number(
            row.get("rating")
        )

        if (
            team
            and rating is not None
        ):

            ratings[team] = rating

    print(
        f"      {len(ratings)} teams"
    )

    return ratings


def get_games(year):

    print(
        f"   Loading {year} games..."
    )

    raw = cfbd_get(
        "/games",
        {
            "year": year,
            "seasonType": "regular",
            "classification": "fbs",
        }
    )

    games = []

    for game in raw:

        home = game.get(
            "homeTeam"
        )

        away = game.get(
            "awayTeam"
        )

        home_points = safe_number(
            game.get(
                "homePoints"
            )
        )

        away_points = safe_number(
            game.get(
                "awayPoints"
            )
        )

        if (
            not home
            or not away
            or home_points is None
            or away_points is None
        ):
            continue

        neutral = bool(
            game.get(
                "neutralSite",
                False
            )
        )

        games.append({
            "id":
                game.get("id"),

            "week":
                game.get("week"),

            "home":
                home,

            "away":
                away,

            "home_points":
                home_points,

            "away_points":
                away_points,

            "neutral":
                neutral,

            "actual_home_margin":
                home_points
                - away_points,
        })

    print(
        f"      {len(games)} completed games"
    )

    return games


# =============================================================================
# BUILD HISTORICAL SAMPLE
# =============================================================================

def build_sample():

    sample = []

    print("")
    print(
        "📚 Building historical sample"
    )

    for year in range(
        START_YEAR,
        END_YEAR + 1
    ):

        print("")
        print(
            f"▶ {year}"
        )

        ratings = get_sp_ratings(
            year
        )

        games = get_games(
            year
        )

        matched = 0

        for game in games:

            home_rating = ratings.get(
                game["home"]
            )

            away_rating = ratings.get(
                game["away"]
            )

            if (
                home_rating is None
                or away_rating is None
            ):
                continue

            rating_diff = (
                home_rating
                - away_rating
            )

            sample.append({
                "year":
                    year,

                "week":
                    game["week"],

                "home":
                    game["home"],

                "away":
                    game["away"],

                "neutral":
                    game["neutral"],

                "home_rating":
                    home_rating,

                "away_rating":
                    away_rating,

                "rating_diff":
                    rating_diff,

                "actual_home_margin":
                    game[
                        "actual_home_margin"
                    ],
            })

            matched += 1

        print(
            f"      {matched} rating-matched games"
        )

    return sample


# =============================================================================
# CALIBRATION
# =============================================================================

def calibrate(sample):

    if len(sample) < MIN_GAMES:

        print(
            f"❌ Only {len(sample)} usable games."
        )

        print(
            f"   Need at least {MIN_GAMES}."
        )

        sys.exit(1)

    rating_diffs = [
        game["rating_diff"]
        for game in sample
    ]

    actual_margins = [
        game["actual_home_margin"]
        for game in sample
    ]

    overall_fit = regression(
        rating_diffs,
        actual_margins
    )

    neutral_games = [
        game
        for game in sample
        if game["neutral"]
    ]

    non_neutral_games = [
        game
        for game in sample
        if not game["neutral"]
    ]

    # Estimate HFA as the residual home advantage
    # after accounting for SP+ rating difference.

    slope_without_hfa = (
        overall_fit["slope"]
    )

    home_residuals = [
        game["actual_home_margin"]
        - (
            slope_without_hfa
            * game["rating_diff"]
        )
        for game in non_neutral_games
    ]

    estimated_hfa = mean(
        home_residuals
    )

    if estimated_hfa is None:
        estimated_hfa = CURRENT_HFA

    predictions = []

    for game in sample:

        hfa = (
            0.0
            if game["neutral"]
            else estimated_hfa
        )

        prediction = (
            overall_fit["slope"]
            * game["rating_diff"]
            + hfa
        )

        predictions.append(
            prediction
        )

        game["calibrated_prediction"] = (
            prediction
        )

        game["absolute_error"] = abs(
            prediction
            - game["actual_home_margin"]
        )

    actuals = [
        game["actual_home_margin"]
        for game in sample
    ]

    # -------------------------------------------------------------------------
    # Extreme-margin audit
    # -------------------------------------------------------------------------

    buckets = []

    for low, high in MARGIN_BUCKETS:

        bucket_games = [
            game
            for game in sample
            if (
                abs(
                    game[
                        "calibrated_prediction"
                    ]
                ) >= low
                and
                abs(
                    game[
                        "calibrated_prediction"
                    ]
                ) < high
            )
        ]

        if not bucket_games:
            continue

        predicted_abs = mean([
            abs(
                game[
                    "calibrated_prediction"
                ]
            )
            for game in bucket_games
        ])

        actual_abs = mean([
            abs(
                game[
                    "actual_home_margin"
                ]
            )
            for game in bucket_games
        ])

        bucket_mae = mean([
            game["absolute_error"]
            for game in bucket_games
        ])

        buckets.append({
            "range":
                (
                    f"{low}-{high - 0.1:.1f}"
                    if high < 999
                    else f"{low}+"
                ),

            "games":
                len(bucket_games),

            "average_projected_margin":
                round(
                    predicted_abs,
                    3
                ),

            "average_actual_margin":
                round(
                    actual_abs,
                    3
                ),

            "mae":
                round(
                    bucket_mae,
                    3
                ),

            "actual_minus_projected":
                round(
                    actual_abs
                    - predicted_abs,
                    3
                ),
        })

    # -------------------------------------------------------------------------
    # Favorite direction / bias
    # -------------------------------------------------------------------------

    large_favorites = [
        game
        for game in sample
        if abs(
            game[
                "calibrated_prediction"
            ]
        ) >= 28
    ]

    large_favorite_bias = mean([
        abs(
            game[
                "actual_home_margin"
            ]
        )
        - abs(
            game[
                "calibrated_prediction"
            ]
        )
        for game in large_favorites
    ])

    # -------------------------------------------------------------------------
    # Year-by-year holdout-style reporting
    # -------------------------------------------------------------------------

    yearly = []

    for year in range(
        START_YEAR,
        END_YEAR + 1
    ):

        year_games = [
            game
            for game in sample
            if game["year"] == year
        ]

        if not year_games:
            continue

        year_predictions = [
            game[
                "calibrated_prediction"
            ]
            for game in year_games
        ]

        year_actuals = [
            game[
                "actual_home_margin"
            ]
            for game in year_games
        ]

        yearly.append({
            "year":
                year,

            "games":
                len(year_games),

            "mae":
                round(
                    mae(
                        year_predictions,
                        year_actuals
                    ),
                    3
                ),

            "rmse":
                round(
                    rmse(
                        year_predictions,
                        year_actuals
                    ),
                    3
                ),
        })

    return {
        "sample": {
            "start_year":
                START_YEAR,

            "end_year":
                END_YEAR,

            "games":
                len(sample),

            "neutral_games":
                len(neutral_games),

            "non_neutral_games":
                len(non_neutral_games),
        },

        "rating_to_margin": {
            "slope":
                round(
                    overall_fit["slope"],
                    5
                ),

            "raw_intercept":
                round(
                    overall_fit["intercept"],
                    5
                ),

            "r_squared":
                round(
                    overall_fit["r_squared"],
                    5
                ),
        },

        "home_field": {
            "current_model":
                CURRENT_HFA,

            "historical_estimate":
                round(
                    estimated_hfa,
                    3
                ),
        },

        "accuracy": {
            "mae":
                round(
                    mae(
                        predictions,
                        actuals
                    ),
                    3
                ),

            "rmse":
                round(
                    rmse(
                        predictions,
                        actuals
                    ),
                    3
                ),
        },

        "extreme_favorites": {
            "games_28_plus":
                len(
                    large_favorites
                ),

            "actual_minus_projected_margin":
                (
                    round(
                        large_favorite_bias,
                        3
                    )
                    if large_favorite_bias
                    is not None
                    else None
                ),

            "interpretation":
                (
                    "Negative means large projected "
                    "favorites historically won by "
                    "less than the model projection."
                ),
        },

        "margin_buckets":
            buckets,

        "year_by_year":
            yearly,
    }


# =============================================================================
# OUTPUT
# =============================================================================

def print_report(report):

    print("")
    print(
        "=" * 72
    )

    print(
        "CFB SPREAD CALIBRATION REPORT"
    )

    print(
        "=" * 72
    )

    print("")

    print(
        f"Historical sample: "
        f"{report['sample']['games']} games "
        f"({START_YEAR}-{END_YEAR})"
    )

    print("")

    print(
        "RATING → SCORING MARGIN"
    )

    print(
        f"   Historical coefficient: "
        f"{report['rating_to_margin']['slope']:.3f}"
    )

    print(
        f"   R²: "
        f"{report['rating_to_margin']['r_squared']:.3f}"
    )

    print("")

    print(
        "HOME FIELD"
    )

    print(
        f"   Current model: "
        f"{CURRENT_HFA:.2f} pts"
    )

    print(
        f"   Historical estimate: "
        f"{report['home_field']['historical_estimate']:.2f} pts"
    )

    print("")

    print(
        "PREDICTION ERROR"
    )

    print(
        f"   MAE: "
        f"{report['accuracy']['mae']:.2f} pts"
    )

    print(
        f"   RMSE: "
        f"{report['accuracy']['rmse']:.2f} pts"
    )

    print("")

    print(
        "PROJECTED MARGIN BUCKETS"
    )

    for bucket in report[
        "margin_buckets"
    ]:

        print(
            f"   {bucket['range']:>8} | "
            f"{bucket['games']:>4} games | "
            f"proj {bucket['average_projected_margin']:>6.2f} | "
            f"actual {bucket['average_actual_margin']:>6.2f} | "
            f"MAE {bucket['mae']:>5.2f}"
        )

    print("")

    extreme = report[
        "extreme_favorites"
    ]

    print(
        "28+ POINT PROJECTION CHECK"
    )

    print(
        f"   Games: "
        f"{extreme['games_28_plus']}"
    )

    print(
        f"   Actual minus projected: "
        f"{extreme['actual_minus_projected_margin']}"
    )

    print("")

    if (
        extreme[
            "actual_minus_projected_margin"
        ]
        is not None
        and
        extreme[
            "actual_minus_projected_margin"
        ] < -2.0
    ):

        print(
            "⚠️  Large favorites appear "
            "systematically over-projected."
        )

        print(
            "   We should test margin compression "
            "before trusting huge fair lines."
        )

    else:

        print(
            "✅ No major historical evidence "
            "of extreme-margin inflation."
        )

    print("")
    print(
        "=" * 72
    )


def save_report(
    report,
    sample
):

    output = {
        "report":
            report,

        "games":
            sample,
    }

    os.makedirs(
        os.path.dirname(
            OUTPUT_PATH
        ),
        exist_ok=True
    )

    with open(
        OUTPUT_PATH,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            indent=2
        )

    size_kb = (
        os.path.getsize(
            OUTPUT_PATH
        )
        / 1024
    )

    print(
        f"💾 Saved {OUTPUT_PATH} "
        f"({size_kb:.1f} KB)"
    )


# =============================================================================
# MAIN
# =============================================================================

def main():

    print("")
    print(
        "🧪 CFB spread calibration audit"
    )

    print(
        f"   Seasons: "
        f"{START_YEAR}-{END_YEAR}"
    )

    sample = build_sample()

    print("")
    print(
        f"✅ Historical games matched: "
        f"{len(sample)}"
    )

    report = calibrate(
        sample
    )

    print_report(
        report
    )

    save_report(
        report,
        sample
    )


if __name__ == "__main__":
    main()
