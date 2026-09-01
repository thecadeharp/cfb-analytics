"""
CFB ANALYTICS
calibrate_hfa.py

Leakage-safe validation of team-specific home-field advantage.

Uses:
    data/composite_backtest_report.json

NO API CALLS.

PRODUCTION PHILOSOPHY
---------------------
Neutral-site games:
    HFA = 0.0
    (handled by build_projections.py)

True home games:
    HFA may vary by team.

Production constraints:
    - No team receives negative home-field advantage.
    - No team receives more than 4.0 points of HFA.
    - Team estimates are shrunk toward the national baseline.
    - Parameter choices are evaluated out of sample.

For historical validation:

    Test 2023 -> learn HFA from 2022 only
    Test 2024 -> learn HFA from 2022-2023
    Test 2025 -> learn HFA from 2022-2024

The test season never contributes to its own HFA estimate.
"""

import json
import math
import os
import statistics
import sys
from collections import defaultdict


# =============================================================================
# CONFIG
# =============================================================================

INPUT_PATH = "data/composite_backtest_report.json"
OUTPUT_PATH = "data/hfa_ratings.json"

FIRST_HFA_TEST_YEAR = 2023

MIN_TEAM_HOME_GAMES = 3

# Larger value = stronger pull toward national average.
SHRINKAGE_CANDIDATES = [
    10,
    15,
    20,
    25,
    30,
    40,
    50,
    60,
    80,
    100,
]

# We will test whether allowing elite home fields to reach
# higher levels actually improves prediction accuracy.
MAX_HFA_CANDIDATES = [
    3.0,
    3.25,
    3.5,
    3.75,
    4.0,
]

# A real home team is never penalized simply for being at home.
MIN_HFA = 0.0

# Hard philosophical production ceiling.
ABSOLUTE_MAX_HFA = 4.0

TOP_CONFIGS_TO_PRINT = 12

# "Near ceiling" is useful for detecting whether too many teams
# are getting jammed against the upper constraint.
CEILING_NEAR_DISTANCE = 0.10


# =============================================================================
# GENERAL HELPERS
# =============================================================================

def safe_number(value, default=None):

    try:
        if value is None:
            return default

        return float(value)

    except (TypeError, ValueError):
        return default


def clamp(value, low, high):

    return max(
        low,
        min(
            high,
            value
        )
    )


def calculate_mae(predictions, actuals):

    if not predictions:
        return None

    return statistics.mean(
        abs(prediction - actual)
        for prediction, actual
        in zip(predictions, actuals)
    )


def calculate_rmse(predictions, actuals):

    if not predictions:
        return None

    return math.sqrt(
        statistics.mean(
            (prediction - actual) ** 2
            for prediction, actual
            in zip(predictions, actuals)
        )
    )


# =============================================================================
# LOAD COMPOSITE BACKTEST
# =============================================================================

def load_backtest():

    if not os.path.exists(INPUT_PATH):

        print("")
        print(f"❌ Missing {INPUT_PATH}")
        print("Run scripts/backtest_composite.py first.")

        sys.exit(1)

    with open(
        INPUT_PATH,
        "r",
        encoding="utf-8"
    ) as file:

        data = json.load(file)

    games = data.get(
        "games",
        []
    )

    report = data.get(
        "report",
        {}
    )

    if not games:

        print(
            "❌ Composite backtest contains no games."
        )

        sys.exit(1)

    year_scales = {}

    for item in report.get(
        "year_by_year",
        []
    ):

        year = item.get(
            "year"
        )

        scale = safe_number(
            item.get(
                "rating_to_points"
            )
        )

        if (
            year is not None
            and scale is not None
        ):

            year_scales[
                int(year)
            ] = scale

    if not year_scales:

        print(
            "❌ No year-specific rating scales found."
        )

        sys.exit(1)

    return games, year_scales


# =============================================================================
# BUILD STRENGTH-CONTROLLED HOME RESIDUALS
# =============================================================================

