"""
CFB ANALYTICS
backtest_composite.py

Historical, time-safe backtest of the core efficiency composite
used by the live 2026 model.

IMPORTANT:
- Each historical game is predicted using ONLY data from games
  completed before that game.
- This script does NOT modify the live projection engine.
- This first composite backtest tests the in-season efficiency core:
    Net EPA/PPA
    Net Pass EPA/PPA
    Net Rush EPA/PPA
    Net Success Rate
    Defensive Havoc Created
    Offensive Havoc Allowed

The goal is to learn:
- how predictive the composite is out of sample
- how many scoreboard points one composite rating unit is worth
- historical home-field advantage
- whether model/market disagreement shows ATS signal
"""

import json
import math
import os
import statistics
import sys
import time
from collections import defaultdict

import requests


# =============================================================================
# CONFIG
# =============================================================================

CFBD_BASE = "https://api.collegefootballdata.com"

START_YEAR = 2019
END_YEAR = 2025

FIRST_TEST_YEAR = 2022

OUTPUT_PATH = "data/composite_backtest_report.json"

# Require some actual prior-season/week sample before using
# a team's live efficiency composite.
MIN_PRIOR_GAMES = 2

WEIGHTS = {
    "net_epa": 0.30,
    "net_epa_pass": 0.15,
    "net_epa_rush": 0.15,
    "net_sr": 0.10,
    "def_havoc_created": 0.20,
    "off_havoc_allowed": 0.10,
}

EDGE_BUCKETS = [
    (0.0, 1.5),
    (1.5, 3.0),
    (3.0, 4.0),
    (4.0, 5.0),
    (5.0, 7.0),
    (7.0, 10.0),
    (10.0, 999.0),
]


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
# HELPERS
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


def population_std(values):

    clean = [
        value
        for value in values
        if value is not None
    ]

    if len(clean) < 2:
        return None

    return statistics.pstdev(clean)


def z_scores(values_by_team):

    values = [
        value
        for value in values_by_team.values()
        if value is not None
    ]

    if len(values) < 2:

        return {
            team: 0.0
            for team in values_by_team
        }

    avg = statistics.mean(values)
    std = statistics.pstdev(values)

    if std == 0:

        return {
            team: 0.0
            for team in values_by_team
        }

    output = {}

    for team, value in values_by_team.items():

        if value is None:
            output[team] = 0.0

        else:
            output[team] = (
                value - avg
            ) / std

    return output


def mae(predictions, actuals):

    if not predictions:
        return None

    return statistics.mean(
        abs(predicted - actual)
        for predicted, actual
        in zip(
            predictions,
            actuals
        )
    )


def rmse(predictions, actuals):

    if not predictions:
        return None

    return math.sqrt(
        statistics.mean(
            (predicted - actual) ** 2
            for predicted, actual
            in zip(
                predictions,
                actuals
            )
        )
    )


def regression(x_values, y_values):

    if (
        len(x_values) != len(y_values)
        or len(x_values) < 2
    ):

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
        for x
        in x_values
    )

    slope = (
        numerator / denominator
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
        for x
        in x_values
    ]

    total_variance = sum(
        (y - y_mean) ** 2
        for y
        in y_values
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
# CFBD
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

    for attempt in range(
        1,
        4
    ):

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
                f"⚠ Request failure "
                f"{endpoint} "
                f"({attempt}/3): "
                f"{error}"
            )

            if attempt < 3:

                time.sleep(2)
                continue

            if required:
                sys.exit(1)

            return None

        if response.status_code in (
            401,
            403
        ):

            print(
                "❌ CFBD authentication/access failed."
            )

            sys.exit(1)

        if not response.ok:

            print(
                f"⚠ {endpoint}: "
                f"HTTP {response.status_code}"
            )

            if attempt < 3:

                time.sleep(2)
                continue

            if required:
                sys.exit(1)

            return None

        try:

            return response.json()

        except ValueError:

            print(
                f"❌ Invalid JSON from "
                f"{endpoint}"
            )

            if required:
                sys.exit(1)

            return None

    return None


# =============================================================================
# HISTORICAL GAMES
# =============================================================================

