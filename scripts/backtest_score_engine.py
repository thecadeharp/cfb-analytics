"""
CFB ANALYTICS
backtest_score_engine.py

Leakage-safe historical promotion test for the modular score engine.

Purpose
-------
Compare the existing legacy composite spread engine against a new deterministic
score engine built around:
    context-free team efficiency
    + opponent matchup interactions
    + possessions / game environment
    + home-field context
    = projected team scores, margin, total, and cover probability

DATA SAFETY
-----------
A game in Week N is represented only by information from Weeks < N.
No current-week or future-week plays are allowed into that game's snapshot.

OUT-OF-SAMPLE SAFETY
--------------------
Test seasons are 2023-2025.
For each test season, model coefficients are trained only on prior seasons.

This script is diagnostic only. It never modifies live 2026 projections.
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
FIRST_TEST_YEAR = 2023

OUTPUT_PATH = "data/score_engine_backtest.json"

MIN_PRIOR_PLAYS = 100
MIN_PRIOR_GAMES = 2
MIN_PASS_PLAYS = 30
MIN_RUSH_PLAYS = 30

DEFAULT_PLAYS_PER_POSSESSION = 6.1
RIDGE_LAMBDA = 2.0

LEGACY_WEIGHTS = {
    "net_epa": 0.30,
    "net_epa_pass": 0.15,
    "net_epa_rush": 0.15,
    "net_sr": 0.10,
    "def_havoc_created": 0.20,
    "off_havoc_allowed": 0.10,
}

SCORE_FEATURES = [
    "matchup_epa",
    "matchup_pass_epa",
    "matchup_rush_epa",
    "matchup_success_rate",
    "matchup_explosive_rate",
    "matchup_havoc",
    "expected_possessions",
    "offense_strength",
    "opponent_defense_strength",
    "strength_advantage",
    "strength_advantage_nonlinear",
    "advantage_x_possessions",
    "venue_indicator",
]

FAVORITE_BUCKETS = [
    (0.0, 3.0, "0-3"),
    (3.0, 7.0, "3-7"),
    (7.0, 14.0, "7-14"),
    (14.0, 21.0, "14-21"),
    (21.0, 28.0, "21-28"),
    (28.0, 40.0, "28-40"),
    (40.0, 999.0, "40+"),
]

PROBABILITY_BUCKETS = [
    (0.50, 0.55, "50-55%"),
    (0.55, 0.60, "55-60%"),
    (0.60, 0.65, "60-65%"),
    (0.65, 0.70, "65-70%"),
    (0.70, 1.01, "70%+"),
]


# =============================================================================
# API KEY / HELPERS
# =============================================================================

def clean_api_key(raw):
    if raw is None:
        return ""
    key = str(raw).strip()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
        key = key[1:-1].strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key.replace("\r", "").replace("\n", "").replace("\t", "").strip()


CFBD_API_KEY = clean_api_key(os.environ.get("CFBD_API_KEY", ""))


def first_value(data, *keys, default=None):
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)
    return default


def safe_number(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def mean(values):
    clean = [x for x in values if x is not None and math.isfinite(x)]
    return statistics.mean(clean) if clean else None


def mae(predictions, actuals):
    return mean([abs(p - a) for p, a in zip(predictions, actuals)])


def rmse(predictions, actuals):
    value = mean([(p - a) ** 2 for p, a in zip(predictions, actuals)])
    return math.sqrt(value) if value is not None else None


def normal_cdf(value):
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def cfbd_get(endpoint, params=None, required=True):
    if not CFBD_API_KEY:
        print("❌ CFBD_API_KEY missing.")
        sys.exit(1)

    for attempt in range(1, 4):
        try:
            response = requests.get(
                f"{CFBD_BASE}{endpoint}",
                headers={
                    "Authorization": f"Bearer {CFBD_API_KEY}",
                    "Accept": "application/json",
                },
                params=params,
                timeout=90,
            )
        except requests.RequestException as error:
            print(f"⚠ Request error {endpoint} ({attempt}/3): {error}")
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            if required:
                sys.exit(1)
            return []

        if response.status_code in (401, 403):
            print("❌ CFBD authentication/access failed.")
            sys.exit(1)

        if not response.ok:
            print(f"⚠ CFBD {endpoint}: HTTP {response.status_code}")
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            if required:
                sys.exit(1)
            return []

        try:
            return response.json()
        except ValueError:
            if required:
                print(f"❌ Invalid JSON from {endpoint}")
                sys.exit(1)
            return []

    return []


# =============================================================================
# GAME / LINE DATA
# =============================================================================

def get_games(year):
    raw = cfbd_get(
        "/games",
        {"year": year, "seasonType": "regular", "classification": "fbs"},
    )

    games = []

    for game in raw:
        home_class = str(
            first_value(game, "homeClassification", "home_classification", default="")
        ).lower()
        away_class = str(
            first_value(game, "awayClassification", "away_classification", default="")
        ).lower()

        if home_class != "fbs" or away_class != "fbs":
            continue

        if first_value(game, "completed", default=True) is False:
            continue

        game_id = first_value(game, "id")
        week = safe_number(first_value(game, "week"))
        home = first_value(game, "homeTeam", "home_team")
        away = first_value(game, "awayTeam", "away_team")
        home_points = safe_number(first_value(game, "homePoints", "home_points"))
        away_points = safe_number(first_value(game, "awayPoints", "away_points"))

        if (
            game_id is None
            or week is None
            or not home
            or not away
            or home_points is None
            or away_points is None
        ):
            continue

        games.append(
            {
                "id": int(game_id),
                "year": year,
                "week": int(week),
                "home": home,
                "away": away,
                "neutral": bool(
                    first_value(game, "neutralSite", "neutral_site", default=False)
                ),
                "home_points": home_points,
                "away_points": away_points,
                "actual_home_margin": home_points - away_points,
                "actual_total": home_points + away_points,
            }
        )

    games.sort(key=lambda g: (g["week"], g["id"]))
    print(f"📅 {year}: {len(games)} completed FBS-vs-FBS games")
    return games


def extract_spread(item):
    providers = item.get("lines") or []
    preferred = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "Consensus"]

    for preferred_name in preferred:
        for provider in providers:
            if str(provider.get("provider", "")).lower() == preferred_name.lower():
                spread = safe_number(provider.get("spread"))
                if spread is not None:
                    return spread

    spreads = [
        safe_number(provider.get("spread"))
        for provider in providers
        if safe_number(provider.get("spread")) is not None
    ]
    return statistics.median(spreads) if spreads else None


def get_lines(year):
    raw = cfbd_get(
        "/lines",
        {"year": year, "seasonType": "regular"},
        required=False,
    )

    lookup = {}

    for item in raw:
        game_id = first_value(item, "id", "gameId", "game_id")
        if game_id is None:
            continue
        spread = extract_spread(item)
        if spread is not None:
            lookup[int(game_id)] = spread

    print(f"💰 {year}: {len(lookup)} games with usable spreads")
    return lookup


# =============================================================================
# PLAY NORMALIZATION / CLASSIFICATION
# =============================================================================

def normalize_play(raw):
    return {
        "game_id": first_value(raw, "gameId", "game_id"),
        "drive_id": first_value(raw, "driveId", "drive_id"),
        "offense": first_value(raw, "offense"),
        "defense": first_value(raw, "defense"),
        "offense_score": safe_number(
            first_value(raw, "offenseScore", "offense_score", default=0), 0.0
        ),
        "defense_score": safe_number(
            first_value(raw, "defenseScore", "defense_score", default=0), 0.0
        ),
        "period": int(safe_number(first_value(raw, "period", default=1), 1)),
        "down": safe_number(first_value(raw, "down")),
        "distance": safe_number(first_value(raw, "distance")),
        "yards_gained": safe_number(
            first_value(raw, "yardsGained", "yards_gained", default=0), 0.0
        ),
        "play_type": str(first_value(raw, "playType", "play_type", default="")),
        "play_text": str(first_value(raw, "playText", "play_text", default="")),
        "ppa": safe_number(first_value(raw, "ppa")),
    }


def play_description(play):
    return f"{play.get('play_type', '')} {play.get('play_text', '')}".lower()


def is_pass_play(play):
    text = play_description(play)
    return any(term in text for term in ("pass", "sack", "interception"))


def is_rush_play(play):
    text = play_description(play)
    if "sack" in text:
        return False
    return any(term in text for term in ("rush", "run ", "rushed"))


def is_excluded_play(play):
    text = play_description(play)
    return any(
        term in text
        for term in (
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


def is_garbage_time(play):
    diff = abs(play["offense_score"] - play["defense_score"])
    if play["period"] >= 4 and diff >= 28:
        return True
    if play["period"] >= 3 and diff >= 38:
        return True
    return False


def is_success(play):
    yards = play["yards_gained"]
    distance = play["distance"]
    down = play["down"]

    if distance is None or distance <= 0 or down is None:
        return False

    down = int(down)

    if down == 1:
        return yards >= distance * 0.50
    if down == 2:
        return yards >= distance * 0.70
    if down in (3, 4):
        return yards >= distance
    return False


def is_explosive(play, pass_play, rush_play):
    if pass_play:
        return play["yards_gained"] >= 15
    if rush_play:
        return play["yards_gained"] >= 10
    return False


def is_havoc(play):
    text = play_description(play)
    return any(
        term in text
        for term in (
            "sack",
            "interception",
            "fumble",
            "tackle for loss",
            "tfl",
            "pass breakup",
            "broken up",
        )
    )


def get_week_plays(year, week, valid_game_ids):
    raw = cfbd_get(
        "/plays",
        {
            "year": year,
            "week": week,
            "seasonType": "regular",
            "classification": "fbs",
        },
    )

    plays = []

    for raw_play in raw:
        play = normalize_play(raw_play)

        try:
            game_id = int(play["game_id"])
        except (TypeError, ValueError):
            continue

        if game_id not in valid_game_ids:
            continue
        if not play["offense"] or not play["defense"]:
            continue
        if is_excluded_play(play) or is_garbage_time(play):
            continue
        if play["ppa"] is None:
            continue

        play["game_id"] = game_id
        plays.append(play)

    return plays


# =============================================================================
# HISTORIES / SNAPSHOTS
# =============================================================================

def empty_history():
    return {
        "games": set(),
        "drives": set(),
        "plays": 0,
        "epa_sum": 0.0,
        "epa_count": 0,
        "pass_epa_sum": 0.0,
        "pass_epa_count": 0,
        "rush_epa_sum": 0.0,
        "rush_epa_count": 0,
        "successes": 0,
        "success_plays": 0,
        "explosives": 0,
        "explosive_plays": 0,
        "havoc": 0,
        "havoc_plays": 0,
    }


def add_play(history, play, pass_play, rush_play, success, explosive, havoc):
    history["games"].add(play["game_id"])

    drive_id = play.get("drive_id")
    if drive_id is not None:
        history["drives"].add((play["game_id"], str(drive_id)))

    history["plays"] += 1
    history["epa_sum"] += play["ppa"]
    history["epa_count"] += 1

    if pass_play:
        history["pass_epa_sum"] += play["ppa"]
        history["pass_epa_count"] += 1

    if rush_play:
        history["rush_epa_sum"] += play["ppa"]
        history["rush_epa_count"] += 1

    history["success_plays"] += 1
    if success:
        history["successes"] += 1

    if pass_play or rush_play:
        history["explosive_plays"] += 1
        if explosive:
            history["explosives"] += 1

    history["havoc_plays"] += 1
    if havoc:
        history["havoc"] += 1


def process_week_plays(plays, offense_histories, defense_histories):
    for play in plays:
        pass_play = is_pass_play(play)
        rush_play = is_rush_play(play)
        success = is_success(play)
        explosive = is_explosive(play, pass_play, rush_play)
        havoc = is_havoc(play)

        add_play(
            offense_histories[play["offense"]],
            play,
            pass_play,
            rush_play,
            success,
            explosive,
            havoc,
        )
        add_play(
            defense_histories[play["defense"]],
            play,
            pass_play,
            rush_play,
            success,
            explosive,
            havoc,
        )


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def snapshot(history):
    games = len(history["games"])

    if history["plays"] < MIN_PRIOR_PLAYS or games < MIN_PRIOR_GAMES:
        return None

    drives = len(history["drives"])
    possessions_per_game = (
        drives / games
        if drives > 0
        else (history["plays"] / games) / DEFAULT_PLAYS_PER_POSSESSION
    )

    pass_epa = (
        ratio(history["pass_epa_sum"], history["pass_epa_count"])
        if history["pass_epa_count"] >= MIN_PASS_PLAYS
        else None
    )
    rush_epa = (
        ratio(history["rush_epa_sum"], history["rush_epa_count"])
        if history["rush_epa_count"] >= MIN_RUSH_PLAYS
        else None
    )

    return {
        "games": games,
        "plays": history["plays"],
        "epa": ratio(history["epa_sum"], history["epa_count"]),
        "pass_epa": pass_epa,
        "rush_epa": rush_epa,
        "success_rate": 100.0 * ratio(history["successes"], history["success_plays"]),
        "explosive_rate": 100.0
        * ratio(history["explosives"], history["explosive_plays"]),
        "havoc_rate": 100.0 * ratio(history["havoc"], history["havoc_plays"]),
        "possessions_per_game": possessions_per_game,
    }


def build_snapshots(teams, offense_histories, defense_histories):
    output = {}

    for team in teams:
        offense = snapshot(offense_histories[team])
        defense = snapshot(defense_histories[team])

        if offense is not None and defense is not None:
            output[team] = {
                "offense": offense,
                "defense": defense,
            }

    return output


def league_environment(snapshots):
    if len(snapshots) < 20:
        return None

    return {
        "epa": mean([x["offense"]["epa"] for x in snapshots.values()]),
        "pass_epa": mean([x["offense"]["pass_epa"] for x in snapshots.values()]),
        "rush_epa": mean([x["offense"]["rush_epa"] for x in snapshots.values()]),
        "success_rate": mean(
            [x["offense"]["success_rate"] for x in snapshots.values()]
        ),
        "explosive_rate": mean(
            [x["offense"]["explosive_rate"] for x in snapshots.values()]
        ),
        "havoc_rate": mean([x["defense"]["havoc_rate"] for x in snapshots.values()]),
        "possessions": mean(
            [x["offense"]["possessions_per_game"] for x in snapshots.values()]
        ),
    }


def fill(value, fallback):
    return fallback if value is None else value


def matchup_value(off_value, def_allowed_value, league_value):
    """
    Additive opponent adjustment around the league environment.

    Example:
        offense EPA 0.20
        defense EPA allowed 0.10
        league EPA 0.05
        => projected matchup EPA 0.25

    The model coefficients still decide how much that matchup value matters.
    """
    return fill(off_value, league_value) + fill(def_allowed_value, league_value) - league_value


def build_side_strengths(snapshots):
    """
    Context-free offense and defense strength scores.

    These are built only from the pregame snapshot and contain no opponent,
    venue, weather, travel, rest, or market information. Higher is better.
    They give the scoring model a stable team-strength backbone while the
    matchup features remain game-specific.
    """
    offense_components = {
        "epa": z_scores({t: d["offense"]["epa"] for t, d in snapshots.items()}),
        "pass_epa": z_scores({t: d["offense"]["pass_epa"] for t, d in snapshots.items()}),
        "rush_epa": z_scores({t: d["offense"]["rush_epa"] for t, d in snapshots.items()}),
        "success": z_scores({t: d["offense"]["success_rate"] for t, d in snapshots.items()}),
        "explosive": z_scores({t: d["offense"]["explosive_rate"] for t, d in snapshots.items()}),
        "havoc_allowed": z_scores({t: d["offense"]["havoc_rate"] for t, d in snapshots.items()}),
    }
    defense_components = {
        "epa_allowed": z_scores({t: d["defense"]["epa"] for t, d in snapshots.items()}),
        "pass_epa_allowed": z_scores({t: d["defense"]["pass_epa"] for t, d in snapshots.items()}),
        "rush_epa_allowed": z_scores({t: d["defense"]["rush_epa"] for t, d in snapshots.items()}),
        "success_allowed": z_scores({t: d["defense"]["success_rate"] for t, d in snapshots.items()}),
        "explosive_allowed": z_scores({t: d["defense"]["explosive_rate"] for t, d in snapshots.items()}),
        "havoc_created": z_scores({t: d["defense"]["havoc_rate"] for t, d in snapshots.items()}),
    }

    offense_strength = {}
    defense_strength = {}

    for team in snapshots:
        offense_strength[team] = (
            0.30 * offense_components["epa"][team]
            + 0.15 * offense_components["pass_epa"][team]
            + 0.10 * offense_components["rush_epa"][team]
            + 0.20 * offense_components["success"][team]
            + 0.15 * offense_components["explosive"][team]
            - 0.10 * offense_components["havoc_allowed"][team]
        )
        defense_strength[team] = (
            -0.30 * defense_components["epa_allowed"][team]
            - 0.15 * defense_components["pass_epa_allowed"][team]
            - 0.10 * defense_components["rush_epa_allowed"][team]
            - 0.20 * defense_components["success_allowed"][team]
            - 0.15 * defense_components["explosive_allowed"][team]
            + 0.10 * defense_components["havoc_created"][team]
        )

    return offense_strength, defense_strength


def side_features(
    team,
    opponent,
    snapshots,
    environment,
    offense_strengths,
    defense_strengths,
    venue_indicator,
):
    off = snapshots[team]["offense"]
    opp_def = snapshots[opponent]["defense"]

    expected_possessions = mean(
        [off["possessions_per_game"], snapshots[opponent]["offense"]["possessions_per_game"]]
    )
    expected_possessions = fill(expected_possessions, environment["possessions"])

    offense_strength = offense_strengths[team]
    opponent_defense_strength = defense_strengths[opponent]
    strength_advantage = offense_strength - opponent_defense_strength

    # Signed square preserves direction while allowing historically fitted
    # nonlinear separation in extreme strength mismatches. This is a football
    # strength interaction, not a favorite-size or market-line adjustment.
    nonlinear = math.copysign(strength_advantage ** 2, strength_advantage)

    return {
        "matchup_epa": matchup_value(off["epa"], opp_def["epa"], environment["epa"]),
        "matchup_pass_epa": matchup_value(
            off["pass_epa"], opp_def["pass_epa"], environment["pass_epa"]
        ),
        "matchup_rush_epa": matchup_value(
            off["rush_epa"], opp_def["rush_epa"], environment["rush_epa"]
        ),
        "matchup_success_rate": matchup_value(
            off["success_rate"], opp_def["success_rate"], environment["success_rate"]
        ),
        "matchup_explosive_rate": matchup_value(
            off["explosive_rate"], opp_def["explosive_rate"], environment["explosive_rate"]
        ),
        "matchup_havoc": (
            fill(off["havoc_rate"], environment["havoc_rate"])
            + fill(opp_def["havoc_rate"], environment["havoc_rate"])
            - environment["havoc_rate"]
        ),
        "expected_possessions": expected_possessions,
        "offense_strength": offense_strength,
        "opponent_defense_strength": opponent_defense_strength,
        "strength_advantage": strength_advantage,
        "strength_advantage_nonlinear": nonlinear,
        "advantage_x_possessions": strength_advantage * expected_possessions,
        "venue_indicator": venue_indicator,
    }


# =============================================================================
# LEGACY COMPOSITE SNAPSHOT
# =============================================================================

def z_scores(values):
    clean = [v for v in values.values() if v is not None]
    if len(clean) < 2:
        return {team: 0.0 for team in values}

    avg = statistics.mean(clean)
    std = statistics.pstdev(clean)

    if std == 0:
        return {team: 0.0 for team in values}

    return {
        team: ((value - avg) / std if value is not None else 0.0)
        for team, value in values.items()
    }


def legacy_ratings(snapshots):
    raw = {}

    for team, data in snapshots.items():
        off = data["offense"]
        defense = data["defense"]

        raw[team] = {
            "net_epa": off["epa"] - defense["epa"],
            "net_epa_pass": (
                off["pass_epa"] - defense["pass_epa"]
                if off["pass_epa"] is not None and defense["pass_epa"] is not None
                else None
            ),
            "net_epa_rush": (
                off["rush_epa"] - defense["rush_epa"]
                if off["rush_epa"] is not None and defense["rush_epa"] is not None
                else None
            ),
            "net_sr": off["success_rate"] - defense["success_rate"],
            "def_havoc_created": defense["havoc_rate"],
            "off_havoc_allowed": off["havoc_rate"],
        }

    component_z = {
        component: z_scores(
            {team: values.get(component) for team, values in raw.items()}
        )
        for component in LEGACY_WEIGHTS
    }

    ratings = {}

    for team in raw:
        rating = 0.0
        for component, weight in LEGACY_WEIGHTS.items():
            value = component_z[component][team]
            if component == "off_havoc_allowed":
                value *= -1.0
            rating += value * weight
        ratings[team] = rating

    return ratings


# =============================================================================
# TIME-SAFE RECORD CREATION
# =============================================================================

def build_year_records(year, games, line_lookup):
    teams = sorted({g["home"] for g in games} | {g["away"] for g in games})

    offense_histories = defaultdict(empty_history)
    defense_histories = defaultdict(empty_history)

    records = []
    weeks = sorted({g["week"] for g in games})

    print(f"🧠 Building leakage-safe {year} snapshots...")

    for week in weeks:
        week_games = [g for g in games if g["week"] == week]

        # PRE-GAME snapshot: only Weeks < current week exist here.
        snapshots = build_snapshots(teams, offense_histories, defense_histories)
        environment = league_environment(snapshots)
        ratings = legacy_ratings(snapshots) if environment is not None else {}
        if environment is not None:
            offense_strengths, defense_strengths = build_side_strengths(snapshots)
        else:
            offense_strengths, defense_strengths = {}, {}

        usable = 0

        if environment is not None:
            for game in week_games:
                if game["home"] not in snapshots or game["away"] not in snapshots:
                    continue
                if game["home"] not in ratings or game["away"] not in ratings:
                    continue

                home_venue = 0.0 if game["neutral"] else 1.0
                away_venue = 0.0 if game["neutral"] else -1.0

                home_features = side_features(
                    game["home"],
                    game["away"],
                    snapshots,
                    environment,
                    offense_strengths,
                    defense_strengths,
                    home_venue,
                )
                away_features = side_features(
                    game["away"],
                    game["home"],
                    snapshots,
                    environment,
                    offense_strengths,
                    defense_strengths,
                    away_venue,
                )

                records.append(
                    {
                        "game_id": game["id"],
                        "year": year,
                        "week": week,
                        "home": game["home"],
                        "away": game["away"],
                        "neutral": game["neutral"],
                        "home_points": game["home_points"],
                        "away_points": game["away_points"],
                        "actual_home_margin": game["actual_home_margin"],
                        "actual_total": game["actual_total"],
                        "market_home_spread": line_lookup.get(game["id"]),
                        "legacy_rating_diff": ratings[game["home"]]
                        - ratings[game["away"]],
                        "home_features": home_features,
                        "away_features": away_features,
                    }
                )
                usable += 1

        valid_ids = {g["id"] for g in week_games}
        plays = get_week_plays(year, week, valid_ids)

        # CURRENT week becomes available only AFTER predictions are recorded.
        process_week_plays(plays, offense_histories, defense_histories)

        print(
            f"   Week {week:>2}: {usable:>3} usable pregame matchups"
            f" | {len(plays):>5} qualifying plays"
        )

    print(f"   Total usable {year}: {len(records)}")
    return records


# =============================================================================
# LINEAR ALGEBRA / MODEL FITTING
# =============================================================================

def solve_linear_system(matrix, vector):
    n = len(vector)
    augmented = [list(matrix[i]) + [vector[i]] for i in range(n)]

    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-10:
            raise ValueError("Singular calibration matrix.")

        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]

        divisor = augmented[col][col]
        augmented[col] = [x / divisor for x in augmented[col]]

        for row in range(n):
            if row == col:
                continue
            factor = augmented[row][col]
            if abs(factor) < 1e-15:
                continue
            augmented[row] = [
                a - factor * b
                for a, b in zip(augmented[row], augmented[col])
            ]

    return [augmented[i][-1] for i in range(n)]


def fit_ridge_score_model(training_records):
    rows = []
    targets = []

    for record in training_records:
        for side in ("home", "away"):
            features = record[f"{side}_features"]
            rows.append([features[name] for name in SCORE_FEATURES])
            targets.append(record[f"{side}_points"])

    means = [statistics.mean([row[i] for row in rows]) for i in range(len(SCORE_FEATURES))]
    stds = []
    for i in range(len(SCORE_FEATURES)):
        std = statistics.pstdev([row[i] for row in rows])
        stds.append(std if std > 1e-9 else 1.0)

    standardized = [
        [1.0] + [(row[i] - means[i]) / stds[i] for i in range(len(SCORE_FEATURES))]
        for row in rows
    ]

    p = len(standardized[0])
    xtx = [[0.0 for _ in range(p)] for _ in range(p)]
    xty = [0.0 for _ in range(p)]

    for row, target in zip(standardized, targets):
        for i in range(p):
            xty[i] += row[i] * target
            for j in range(p):
                xtx[i][j] += row[i] * row[j]

    # Ridge only on slopes, never the intercept.
    for i in range(1, p):
        xtx[i][i] += RIDGE_LAMBDA

    coefficients = solve_linear_system(xtx, xty)

    residuals = []
    for row, target in zip(standardized, targets):
        prediction = sum(c * x for c, x in zip(coefficients, row))
        residuals.append(target - prediction)

    return {
        "means": means,
        "stds": stds,
        "coefficients": coefficients,
        "score_residual_std": statistics.pstdev(residuals),
    }


def predict_score(model, features):
    row = [1.0] + [
        (features[name] - model["means"][i]) / model["stds"][i]
        for i, name in enumerate(SCORE_FEATURES)
    ]
    return max(0.0, sum(c * x for c, x in zip(model["coefficients"], row)))


def fit_legacy_margin_model(training_records):
    # y = beta * rating_diff + HFA * home_indicator
    sum_xx = sum_xh = sum_hh = sum_xy = sum_hy = 0.0

    for record in training_records:
        x = record["legacy_rating_diff"]
        h = 0.0 if record["neutral"] else 1.0
        y = record["actual_home_margin"]

        sum_xx += x * x
        sum_xh += x * h
        sum_hh += h * h
        sum_xy += x * y
        sum_hy += h * y

    determinant = sum_xx * sum_hh - sum_xh * sum_xh
    if abs(determinant) < 1e-9:
        raise ValueError("Legacy calibration matrix is singular.")

    beta = (sum_xy * sum_hh - sum_hy * sum_xh) / determinant
    hfa = (sum_hy * sum_xx - sum_xy * sum_xh) / determinant

    predictions = [
        beta * r["legacy_rating_diff"] + (0.0 if r["neutral"] else hfa)
        for r in training_records
    ]
    actuals = [r["actual_home_margin"] for r in training_records]
    residual_std = statistics.pstdev(
        [a - p for a, p in zip(actuals, predictions)]
    )

    average_total = statistics.mean([r["actual_total"] for r in training_records])

    return {
        "rating_to_points": beta,
        "home_field": hfa,
        "margin_residual_std": residual_std,
        "average_total": average_total,
    }


# =============================================================================
# EVALUATION
# =============================================================================

def market_expected_margin(home_spread):
    return -home_spread


def cover_probability(projected_margin, market_margin, residual_std):
    if residual_std <= 1e-9:
        return 0.5

    edge = projected_margin - market_margin
    home_cover_probability = normal_cdf(edge / residual_std)

    if home_cover_probability >= 0.5:
        return home_cover_probability, "home"

    return 1.0 - home_cover_probability, "away"


def side_cover_result(record, chosen_side):
    spread = record.get("market_home_spread")
    if spread is None:
        return None

    home_cover_margin = record["actual_home_margin"] + spread

    if abs(home_cover_margin) < 1e-9:
        return None

    if chosen_side == "home":
        return 1 if home_cover_margin > 0 else 0

    return 1 if home_cover_margin < 0 else 0


def optimize_probability_scale(training_records, margin_predictor, base_std):
    """
    Fit a conservative uncertainty multiplier using only prior training games.
    This calibrates probabilities, not projected margins. It never uses the
    test season and never feeds market information back into team ratings.
    """
    market_games = [r for r in training_records if r.get("market_home_spread") is not None]
    if len(market_games) < 100 or base_std <= 1e-9:
        return 1.0

    best_scale = 1.0
    best_brier = None

    for step in range(20, 81):
        scale = step / 20.0  # 1.00 through 4.00
        errors = []

        for record in market_games:
            projected = margin_predictor(record)
            market_margin = market_expected_margin(record["market_home_spread"])
            edge = projected - market_margin
            home_prob = normal_cdf(edge / (base_std * scale))
            actual_home_cover = 1.0 if (record["actual_home_margin"] + record["market_home_spread"]) > 0 else 0.0
            if abs(record["actual_home_margin"] + record["market_home_spread"]) < 1e-9:
                continue
            errors.append((home_prob - actual_home_cover) ** 2)

        if not errors:
            continue

        brier = statistics.mean(errors)
        if best_brier is None or brier < best_brier:
            best_brier = brier
            best_scale = scale

    return best_scale


def score_test_year(test_year, training, testing):
    score_model = fit_ridge_score_model(training)
    legacy_model = fit_legacy_margin_model(training)

    # Estimate modular margin uncertainty from TRAINING residuals only.
    modular_training_margin_residuals = []
    for record in training:
        hp = predict_score(score_model, record["home_features"])
        ap = predict_score(score_model, record["away_features"])
        modular_training_margin_residuals.append(
            record["actual_home_margin"] - (hp - ap)
        )

    modular_margin_std = statistics.pstdev(modular_training_margin_residuals)

    def modular_training_predictor(record):
        return (
            predict_score(score_model, record["home_features"])
            - predict_score(score_model, record["away_features"])
        )

    def legacy_training_predictor(record):
        return (
            legacy_model["rating_to_points"] * record["legacy_rating_diff"]
            + (0.0 if record["neutral"] else legacy_model["home_field"])
        )

    modular_probability_scale = optimize_probability_scale(
        training, modular_training_predictor, modular_margin_std
    )
    legacy_probability_scale = optimize_probability_scale(
        training, legacy_training_predictor, legacy_model["margin_residual_std"]
    )

    scored = []

    for record in testing:
        modular_home = predict_score(score_model, record["home_features"])
        modular_away = predict_score(score_model, record["away_features"])
        modular_margin = modular_home - modular_away
        modular_total = modular_home + modular_away

        legacy_margin = (
            legacy_model["rating_to_points"] * record["legacy_rating_diff"]
            + (0.0 if record["neutral"] else legacy_model["home_field"])
        )

        # Legacy did not independently predict team scores. For apples-to-apples
        # score/total diagnostics, reconstruct its implied scores around the
        # prior-training average total.
        legacy_total = legacy_model["average_total"]
        legacy_home = max(0.0, (legacy_total + legacy_margin) / 2.0)
        legacy_away = max(0.0, (legacy_total - legacy_margin) / 2.0)

        output = dict(record)
        output.update(
            {
                "modular_home_score": modular_home,
                "modular_away_score": modular_away,
                "modular_margin": modular_margin,
                "modular_total": modular_total,
                "legacy_home_score": legacy_home,
                "legacy_away_score": legacy_away,
                "legacy_margin": legacy_margin,
                "legacy_total": legacy_total,
            }
        )

        spread = record.get("market_home_spread")
        if spread is not None:
            market_margin = market_expected_margin(spread)

            mod_prob, mod_side = cover_probability(
                modular_margin,
                market_margin,
                modular_margin_std * modular_probability_scale,
            )
            leg_prob, leg_side = cover_probability(
                legacy_margin,
                market_margin,
                legacy_model["margin_residual_std"] * legacy_probability_scale,
            )

            output.update(
                {
                    "market_expected_home_margin": market_margin,
                    "market_favorite_size": abs(market_margin),
                    "modular_cover_probability": mod_prob,
                    "modular_cover_side": mod_side,
                    "modular_cover_result": side_cover_result(output, mod_side),
                    "legacy_cover_probability": leg_prob,
                    "legacy_cover_side": leg_side,
                    "legacy_cover_result": side_cover_result(output, leg_side),
                }
            )

        scored.append(output)

    return scored, {
        "year": test_year,
        "training_games": len(training),
        "test_games": len(testing),
        "modular_margin_residual_std": modular_margin_std,
        "legacy_margin_residual_std": legacy_model["margin_residual_std"],
        "modular_probability_scale": modular_probability_scale,
        "legacy_probability_scale": legacy_probability_scale,
        "legacy_rating_to_points": legacy_model["rating_to_points"],
        "legacy_home_field": legacy_model["home_field"],
        "legacy_average_total": legacy_model["average_total"],
        "score_coefficients": {
            "intercept": score_model["coefficients"][0],
            **{
                name: score_model["coefficients"][i + 1]
                for i, name in enumerate(SCORE_FEATURES)
            },
        },
    }


def score_mae(games, prefix):
    predictions = []
    actuals = []

    for game in games:
        predictions.extend(
            [game[f"{prefix}_home_score"], game[f"{prefix}_away_score"]]
        )
        actuals.extend([game["home_points"], game["away_points"]])

    return mae(predictions, actuals)


def summary_metrics(games, prefix):
    margins = [g[f"{prefix}_margin"] for g in games]
    actual_margins = [g["actual_home_margin"] for g in games]
    totals = [g[f"{prefix}_total"] for g in games]
    actual_totals = [g["actual_total"] for g in games]

    return {
        "games": len(games),
        "score_mae": score_mae(games, prefix),
        "margin_mae": mae(margins, actual_margins),
        "margin_rmse": rmse(margins, actual_margins),
        "total_mae": mae(totals, actual_totals),
        "margin_bias": mean(
            [prediction - actual for prediction, actual in zip(margins, actual_margins)]
        ),
        "total_bias": mean(
            [prediction - actual for prediction, actual in zip(totals, actual_totals)]
        ),
    }


def favorite_size_report(games):
    market_games = [
        g for g in games if g.get("market_favorite_size") is not None
    ]

    output = []

    for low, high, label in FAVORITE_BUCKETS:
        bucket = [
            g
            for g in market_games
            if g["market_favorite_size"] >= low
            and g["market_favorite_size"] < high
        ]

        if not bucket:
            output.append(
                {
                    "range": label,
                    "games": 0,
                    "legacy_mae": None,
                    "modular_mae": None,
                    "legacy_bias": None,
                    "modular_bias": None,
                }
            )
            continue

        output.append(
            {
                "range": label,
                "games": len(bucket),
                "legacy_mae": mae(
                    [g["legacy_margin"] for g in bucket],
                    [g["actual_home_margin"] for g in bucket],
                ),
                "modular_mae": mae(
                    [g["modular_margin"] for g in bucket],
                    [g["actual_home_margin"] for g in bucket],
                ),
                "legacy_bias": mean(
                    [
                        g["legacy_margin"] - g["actual_home_margin"]
                        for g in bucket
                    ]
                ),
                "modular_bias": mean(
                    [
                        g["modular_margin"] - g["actual_home_margin"]
                        for g in bucket
                    ]
                ),
            }
        )

    return output


def probability_calibration(games, prefix):
    probability_key = f"{prefix}_cover_probability"
    result_key = f"{prefix}_cover_result"

    usable = [
        g
        for g in games
        if g.get(probability_key) is not None
        and g.get(result_key) is not None
    ]

    buckets = []
    weighted_error_numerator = 0.0
    weighted_count = 0

    for low, high, label in PROBABILITY_BUCKETS:
        bucket = [
            g
            for g in usable
            if g[probability_key] >= low and g[probability_key] < high
        ]

        if not bucket:
            buckets.append(
                {
                    "range": label,
                    "games": 0,
                    "average_predicted": None,
                    "actual_cover_rate": None,
                    "calibration_error": None,
                }
            )
            continue

        predicted = mean([g[probability_key] for g in bucket])
        actual = mean([g[result_key] for g in bucket])
        error = abs(predicted - actual)

        weighted_error_numerator += error * len(bucket)
        weighted_count += len(bucket)

        buckets.append(
            {
                "range": label,
                "games": len(bucket),
                "average_predicted": predicted,
                "actual_cover_rate": actual,
                "calibration_error": error,
            }
        )

    return {
        "games": len(usable),
        "weighted_binned_error": (
            weighted_error_numerator / weighted_count if weighted_count else None
        ),
        "buckets": buckets,
    }


def round_values(value):
    if isinstance(value, dict):
        return {k: round_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [round_values(v) for v in value]
    if isinstance(value, float):
        return round(value, 4)
    return value


def build_promotion_matrix(scored):
    legacy = summary_metrics(scored, "legacy")
    modular = summary_metrics(scored, "modular")

    thresholds = {
        "score_mae": 6.8,
        "margin_mae": 9.8,
        "margin_rmse": 13.0,
        "total_mae": 9.5,
        "probability_calibration_error": 0.02,
    }

    modular_probability = probability_calibration(scored, "modular")
    legacy_probability = probability_calibration(scored, "legacy")

    # "Stable across favorite buckets" is a diagnostic, not a single magic
    # threshold. Report max/min bucket MAE spread where n >= 25.
    favorite_report = favorite_size_report(scored)
    stable_buckets = [
        b for b in favorite_report if b["games"] >= 25 and b["modular_mae"] is not None
    ]
    favorite_mae_range = (
        max(b["modular_mae"] for b in stable_buckets)
        - min(b["modular_mae"] for b in stable_buckets)
        if len(stable_buckets) >= 2
        else None
    )

    gates = {
        "beats_legacy_margin_rmse": modular["margin_rmse"] < legacy["margin_rmse"],
        "beats_legacy_margin_mae": modular["margin_mae"] < legacy["margin_mae"],
        "score_mae_under_target": modular["score_mae"] < thresholds["score_mae"],
        "margin_mae_under_target": modular["margin_mae"] < thresholds["margin_mae"],
        "margin_rmse_under_target": modular["margin_rmse"] < thresholds["margin_rmse"],
        "total_mae_under_target": modular["total_mae"] < thresholds["total_mae"],
        "probability_calibration_under_target": (
            modular_probability["weighted_binned_error"] is not None
            and modular_probability["weighted_binned_error"]
            < thresholds["probability_calibration_error"]
        ),
    }

    # Promotion is deliberately strict on the two most important production
    # requirements: margin accuracy and probability calibration must improve.
    # Numerical benchmark misses remain visible rather than being hidden.
    promote = (
        gates["beats_legacy_margin_rmse"]
        and gates["beats_legacy_margin_mae"]
        and (
            modular_probability["weighted_binned_error"] is not None
            and legacy_probability["weighted_binned_error"] is not None
            and modular_probability["weighted_binned_error"]
            < legacy_probability["weighted_binned_error"]
        )
    )

    return {
        "targets": thresholds,
        "legacy": legacy,
        "modular": modular,
        "favorite_size_calibration": favorite_report,
        "favorite_bucket_mae_range": favorite_mae_range,
        "legacy_probability_calibration": legacy_probability,
        "modular_probability_calibration": modular_probability,
        "gates": gates,
        "promotion_recommendation": "PROMOTE" if promote else "HOLD",
        "promotion_rule": (
            "PROMOTE only if modular margin MAE and RMSE both beat legacy and "
            "modular probability calibration error also beats legacy. Absolute "
            "benchmarks are reported separately and are not silently relaxed."
        ),
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("")
    print("=" * 78)
    print("CFB MODULAR SCORE ENGINE — LEAKAGE-SAFE PROMOTION BACKTEST")
    print("=" * 78)
    print(f"Historical build: {START_YEAR}-{END_YEAR}")
    print(f"Out-of-sample test: {FIRST_TEST_YEAR}-{END_YEAR}")
    print("Week N uses only Weeks < N.")
    print("")

    records_by_year = {}

    for year in range(START_YEAR, END_YEAR + 1):
        print("#" * 78)
        print(f"# {year}")
        games = get_games(year)
        lines = get_lines(year)
        records_by_year[year] = build_year_records(year, games, lines)

    all_scored = []
    year_reports = []

    for test_year in range(FIRST_TEST_YEAR, END_YEAR + 1):
        training = []
        for year in range(START_YEAR, test_year):
            training.extend(records_by_year.get(year, []))

        testing = records_by_year.get(test_year, [])

        if len(training) < 300 or len(testing) < 50:
            print(f"⚠ Skipping {test_year}: insufficient training/testing sample.")
            continue

        scored, model_info = score_test_year(test_year, training, testing)
        all_scored.extend(scored)

        legacy_metrics = summary_metrics(scored, "legacy")
        modular_metrics = summary_metrics(scored, "modular")

        year_reports.append(
            {
                "year": test_year,
                "model_info": model_info,
                "legacy": legacy_metrics,
                "modular": modular_metrics,
            }
        )

        print("")
        print(f"▶ OUT-OF-SAMPLE {test_year}")
        print(
            f"   Legacy  margin MAE/RMSE: "
            f"{legacy_metrics['margin_mae']:.2f} / {legacy_metrics['margin_rmse']:.2f}"
        )
        print(
            f"   Modular margin MAE/RMSE: "
            f"{modular_metrics['margin_mae']:.2f} / {modular_metrics['margin_rmse']:.2f}"
        )
        print(
            f"   Modular score MAE: {modular_metrics['score_mae']:.2f} | "
            f"total MAE: {modular_metrics['total_mae']:.2f}"
        )

    if not all_scored:
        print("❌ No out-of-sample games scored.")
        sys.exit(1)

    promotion = build_promotion_matrix(all_scored)

    output = round_values(
        {
            "meta": {
                "type": "v2_scoring_promotion_backtest_v1_1",
                "historical_years": f"{START_YEAR}-{END_YEAR}",
                "test_years": f"{FIRST_TEST_YEAR}-{END_YEAR}",
                "leakage_safe": True,
                "week_rule": "Week N predicted using only data from Weeks < N",
                "deterministic": True,
                "score_features": SCORE_FEATURES,
                "ridge_lambda": RIDGE_LAMBDA,
                "architecture": "context-free strength backbone + nonlinear matchup interaction + symmetric venue + probability shrinkage",
            },
            "promotion_matrix": promotion,
            "year_by_year": year_reports,
            "games": all_scored,
        }
    )

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as file:
        json.dump(output, file, indent=2)

    print("")
    print("=" * 78)
    print("PROMOTION MATRIX")
    print("=" * 78)

    legacy = promotion["legacy"]
    modular = promotion["modular"]

    print(
        f"Score MAE       | Legacy {legacy['score_mae']:.2f} | "
        f"Modular {modular['score_mae']:.2f} | target < 6.80"
    )
    print(
        f"Margin MAE      | Legacy {legacy['margin_mae']:.2f} | "
        f"Modular {modular['margin_mae']:.2f} | target < 9.80"
    )
    print(
        f"Margin RMSE     | Legacy {legacy['margin_rmse']:.2f} | "
        f"Modular {modular['margin_rmse']:.2f} | target < 13.00"
    )
    print(
        f"Total MAE       | Legacy {legacy['total_mae']:.2f} | "
        f"Modular {modular['total_mae']:.2f} | target < 9.50"
    )

    mod_cal = promotion["modular_probability_calibration"][
        "weighted_binned_error"
    ]
    leg_cal = promotion["legacy_probability_calibration"][
        "weighted_binned_error"
    ]

    print(
        "Prob calibration | "
        f"Legacy {(leg_cal * 100):.2f}% | "
        f"Modular {(mod_cal * 100):.2f}% | target < 2.00%"
        if leg_cal is not None and mod_cal is not None
        else "Prob calibration | insufficient market sample"
    )

    print("")
    print(f"DECISION: {promotion['promotion_recommendation']}")
    print(f"💾 Saved {OUTPUT_PATH}")
    print("=" * 78)


if __name__ == "__main__":
    main()