def build_home_residuals(
    games,
    year_scales
):

    residuals = []

    neutral_skipped = 0
    missing_skipped = 0

    for game in games:

        # Neutral-site games are deliberately excluded
        # from learning team home-field advantage.

        if game.get(
            "neutral"
        ):

            neutral_skipped += 1
            continue

        year = game.get(
            "year"
        )

        home = game.get(
            "home"
        )

        away = game.get(
            "away"
        )

        rating_diff = safe_number(
            game.get(
                "rating_diff"
            )
        )

        actual_home_margin = safe_number(
            game.get(
                "actual_home_margin"
            )
        )

        if (
            year is None
            or not home
            or not away
            or rating_diff is None
            or actual_home_margin is None
        ):

            missing_skipped += 1
            continue

        try:
            year = int(year)

        except (TypeError, ValueError):

            missing_skipped += 1
            continue

        rating_to_points = year_scales.get(
            year
        )

        if rating_to_points is None:

            missing_skipped += 1
            continue

        # Expected margin from team strength only.
        # HFA is intentionally omitted here.

        strength_margin = (
            rating_diff
            *
            rating_to_points
        )

        home_residual = (
            actual_home_margin
            -
            strength_margin
        )

        residuals.append({

            "year":
                year,

            "week":
                game.get(
                    "week"
                ),

            "game_id":
                game.get(
                    "game_id"
                ),

            "home":
                home,

            "away":
                away,

            "rating_diff":
                rating_diff,

            "rating_to_points":
                rating_to_points,

            "strength_margin":
                strength_margin,

            "actual_home_margin":
                actual_home_margin,

            "home_residual":
                home_residual,
        })

    print("")
    print(
        "🏟️  Building strength-controlled home residuals"
    )

    print(
        f"   Non-neutral games: {len(residuals)}"
    )

    print(
        f"   Neutral games skipped: {neutral_skipped}"
    )

    if missing_skipped:

        print(
            f"   Missing-data games skipped: "
            f"{missing_skipped}"
        )

    return residuals


# =============================================================================
# BUILD TRAINING SAMPLE
# =============================================================================

def build_training_hfa(
    training_residuals
):

    if not training_residuals:
        return None

    national_raw_hfa = statistics.mean(
        game[
            "home_residual"
        ]
        for game
        in training_residuals
    )

    team_values = defaultdict(
        list
    )

    for game in training_residuals:

        team_values[
            game[
                "home"
            ]
        ].append(
            game[
                "home_residual"
            ]
        )

    teams = {}

    for team, values in team_values.items():

        teams[
            team
        ] = {

            "games":
                len(values),

            "raw_hfa":
                statistics.mean(
                    values
                ),
        }

    return {

        "national_raw_hfa":
            national_raw_hfa,

        "teams":
            teams,
    }


# =============================================================================
# HFA MODELS
# =============================================================================

def flat_hfa(
    training,
    max_hfa
):

    return clamp(
        training[
            "national_raw_hfa"
        ],
        MIN_HFA,
        max_hfa
    )


def team_hfa(
    team,
    training,
    shrinkage_games,
    max_hfa
):

    national_raw = training[
        "national_raw_hfa"
    ]

    # The baseline itself must obey production bounds.

    national_bounded = clamp(
        national_raw,
        MIN_HFA,
        max_hfa
    )

    info = training[
        "teams"
    ].get(
        team
    )

    if (
        not info
        or info[
            "games"
        ] < MIN_TEAM_HOME_GAMES
    ):

        return national_bounded

    n = info[
        "games"
    ]

    raw_team_hfa = info[
        "raw_hfa"
    ]

    # Empirical-Bayes-style shrinkage:
    #
    # n / (n + K)
    #
    # Small samples remain close to national average.

    weight = (
        n
        /
        (
            n
            +
            shrinkage_games
        )
    )

    raw_modifier = (
        raw_team_hfa
        -
        national_raw
    )

    shrunk_hfa = (
        national_raw
        +
        weight
        *
        raw_modifier
    )

    # Critical production rule:
    #
    # Home field can help by 0 to max_hfa points.
    # It can never become a negative home penalty.

    return clamp(
        shrunk_hfa,
        MIN_HFA,
        max_hfa
    )


# =============================================================================
# SCORE FLAT MODEL
# =============================================================================