def get_games(year):

    print(
        f"📅 Loading {year} games..."
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
            home_points is None
            or away_points is None
        ):
            continue

        games.append({
            "id":
                game.get("id"),

            "year":
                year,

            "week":
                int(
                    game.get(
                        "week",
                        0
                    )
                ),

            "home":
                game.get(
                    "homeTeam"
                ),

            "away":
                game.get(
                    "awayTeam"
                ),

            "neutral":
                bool(
                    game.get(
                        "neutralSite",
                        False
                    )
                ),

            "home_points":
                home_points,

            "away_points":
                away_points,

            "actual_home_margin":
                home_points
                -
                away_points,
        })

    games.sort(
        key=lambda game:
            (
                game["week"],
                game["id"]
                if game["id"]
                is not None
                else 0
            )
    )

    print(
        f"   {len(games)} FBS-vs-FBS games"
    )

    return games


# =============================================================================
# ADVANCED BOX SCORE
# =============================================================================

def get_advanced_box(game_id):

    return cfbd_get(
        "/game/box/advanced",
        {
            "id": game_id,
        },
        required=False
    )


def find_team_record(
    records,
    team
):

    if not records:
        return None

    for record in records:

        if (
            record.get(
                "team"
            )
            ==
            team
        ):

            return record

    return None


def nested_total(
    record,
    section
):

    if not record:
        return None

    value = record.get(
        section
    )

    if isinstance(
        value,
        dict
    ):

        return safe_number(
            value.get(
                "total"
            )
        )

    return safe_number(
        value
    )


def parse_advanced_game(
    game,
    box
):

    if not box:

        return None

    teams = (
        box.get(
            "teams"
        )
        or {}
    )

    ppa_records = (
        teams.get(
            "ppa"
        )
        or []
    )

    success_records = (
        teams.get(
            "successRates"
        )
        or []
    )

    havoc_records = (
        teams.get(
            "havoc"
        )
        or []
    )

    home = game["home"]
    away = game["away"]

    home_ppa = find_team_record(
        ppa_records,
        home
    )

    away_ppa = find_team_record(
        ppa_records,
        away
    )

    home_success = find_team_record(
        success_records,
        home
    )

    away_success = find_team_record(
        success_records,
        away
    )

    home_havoc = find_team_record(
        havoc_records,
        home
    )

    away_havoc = find_team_record(
        havoc_records,
        away
    )

    if (
        home_ppa is None
        or away_ppa is None
        or home_success is None
        or away_success is None
    ):

        return None

    home_off_epa = nested_total(
        home_ppa,
        "overall"
    )

    away_off_epa = nested_total(
        away_ppa,
        "overall"
    )

    home_pass_epa = nested_total(
        home_ppa,
        "passing"
    )

    away_pass_epa = nested_total(
        away_ppa,
        "passing"
    )

    home_rush_epa = nested_total(
        home_ppa,
        "rushing"
    )

    away_rush_epa = nested_total(
        away_ppa,
        "rushing"
    )

    home_sr = nested_total(
        home_success,
        "overall"
    )

    away_sr = nested_total(
        away_success,
        "overall"
    )

    home_havoc_rate = (
        safe_number(
            home_havoc.get(
                "total"
            )
        )
        if home_havoc
        else None
    )

    away_havoc_rate = (
        safe_number(
            away_havoc.get(
                "total"
            )
        )
        if away_havoc
        else None
    )

    required = [
        home_off_epa,
        away_off_epa,
        home_sr,
        away_sr,
    ]

    if any(
        value is None
        for value in required
    ):

        return None

    return {
        home: {
            "off_epa":
                home_off_epa,

            "def_epa_allowed":
                away_off_epa,

            "off_pass_epa":
                home_pass_epa,

            "def_pass_epa_allowed":
                away_pass_epa,

            "off_rush_epa":
                home_rush_epa,

            "def_rush_epa_allowed":
                away_rush_epa,

            "off_success":
                home_sr,

            "def_success_allowed":
                away_sr,

            "def_havoc_created":
                home_havoc_rate,

            "off_havoc_allowed":
                away_havoc_rate,
        },

        away: {
            "off_epa":
                away_off_epa,

            "def_epa_allowed":
                home_off_epa,

            "off_pass_epa":
                away_pass_epa,

            "def_pass_epa_allowed":
                home_pass_epa,

            "off_rush_epa":
                away_rush_epa,

            "def_rush_epa_allowed":
                home_rush_epa,

            "off_success":
                away_sr,

            "def_success_allowed":
                home_sr,

            "def_havoc_created":
                away_havoc_rate,

            "off_havoc_allowed":
                home_havoc_rate,
        },
    }


