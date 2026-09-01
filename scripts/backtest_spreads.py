"""
CFB ANALYTICS
backtest_spreads.py

Time-safe historical spread backtest.

Uses:
- CFBD pregame Elo ratings from each historical game
- Actual final scoring margin
- Historical closing betting lines when available

Goals:
- Fit Elo difference -> scoring margin using PRIOR seasons only
- Estimate home-field advantage without future leakage
- Test projected margin accuracy out of sample
- Compare model projections to historical closing lines
- Measure ATS performance by model/market disagreement size

IMPORTANT:
This is a diagnostic backtest.
It does NOT modify the live 2026 projection engine.
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

# First year we will actually score as out-of-sample.
# Earlier seasons become the initial training set.
FIRST_TEST_YEAR = 2022

OUTPUT_PATH = "data/backtest_report.json"

MIN_TRAINING_GAMES = 500

# Edge buckets are ABSOLUTE model-vs-market disagreement.
EDGE_BUCKETS = [
    (0.0, 1.5),
    (1.5, 3.0),
    (3.0, 4.0),
    (4.0, 5.0),
    (5.0, 7.0),
    (7.0, 10.0),
    (10.0, 999.0),
]

# Display thresholds we are evaluating.
PROPOSED_WATCH_MAX = 3.0
PROPOSED_EDGE_MIN = 3.0
PROPOSED_HIGH_CONVICTION_MIN = 7.0


# =============================================================================
# API KEY
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


# =============================================================================
# BASIC HELPERS
# =============================================================================

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

    clean = [
        value
        for value in values
        if value is not None
    ]

    if not clean:
        return None

    return statistics.mean(clean)


def mae(predictions, actuals):

    if not predictions:
        return None

    return statistics.mean(
        abs(predicted - actual)
        for predicted, actual
        in zip(predictions, actuals)
    )


def rmse(predictions, actuals):

    if not predictions:
        return None

    return math.sqrt(
        statistics.mean(
            (predicted - actual) ** 2
            for predicted, actual
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

    x_mean = statistics.mean(
        x_values
    )

    y_mean = statistics.mean(
        y_values
    )

    numerator = sum(
        (x - x_mean)
        *
        (y - y_mean)
        for x, y
        in zip(
            x_values,
            y_values
        )
    )

    denominator = sum(
        (x - x_mean) ** 2
        for x in x_values
    )

    slope = (
        numerator
        /
        denominator
        if denominator
        else 0.0
    )

    intercept = (
        y_mean
        -
        slope * x_mean
    )

    predictions = [
        intercept
        +
        slope * x
        for x in x_values
    ]

    total_variance = sum(
        (y - y_mean) ** 2
        for y in y_values
    )

    residual_variance = sum(
        (y - prediction) ** 2
        for y, prediction
        in zip(
            y_values,
            predictions
        )
    )

    r_squared = (
        1.0
        -
        residual_variance
        /
        total_variance
        if total_variance
        else 0.0
    )

    return {
        "slope": slope,
        "intercept": intercept,
        "r_squared": r_squared,
    }


# =============================================================================
# CFBD REQUEST
# =============================================================================

def cfbd_get(
    endpoint,
    params=None,
    required=True
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

        if required:
            sys.exit(1)

        return []

    if response.status_code in (
        401,
        403
    ):

        if required:

            print(
                "❌ CFBD authentication/access failed."
            )

            sys.exit(1)

        print(
            f"⚠ CFBD access unavailable for {endpoint}."
        )

        return []

    if not response.ok:

        print(
            f"⚠ CFBD {endpoint}: "
            f"HTTP {response.status_code}"
        )

        if required:
            sys.exit(1)

        return []

    try:

        return response.json()

    except ValueError:

        print(
            f"⚠ Invalid JSON from {endpoint}"
        )

        if required:
            sys.exit(1)

        return []


# =============================================================================
# HISTORICAL GAMES
# =============================================================================

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

        home_elo = safe_number(
            game.get(
                "homePregameElo"
            )
        )

        away_elo = safe_number(
            game.get(
                "awayPregameElo"
            )
        )

        home_class = str(
            game.get(
                "homeClassification",
                ""
            )
        ).lower()

        away_class = str(
            game.get(
                "awayClassification",
                ""
            )
        ).lower()

        if (
            home_class != "fbs"
            or away_class != "fbs"
        ):
            continue

        if (
            not home
            or not away
            or home_points is None
            or away_points is None
            or home_elo is None
            or away_elo is None
        ):
            continue

        neutral = bool(
            game.get(
                "neutralSite",
                False
            )
        )

        games.append({
            "game_id":
                game.get("id"),

            "year":
                year,

            "week":
                game.get("week"),

            "home":
                home,

            "away":
                away,

            "neutral":
                neutral,

            "home_elo":
                home_elo,

            "away_elo":
                away_elo,

            "elo_diff":
                home_elo - away_elo,

            "actual_home_margin":
                home_points
                - away_points,
        })

    print(
        f"      {len(games)} usable FBS games"
    )

    return games


# =============================================================================
# HISTORICAL BETTING LINES
# =============================================================================

def choose_spread_from_provider(provider):

    if not isinstance(
        provider,
        dict
    ):
        return None

    spread = safe_number(
        provider.get(
            "spread"
        )
    )

    if spread is not None:
        return spread

    return None


def extract_consensus_spread(line_game):

    providers = (
        line_game.get(
            "lines"
        )
        or []
    )

    if not providers:
        return None

    preferred = [
        "DraftKings",
        "FanDuel",
        "BetMGM",
        "Caesars",
        "Consensus",
    ]

    for provider_name in preferred:

        for provider in providers:

            if (
                str(
                    provider.get(
                        "provider",
                        ""
                    )
                ).lower()
                ==
                provider_name.lower()
            ):

                spread = (
                    choose_spread_from_provider(
                        provider
                    )
                )

                if spread is not None:
                    return spread

    all_spreads = []

    for provider in providers:

        spread = (
            choose_spread_from_provider(
                provider
            )
        )

        if spread is not None:
            all_spreads.append(
                spread
            )

    if not all_spreads:
        return None

    return statistics.median(
        all_spreads
    )


def get_lines(year):

    print(
        f"   Loading {year} closing lines..."
    )

    raw = cfbd_get(
        "/lines",
        {
            "year": year,
            "seasonType": "regular",
        },
        required=False
    )

    lines = {}

    if not raw:

        print(
            "      No historical lines returned."
        )

        return lines

    matched = 0

    for item in raw:

        game_id = (
            item.get(
                "id"
            )
            or
            item.get(
                "gameId"
            )
        )

        if game_id is None:
            continue

        spread = (
            extract_consensus_spread(
                item
            )
        )

        if spread is None:
            continue

        lines[
            int(game_id)
        ] = spread

        matched += 1

    print(
        f"      {matched} games with spreads"
    )

    return lines


# =============================================================================
# TRAINING
# =============================================================================

def fit_model(training_games):

    if len(training_games) < MIN_TRAINING_GAMES:

        raise ValueError(
            f"Only {len(training_games)} "
            f"training games available."
        )

    elo_diffs = [
        game["elo_diff"]
        for game in training_games
    ]

    actual_margins = [
        game[
            "actual_home_margin"
        ]
        for game in training_games
    ]

    # Fit neutral/overall Elo relationship first.
    overall_fit = regression(
        elo_diffs,
        actual_margins
    )

    # Estimate home-field advantage from
    # residuals on non-neutral games.
    non_neutral = [
        game
        for game in training_games
        if not game["neutral"]
    ]

    residuals = [
        game["actual_home_margin"]
        -
        (
            overall_fit["slope"]
            *
            game["elo_diff"]
        )
        for game in non_neutral
    ]

    hfa = mean(
        residuals
    )

    if hfa is None:
        hfa = 2.0

    return {
        "elo_coefficient":
            overall_fit["slope"],

        "raw_intercept":
            overall_fit["intercept"],

        "r_squared":
            overall_fit["r_squared"],

        "home_field":
            hfa,
    }


# =============================================================================
# ATS LOGIC
# =============================================================================

def evaluate_ats(
    actual_home_margin,
    market_home_spread,
    model_home_margin
):

    # Market spread convention:
    #
    # Home favorite -7
    # Home underdog +7
    #
    # Convert market spread into the
    # market's expected HOME margin.
    #
    # Example:
    # home -7 => market expected home margin +7

    market_home_margin = (
        -market_home_spread
    )

    model_edge = (
        model_home_margin
        -
        market_home_margin
    )

    if model_edge > 0:

        # Model likes HOME relative to market.
        model_side = "home"

        cover_margin = (
            actual_home_margin
            +
            market_home_spread
        )

    elif model_edge < 0:

        # Model likes AWAY relative to market.
        model_side = "away"

        cover_margin = -(
            actual_home_margin
            +
            market_home_spread
        )

    else:

        return {
            "model_edge":
                0.0,

            "absolute_edge":
                0.0,

            "model_side":
                "none",

            "ats_result":
                "no_edge",
        }

    if cover_margin > 0:

        result = "win"

    elif cover_margin < 0:

        result = "loss"

    else:

        result = "push"

    return {
        "model_edge":
            model_edge,

        "absolute_edge":
            abs(
                model_edge
            ),

        "model_side":
            model_side,

        "ats_result":
            result,
    }


# =============================================================================
# EDGE REPORTING
# =============================================================================

def summarize_edge_games(
    games
):

    decisions = [
        game
        for game in games
        if game.get(
            "ats_result"
        )
        in (
            "win",
            "loss",
            "push"
        )
    ]

    wins = sum(
        1
        for game in decisions
        if game["ats_result"] == "win"
    )

    losses = sum(
        1
        for game in decisions
        if game["ats_result"] == "loss"
    )

    pushes = sum(
        1
        for game in decisions
        if game["ats_result"] == "push"
    )

    graded = (
        wins + losses
    )

    win_rate = (
        wins / graded
        if graded
        else None
    )

    return {
        "games":
            len(decisions),

        "wins":
            wins,

        "losses":
            losses,

        "pushes":
            pushes,

        "win_rate":
            (
                round(
                    win_rate * 100,
                    2
                )
                if win_rate
                is not None
                else None
            ),
    }


# =============================================================================
# ROLLING OUT-OF-SAMPLE BACKTEST
# =============================================================================

def run_backtest(
    games_by_year,
    lines_by_year
):

    scored_games = []
    yearly_reports = []

    print("")
    print(
        "🧪 Rolling out-of-sample backtest"
    )

    for test_year in range(
        FIRST_TEST_YEAR,
        END_YEAR + 1
    ):

        training_games = []

        for year in range(
            START_YEAR,
            test_year
        ):

            training_games.extend(
                games_by_year.get(
                    year,
                    []
                )
            )

        test_games = games_by_year.get(
            test_year,
            []
        )

        if (
            len(training_games)
            < MIN_TRAINING_GAMES
        ):

            print(
                f"⚠ Skipping {test_year}: "
                "insufficient training sample."
            )

            continue

        model = fit_model(
            training_games
        )

        print("")
        print(
            f"▶ Test season {test_year}"
        )

        print(
            f"   Training games: "
            f"{len(training_games)}"
        )

        print(
            f"   Elo coefficient: "
            f"{model['elo_coefficient']:.4f}"
        )

        print(
            f"   HFA: "
            f"{model['home_field']:.3f}"
        )

        year_predictions = []
        year_actuals = []
        year_scored = []

        line_lookup = (
            lines_by_year.get(
                test_year,
                {}
            )
        )

        for game in test_games:

            hfa = (
                0.0
                if game["neutral"]
                else model[
                    "home_field"
                ]
            )

            projected_home_margin = (
                model[
                    "elo_coefficient"
                ]
                *
                game["elo_diff"]
                +
                hfa
            )

            record = dict(
                game
            )

            record[
                "projected_home_margin"
            ] = projected_home_margin

            record[
                "absolute_error"
            ] = abs(
                projected_home_margin
                -
                game[
                    "actual_home_margin"
                ]
            )

            market_spread = (
                line_lookup.get(
                    int(
                        game["game_id"]
                    )
                )
                if game["game_id"]
                is not None
                else None
            )

            record[
                "market_home_spread"
            ] = market_spread

            if market_spread is not None:

                ats = evaluate_ats(
                    game[
                        "actual_home_margin"
                    ],
                    market_spread,
                    projected_home_margin
                )

                record.update(
                    ats
                )

            else:

                record[
                    "model_edge"
                ] = None

                record[
                    "absolute_edge"
                ] = None

                record[
                    "model_side"
                ] = None

                record[
                    "ats_result"
                ] = None

            scored_games.append(
                record
            )

            year_scored.append(
                record
            )

            year_predictions.append(
                projected_home_margin
            )

            year_actuals.append(
                game[
                    "actual_home_margin"
                ]
            )

        year_mae = mae(
            year_predictions,
            year_actuals
        )

        year_rmse = rmse(
            year_predictions,
            year_actuals
        )

        with_market = [
            game
            for game in year_scored
            if game[
                "market_home_spread"
            ]
            is not None
        ]

        yearly_reports.append({
            "year":
                test_year,

            "training_games":
                len(training_games),

            "test_games":
                len(year_scored),

            "games_with_market":
                len(with_market),

            "elo_coefficient":
                round(
                    model[
                        "elo_coefficient"
                    ],
                    5
                ),

            "home_field":
                round(
                    model[
                        "home_field"
                    ],
                    3
                ),

            "mae":
                round(
                    year_mae,
                    3
                ),

            "rmse":
                round(
                    year_rmse,
                    3
                ),
        })

        print(
            f"   Test games: "
            f"{len(year_scored)}"
        )

        print(
            f"   Games with market: "
            f"{len(with_market)}"
        )

        print(
            f"   MAE: "
            f"{year_mae:.3f}"
        )

        print(
            f"   RMSE: "
            f"{year_rmse:.3f}"
        )

    return (
        scored_games,
        yearly_reports
    )


# =============================================================================
# FINAL REPORT
# =============================================================================

def build_report(
    scored_games,
    yearly_reports
):

    predictions = [
        game[
            "projected_home_margin"
        ]
        for game in scored_games
    ]

    actuals = [
        game[
            "actual_home_margin"
        ]
        for game in scored_games
    ]

    market_games = [
        game
        for game in scored_games
        if (
            game.get(
                "absolute_edge"
            )
            is not None
        )
    ]

    edge_buckets = []

    for low, high in EDGE_BUCKETS:

        bucket = [
            game
            for game in market_games
            if (
                game[
                    "absolute_edge"
                ] >= low
                and
                game[
                    "absolute_edge"
                ] < high
            )
        ]

        summary = (
            summarize_edge_games(
                bucket
            )
        )

        summary[
            "range"
        ] = (
            f"{low:.1f}-{high:.1f}"
            if high < 999
            else f"{low:.1f}+"
        )

        summary[
            "average_edge"
        ] = (
            round(
                mean([
                    game[
                        "absolute_edge"
                    ]
                    for game in bucket
                ]),
                3
            )
            if bucket
            else None
        )

        edge_buckets.append(
            summary
        )

    watch_games = [
        game
        for game in market_games
        if (
            game[
                "absolute_edge"
            ]
            <
            PROPOSED_WATCH_MAX
        )
    ]

    edge_games = [
        game
        for game in market_games
        if (
            game[
                "absolute_edge"
            ]
            >=
            PROPOSED_EDGE_MIN
            and
            game[
                "absolute_edge"
            ]
            <
            PROPOSED_HIGH_CONVICTION_MIN
        )
    ]

    high_conviction_games = [
        game
        for game in market_games
        if (
            game[
                "absolute_edge"
            ]
            >=
            PROPOSED_HIGH_CONVICTION_MIN
        )
    ]

    return {
        "methodology": {
            "training":
                (
                    "Expanding-window training. "
                    "Each test season uses only "
                    "prior seasons."
                ),

            "pregame_signal":
                "CFBD homePregameElo / awayPregameElo",

            "market":
                "CFBD historical closing spreads",

            "first_test_year":
                FIRST_TEST_YEAR,

            "last_test_year":
                END_YEAR,
        },

        "overall_accuracy": {
            "games":
                len(scored_games),

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

        "market_sample": {
            "games":
                len(
                    market_games
                )
        },

        "proposed_labels": {
            "watch":
                summarize_edge_games(
                    watch_games
                ),

            "edge":
                summarize_edge_games(
                    edge_games
                ),

            "high_conviction":
                summarize_edge_games(
                    high_conviction_games
                ),
        },

        "edge_buckets":
            edge_buckets,

        "year_by_year":
            yearly_reports,
    }


# =============================================================================
# PRINT REPORT
# =============================================================================

def print_report(report):

    print("")
    print(
        "=" * 78
    )

    print(
        "TIME-SAFE SPREAD BACKTEST"
    )

    print(
        "=" * 78
    )

    print("")

    accuracy = report[
        "overall_accuracy"
    ]

    print(
        "OUT-OF-SAMPLE MARGIN ACCURACY"
    )

    print(
        f"   Games: "
        f"{accuracy['games']}"
    )

    print(
        f"   MAE: "
        f"{accuracy['mae']:.2f} pts"
    )

    print(
        f"   RMSE: "
        f"{accuracy['rmse']:.2f} pts"
    )

    print("")

    print(
        "MARKET SAMPLE"
    )

    print(
        f"   Games with closing spread: "
        f"{report['market_sample']['games']}"
    )

    print("")

    print(
        "ATS BY MODEL / MARKET DISAGREEMENT"
    )

    for bucket in report[
        "edge_buckets"
    ]:

        rate = (
            f"{bucket['win_rate']:.2f}%"
            if bucket[
                "win_rate"
            ]
            is not None
            else "N/A"
        )

        print(
            f"   {bucket['range']:>10} | "
            f"{bucket['games']:>4} games | "
            f"{bucket['wins']:>4}-"
            f"{bucket['losses']:<4} | "
            f"{rate}"
        )

    print("")

    print(
        "PROPOSED SITE LABELS"
    )

    labels = report[
        "proposed_labels"
    ]

    for name in (
        "watch",
        "edge",
        "high_conviction"
    ):

        result = labels[
            name
        ]

        rate = (
            f"{result['win_rate']:.2f}%"
            if result[
                "win_rate"
            ]
            is not None
            else "N/A"
        )

        print(
            f"   {name.upper():<16} "
            f"{result['games']:>4} games | "
            f"{result['wins']:>4}-"
            f"{result['losses']:<4} | "
            f"{rate}"
        )

    print("")

    print(
        "=" * 78
    )

    print(
        "INTERPRETATION"
    )

    print(
        "=" * 78
    )

    high = labels[
        "high_conviction"
    ]

    edge = labels[
        "edge"
    ]

    if (
        high[
            "win_rate"
        ]
        is not None
        and
        high[
            "games"
        ] >= 50
    ):

        if (
            high[
                "win_rate"
            ]
            >= 54.0
        ):

            print(
                "✅ 7+ point disagreements "
                "show meaningful historical signal."
            )

        elif (
            high[
                "win_rate"
            ]
            >= 52.4
        ):

            print(
                "⚠ 7+ point disagreements "
                "show a modest historical signal."
            )

        else:

            print(
                "❌ 7+ point disagreements "
                "do NOT show enough historical "
                "ATS strength to justify a "
                "highest-conviction label."
            )

    else:

        print(
            "⚠ Not enough 7+ point games "
            "for a strong conclusion."
        )

    if (
        edge[
            "win_rate"
        ]
        is not None
        and
        edge[
            "games"
        ] >= 100
    ):

        if (
            edge[
                "win_rate"
            ]
            >= 52.4
        ):

            print(
                "✅ 3-7 point disagreements "
                "clear the basic break-even "
                "benchmark before vig adjustments."
            )

        else:

            print(
                "⚠ 3-7 point disagreements "
                "do not show sufficient "
                "historical ATS strength."
            )

    print("")

    print(
        "NOTE:"
    )

    print(
        "This validates a time-safe rating/"
        "market framework, not the exact "
        "2026 custom model coefficients."
    )

    print(
        "=" * 78
    )


# =============================================================================
# SAVE
# =============================================================================

def save_report(
    report,
    scored_games
):

    output = {
        "report":
            report,

        "games":
            scored_games,
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
        /
        1024
    )

    print("")

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
        "📊 CFB time-safe spread backtest"
    )

    print(
        f"   Data: "
        f"{START_YEAR}-{END_YEAR}"
    )

    print(
        f"   Out-of-sample testing: "
        f"{FIRST_TEST_YEAR}-{END_YEAR}"
    )

    games_by_year = {}
    lines_by_year = {}

    print("")
    print(
        "📚 Loading historical data"
    )

    for year in range(
        START_YEAR,
        END_YEAR + 1
    ):

        print("")
        print(
            f"▶ {year}"
        )

        games_by_year[
            year
        ] = get_games(
            year
        )

        lines_by_year[
            year
        ] = get_lines(
            year
        )

    (
        scored_games,
        yearly_reports
    ) = run_backtest(
        games_by_year,
        lines_by_year
    )

    report = build_report(
        scored_games,
        yearly_reports
    )

    print_report(
        report
    )

    save_report(
        report,
        scored_games
    )


if __name__ == "__main__":
    main()