def score_flat_model(
    residuals,
    max_hfa
):

    years = sorted(
        set(
            game[
                "year"
            ]
            for game
            in residuals
            if game[
                "year"
            ] >= FIRST_HFA_TEST_YEAR
        )
    )

    predictions = []
    actuals = []

    yearly = []

    for test_year in years:

        training_games = [
            game
            for game
            in residuals
            if game[
                "year"
            ] < test_year
        ]

        test_games = [
            game
            for game
            in residuals
            if game[
                "year"
            ] == test_year
        ]

        if (
            not training_games
            or not test_games
        ):
            continue

        training = build_training_hfa(
            training_games
        )

        hfa = flat_hfa(
            training,
            max_hfa
        )

        year_predictions = []
        year_actuals = []

        for game in test_games:

            prediction = (
                game[
                    "strength_margin"
                ]
                +
                hfa
            )

            actual = game[
                "actual_home_margin"
            ]

            predictions.append(
                prediction
            )

            actuals.append(
                actual
            )

            year_predictions.append(
                prediction
            )

            year_actuals.append(
                actual
            )

        yearly.append({

            "year":
                test_year,

            "training_games":
                len(
                    training_games
                ),

            "test_games":
                len(
                    test_games
                ),

            "learned_raw_national_hfa":
                round(
                    training[
                        "national_raw_hfa"
                    ],
                    3
                ),

            "applied_flat_hfa":
                round(
                    hfa,
                    3
                ),

            "mae":
                round(
                    calculate_mae(
                        year_predictions,
                        year_actuals
                    ),
                    3
                ),

            "rmse":
                round(
                    calculate_rmse(
                        year_predictions,
                        year_actuals
                    ),
                    3
                ),
        })

    return {

        "model":
            "flat",

        "max_hfa":
            max_hfa,

        "games":
            len(
                predictions
            ),

        "mae":
            calculate_mae(
                predictions,
                actuals
            ),

        "rmse":
            calculate_rmse(
                predictions,
                actuals
            ),

        "year_by_year":
            yearly,
    }


# =============================================================================
# SCORE TEAM-SPECIFIC MODEL
# =============================================================================

def score_team_model(
    residuals,
    shrinkage_games,
    max_hfa
):

    years = sorted(
        set(
            game[
                "year"
            ]
            for game
            in residuals
            if game[
                "year"
            ] >= FIRST_HFA_TEST_YEAR
        )
    )

    predictions = []
    actuals = []

    yearly = []

    total_floor_hits = 0
    total_ceiling_hits = 0

    for test_year in years:

        training_games = [
            game
            for game
            in residuals
            if game[
                "year"
            ] < test_year
        ]

        test_games = [
            game
            for game
            in residuals
            if game[
                "year"
            ] == test_year
        ]

        if (
            not training_games
            or not test_games
        ):
            continue

        training = build_training_hfa(
            training_games
        )

        year_predictions = []
        year_actuals = []

        year_floor_hits = 0
        year_ceiling_hits = 0

        for game in test_games:

            hfa = team_hfa(
                game[
                    "home"
                ],
                training,
                shrinkage_games,
                max_hfa
            )

            if hfa <= (
                MIN_HFA
                +
                CEILING_NEAR_DISTANCE
            ):
                year_floor_hits += 1

            if hfa >= (
                max_hfa
                -
                CEILING_NEAR_DISTANCE
            ):
                year_ceiling_hits += 1

            prediction = (
                game[
                    "strength_margin"
                ]
                +
                hfa
            )

            actual = game[
                "actual_home_margin"
            ]

            predictions.append(
                prediction
            )

            actuals.append(
                actual
            )

            year_predictions.append(
                prediction
            )

            year_actuals.append(
                actual
            )

        total_floor_hits += (
            year_floor_hits
        )

        total_ceiling_hits += (
            year_ceiling_hits
        )

        yearly.append({

            "year":
                test_year,

            "training_games":
                len(
                    training_games
                ),

            "test_games":
                len(
                    test_games
                ),

            "learned_raw_national_hfa":
                round(
                    training[
                        "national_raw_hfa"
                    ],
                    3
                ),

            "mae":
                round(
                    calculate_mae(
                        year_predictions,
                        year_actuals
                    ),
                    3
                ),

            "rmse":
                round(
                    calculate_rmse(
                        year_predictions,
                        year_actuals
                    ),
                    3
                ),

            "near_floor_games":
                year_floor_hits,

            "near_ceiling_games":
                year_ceiling_hits,
        })

    return {

        "model":
            "team_specific",

        "shrinkage_games":
            shrinkage_games,

        "max_hfa":
            max_hfa,

        "games":
            len(
                predictions
            ),

        "mae":
            calculate_mae(
                predictions,
                actuals
            ),

        "rmse":
            calculate_rmse(
                predictions,
                actuals
            ),

        "near_floor_games":
            total_floor_hits,

        "near_ceiling_games":
            total_ceiling_hits,

        "year_by_year":
            yearly,
    }