# =============================================================================
# TEAM RUNNING DATA
# =============================================================================

def empty_team_history():

    return {
        "games":
            0,

        "off_epa":
            [],

        "def_epa_allowed":
            [],

        "off_pass_epa":
            [],

        "def_pass_epa_allowed":
            [],

        "off_rush_epa":
            [],

        "def_rush_epa_allowed":
            [],

        "off_success":
            [],

        "def_success_allowed":
            [],

        "def_havoc_created":
            [],

        "off_havoc_allowed":
            [],
    }


def update_history(
    history,
    team_metrics
):

    history["games"] += 1

    for key in (
        "off_epa",
        "def_epa_allowed",
        "off_pass_epa",
        "def_pass_epa_allowed",
        "off_rush_epa",
        "def_rush_epa_allowed",
        "off_success",
        "def_success_allowed",
        "def_havoc_created",
        "off_havoc_allowed",
    ):

        value = team_metrics.get(
            key
        )

        if value is not None:

            history[key].append(
                value
            )


def team_snapshot(history):

    if (
        not history
        or history["games"]
        < MIN_PRIOR_GAMES
    ):

        return None

    off_epa = mean(
        history[
            "off_epa"
        ]
    )

    def_epa = mean(
        history[
            "def_epa_allowed"
        ]
    )

    off_pass = mean(
        history[
            "off_pass_epa"
        ]
    )

    def_pass = mean(
        history[
            "def_pass_epa_allowed"
        ]
    )

    off_rush = mean(
        history[
            "off_rush_epa"
        ]
    )

    def_rush = mean(
        history[
            "def_rush_epa_allowed"
        ]
    )

    off_sr = mean(
        history[
            "off_success"
        ]
    )

    def_sr = mean(
        history[
            "def_success_allowed"
        ]
    )

    def_havoc = mean(
        history[
            "def_havoc_created"
        ]
    )

    off_havoc = mean(
        history[
            "off_havoc_allowed"
        ]
    )

    if (
        off_epa is None
        or def_epa is None
        or off_sr is None
        or def_sr is None
    ):

        return None

    return {
        "net_epa":
            off_epa
            -
            def_epa,

        "net_epa_pass":
            (
                off_pass
                -
                def_pass
                if (
                    off_pass is not None
                    and def_pass is not None
                )
                else None
            ),

        "net_epa_rush":
            (
                off_rush
                -
                def_rush
                if (
                    off_rush is not None
                    and def_rush is not None
                )
                else None
            ),

        "net_sr":
            off_sr
            -
            def_sr,

        "def_havoc_created":
            def_havoc,

        "off_havoc_allowed":
            off_havoc,
    }


# =============================================================================
# BUILD WEEKLY COMPOSITE RATINGS
# =============================================================================

def build_composite_ratings(
    histories
):

    snapshots = {}

    for team, history in histories.items():

        snapshot = team_snapshot(
            history
        )

        if snapshot is not None:

            snapshots[
                team
            ] = snapshot

    if len(snapshots) < 20:

        return {}

    component_z = {}

    for component in WEIGHTS:

        values = {
            team:
                snapshot.get(
                    component
                )
            for team, snapshot
            in snapshots.items()
        }

        component_z[
            component
        ] = z_scores(
            values
        )

    ratings = {}

    for team in snapshots:

        rating = 0.0

        for (
            component,
            weight
        ) in WEIGHTS.items():

            value = component_z[
                component
            ].get(
                team,
                0.0
            )

            # Havoc ALLOWED is bad.
            if (
                component
                ==
                "off_havoc_allowed"
            ):

                value *= -1.0

            rating += (
                value
                *
                weight
            )

        ratings[
            team
        ] = rating

    return ratings


# =============================================================================
# HISTORICAL LINES
# =============================================================================

def choose_spread(provider):

    if not isinstance(
        provider,
        dict
    ):

        return None

    return safe_number(
        provider.get(
            "spread"
        )
    )


