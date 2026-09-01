"""
CFB ANALYTICS
calibrate_hfa.py

Estimate team-specific college football home-field advantage.

This script uses the leakage-safe out-of-sample game records already created
by scripts/backtest_composite.py.

For each non-neutral game:

    home residual
    =
    actual home margin
    -
    expected margin from composite team strength

That residual represents the amount left over after accounting for the
relative strength of the two teams.

Across thousands of games, the average residual estimates national HFA.

For each home team, we calculate its own average residual and then shrink
that estimate toward the national average so small samples do not produce
wild home-field ratings.

NO API CALLS ARE MADE BY THIS SCRIPT.
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

# Controls how aggressively team-specific HFA estimates are pulled toward
# the national average.
#
# Example:
#   6 home games  -> 6 / (6 + 15) = 29% team data
#   15 home games -> 15 / (15 + 15) = 50% team data
#   30 home games -> 30 / (30 + 15) = 67% team data
#
# This is intentionally conservative.
SHRINKAGE_GAMES = 15

MIN_HOME_GAMES_FOR_TEAM_ESTIMATE = 3


# =============================================================================
# HELPERS
# =============================================================================

def safe_number(value, default=None):

    try:

        if value is None:
            return default

        return float(value)

    except (TypeError, ValueError):

        return default


def mean(values):

    clean = [
        value
        for value in values
        if value is not None
    ]

    if not clean:
        return None

    return statistics.mean(clean)


def sample_std(values):

    clean = [
        value
        for value in values
        if value is not None
    ]

    if len(clean) < 2:
        return None

    return statistics.stdev(clean)


def round_or_none(value, digits=3):

    if value is None:
        return None

    return round(value, digits)


# =============================================================================
# LOAD COMPOSITE BACKTEST
# =============================================================================

def load_backtest():

    if not os.path.exists(INPUT_PATH):

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

    year_reports = {}

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

            year_reports[
                int(year)
            ] = scale

    if not year_reports:

        print(
            "❌ No year-by-year rating scales found."
        )

        sys.exit(1)

    return (
        games,
        year_reports
    )


# =============================================================================
# CREATE HOME-FIELD RESIDUALS
# =============================================================================

def build_home_residuals(
    games,
    year_scales
):

    residuals = []

    skipped_neutral = 0
    skipped_missing = 0

    for game in games:

        if game.get(
            "neutral"
        ):

            skipped_neutral += 1
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

            skipped_missing += 1
            continue

        try:

            year = int(year)

        except (TypeError, ValueError):

            skipped_missing += 1
            continue

        rating_to_points = year_scales.get(
            year
        )

        if rating_to_points is None:

            skipped_missing += 1
            continue

        # -------------------------------------------------------------
        # IMPORTANT
        # -------------------------------------------------------------
        #
        # We deliberately DO NOT include the historical HFA term here.
        #
        # We want to estimate HFA ourselves.
        #
        # Therefore:
        #
        # expected margin =
        #     rating difference * historical rating-to-points scale
        #
        # residual =
        #     actual margin - strength-only expected margin
        #
        # -------------------------------------------------------------

        expected_strength_margin = (
            rating_diff
            *
            rating_to_points
        )

        residual = (
            actual_home_margin
            -
            expected_strength_margin
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

            "expected_strength_margin":
                expected_strength_margin,

            "actual_home_margin":
                actual_home_margin,

            "home_field_residual":
                residual,
        })

    print(
        f"   Non-neutral games used: "
        f"{len(residuals)}"
    )

    print(
        f"   Neutral-site games skipped: "
        f"{skipped_neutral}"
    )

    if skipped_missing:

        print(
            f"   Games skipped for missing data: "
            f"{skipped_missing}"
        )

    return residuals


# =============================================================================
# NATIONAL HFA
# =============================================================================

def calculate_national_hfa(
    residuals
):

    values = [
        game[
            "home_field_residual"
        ]
        for game in residuals
    ]

    national_hfa = statistics.mean(
        values
    )

    residual_std = statistics.stdev(
        values
    )

    standard_error = (
        residual_std
        /
        math.sqrt(
            len(values)
        )
    )

    ci_95 = (
        national_hfa
        -
        1.96 * standard_error,

        national_hfa
        +
        1.96 * standard_error
    )

    return {
        "hfa":
            national_hfa,

        "games":
            len(values),

        "residual_std":
            residual_std,

        "standard_error":
            standard_error,

        "ci_95_low":
            ci_95[0],

        "ci_95_high":
            ci_95[1],
    }


# =============================================================================
# TEAM HFA
# =============================================================================

def calculate_team_hfa(
    residuals,
    national_hfa
):

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

        residual = game[
            "home_field_residual"
        ]

        by_team[
            team
        ].append(
            residual
        )

        by_team_year[
            team
        ][
            year
        ].append(
            residual
        )

    output = []

    for team in sorted(
        by_team
    ):

        values = by_team[
            team
        ]

        games = len(
            values
        )

        raw_hfa = statistics.mean(
            values
        )

        std = sample_std(
            values
        )

        standard_error = (
            std
            /
            math.sqrt(
                games
            )
            if (
                std is not None
                and games > 0
            )
            else None
        )

        # -------------------------------------------------------------
        # SHRINKAGE
        # -------------------------------------------------------------
        #
        # Team estimate weight:
        #
        #       n
        #  ------------
        #    n + K
        #
        # where K = SHRINKAGE_GAMES
        #
        # Small samples stay close to national HFA.
        # Large samples earn more team-specific influence.
        # -------------------------------------------------------------

        if (
            games
            <
            MIN_HOME_GAMES_FOR_TEAM_ESTIMATE
        ):

            team_weight = 0.0

        else:

            team_weight = (
                games
                /
                (
                    games
                    +
                    SHRINKAGE_GAMES
                )
            )

        national_weight = (
            1.0
            -
            team_weight
        )

        adjusted_hfa = (
            raw_hfa
            *
            team_weight
            +
            national_hfa
            *
            national_weight
        )

        if games >= 20:

            reliability = "HIGH"

        elif games >= 12:

            reliability = "MEDIUM"

        else:

            reliability = "LOW"

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
                str(year)
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

        output.append({
            "team":
                team,

            "home_games":
                games,

            "raw_hfa":
                round(
                    raw_hfa,
                    3
                ),

            "adjusted_hfa":
                round(
                    adjusted_hfa,
                    3
                ),

            "team_weight":
                round(
                    team_weight,
                    3
                ),

            "national_weight":
                round(
                    national_weight,
                    3
                ),

            "standard_deviation":
                round_or_none(
                    std
                ),

            "standard_error":
                round_or_none(
                    standard_error
                ),

            "reliability":
                reliability,

            "year_by_year":
                yearly,
        })

    output.sort(
        key=lambda item:
            item[
                "adjusted_hfa"
            ],
        reverse=True
    )

    return output


# =============================================================================
# YEAR-BY-YEAR NATIONAL HFA
# =============================================================================

def calculate_yearly_hfa(
    residuals
):

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
                "home_field_residual"
            ]
        )

    output = []

    for year in sorted(
        by_year
    ):

        values = by_year[
            year
        ]

        output.append({
            "year":
                year,

            "games":
                len(
                    values
                ),

            "hfa":
                round(
                    statistics.mean(
                        values
                    ),
                    3
                ),
        })

    return output


# =============================================================================
# CONFERENCE-FREE RANKING SUMMARY
# =============================================================================

def ranking_summary(
    teams,
    count=15
):

    strongest = teams[
        :count
    ]

    weakest = list(
        reversed(
            teams[
                -count:
            ]
        )
    )

    return {
        "strongest":
            [
                {
                    "team":
                        item[
                            "team"
                        ],

                    "hfa":
                        item[
                            "adjusted_hfa"
                        ],

                    "games":
                        item[
                            "home_games"
                        ],

                    "reliability":
                        item[
                            "reliability"
                        ],
                }
                for item
                in strongest
            ],

        "weakest":
            [
                {
                    "team":
                        item[
                            "team"
                        ],

                    "hfa":
                        item[
                            "adjusted_hfa"
                        ],

                    "games":
                        item[
                            "home_games"
                        ],

                    "reliability":
                        item[
                            "reliability"
                        ],
                }
                for item
                in weakest
            ],
    }


# =============================================================================
# PRINT
# =============================================================================

def print_report(
    national,
    yearly,
    teams
):

    print("")
    print(
        "=" * 78
    )

    print(
        "TEAM-SPECIFIC HOME-FIELD ADVANTAGE"
    )

    print(
        "=" * 78
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
        f"   HFA: "
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
        "YEAR-BY-YEAR NATIONAL HFA"
    )

    for item in yearly:

        print(
            f"   {item['year']} | "
            f"{item['games']:>4} games | "
            f"{item['hfa']:+.3f}"
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
            f"{item['adjusted_hfa']:+.2f} | "
            f"raw {item['raw_hfa']:+.2f} | "
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
            f"{item['adjusted_hfa']:+.2f} | "
            f"raw {item['raw_hfa']:+.2f} | "
            f"{item['home_games']:>2} games | "
            f"{item['reliability']}"
        )

    print("")
    print(
        "=" * 78
    )

    print(
        "IMPORTANT:"
    )

    print(
        "These values control for the composite "
        "strength difference before measuring "
        "home performance."
    )

    print(
        "Small samples are shrunk toward the "
        "national average."
    )

    print(
        "No conference bonus, stadium-size bonus, "
        "or subjective atmosphere adjustment "
        "is included."
    )

    print(
        "=" * 78
    )


# =============================================================================
# SAVE
# =============================================================================

def save_output(
    national,
    yearly,
    teams,
    residuals
):

    output = {
        "methodology": {
            "source":
                INPUT_PATH,

            "description":
                (
                    "Team-specific home-field advantage "
                    "estimated from actual margin minus "
                    "strength-only expected margin using "
                    "leakage-safe composite ratings."
                ),

            "shrinkage_games":
                SHRINKAGE_GAMES,

            "minimum_home_games":
                MIN_HOME_GAMES_FOR_TEAM_ESTIMATE,

            "neutral_sites_excluded":
                True,

            "conference_adjustment":
                False,

            "subjective_stadium_adjustment":
                False,
        },

        "national": {
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

            "residual_std":
                round(
                    national[
                        "residual_std"
                    ],
                    3
                ),

            "standard_error":
                round(
                    national[
                        "standard_error"
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
        },

        "year_by_year":
            yearly,

        "rankings":
            ranking_summary(
                teams
            ),

        "teams":
            teams,

        "games":
            residuals,
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
        "🏟️ CFB team-specific HFA calibration"
    )

    print(
        "   Source: leakage-safe composite backtest"
    )

    print(
        f"   Shrinkage strength: "
        f"{SHRINKAGE_GAMES} games"
    )

    print("")

    (
        games,
        year_scales
    ) = load_backtest()

    print(
        f"📊 Loaded {len(games)} "
        "out-of-sample games"
    )

    print(
        f"📅 Historical scales available: "
        f"{len(year_scales)} seasons"
    )

    print("")
    print(
        "🏠 Calculating strength-adjusted "
        "home residuals..."
    )

    residuals = build_home_residuals(
        games,
        year_scales
    )

    if len(residuals) < 500:

        print(
            "❌ HFA sample unexpectedly small."
        )

        sys.exit(1)

    national = calculate_national_hfa(
        residuals
    )

    yearly = calculate_yearly_hfa(
        residuals
    )

    teams = calculate_team_hfa(
        residuals,
        national[
            "hfa"
        ]
    )

    print_report(
        national,
        yearly,
        teams
    )

    save_output(
        national,
        yearly,
        teams,
        residuals
    )


if __name__ == "__main__":
    main()