# =============================================================================
# VALIDATION GRID
# =============================================================================

def run_validation(
    residuals
):

    print("")
    print(
        "=" * 88
    )

    print(
        "LEAKAGE-SAFE HOME-FIELD VALIDATION"
    )

    print(
        "=" * 88
    )

    # Flat benchmark.
    #
    # 4.0 is used as the ceiling because it is our absolute
    # production maximum.

    flat = score_flat_model(
        residuals,
        ABSOLUTE_MAX_HFA
    )

    grid_results = []

    for shrinkage in SHRINKAGE_CANDIDATES:

        for max_hfa in MAX_HFA_CANDIDATES:

            result = score_team_model(
                residuals,
                shrinkage,
                max_hfa
            )

            grid_results.append(
                result
            )

    grid_results.sort(
        key=lambda result: (
            result[
                "mae"
            ],
            result[
                "rmse"
            ],
            result[
                "near_ceiling_games"
            ]
        )
    )

    if not grid_results:

        print(
            "❌ No team-specific configurations scored."
        )

        sys.exit(1)

    best = grid_results[
        0
    ]

    print("")
    print(
        "FLAT HFA BENCHMARK"
    )

    print(
        f"   Games: {flat['games']}"
    )

    print(
        f"   MAE:   {flat['mae']:.3f}"
    )

    print(
        f"   RMSE:  {flat['rmse']:.3f}"
    )

    print("")
    print(
        f"TOP {TOP_CONFIGS_TO_PRINT} "
        f"TEAM-SPECIFIC CONFIGURATIONS"
    )

    print("")

    for rank, result in enumerate(
        grid_results[
            :TOP_CONFIGS_TO_PRINT
        ],
        start=1
    ):

        improvement = (
            flat[
                "mae"
            ]
            -
            result[
                "mae"
            ]
        )

        print(
            f"   {rank:>2}. "
            f"K={result['shrinkage_games']:<3} | "
            f"MAX={result['max_hfa']:.2f} | "
            f"MAE {result['mae']:.3f} | "
            f"RMSE {result['rmse']:.3f} | "
            f"vs flat {improvement:+.3f} | "
            f"ceiling games "
            f"{result['near_ceiling_games']}"
        )

    print("")
    print(
        "MATHEMATICAL WINNER"
    )

    print(
        f"   Shrinkage K: "
        f"{best['shrinkage_games']}"
    )

    print(
        f"   Maximum HFA: "
        f"{best['max_hfa']:.2f}"
    )

    print(
        f"   MAE: "
        f"{best['mae']:.3f}"
    )

    print(
        f"   RMSE: "
        f"{best['rmse']:.3f}"
    )

    print(
        f"   MAE improvement vs flat: "
        f"{flat['mae'] - best['mae']:+.3f}"
    )

    print("")
    print(
        "WINNER YEAR BY YEAR"
    )

    for item in best[
        "year_by_year"
    ]:

        print(
            f"   {item['year']} | "
            f"raw national "
            f"{item['learned_raw_national_hfa']:+.3f} | "
            f"{item['test_games']:>4} games | "
            f"MAE {item['mae']:.3f} | "
            f"RMSE {item['rmse']:.3f} | "
            f"floor {item['near_floor_games']} | "
            f"ceiling {item['near_ceiling_games']}"
        )

    print("")

    if (
        best[
            "mae"
        ]
        <
        flat[
            "mae"
        ]
    ):

        print(
            "✅ Constrained team-specific HFA "
            "beat flat HFA out of sample."
        )

    else:

        print(
            "❌ Constrained team-specific HFA "
            "did not beat flat HFA."
        )

    return {

        "flat":
            flat,

        "best":
            best,

        "top_configurations":
            grid_results[
                :TOP_CONFIGS_TO_PRINT
            ],

        "all_configurations":
            grid_results,
    }