def extract_spread(line_game):

    providers = (
        line_game.get(
            "lines"
        )
        or []
    )

    preferred = [
        "DraftKings",
        "FanDuel",
        "BetMGM",
        "Caesars",
        "Consensus",
    ]

    for name in preferred:

        for provider in providers:

            if (
                str(
                    provider.get(
                        "provider",
                        ""
                    )
                ).lower()
                ==
                name.lower()
            ):

                spread = choose_spread(
                    provider
                )

                if spread is not None:
                    return spread

    spreads = [
        choose_spread(
            provider
        )
        for provider
        in providers
    ]

    spreads = [
        spread
        for spread in spreads
        if spread is not None
    ]

    if not spreads:
        return None

    return statistics.median(
        spreads
    )


def get_lines(year):

    raw = cfbd_get(
        "/lines",
        {
            "year":
                year,

            "seasonType":
                "regular",
        },
        required=False
    )

    lookup = {}

    if not raw:
        return lookup

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

        spread = extract_spread(
            item
        )

        if spread is None:
            continue

        lookup[
            int(
                game_id
            )
        ] = spread

    return lookup


# =============================================================================
# TRAINING MODEL
# =============================================================================

def fit_scoring_model(
    training_records
):

    x_values = [
        record[
            "rating_diff"
        ]
        for record
        in training_records
    ]

    y_values = [
        record[
            "actual_home_margin"
        ]
        for record
        in training_records
    ]

    fit = regression(
        x_values,
        y_values
    )

    non_neutral = [
        record
        for record
        in training_records
        if not record[
            "neutral"
        ]
    ]

    residuals = [
        record[
            "actual_home_margin"
        ]
        -
        (
            fit[
                "slope"
            ]
            *
            record[
                "rating_diff"
            ]
        )
        for record
        in non_neutral
    ]

    hfa = mean(
        residuals
    )

    if hfa is None:
        hfa = 2.0

    return {
        "rating_to_points":
            fit["slope"],

        "raw_intercept":
            fit["intercept"],

        "r_squared":
            fit["r_squared"],

        "home_field":
            hfa,
    }


# =============================================================================
# ATS
# =============================================================================

def evaluate_ats(
    actual_home_margin,
    market_home_spread,
    projected_home_margin
):

    market_expected_home_margin = (
        -market_home_spread
    )

    model_edge = (
        projected_home_margin
        -
        market_expected_home_margin
    )

    if model_edge == 0:

        return {
            "model_edge":
                0.0,

            "absolute_edge":
                0.0,

            "ats_result":
                "no_edge",
        }

    home_cover_margin = (
        actual_home_margin
        +
        market_home_spread
    )

    if model_edge > 0:

        cover_margin = (
            home_cover_margin
        )

    else:

        cover_margin = (
            -home_cover_margin
        )

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

        "ats_result":
            result,
    }


# =============================================================================
# BUILD TIME-SAFE DATASET
# =============================================================================

def build_year_records(
    year,
    games,
    line_lookup
):

    histories = defaultdict(
        empty_team_history
    )

    records = []

    weeks = sorted(
        set(
            game["week"]
            for game in games
        )
    )

    print("")
    print(
        f"🧠 Building {year} weekly snapshots"
    )

    for week in weeks:

        week_games = [
            game
            for game in games
            if game[
                "week"
            ] == week
        ]

        # IMPORTANT:
        # Ratings are created BEFORE processing
        # any games from this week.
        ratings = build_composite_ratings(
            histories
        )

        usable_this_week = 0

        for game in week_games:

            home_rating = ratings.get(
                game["home"]
            )

            away_rating = ratings.get(
                game["away"]
            )

            if (
                home_rating is not None
                and away_rating is not None
            ):

                record = {
                    "game_id":
                        game["id"],

                    "year":
                        year,

                    "week":
                        week,

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
                        home_rating
                        -
                        away_rating,

                    "actual_home_margin":
                        game[
                            "actual_home_margin"
                        ],

                    "market_home_spread":
                        (
                            line_lookup.get(
                                int(
                                    game["id"]
                                )
                            )
                            if game["id"]
                            is not None
                            else None
                        ),
                }

                records.append(
                    record
                )

                usable_this_week += 1

        print(
            f"   Week {week:>2}: "
            f"{usable_this_week:>3} "
            "pregame composite matchups"
        )

        # Only AFTER predictions are recorded
        # do we add this week's game data.
        for game in week_games:

            if game["id"] is None:
                continue

            box = get_advanced_box(
                game["id"]
            )

            parsed = parse_advanced_game(
                game,
                box
            )

            if not parsed:
                continue

            for team, metrics in parsed.items():

                update_history(
                    histories[
                        team
                    ],
                    metrics
                )

    print(
        f"   Total usable {year}: "
        f"{len(records)}"
    )

    return records


