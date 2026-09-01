"""
CFB ANALYTICS
backtest_composite.py

Time-safe historical backtest of the core efficiency composite
used by the live 2026 projection model.

This version intentionally mirrors the live model's play-level logic:

    Net EPA/PPA              30%
    Net Pass EPA/PPA         15%
    Net Rush EPA/PPA         15%
    Net Success Rate         10%
    Defensive Havoc Created  20%
    Offensive Havoc Allowed  10%

DATA SAFETY
-----------
A game in Week N is predicted using ONLY plays from Weeks < N.

No game being predicted contributes to its own rating.
No future week contributes to an earlier prediction.

API EFFICIENCY
--------------
Instead of one advanced-box request per game, this script downloads:
- games once per season
- betting lines once per season
- plays once per historical week

This keeps the request count relatively small.

IMPORTANT
---------
This script is diagnostic only.
It does NOT modify live 2026 projections.
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

WEIGHTS = {
    "net_epa": 0.30,
    "net_epa_pass": 0.15,
    "net_epa_rush": 0.15,
    "net_sr": 0.10,
    "def_havoc_created": 0.20,
    "off_havoc_allowed": 0.10,
}

# We do not want to treat 10-20 plays as a stable in-season rating.
MIN_PRIOR_PLAYS = 100

MIN_PASS_PLAYS = 30
MIN_RUSH_PLAYS = 30

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
# GENERAL HELPERS
# =============================================================================

def safe_number(
    value,
    default=None
):

    try:

        if value is None:
            return default

        return float(value)

    except (
        TypeError,
        ValueError
    ):

        return default


def first_value(
    data,
    *keys,
    default=None
):

    for key in keys:

        if (
            key in data
            and data.get(key) is not None
        ):
            return data.get(key)

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


def mae(
    predictions,
    actuals
):

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


def rmse(
    predictions,
    actuals
):

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


def z_scores(
    values_by_team
):

    clean = [
        value
        for value in values_by_team.values()
        if value is not None
    ]

    if len(clean) < 2:

        return {
            team: 0.0
            for team
            in values_by_team
        }

    avg = statistics.mean(
        clean
    )

    std = statistics.pstdev(
        clean
    )

    if std == 0:

        return {
            team: 0.0
            for team
            in values_by_team
        }

    output = {}

    for team, value in values_by_team.items():

        if value is None:

            output[
                team
            ] = 0.0

        else:

            output[
                team
            ] = (
                value - avg
            ) / std

    return output


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
                timeout=90
            )

        except requests.RequestException as error:

            print(
                f"⚠ Request error "
                f"{endpoint} "
                f"({attempt}/3): "
                f"{error}"
            )

            if attempt < 3:

                time.sleep(2)
                continue

            if required:

                sys.exit(1)

            return []

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
                f"⚠ CFBD {endpoint}: "
                f"HTTP {response.status_code}"
            )

            print(
                response.text[:300]
            )

            if attempt < 3:

                time.sleep(2)
                continue

            if required:

                sys.exit(1)

            return []

        try:

            return response.json()

        except ValueError:

            print(
                f"❌ Invalid JSON from "
                f"{endpoint}"
            )

            if required:

                sys.exit(1)

            return []

    return []


# =============================================================================
# GAMES
# =============================================================================

def get_games(year):

    print(
        f"📅 Loading {year} games..."
    )

    raw = cfbd_get(
        "/games",
        {
            "year":
                year,

            "seasonType":
                "regular",

            "classification":
                "fbs",
        }
    )

    games = []

    for game in raw:

        home_class = str(
            first_value(
                game,
                "homeClassification",
                "home_classification",
                default=""
            )
        ).lower()

        away_class = str(
            first_value(
                game,
                "awayClassification",
                "away_classification",
                default=""
            )
        ).lower()

        if (
            home_class != "fbs"
            or away_class != "fbs"
        ):
            continue

        completed = first_value(
            game,
            "completed",
            default=True
        )

        if completed is False:
            continue

        home_points = safe_number(
            first_value(
                game,
                "homePoints",
                "home_points"
            )
        )

        away_points = safe_number(
            first_value(
                game,
                "awayPoints",
                "away_points"
            )
        )

        game_id = first_value(
            game,
            "id"
        )

        week = safe_number(
            first_value(
                game,
                "week"
            )
        )

        home = first_value(
            game,
            "homeTeam",
            "home_team"
        )

        away = first_value(
            game,
            "awayTeam",
            "away_team"
        )

        if (
            game_id is None
            or week is None
            or not home
            or not away
            or home_points is None
            or away_points is None
        ):
            continue

        games.append({
            "id":
                int(
                    game_id
                ),

            "year":
                year,

            "week":
                int(
                    week
                ),

            "home":
                home,

            "away":
                away,

            "neutral":
                bool(
                    first_value(
                        game,
                        "neutralSite",
                        "neutral_site",
                        default=False
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
                game[
                    "week"
                ],
                game[
                    "id"
                ]
            )
    )

    print(
        f"   {len(games)} "
        "completed FBS-vs-FBS games"
    )

    return games


# =============================================================================
# HISTORICAL BETTING LINES
# =============================================================================

def choose_spread(
    provider
):

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


def extract_spread(
    game
):

    providers = (
        game.get(
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

    for preferred_name in preferred:

        for provider in providers:

            provider_name = str(
                provider.get(
                    "provider",
                    ""
                )
            )

            if (
                provider_name.lower()
                ==
                preferred_name.lower()
            ):

                spread = choose_spread(
                    provider
                )

                if spread is not None:

                    return spread

    all_spreads = []

    for provider in providers:

        spread = choose_spread(
            provider
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
        f"💰 Loading {year} historical lines..."
    )

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

    for item in raw:

        game_id = first_value(
            item,
            "id",
            "gameId",
            "game_id"
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

    print(
        f"   {len(lookup)} games "
        "with usable spread data"
    )

    return lookup


# =============================================================================
# PLAY NORMALIZATION
# =============================================================================

def normalize_play(raw):

    return {
        "game_id":
            first_value(
                raw,
                "gameId",
                "game_id"
            ),

        "offense":
            first_value(
                raw,
                "offense"
            ),

        "defense":
            first_value(
                raw,
                "defense"
            ),

        "offense_score":
            safe_number(
                first_value(
                    raw,
                    "offenseScore",
                    "offense_score",
                    default=0
                ),
                0
            ),

        "defense_score":
            safe_number(
                first_value(
                    raw,
                    "defenseScore",
                    "defense_score",
                    default=0
                ),
                0
            ),

        "period":
            int(
                safe_number(
                    first_value(
                        raw,
                        "period",
                        default=1
                    ),
                    1
                )
            ),

        "down":
            safe_number(
                first_value(
                    raw,
                    "down"
                )
            ),

        "distance":
            safe_number(
                first_value(
                    raw,
                    "distance"
                )
            ),

        "yards_gained":
            safe_number(
                first_value(
                    raw,
                    "yardsGained",
                    "yards_gained",
                    default=0
                ),
                0
            ),

        "play_type":
            str(
                first_value(
                    raw,
                    "playType",
                    "play_type",
                    default=""
                )
            ),

        "play_text":
            str(
                first_value(
                    raw,
                    "playText",
                    "play_text",
                    default=""
                )
            ),

        "ppa":
            safe_number(
                first_value(
                    raw,
                    "ppa"
                )
            ),
    }


# =============================================================================
# PLAY CLASSIFICATION
# =============================================================================

def play_description(
    play
):

    return (
        f"{play.get('play_type', '')} "
        f"{play.get('play_text', '')}"
    ).lower()


def is_pass_play(
    play
):

    text = play_description(
        play
    )

    return any(
        phrase in text
        for phrase in (
            "pass",
            "sack",
            "interception",
        )
    )


def is_rush_play(
    play
):

    text = play_description(
        play
    )

    if "sack" in text:
        return False

    return any(
        phrase in text
        for phrase in (
            "rush",
            "run ",
            "rushed",
        )
    )


def is_excluded_play(
    play
):

    text = play_description(
        play
    )

    return any(
        phrase in text
        for phrase in (
            "kickoff",
            "extra point",
            "timeout",
            "end of",
            "coin toss",
            "penalty",
            "two point",
            "2-point",
        )
    )


def is_garbage_time(
    play
):

    period = play[
        "period"
    ]

    score_difference = abs(
        play[
            "offense_score"
        ]
        -
        play[
            "defense_score"
        ]
    )

    if (
        period >= 4
        and score_difference >= 28
    ):
        return True

    if (
        period >= 3
        and score_difference >= 38
    ):
        return True

    return False


def is_success(
    play
):

    yards = play[
        "yards_gained"
    ]

    distance = play[
        "distance"
    ]

    down = play[
        "down"
    ]

    if (
        distance is None
        or distance <= 0
        or down is None
    ):
        return False

    down = int(
        down
    )

    if down == 1:

        return (
            yards
            >=
            distance * 0.50
        )

    if down == 2:

        return (
            yards
            >=
            distance * 0.70
        )

    if down in (
        3,
        4
    ):

        return (
            yards
            >=
            distance
        )

    return False


def is_havoc(
    play
):

    text = play_description(
        play
    )

    return any(
        phrase in text
        for phrase in (
            "sack",
            "interception",
            "fumble",
            "tackle for loss",
            "tfl",
            "pass breakup",
            "broken up",
        )
    )


# =============================================================================
# TEAM HISTORY
# =============================================================================

def empty_history():

    return {
        "plays":
            0,

        "epa_sum":
            0.0,

        "epa_count":
            0,

        "pass_epa_sum":
            0.0,

        "pass_epa_count":
            0,

        "rush_epa_sum":
            0.0,

        "rush_epa_count":
            0,

        "successes":
            0,

        "success_plays":
            0,

        "havoc_created":
            0,

        "havoc_def_plays":
            0,

        "havoc_allowed":
            0,

        "havoc_off_plays":
            0,
    }


def add_offensive_play(
    history,
    play,
    pass_play,
    rush_play,
    success,
    havoc
):

    history[
        "plays"
    ] += 1

    ppa = play[
        "ppa"
    ]

    if ppa is not None:

        history[
            "epa_sum"
        ] += ppa

        history[
            "epa_count"
        ] += 1

        if pass_play:

            history[
                "pass_epa_sum"
            ] += ppa

            history[
                "pass_epa_count"
            ] += 1

        if rush_play:

            history[
                "rush_epa_sum"
            ] += ppa

            history[
                "rush_epa_count"
            ] += 1

    history[
        "success_plays"
    ] += 1

    if success:

        history[
            "successes"
        ] += 1

    history[
        "havoc_off_plays"
    ] += 1

    if havoc:

        history[
            "havoc_allowed"
        ] += 1


def add_defensive_play(
    history,
    play,
    pass_play,
    rush_play,
    success,
    havoc
):

    # Defensive EPA is stored from the opponent's
    # offensive PPA, then subtracted later.
    ppa = play[
        "ppa"
    ]

    key_map = (
        ("def_epa_sum", "def_epa_count"),
        (
            "def_pass_epa_sum",
            "def_pass_epa_count"
        )
        if pass_play
        else (None, None),
        (
            "def_rush_epa_sum",
            "def_rush_epa_count"
        )
        if rush_play
        else (None, None),
    )

    if ppa is not None:

        for sum_key, count_key in key_map:

            if sum_key is None:
                continue

            if sum_key not in history:
                history[
                    sum_key
                ] = 0.0

            if count_key not in history:
                history[
                    count_key
                ] = 0

            history[
                sum_key
            ] += ppa

            history[
                count_key
            ] += 1

    if (
        "def_successes_allowed"
        not in history
    ):
        history[
            "def_successes_allowed"
        ] = 0

    if (
        "def_success_plays"
        not in history
    ):
        history[
            "def_success_plays"
        ] = 0

    history[
        "def_success_plays"
    ] += 1

    if success:

        history[
            "def_successes_allowed"
        ] += 1

    history[
        "havoc_def_plays"
    ] += 1

    if havoc:

        history[
            "havoc_created"
        ] += 1


# =============================================================================
# WEEKLY PLAY DOWNLOAD
# =============================================================================

def get_week_plays(
    year,
    week,
    valid_game_ids
):

    raw = cfbd_get(
        "/plays",
        {
            "year":
                year,

            "week":
                week,

            "seasonType":
                "regular",

            "classification":
                "fbs",
        }
    )

    plays = []

    for raw_play in raw:

        play = normalize_play(
            raw_play
        )

        game_id = play[
            "game_id"
        ]

        if game_id is None:
            continue

        try:

            game_id = int(
                game_id
            )

        except (
            TypeError,
            ValueError
        ):
            continue

        if (
            game_id
            not in valid_game_ids
        ):
            continue

        if (
            not play[
                "offense"
            ]
            or not play[
                "defense"
            ]
        ):
            continue

        if is_excluded_play(
            play
        ):
            continue

        if is_garbage_time(
            play
        ):
            continue

        if play[
            "ppa"
        ] is None:
            continue

        plays.append(
            play
        )

    return plays


# =============================================================================
# SNAPSHOT
# =============================================================================

def average(
    total,
    count
):

    if not count:
        return None

    return (
        total
        /
        count
    )


def team_snapshot(
    offense_history,
    defense_history
):

    if (
        offense_history[
            "plays"
        ]
        <
        MIN_PRIOR_PLAYS
    ):

        return None

    if (
        offense_history[
            "epa_count"
        ]
        <
        MIN_PRIOR_PLAYS
    ):

        return None

    if (
        defense_history.get(
            "def_epa_count",
            0
        )
        <
        MIN_PRIOR_PLAYS
    ):

        return None

    off_epa = average(
        offense_history[
            "epa_sum"
        ],
        offense_history[
            "epa_count"
        ]
    )

    def_epa_allowed = average(
        defense_history[
            "def_epa_sum"
        ],
        defense_history[
            "def_epa_count"
        ]
    )

    off_pass = average(
        offense_history[
            "pass_epa_sum"
        ],
        offense_history[
            "pass_epa_count"
        ]
    )

    def_pass = average(
        defense_history.get(
            "def_pass_epa_sum",
            0.0
        ),
        defense_history.get(
            "def_pass_epa_count",
            0
        )
    )

    off_rush = average(
        offense_history[
            "rush_epa_sum"
        ],
        offense_history[
            "rush_epa_count"
        ]
    )

    def_rush = average(
        defense_history.get(
            "def_rush_epa_sum",
            0.0
        ),
        defense_history.get(
            "def_rush_epa_count",
            0
        )
    )

    if (
        offense_history[
            "pass_epa_count"
        ] < MIN_PASS_PLAYS
        or defense_history.get(
            "def_pass_epa_count",
            0
        ) < MIN_PASS_PLAYS
    ):
        off_pass = None
        def_pass = None

    if (
        offense_history[
            "rush_epa_count"
        ] < MIN_RUSH_PLAYS
        or defense_history.get(
            "def_rush_epa_count",
            0
        ) < MIN_RUSH_PLAYS
    ):
        off_rush = None
        def_rush = None

    off_sr = (
        offense_history[
            "successes"
        ]
        /
        offense_history[
            "success_plays"
        ]
        *
        100
        if offense_history[
            "success_plays"
        ]
        else None
    )

    def_sr_allowed = (
        defense_history.get(
            "def_successes_allowed",
            0
        )
        /
        defense_history.get(
            "def_success_plays",
            1
        )
        *
        100
        if defense_history.get(
            "def_success_plays",
            0
        )
        else None
    )

    def_havoc = (
        defense_history[
            "havoc_created"
        ]
        /
        defense_history[
            "havoc_def_plays"
        ]
        *
        100
        if defense_history[
            "havoc_def_plays"
        ]
        else None
    )

    off_havoc_allowed = (
        offense_history[
            "havoc_allowed"
        ]
        /
        offense_history[
            "havoc_off_plays"
        ]
        *
        100
        if offense_history[
            "havoc_off_plays"
        ]
        else None
    )

    return {
        "net_epa":
            (
                off_epa
                -
                def_epa_allowed
            ),

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
            (
                off_sr
                -
                def_sr_allowed
            ),

        "def_havoc_created":
            def_havoc,

        "off_havoc_allowed":
            off_havoc_allowed,
    }


# =============================================================================
# COMPOSITE RATING
# =============================================================================

def build_ratings(
    teams,
    offense_histories,
    defense_histories
):

    snapshots = {}

    for team in teams:

        snapshot = team_snapshot(
            offense_histories[
                team
            ],
            defense_histories[
                team
            ]
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

        for component, weight in WEIGHTS.items():

            z = component_z[
                component
            ].get(
                team,
                0.0
            )

            # Higher havoc allowed is BAD.
            if (
                component
                ==
                "off_havoc_allowed"
            ):

                z *= -1.0

            rating += (
                z
                *
                weight
            )

        ratings[
            team
        ] = rating

    return ratings


# =============================================================================
# UPDATE HISTORIES
# =============================================================================

def process_week_plays(
    plays,
    offense_histories,
    defense_histories
):

    for play in plays:

        offense = play[
            "offense"
        ]

        defense = play[
            "defense"
        ]

        pass_play = is_pass_play(
            play
        )

        rush_play = is_rush_play(
            play
        )

        success = is_success(
            play
        )

        havoc = is_havoc(
            play
        )

        add_offensive_play(
            offense_histories[
                offense
            ],
            play,
            pass_play,
            rush_play,
            success,
            havoc
        )

        add_defensive_play(
            defense_histories[
                defense
            ],
            play,
            pass_play,
            rush_play,
            success,
            havoc
        )


# =============================================================================
# BUILD TIME-SAFE YEAR
# =============================================================================

def build_year_records(
    year,
    games,
    line_lookup
):

    teams = sorted(
        set(
            [
                game[
                    "home"
                ]
                for game in games
            ]
            +
            [
                game[
                    "away"
                ]
                for game in games
            ]
        )
    )

    offense_histories = defaultdict(
        empty_history
    )

    defense_histories = defaultdict(
        empty_history
    )

    records = []

    weeks = sorted(
        set(
            game[
                "week"
            ]
            for game in games
        )
    )

    print("")
    print(
        f"🧠 Building time-safe "
        f"{year} snapshots"
    )

    for week in weeks:

        week_games = [
            game
            for game in games
            if game[
                "week"
            ] == week
        ]

        # -------------------------------------------------------------
        # FIRST: CREATE RATINGS
        # -------------------------------------------------------------
        #
        # These ratings contain only PREVIOUS weeks.
        #
        # We have NOT downloaded/processed this week's plays yet.
        # -------------------------------------------------------------

        ratings = build_ratings(
            teams,
            offense_histories,
            defense_histories
        )

        usable = 0

        for game in week_games:

            home_rating = ratings.get(
                game[
                    "home"
                ]
            )

            away_rating = ratings.get(
                game[
                    "away"
                ]
            )

            if (
                home_rating is None
                or away_rating is None
            ):
                continue

            records.append({
                "game_id":
                    game[
                        "id"
                    ],

                "year":
                    year,

                "week":
                    week,

                "home":
                    game[
                        "home"
                    ],

                "away":
                    game[
                        "away"
                    ],

                "neutral":
                    game[
                        "neutral"
                    ],

                "home_rating":
                    home_rating,

                "away_rating":
                    away_rating,

                "rating_diff":
                    (
                        home_rating
                        -
                        away_rating
                    ),

                "actual_home_margin":
                    game[
                        "actual_home_margin"
                    ],

                "market_home_spread":
                    line_lookup.get(
                        game[
                            "id"
                        ]
                    ),
            })

            usable += 1

        print(
            f"   Week {week:>2}: "
            f"{usable:>3} usable "
            "pregame matchups",
            end=""
        )

        # -------------------------------------------------------------
        # SECOND: DOWNLOAD THIS WEEK'S PLAYS
        # -------------------------------------------------------------

        valid_game_ids = {
            game[
                "id"
            ]
            for game in week_games
        }

        plays = get_week_plays(
            year,
            week,
            valid_game_ids
        )

        print(
            f" | {len(plays):>5} "
            "qualifying plays"
        )

        # -------------------------------------------------------------
        # THIRD: ADD WEEK TO HISTORY
        # -------------------------------------------------------------
        #
        # These plays become available for NEXT week's ratings.
        # -------------------------------------------------------------

        process_week_plays(
            plays,
            offense_histories,
            defense_histories
        )

    print(
        f"   Total usable "
        f"{year} games: "
        f"{len(records)}"
    )

    return records


# =============================================================================
# FIT RATING -> SCORE MARGIN
# =============================================================================

def fit_scoring_model(
    training_records
):

    """
    Fit:

        actual margin
        =
        beta * composite rating difference
        +
        HFA * home_indicator

    Neutral-site games receive home_indicator = 0.

    We solve the two-variable OLS normal equations directly.
    No future test-season games are used.
    """

    if len(
        training_records
    ) < 100:

        raise ValueError(
            "Insufficient training sample."
        )

    sum_xx = 0.0
    sum_xh = 0.0
    sum_hh = 0.0

    sum_xy = 0.0
    sum_hy = 0.0

    for record in training_records:

        x = record[
            "rating_diff"
        ]

        h = (
            0.0
            if record[
                "neutral"
            ]
            else 1.0
        )

        y = record[
            "actual_home_margin"
        ]

        sum_xx += x * x
        sum_xh += x * h
        sum_hh += h * h

        sum_xy += x * y
        sum_hy += h * y

    determinant = (
        sum_xx
        *
        sum_hh
        -
        sum_xh
        *
        sum_xh
    )

    if abs(
        determinant
    ) < 1e-9:

        raise ValueError(
            "Scoring calibration matrix "
            "is singular."
        )

    rating_to_points = (
        (
            sum_xy
            *
            sum_hh
        )
        -
        (
            sum_hy
            *
            sum_xh
        )
    ) / determinant

    home_field = (
        (
            sum_hy
            *
            sum_xx
        )
        -
        (
            sum_xy
            *
            sum_xh
        )
    ) / determinant

    predictions = []

    actuals = []

    for record in training_records:

        prediction = (
            rating_to_points
            *
            record[
                "rating_diff"
            ]
            +
            (
                0.0
                if record[
                    "neutral"
                ]
                else home_field
            )
        )

        predictions.append(
            prediction
        )

        actuals.append(
            record[
                "actual_home_margin"
            ]
        )

    actual_mean = statistics.mean(
        actuals
    )

    ss_total = sum(
        (
            actual
            -
            actual_mean
        ) ** 2
        for actual in actuals
    )

    ss_residual = sum(
        (
            actual
            -
            prediction
        ) ** 2
        for prediction, actual
        in zip(
            predictions,
            actuals
        )
    )

    r_squared = (
        1.0
        -
        ss_residual
        /
        ss_total
        if ss_total
        else 0.0
    )

    return {
        "rating_to_points":
            rating_to_points,

        "home_field":
            home_field,

        "r_squared":
            r_squared,

        "training_mae":
            mae(
                predictions,
                actuals
            ),
    }


# =============================================================================
# ATS
# =============================================================================

def evaluate_ats(
    actual_home_margin,
    market_home_spread,
    projected_home_margin
):

    # Historical line is treated as the HOME spread:
    #
    # home favorite -7
    # =>
    # market expected home margin +7

    market_expected_home_margin = (
        -market_home_spread
    )

    model_edge = (
        projected_home_margin
        -
        market_expected_home_margin
    )

    absolute_edge = abs(
        model_edge
    )

    if abs(
        model_edge
    ) < 1e-9:

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

    home_cover_margin = (
        actual_home_margin
        +
        market_home_spread
    )

    if model_edge > 0:

        model_side = "home"

        cover_margin = (
            home_cover_margin
        )

    else:

        model_side = "away"

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
            absolute_edge,

        "model_side":
            model_side,

        "ats_result":
            result,
    }


# =============================================================================
# ROLLING OUT-OF-SAMPLE TEST
# =============================================================================

def run_out_of_sample(
    records_by_year
):

    scored = []

    yearly_reports = []

    print("")
    print(
        "=" * 78
    )

    print(
        "ROLLING OUT-OF-SAMPLE TEST"
    )

    print(
        "=" * 78
    )

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
            len(training) < 100
            or len(testing) < 25
        ):

            print(
                f"⚠ Skipping {test_year}: "
                "insufficient sample."
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

            output = dict(
                record
            )

            output[
                "projected_home_margin"
            ] = projected

            output[
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

                output.update(
                    evaluate_ats(
                        record[
                            "actual_home_margin"
                        ],
                        market_spread,
                        projected
                    )
                )

            else:

                output[
                    "model_edge"
                ] = None

                output[
                    "absolute_edge"
                ] = None

                output[
                    "model_side"
                ] = None

                output[
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
                output
            )

            scored.append(
                output
            )

        market_games = [
            game
            for game in year_scored
            if game.get(
                "absolute_edge"
            )
            is not None
        ]

        year_mae = mae(
            predictions,
            actuals
        )

        year_rmse = rmse(
            predictions,
            actuals
        )

        yearly_reports.append({
            "year":
                test_year,

            "training_games":
                len(
                    training
                ),

            "test_games":
                len(
                    testing
                ),

            "market_games":
                len(
                    market_games
                ),

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

            "training_r_squared":
                round(
                    model[
                        "r_squared"
                    ],
                    4
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
            f"   Market games: "
            f"{len(market_games)}"
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
            f"   Training R²: "
            f"{model['r_squared']:.3f}"
        )

        print(
            f"   Test MAE: "
            f"{year_mae:.3f}"
        )

        print(
            f"   Test RMSE: "
            f"{year_rmse:.3f}"
        )

    return (
        scored,
        yearly_reports
    )


# =============================================================================
# ATS REPORTING
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
        for game in graded
        if game[
            "ats_result"
        ] == "win"
    )

    losses = sum(
        1
        for game in graded
        if game[
            "ats_result"
        ] == "loss"
    )

    pushes = sum(
        1
        for game in graded
        if game[
            "ats_result"
        ] == "push"
    )

    decisions = (
        wins
        +
        losses
    )

    win_rate = (
        wins
        /
        decisions
        *
        100
        if decisions
        else None
    )

    return {
        "games":
            len(
                graded
            ),

        "wins":
            wins,

        "losses":
            losses,

        "pushes":
            pushes,

        "win_rate":
            (
                round(
                    win_rate,
                    2
                )
                if win_rate
                is not None
                else None
            ),
    }


def build_report(
    scored,
    yearly_reports
):

    predictions = [
        game[
            "projected_home_margin"
        ]
        for game in scored
    ]

    actuals = [
        game[
            "actual_home_margin"
        ]
        for game in scored
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

        games = [
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
            games
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
                mean(
                    [
                        game[
                            "absolute_edge"
                        ]
                        for game in games
                    ]
                ),
                3
            )
            if games
            else None
        )

        buckets.append(
            summary
        )

    # Candidate site categories.
    watch = [
        game
        for game in market_games
        if game[
            "absolute_edge"
        ] < 3.0
    ]

    edge = [
        game
        for game in market_games
        if (
            game[
                "absolute_edge"
            ] >= 3.0
            and
            game[
                "absolute_edge"
            ] < 7.0
        )
    ]

    high_conviction = [
        game
        for game in market_games
        if game[
            "absolute_edge"
        ] >= 7.0
    ]

    return {
        "methodology": {
            "years":
                f"{START_YEAR}-{END_YEAR}",

            "first_test_year":
                FIRST_TEST_YEAR,

            "time_safe":
                True,

            "minimum_prior_plays":
                MIN_PRIOR_PLAYS,

            "weights":
                WEIGHTS,

            "description":
                (
                    "Weekly play-level composite "
                    "ratings built before each "
                    "game using only completed "
                    "prior weeks."
                ),
        },

        "overall": {
            "games":
                len(
                    scored
                ),

            "market_games":
                len(
                    market_games
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
        },

        "ats_edge_buckets":
            buckets,

        "candidate_labels": {
            "watch_under_3":
                summarize_ats(
                    watch
                ),

            "edge_3_to_7":
                summarize_ats(
                    edge
                ),

            "high_conviction_7_plus":
                summarize_ats(
                    high_conviction
                ),
        },

        "year_by_year":
            yearly_reports,
    }


# =============================================================================
# PRINT REPORT
# =============================================================================

def print_report(
    report
):

    print("")
    print(
        "=" * 78
    )

    print(
        "COMPOSITE MODEL OUT-OF-SAMPLE BACKTEST"
    )

    print(
        "=" * 78
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
        f"   Games with spread: "
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
        "CANDIDATE SITE LABELS"
    )

    labels = report[
        "candidate_labels"
    ]

    for label, summary in labels.items():

        rate = (
            f"{summary['win_rate']:.2f}%"
            if summary[
                "win_rate"
            ]
            is not None
            else "N/A"
        )

        print(
            f"   {label:<28} "
            f"{summary['games']:>4} games | "
            f"{summary['wins']:>4}-"
            f"{summary['losses']:<4} | "
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
            f"scale "
            f"{year['rating_to_points']:.3f} | "
            f"HFA "
            f"{year['home_field']:.2f} | "
            f"MAE "
            f"{year['mae']:.2f}"
        )

    print("")
    print(
        "=" * 78
    )

    print(
        "NOTE:"
    )

    print(
        "This validates the historical "
        "in-season efficiency core. "
        "It does not yet reproduce the "
        "2026 preseason prior/portal/"
        "returning-production layer."
    )

    print(
        "=" * 78
    )


# =============================================================================
# SAVE
# =============================================================================

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
        "📊 CFB composite-model backtest"
    )

    print(
        f"   Historical seasons: "
        f"{START_YEAR}-{END_YEAR}"
    )

    print(
        f"   Out-of-sample testing: "
        f"{FIRST_TEST_YEAR}-{END_YEAR}"
    )

    print(
        f"   Minimum prior sample: "
        f"{MIN_PRIOR_PLAYS} plays"
    )

    records_by_year = {}

    for year in range(
        START_YEAR,
        END_YEAR + 1
    ):

        print("")
        print(
            "#" * 78
        )

        print(
            f"# {year}"
        )

        print(
            "#" * 78
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
        yearly_reports
    ) = run_out_of_sample(
        records_by_year
    )

    report = build_report(
        scored,
        yearly_reports
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