# =============================================================================
# BUILD FINAL 2026 TEAM HFA TABLE
# =============================================================================

def build_final_ratings(
    residuals,
    configuration
):

    training = build_training_hfa(
        residuals
    )

    national_raw = training[
        "national_raw_hfa"
    ]

    shrinkage = configuration[
        "shrinkage_games"
    ]

    max_hfa = min(
        configuration[
            "max_hfa"
        ],
        ABSOLUTE_MAX_HFA
    )

    national_applied = clamp(
        national_raw,
        MIN_HFA,
        max_hfa
    )

    team_names = sorted(
        training[
            "teams"
        ].keys()
    )

    teams = []

    for team in team_names:

        info = training[
            "teams"
        ][
            team
        ]

        n = info[
            "games"
        ]

        raw_hfa = info[
            "raw_hfa"
        ]

        if n >= MIN_TEAM_HOME_GAMES:

            weight = (
                n
                /
                (
                    n
                    +
                    shrinkage
                )
            )

        else:

            weight = 0.0

        raw_modifier = (
            raw_hfa
            -
            national_raw
        )

        shrunk_unbounded = (
            national_raw
            +
            weight
            *
            raw_modifier
        )

        final_hfa = clamp(
            shrunk_unbounded,
            MIN_HFA,
            max_hfa
        )

        modifier_vs_baseline = (
            final_hfa
            -
            national_applied
        )

        if n >= 20:
            reliability = "HIGH"

        elif n >= 12:
            reliability = "MEDIUM"

        else:
            reliability = "LOW"

        teams.append({

            "team":
                team,

            "home_games":
                n,

            "raw_hfa":
                round(
                    raw_hfa,
                    3
                ),

            "raw_modifier":
                round(
                    raw_modifier,
                    3
                ),

            "shrinkage_weight":
                round(
                    weight,
                    3
                ),

            "shrunk_unbounded_hfa":
                round(
                    shrunk_unbounded,
                    3
                ),

            "final_hfa":
                round(
                    final_hfa,
                    3
                ),

            "modifier_vs_national":
                round(
                    modifier_vs_baseline,
                    3
                ),

            "at_floor":
                (
                    final_hfa
                    <=
                    MIN_HFA
                    +
                    CEILING_NEAR_DISTANCE
                ),

            "at_ceiling":
                (
                    final_hfa
                    >=
                    max_hfa
                    -
                    CEILING_NEAR_DISTANCE
                ),

            "reliability":
                reliability,
        })

    teams.sort(
        key=lambda item:
            item[
                "final_hfa"
            ],
        reverse=True
    )

    return {

        "national_raw_hfa":
            national_raw,

        "national_applied_hfa":
            national_applied,

        "shrinkage_games":
            shrinkage,

        "max_hfa":
            max_hfa,

        "teams":
            teams,
    }


# =============================================================================
# PRINT FINAL TABLE
# =============================================================================