# =============================================================================
# ROLLING OUT-OF-SAMPLE TEST
# =============================================================================

def run_out_of_sample(
    records_by_year
):

    scored = []
    yearly = []

    for test_year in range(
        FIRST_TEST_YEAR,
        END_YEAR + 1
    ):

        training = []

        for year in range(
            START_YEAR,
            test_year
        ):

            training.extend(
                records_by_year.get(
                    year,
                    []
                )
            )

        testing = records_by_year.get(
            test_year,
            []
        )

        if (
            len(training) < 200
            or len(testing) < 50
        ):

            print(
                f"⚠ Skipping {test_year}: "
                "insufficient sample"
            )

            continue

        model = fit_scoring_model(
            training
        )

        predictions = []
        actuals = []

        year_scored = []

        for record in testing:

            hfa = (
                0.0
                if record[
                    "neutral"
                ]
                else model[
                    "home_field"
                ]
            )

            projected = (
                model[
                    "rating_to_points"
                ]
                *
                record[
                    "rating_diff"
                ]
                +
                hfa
            )

            scored_record = dict(
                record
            )

            scored_record[
                "projected_home_margin"
            ] = projected

            scored_record[
                "absolute_error"
            ] = abs(
                projected
                -
                record[
                    "actual_home_margin"
                ]
            )

            market_spread = record.get(
                "market_home_spread"
            )

            if market_spread is not None:

                scored_record.update(
                    evaluate_ats(
                        record[
                            "actual_home_margin"
                        ],
                        market_spread,
                        projected
                    )
                )

            else:

                scored_record[
                    "model_edge"
                ] = None

                scored_record[
                    "absolute_edge"
                ] = None

                scored_record[
                    "ats_result"
                ] = None

            predictions.append(
                projected
            )

            actuals.append(
                record[
                    "actual_home_margin"
                ]
            )

            year_scored.append(
                scored_record
            )

            scored.append(
                scored_record
            )

        year_market = [
            game
            for game in year_scored
            if game.get(
                "absolute_edge"
            )
            is not None
        ]

        yearly.append({
            "year":
                test_year,

            "training_games":
                len(training),

            "test_games":
                len(testing),

            "market_games":
                len(year_market),

            "rating_to_points":
                round(
                    model[
                        "rating_to_points"
                    ],
                    4
                ),

            "home_field":
                round(
                    model[
                        "home_field"
                    ],
                    3
                ),

            "r_squared":
                round(
                    model[
                        "r_squared"
                    ],
                    4
                ),

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
        })

        print("")
        print(
            f"▶ TEST {test_year}"
        )

        print(
            f"   Training games: "
            f"{len(training)}"
        )

        print(
            f"   Test games: "
            f"{len(testing)}"
        )

        print(
            f"   Rating → points: "
            f"{model['rating_to_points']:.3f}"
        )

        print(
            f"   HFA: "
            f"{model['home_field']:.3f}"
        )

        print(
            f"   MAE: "
            f"{mae(predictions, actuals):.3f}"
        )

        print(
            f"   RMSE: "
            f"{rmse(predictions, actuals):.3f}"
        )

        print(
            f"   Market games: "
            f"{len(year_market)}"
        )

    return (
        scored,
        yearly
    )


# =============================================================================
# REPORT
# =============================================================================

def summarize_ats(
    games
):

    graded = [
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
        for game
        in graded
        if game[
            "ats_result"
        ] == "win"
    )

    losses = sum(
        1
        for game
        in graded
        if game[
            "ats_result"
        ] == "loss"
    )

    pushes = sum(
        1
        for game
        in graded
        if game[
            "ats_result"
        ] == "push"
    )

    decisions = (
        wins + losses
    )

    return {
        "games":
            len(graded),

        "wins":
            wins,

        "losses":
            losses,

        "pushes":
            pushes,

        "win_rate":
            (
                round(
                    wins
                    /
                    decisions
                    *
                    100,
                    2
                )
                if decisions
                else None
            ),
    }


