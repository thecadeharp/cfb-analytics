"""
CFB ANALYTICS
calibrate_hfa.py

Leakage-safe validation of team-specific home-field advantage.

This script uses the already-created:
    data/composite_backtest_report.json

NO API CALLS ARE MADE.

GOAL
----
Determine whether team-specific HFA actually improves predictions over
a single national home-field value.

For each historical test season:

    Test 2023 -> HFA learned only from 2022
    Test 2024 -> HFA learned only from 2022-2023
    Test 2025 -> HFA learned only from 2022-2024

The test season never contributes to its own HFA estimate.

We compare:

1. FLAT
   Every home team receives the learned national HFA.

2. RAW TEAM
   Each team receives its raw historical home residual.

3. SHRUNK TEAM
   Team-specific HFA is pulled toward the national average.

4. SHRUNK + CAPPED TEAM
   Same shrinkage, but the team-specific modifier is bounded.

We also test multiple shrinkage and cap combinations and select the
best-performing configuration on historical out-of-sample predictions.

The final 2026 HFA ratings are then estimated using all available
historical residuals and the winning configuration.
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

# We need at least this many historical home games before allowing
# a raw team estimate to stand on its own.
MIN_TEAM_HOME_GAMES = 3

# Candidate shrinkage strengths.
#
# weight = n / (n + K)
#
# Larger K = more conservative.
SHRINKAGE_CANDIDATES = [
    10,
    20,
    30,
    40,
    60,
    80,
]

# Maximum number of points a team may move above/below national HFA.
CAP_CANDIDATES = [
    0.5,
    1.0,
    1.5,
    2.0,
    2.5,
    3.0,
]

# Simple benchmark version for the uncapped shrunk model.
DEFAULT_SHRINKAGE = 30

# First season with a previous test-season sample available.
FIRST_HFA_TEST_YEAR = 2023


# =============================================================================
# GENERAL HELPERS
# =============================================================================

def safe_number(value, default=None):

    try:

        if value is None:
            return default

        return float(value)

    except (
        TypeError,
        ValueError
    ):

        return default


def mean(values):

    clean = [
        value
        for value in values
        if value is not None
    ]

    if not clean:
        return None

    return statistics.mean(
        clean
    )


def mae(predictions, actuals):

    if not predictions:
        return None

    return statistics.mean(
        abs(
            prediction - actual
        )
        for prediction, actual
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
            (
                prediction
                -
                actual
            ) ** 2
            for prediction, actual
            in zip(
                predictions,
                actuals
            )
        )
    )


def clamp(
    value,
    low,
    high
):

    return max(
        low,
        min(
            high,
            value
        )
    )


def round_or_none(
    value,
    digits=3
):

    if value is None:
        return None

    return round(
        value,
        digits
    )


# =============================================================================
# LOAD COMPOSITE BACKTEST
# =============================================================================

def load_backtest():

    if not os.path.exists(
        INPUT_PATH
    ):

        print("")
        print(
            f"❌ Missing {INPUT_PATH}"
        )

        print(
            "Run scripts/backtest_composite.py first."
        )

        sys.exit(1)

    with open(
        INPUT_PATH,
        "r",
        encoding="utf-8"
    ) as file:

        data = json.load(
            file
        )

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

    return (
        games,
        year_scales
    )


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

            year = int(
                year
            )

        except (
            TypeError,
            ValueError
        ):

            missing_skipped += 1
            continue

        rating_to_points = (
            year_scales.get(
                year
            )
        )

        if rating_to_points is None:

            missing_skipped += 1
            continue

        # Strength-only expected margin.
        #
        # We deliberately exclude HFA here because this script
        # is trying to estimate HFA from the remaining residual.

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
        f"   Non-neutral games: "
        f"{len(residuals)}"
    )

    print(
        f"   Neutral games skipped: "
        f"{neutral_skipped}"
    )

    if missing_skipped:

        print(
            f"   Missing-data games skipped: "
            f"{missing_skipped}"
        )

    return residuals


# =============================================================================
# HFA ESTIMATION
# =============================================================================

def build_training_hfa(
    training_residuals
):

    if not training_residuals:

        return None

    national_hfa = statistics.mean(
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
                len(
                    values
                ),

            "raw_hfa":
                statistics.mean(
                    values
                ),
        }

    return {
        "national_hfa":
            national_hfa,

        "teams":
            teams,
    }


def team_hfa_raw(
    team,
    training
):

    national = training[
        "national_hfa"
    ]

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

        return national

    return info[
        "raw_hfa"
    ]


def team_hfa_shrunk(
    team,
    training,
    shrinkage_games
):

    national = training[
        "national_hfa"
    ]

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

        return national

    n = info[
        "games"
    ]

    raw = info[
        "raw_hfa"
    ]

    weight = (
        n
        /
        (
            n
            +
            shrinkage_games
        )
    )

    modifier = (
        raw
        -
        national
    )

    return (
        national
        +
        weight
        *
        modifier
    )


def team_hfa_shrunk_capped(
    team,
    training,
    shrinkage_games,
    modifier_cap
):

    national = training[
        "national_hfa"
    ]

    shrunk = team_hfa_shrunk(
        team,
        training,
        shrinkage_games
    )

    modifier = (
        shrunk
        -
        national
    )

    modifier = clamp(
        modifier,
        -modifier_cap,
        modifier_cap
    )

    return (
        national
        +
        modifier
    )


# =============================================================================
# SCORE A PARTICULAR HFA SYSTEM
# =============================================================================

def score_model(
    model_name,
    residuals,
    shrinkage_games=None,
    modifier_cap=None
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

    all_predictions = []
    all_actuals = []

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

        year_predictions = []
        year_actuals = []

        for game in test_games:

            home = game[
                "home"
            ]

            if model_name == "flat":

                hfa = training[
                    "national_hfa"
                ]

            elif model_name == "raw_team":

                hfa = team_hfa_raw(
                    home,
                    training
                )

            elif model_name == "shrunk_team":

                hfa = team_hfa_shrunk(
                    home,
                    training,
                    shrinkage_games
                )

            elif model_name == "shrunk_capped":

                hfa = (
                    team_hfa_shrunk_capped(
                        home,
                        training,
                        shrinkage_games,
                        modifier_cap
                    )
                )

            else:

                raise ValueError(
                    f"Unknown model: {model_name}"
                )

            predicted_margin = (
                game[
                    "strength_margin"
                ]
                +
                hfa
            )

            actual_margin = game[
                "actual_home_margin"
            ]

            year_predictions.append(
                predicted_margin
            )

            year_actuals.append(
                actual_margin
            )

            all_predictions.append(
                predicted_margin
            )

            all_actuals.append(
                actual_margin
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

            "learned_national_hfa":
                round(
                    training[
                        "national_hfa"
                    ],
                    3
                ),

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
        "model":
            model_name,

        "shrinkage_games":
            shrinkage_games,

        "modifier_cap":
            modifier_cap,

        "games":
            len(
                all_predictions
            ),

        "mae":
            mae(
                all_predictions,
                all_actuals
            ),

        "rmse":
            rmse(
                all_predictions,
                all_actuals
            ),

        "year_by_year":
            yearly,
    }


# =============================================================================
# TEST ALL HFA SYSTEMS
# =============================================================================

def run_validation(
    residuals
):

    print("")
    print(
        "=" * 82
    )

    print(
        "LEAKAGE-SAFE HOME-FIELD VALIDATION"
    )

    print(
        "=" * 82
    )

    flat = score_model(
        "flat",
        residuals
    )

    raw = score_model(
        "raw_team",
        residuals
    )

    shrunk = score_model(
        "shrunk_team",
        residuals,
        shrinkage_games=DEFAULT_SHRINKAGE
    )

    grid_results = []

    for shrinkage in SHRINKAGE_CANDIDATES:

        for cap in CAP_CANDIDATES:

            result = score_model(
                "shrunk_capped",
                residuals,
                shrinkage_games=shrinkage,
                modifier_cap=cap
            )

            grid_results.append(
                result
            )

    valid_grid = [
        result
        for result
        in grid_results
        if result[
            "mae"
        ] is not None
    ]

    valid_grid.sort(
        key=lambda result:
            (
                result[
                    "mae"
                ],
                result[
                    "rmse"
                ]
            )
    )

    if not valid_grid:

        print(
            "❌ No HFA validation models could be scored."
        )

        sys.exit(1)

    best = valid_grid[
        0
    ]

    print("")
    print(
        "OUT-OF-SAMPLE MODEL COMPARISON"
    )

    print(
        f"   FLAT HFA            | "
        f"{flat['games']:>4} games | "
        f"MAE {flat['mae']:.3f} | "
        f"RMSE {flat['rmse']:.3f}"
    )

    print(
        f"   RAW TEAM HFA        | "
        f"{raw['games']:>4} games | "
        f"MAE {raw['mae']:.3f} | "
        f"RMSE {raw['rmse']:.3f}"
    )

    print(
        f"   SHRUNK TEAM HFA     | "
        f"{shrunk['games']:>4} games | "
        f"K={DEFAULT_SHRINKAGE:<2} | "
        f"MAE {shrunk['mae']:.3f} | "
        f"RMSE {shrunk['rmse']:.3f}"
    )

    print("")
    print(
        "BEST SHRUNK + CAPPED CONFIGURATION"
    )

    print(
        f"   Shrinkage games: "
        f"{best['shrinkage_games']}"
    )

    print(
        f"   Team modifier cap: "
        f"±{best['modifier_cap']:.1f} pts"
    )

    print(
        f"   Games: "
        f"{best['games']}"
    )

    print(
        f"   MAE: "
        f"{best['mae']:.3f}"
    )

    print(
        f"   RMSE: "
        f"{best['rmse']:.3f}"
    )

    flat_improvement = (
        flat[
            "mae"
        ]
        -
        best[
            "mae"
        ]
    )

    print(
        f"   MAE improvement vs flat: "
        f"{flat_improvement:+.3f} pts/game"
    )

    print("")
    print(
        "BEST MODEL YEAR BY YEAR"
    )

    for item in best[
        "year_by_year"
    ]:

        print(
            f"   {item['year']} | "
            f"national HFA "
            f"{item['learned_national_hfa']:+.3f} | "
            f"{item['test_games']:>4} games | "
            f"MAE {item['mae']:.3f} | "
            f"RMSE {item['rmse']:.3f}"
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
            "✅ Team-specific HFA improved "
            "out-of-sample margin accuracy."
        )

    else:

        print(
            "❌ Team-specific HFA did not beat "
            "a flat national HFA."
        )

    return {
        "flat":
            flat,

        "raw_team":
            raw,

        "shrunk_team":
            shrunk,

        "best_shrunk_capped":
            best,

        "grid_results":
            grid_results,

        "mae_improvement_vs_flat":
            flat_improvement,
    }


# =============================================================================
# FINAL 2026 HFA RATINGS
# =============================================================================

def build_final_2026_ratings(
    residuals,
    best_model
):

    national_hfa = statistics.mean(
        game[
            "home_residual"
        ]
        for game
        in residuals
    )

    by_team = defaultdict(
        list
    )

    by_team_year = defaultdict(
        lambda:
            defaultdict(
                list
            )
    )

    for game in residuals:

        team = game[
            "home"
        ]

        year = game[
            "year"
        ]

        value = game[
            "home_residual"
        ]

        by_team[
            team
        ].append(
            value
        )

        by_team_year[
            team
        ][
            year
        ].append(
            value
        )

    shrinkage = best_model[
        "shrinkage_games"
    ]

    cap = best_model[
        "modifier_cap"
    ]

    teams = []

    for team in sorted(
        by_team
    ):

        values = by_team[
            team
        ]

        n = len(
            values
        )

        raw_hfa = statistics.mean(
            values
        )

        raw_modifier = (
            raw_hfa
            -
            national_hfa
        )

        if (
            n
            <
            MIN_TEAM_HOME_GAMES
        ):

            team_weight = 0.0

        else:

            team_weight = (
                n
                /
                (
                    n
                    +
                    shrinkage
                )
            )

        shrunk_modifier = (
            raw_modifier
            *
            team_weight
        )

        capped_modifier = clamp(
            shrunk_modifier,
            -cap,
            cap
        )

        final_hfa = (
            national_hfa
            +
            capped_modifier
        )

        yearly = {}

        for year in sorted(
            by_team_year[
                team
            ]
        ):

            year_values = (
                by_team_year[
                    team
                ][
                    year
                ]
            )

            yearly[
                str(
                    year
                )
            ] = {
                "games":
                    len(
                        year_values
                    ),

                "raw_hfa":
                    round(
                        statistics.mean(
                            year_values
                        ),
                        3
                    ),
            }

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

            "team_weight":
                round(
                    team_weight,
                    3
                ),

            "shrunk_modifier":
                round(
                    shrunk_modifier,
                    3
                ),

            "capped_modifier":
                round(
                    capped_modifier,
                    3
                ),

            "final_hfa":
                round(
                    final_hfa,
                    3
                ),

            "reliability":
                reliability,

            "year_by_year":
                yearly,
        })

    teams.sort(
        key=lambda item:
            item[
                "final_hfa"
            ],
        reverse=True
    )

    return {
        "national_hfa":
            national_hfa,

        "shrinkage_games":
            shrinkage,

        "modifier_cap":
            cap,

        "teams":
            teams,
    }


# =============================================================================
# NATIONAL HFA SUMMARY
# =============================================================================

def national_summary(
    residuals
):

    values = [
        game[
            "home_residual"
        ]
        for game
        in residuals
    ]

    national = statistics.mean(
        values
    )

    std = statistics.stdev(
        values
    )

    se = (
        std
        /
        math.sqrt(
            len(
                values
            )
        )
    )

    by_year = defaultdict(
        list
    )

    for game in residuals:

        by_year[
            game[
                "year"
            ]
        ].append(
            game[
                "home_residual"
            ]
        )

    yearly = []

    for year in sorted(
        by_year
    ):

        year_values = by_year[
            year
        ]

        yearly.append({
            "year":
                year,

            "games":
                len(
                    year_values
                ),

            "hfa":
                round(
                    statistics.mean(
                        year_values
                    ),
                    3
                ),
        })

    return {
        "games":
            len(
                values
            ),

        "hfa":
            national,

        "standard_deviation":
            std,

        "standard_error":
            se,

        "ci_95_low":
            national
            -
            1.96 * se,

        "ci_95_high":
            national
            +
            1.96 * se,

        "year_by_year":
            yearly,
    }


# =============================================================================
# PRINT FINAL RATINGS
# =============================================================================

def print_final_ratings(
    national,
    final_ratings
):

    teams = final_ratings[
        "teams"
    ]

    print("")
    print(
        "=" * 82
    )

    print(
        "FINAL 2026 HOME-FIELD RATINGS"
    )

    print(
        "=" * 82
    )

    print("")
    print(
        "NATIONAL HOME-FIELD ADVANTAGE"
    )

    print(
        f"   Games: "
        f"{national['games']}"
    )

    print(
        f"   Historical HFA: "
        f"{national['hfa']:+.3f} points"
    )

    print(
        f"   95% CI: "
        f"{national['ci_95_low']:+.3f} "
        f"to "
        f"{national['ci_95_high']:+.3f}"
    )

    print("")
    print(
        "FINAL MODEL PARAMETERS"
    )

    print(
        f"   Shrinkage games: "
        f"{final_ratings['shrinkage_games']}"
    )

    print(
        f"   Team modifier cap: "
        f"±{final_ratings['modifier_cap']:.1f}"
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
            f"modifier "
            f"{item['capped_modifier']:+.2f} | "
            f"raw "
            f"{item['raw_hfa']:+.2f} | "
            f"{item['home_games']:>2} games | "
            f"{item['reliability']}"
        )

    print("")
    print(
        "WEAKEST ADJUSTED HOME FIELDS"
    )

    weakest = list(
        reversed(
            teams[
                -20:
            ]
        )
    )

    for rank, item in enumerate(
        weakest,
        start=1
    ):

        print(
            f"   {rank:>2}. "
            f"{item['team']:<24} "
            f"{item['final_hfa']:+.2f} | "
            f"modifier "
            f"{item['capped_modifier']:+.2f} | "
            f"raw "
            f"{item['raw_hfa']:+.2f} | "
            f"{item['home_games']:>2} games | "
            f"{item['reliability']}"
        )

    print("")
    print(
        "=" * 82
    )


# =============================================================================
# SAVE
# =============================================================================

def save_output(
    national,
    validation,
    final_ratings
):

    output = {
        "methodology": {
            "description":
                (
                    "Leakage-safe team-specific HFA validation. "
                    "Each historical test season uses only prior "
                    "seasons to estimate national and team HFA."
                ),

            "first_test_year":
                FIRST_HFA_TEST_YEAR,

            "minimum_team_home_games":
                MIN_TEAM_HOME_GAMES,

            "candidate_shrinkage_games":
                SHRINKAGE_CANDIDATES,

            "candidate_modifier_caps":
                CAP_CANDIDATES,
        },

        "national":
            {
                "games":
                    national[
                        "games"
                    ],

                "hfa":
                    round(
                        national[
                            "hfa"
                        ],
                        3
                    ),

                "ci_95_low":
                    round(
                        national[
                            "ci_95_low"
                        ],
                        3
                    ),

                "ci_95_high":
                    round(
                        national[
                            "ci_95_high"
                        ],
                        3
                    ),

                "year_by_year":
                    national[
                        "year_by_year"
                    ],
            },

        "validation": {
            "flat":
                validation[
                    "flat"
                ],

            "raw_team":
                validation[
                    "raw_team"
                ],

            "shrunk_team":
                validation[
                    "shrunk_team"
                ],

            "best_shrunk_capped":
                validation[
                    "best_shrunk_capped"
                ],

            "mae_improvement_vs_flat":
                round(
                    validation[
                        "mae_improvement_vs_flat"
                    ],
                    4
                ),
        },

        "final_2026": {
            "national_hfa":
                round(
                    final_ratings[
                        "national_hfa"
                    ],
                    3
                ),

            "shrinkage_games":
                final_ratings[
                    "shrinkage_games"
                ],

            "modifier_cap":
                final_ratings[
                    "modifier_cap"
                ],

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
        "🏟️  CFB team-specific HFA validation"
    )

    print(
        "   No API calls required."
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

    national = national_summary(
        residuals
    )

    final_ratings = (
        build_final_2026_ratings(
            residuals,
            validation[
                "best_shrunk_capped"
            ]
        )
    )

    print_final_ratings(
        national,
        final_ratings
    )

    save_output(
        national,
        validation,
        final_ratings
    )


if __name__ == "__main__":
    main()