def print_final_ratings(
    final_ratings
):

    teams = final_ratings[
        "teams"
    ]

    max_hfa = final_ratings[
        "max_hfa"
    ]

    ceiling_teams = [
        team
        for team in teams
        if team[
            "at_ceiling"
        ]
    ]

    floor_teams = [
        team
        for team in teams
        if team[
            "at_floor"
        ]
    ]

    four_point_teams = [
        team
        for team in teams
        if team[
            "final_hfa"
        ] >= 3.90
    ]

    print("")
    print(
        "=" * 88
    )

    print(
        "FINAL 2026 CONSTRAINED HOME-FIELD RATINGS"
    )

    print(
        "=" * 88
    )

    print("")
    print(
        "PRODUCTION PARAMETERS"
    )

    print(
        f"   Historical raw national HFA: "
        f"{final_ratings['national_raw_hfa']:+.3f}"
    )

    print(
        f"   Applied national baseline: "
        f"{final_ratings['national_applied_hfa']:+.3f}"
    )

    print(
        f"   Shrinkage K: "
        f"{final_ratings['shrinkage_games']}"
    )

    print(
        f"   Maximum home-field value: "
        f"{max_hfa:.2f}"
    )

    print(
        f"   Minimum home-field value: "
        f"{MIN_HFA:.2f}"
    )

    print("")
    print(
        "CEILING / FLOOR DIAGNOSTICS"
    )

    print(
        f"   Teams within 0.10 of model ceiling: "
        f"{len(ceiling_teams)}"
    )

    print(
        f"   Teams at 3.90+ HFA: "
        f"{len(four_point_teams)}"
    )

    print(
        f"   Teams within 0.10 of zero: "
        f"{len(floor_teams)}"
    )

    print("")
    print(
        "STRONGEST ADJUSTED HOME FIELDS"
    )

    for rank, item in enumerate(
        teams[:20],
        start=1
    ):

        print(
            f"   {rank:>2}. "
            f"{item['team']:<24} "
            f"{item['final_hfa']:+.2f} | "
            f"vs national "
            f"{item['modifier_vs_national']:+.2f} | "
            f"raw "
            f"{item['raw_hfa']:+.2f} | "
            f"{item['home_games']:>2} games | "
            f"{item['reliability']}"
        )

    print("")
    print(
        "WEAKEST ADJUSTED HOME FIELDS"
    )

    weakest = sorted(
        teams,
        key=lambda item:
            item[
                "final_hfa"
            ]
    )[:20]

    for rank, item in enumerate(
        weakest,
        start=1
    ):

        print(
            f"   {rank:>2}. "
            f"{item['team']:<24} "
            f"{item['final_hfa']:+.2f} | "
            f"vs national "
            f"{item['modifier_vs_national']:+.2f} | "
            f"raw "
            f"{item['raw_hfa']:+.2f} | "
            f"{item['home_games']:>2} games | "
            f"{item['reliability']}"
        )

    print("")
    print(
        "=" * 88
    )


# =============================================================================
# SAVE
# =============================================================================

def save_output(
    validation,
    final_ratings
):

    output = {

        "methodology": {

            "description":
                (
                    "Leakage-safe constrained team-specific "
                    "home-field validation."
                ),

            "neutral_site_hfa":
                0.0,

            "minimum_home_hfa":
                MIN_HFA,

            "absolute_maximum_home_hfa":
                ABSOLUTE_MAX_HFA,

            "first_test_year":
                FIRST_HFA_TEST_YEAR,

            "minimum_team_home_games":
                MIN_TEAM_HOME_GAMES,

            "shrinkage_candidates":
                SHRINKAGE_CANDIDATES,

            "max_hfa_candidates":
                MAX_HFA_CANDIDATES,
        },

        "validation": {

            "flat":
                validation[
                    "flat"
                ],

            "mathematical_winner":
                validation[
                    "best"
                ],

            "top_configurations":
                validation[
                    "top_configurations"
                ],
        },

        "final_2026": {

            "national_raw_hfa":
                round(
                    final_ratings[
                        "national_raw_hfa"
                    ],
                    3
                ),

            "national_applied_hfa":
                round(
                    final_ratings[
                        "national_applied_hfa"
                    ],
                    3
                ),

            "shrinkage_games":
                final_ratings[
                    "shrinkage_games"
                ],

            "max_hfa":
                final_ratings[
                    "max_hfa"
                ],

            "neutral_site_hfa":
                0.0,

            "minimum_home_hfa":
                MIN_HFA,

            "teams":
                final_ratings[
                    "teams"
                ],
        },
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
        "🏟️  CFB constrained team-specific HFA validation"
    )

    print(
        "   No API calls required."
    )

    print(
        "   Neutral-site HFA = 0.0"
    )

    print(
        "   Home HFA range = "
        f"{MIN_HFA:.1f} to "
        f"{ABSOLUTE_MAX_HFA:.1f}"
    )

    games, year_scales = load_backtest()

    residuals = build_home_residuals(
        games,
        year_scales
    )

    if len(
        residuals
    ) < 500:

        print(
            "❌ Not enough historical home games "
            "for HFA validation."
        )

        sys.exit(1)

    validation = run_validation(
        residuals
    )

    final_ratings = build_final_ratings(
        residuals,
        validation[
            "best"
        ]
    )

    print_final_ratings(
        final_ratings
    )

    save_output(
        validation,
        final_ratings
    )


if __name__ == "__main__":
    main()