def build_report(
    scored,
    yearly
):

    predictions = [
        game[
            "projected_home_margin"
        ]
        for game
        in scored
    ]

    actuals = [
        game[
            "actual_home_margin"
        ]
        for game
        in scored
    ]

    market_games = [
        game
        for game in scored
        if game.get(
            "absolute_edge"
        )
        is not None
    ]

    buckets = []

    for low, high in EDGE_BUCKETS:

        bucket_games = [
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

        summary = summarize_ats(
            bucket_games
        )

        summary[
            "range"
        ] = (
            f"{low:.1f}-{high:.1f}"
            if high < 999
            else f"{low:.1f}+"
        )

        buckets.append(
            summary
        )

    return {
        "methodology": {
            "years":
                f"{START_YEAR}-{END_YEAR}",

            "first_test_year":
                FIRST_TEST_YEAR,

            "minimum_prior_games":
                MIN_PRIOR_GAMES,

            "weights":
                WEIGHTS,

            "time_safe":
                True,

            "description":
                (
                    "Weekly historical composite "
                    "snapshots generated before "
                    "the games being predicted."
                ),
        },

        "overall": {
            "games":
                len(scored),

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

            "market_games":
                len(
                    market_games
                ),
        },

        "ats_edge_buckets":
            buckets,

        "year_by_year":
            yearly,
    }


def print_report(
    report
):

    print("")
    print(
        "=" * 76
    )

    print(
        "COMPOSITE MODEL OUT-OF-SAMPLE BACKTEST"
    )

    print(
        "=" * 76
    )

    overall = report[
        "overall"
    ]

    print("")
    print(
        "MARGIN ACCURACY"
    )

    print(
        f"   Games: "
        f"{overall['games']}"
    )

    print(
        f"   MAE: "
        f"{overall['mae']:.2f} pts"
    )

    print(
        f"   RMSE: "
        f"{overall['rmse']:.2f} pts"
    )

    print("")
    print(
        "MARKET SAMPLE"
    )

    print(
        f"   Games: "
        f"{overall['market_games']}"
    )

    print("")
    print(
        "ATS BY MODEL / MARKET DISAGREEMENT"
    )

    for bucket in report[
        "ats_edge_buckets"
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
        "YEAR-BY-YEAR CALIBRATION"
    )

    for year in report[
        "year_by_year"
    ]:

        print(
            f"   {year['year']} | "
            f"scale {year['rating_to_points']:.3f} | "
            f"HFA {year['home_field']:.2f} | "
            f"MAE {year['mae']:.2f}"
        )

    print("")
    print(
        "=" * 76
    )

    print(
        "This script does NOT change "
        "the live 2026 model."
    )

    print(
        "=" * 76
    )


def save_report(
    report,
    scored
):

    output = {
        "report":
            report,

        "games":
            scored,
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
        f"💾 Saved "
        f"{OUTPUT_PATH} "
        f"({size_kb:.1f} KB)"
    )


# =============================================================================
# MAIN
# =============================================================================

def main():

    print("")
    print(
        "📊 Composite-model historical backtest"
    )

    print(
        f"   Historical seasons: "
        f"{START_YEAR}-{END_YEAR}"
    )

    print(
        f"   Out-of-sample seasons: "
        f"{FIRST_TEST_YEAR}-{END_YEAR}"
    )

    records_by_year = {}

    for year in range(
        START_YEAR,
        END_YEAR + 1
    ):

        print("")
        print(
            "#" * 76
        )

        print(
            f"# {year}"
        )

        print(
            "#" * 76
        )

        games = get_games(
            year
        )

        lines = get_lines(
            year
        )

        records_by_year[
            year
        ] = build_year_records(
            year,
            games,
            lines
        )

    (
        scored,
        yearly
    ) = run_out_of_sample(
        records_by_year
    )

    report = build_report(
        scored,
        yearly
    )

    print_report(
        report
    )

    save_report(
        report,
        scored
    )


if __name__ == "__main__":
    main()
