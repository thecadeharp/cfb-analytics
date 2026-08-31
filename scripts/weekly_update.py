"""
CFB ANALYTICS
weekly_update.py

Updates the live 2026 team metrics used by the projection model.

What this script does:
- Securely reads CFBD_API_KEY from GitHub Secrets
- Validates CFBD authentication
- Detects the most recently completed 2026 week
- Pulls play-by-play
- Calculates EPA, success rate, explosiveness and havoc
- Blends live 2026 performance into the preseason baseline
- Updates data/cfb_metrics.json

IMPORTANT:
If CFBD authentication or a required API request fails, this script
FAILS the GitHub Action instead of silently publishing bad data.
"""

import json
import os
import sys
import time
from datetime import datetime

import pandas as pd
import requests


# =============================================================================
# CONFIG
# =============================================================================

YEAR = 2026

BASE_URL = "https://api.collegefootballdata.com"

DATA_PATH = "data/cfb_metrics.json"

WEIGHTS = {
    "net_epa": 0.30,
    "net_epa_pass": 0.15,
    "net_epa_rush": 0.15,
    "net_sr": 0.10,
    "def_havoc_created": 0.20,
    "off_havoc_allowed": 0.10,
}


# =============================================================================
# API KEY
# =============================================================================

def clean_api_key(raw_key):
    """
    Clean accidental whitespace, quotes, or a pasted 'Bearer ' prefix.

    GitHub Secret should ideally contain ONLY the raw API key,
    but this makes the pipeline more forgiving.
    """

    if raw_key is None:
        return ""

    key = str(raw_key).strip()

    # Remove accidental wrapping quotes.
    if (
        len(key) >= 2
        and key[0] == key[-1]
        and key[0] in ("'", '"')
    ):
        key = key[1:-1].strip()

    # Remove accidental "Bearer " prefix.
    if key.lower().startswith("bearer "):
        key = key[7:].strip()

    # Remove carriage returns / newlines.
    key = key.replace("\r", "").replace("\n", "").strip()

    return key


API_KEY = clean_api_key(
    os.environ.get("CFBD_API_KEY", "")
)


if not API_KEY:
    print("❌ CFBD_API_KEY is missing.")
    print("   GitHub → Settings → Secrets and variables → Actions")
    print("   Make sure CFBD_API_KEY contains the raw API key.")
    sys.exit(1)


HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json",
}


# =============================================================================
# GENERAL HELPERS
# =============================================================================

def first_value(data, *keys, default=None):
    """
    Get the first available field from old/new CFBD field names.

    Example:
        first_value(game, "homePoints", "home_points")
    """

    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)

    return default


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default

        return float(value)

    except (TypeError, ValueError):
        return default


def z_score(series):
    s = series.copy().astype(float)

    mean = s.mean()
    std = s.std()

    if std == 0 or pd.isna(std):
        return pd.Series(
            0.0,
            index=series.index
        )

    return (s - mean) / std


# =============================================================================
# CFBD REQUEST HANDLER
# =============================================================================

def cfbd(endpoint, params=None, required=True):
    """
    Make a CFBD request.

    Behavior:
    - 401 / 403 → immediately fail workflow
    - repeated request failure on required data → fail workflow
    - successful empty response → return []
    """

    url = f"{BASE_URL}{endpoint}"

    for attempt in range(1, 4):

        try:
            response = requests.get(
                url,
                headers=HEADERS,
                params=params,
                timeout=45
            )

        except requests.RequestException as error:

            print(
                f"⚠ CFBD request error "
                f"{endpoint} "
                f"(attempt {attempt}/3): {error}"
            )

            if attempt < 3:
                time.sleep(2)
                continue

            if required:
                print(
                    f"❌ Required CFBD request failed: "
                    f"{endpoint}"
                )
                sys.exit(1)

            return []

        # ---------------------------------------------------------------------
        # AUTH FAILURE
        # ---------------------------------------------------------------------

        if response.status_code in (401, 403):

            print("")
            print("❌ CFBD AUTHENTICATION FAILED")
            print(
                f"   HTTP status: "
                f"{response.status_code}"
            )

            print(
                "   Check the CFBD_API_KEY GitHub Secret."
            )

            print(
                "   The secret must contain ONLY "
                "the raw API key."
            )

            try:
                print(
                    f"   CFBD response: "
                    f"{response.text[:300]}"
                )
            except Exception:
                pass

            sys.exit(1)

        # ---------------------------------------------------------------------
        # OTHER HTTP FAILURE
        # ---------------------------------------------------------------------

        if not response.ok:

            print(
                f"⚠ CFBD returned HTTP "
                f"{response.status_code} "
                f"for {endpoint}"
            )

            print(
                f"   Params: {params}"
            )

            try:
                print(
                    f"   Response: "
                    f"{response.text[:500]}"
                )
            except Exception:
                pass

            if attempt < 3:
                time.sleep(2)
                continue

            if required:
                print(
                    f"❌ Required CFBD request failed "
                    f"after 3 attempts: {endpoint}"
                )
                sys.exit(1)

            return []

        # ---------------------------------------------------------------------
        # JSON
        # ---------------------------------------------------------------------

        try:
            return response.json()

        except ValueError:

            print(
                f"⚠ CFBD returned invalid JSON "
                f"for {endpoint}"
            )

            if required:
                sys.exit(1)

            return []

    if required:
        sys.exit(1)

    return []


# =============================================================================
# API CONNECTION TEST
# =============================================================================

def validate_cfbd():
    """
    Make one lightweight real request before doing any heavy work.

    This prevents a malformed secret from producing a fake-success workflow.
    """

    print("")
    print("🔐 Validating CFBD connection...")

    test = cfbd(
        "/games",
        {
            "year": YEAR,
            "week": 1,
            "seasonType": "regular",
            "classification": "fbs",
        },
        required=True
    )

    if not isinstance(test, list):
        print(
            "❌ CFBD returned an unexpected response format."
        )
        sys.exit(1)

    print("✅ CFBD authentication successful")


# =============================================================================
# EXPECTED POINTS
# =============================================================================

EP_TABLE = {
    (1, 1): 1.62,
    (1, 2): 1.50,
    (1, 3): 1.35,
    (1, 4): 1.18,
    (1, 5): 1.00,
    (1, 6): 0.82,
    (1, 7): 0.65,
    (1, 8): 0.50,
    (1, 9): 0.38,
    (1, 10): 0.28,
    (1, 11): 0.18,
    (1, 12): 0.08,

    (2, 1): 2.10,
    (2, 2): 1.95,
    (2, 3): 1.75,
    (2, 4): 1.52,
    (2, 5): 1.28,
    (2, 6): 1.05,
    (2, 7): 0.83,
    (2, 8): 0.62,
    (2, 9): 0.44,
    (2, 10): 0.28,
    (2, 11): 0.14,
    (2, 12): -0.02,

    (3, 1): 2.85,
    (3, 2): 2.45,
    (3, 3): 2.05,
    (3, 4): 1.65,
    (3, 5): 1.28,
    (3, 6): 0.95,
    (3, 7): 0.65,
    (3, 8): 0.38,
    (3, 9): 0.14,
    (3, 10): -0.08,
    (3, 11): -0.28,
    (3, 12): -0.45,

    (4, 1): 1.20,
    (4, 2): 0.85,
    (4, 3): 0.50,
    (4, 4): 0.18,
    (4, 5): -0.15,
    (4, 6): -0.45,
    (4, 7): -0.72,
    (4, 8): -0.95,
    (4, 9): -1.15,
    (4, 10): -1.32,
    (4, 11): -1.48,
    (4, 12): -1.62,
}


YARD_LINE_ADJUSTMENT = {
    (1, 10): 3.5,
    (11, 20): 2.8,
    (21, 30): 2.2,
    (31, 40): 1.7,
    (41, 50): 1.2,
    (51, 60): 0.7,
    (61, 70): 0.3,
    (71, 80): -0.1,
    (81, 90): -0.5,
    (91, 100): -1.0,
}


def get_yard_adj(yards_to_goal):
    try:
        ytg = int(
            safe_float(
                yards_to_goal,
                50
            )
        )

    except Exception:
        ytg = 50

    ytg = max(1, min(99, ytg))

    for (low, high), adjustment in (
        YARD_LINE_ADJUSTMENT.items()
    ):
        if low <= ytg <= high:
            return adjustment

    return 0.0


def calc_ep(
    down,
    distance,
    yards_to_goal
):
    if pd.isna(down) or pd.isna(distance):
        return 0.0

    try:
        d = int(down)

        dist_bucket = min(
            12,
            max(
                1,
                int(float(distance))
            )
        )

    except Exception:
        return 0.0

    base = EP_TABLE.get(
        (d, dist_bucket),
        0.0
    )

    adjustment = get_yard_adj(
        yards_to_goal
    )

    return base + adjustment * 0.3


def calc_epa(play):

    try:
        ep_before = calc_ep(
            play.get("down"),
            play.get("distance"),
            play.get("yards_to_goal")
        )

        play_type = str(
            play.get("play_type", "")
        ).lower()

        yards_gained = safe_float(
            play.get("yards_gained"),
            0
        )

        if (
            "touchdown" in play_type
            or " td" in play_type
        ):
            ep_after = (
                -2.0
                if "safety" in play_type
                else 6.96
            )

        elif (
            "field goal" in play_type
            and "made" in play_type
        ):
            ep_after = 3.0

        elif (
            "field goal" in play_type
            and "missed" in play_type
        ):
            ep_after = -0.5

        elif (
            "interception" in play_type
            or "fumble" in play_type
        ):
            ep_after = (
                -ep_before - 1.5
            )

        elif "punt" in play_type:

            new_ytg = max(
                1,
                safe_float(
                    play.get("yards_to_goal"),
                    50
                )
                - yards_gained
                + 40
            )

            ep_after = -calc_ep(
                1,
                10,
                new_ytg
            )

        elif "sack" in play_type:

            new_dist = max(
                1,
                safe_float(
                    play.get("distance"),
                    10
                )
                - yards_gained
            )

            new_ytg = max(
                1,
                safe_float(
                    play.get("yards_to_goal"),
                    50
                )
                - yards_gained
            )

            ep_after = calc_ep(
                2,
                new_dist,
                new_ytg
            )

        else:

            distance = safe_float(
                play.get("distance"),
                10
            )

            new_ytg = max(
                1,
                safe_float(
                    play.get("yards_to_goal"),
                    50
                )
                - yards_gained
            )

            new_dist = max(
                1,
                distance - yards_gained
            )

            if yards_gained >= distance:

                ep_after = calc_ep(
                    1,
                    10,
                    new_ytg
                )

            else:

                next_down = (
                    int(
                        safe_float(
                            play.get("down"),
                            1
                        )
                    )
                    + 1
                )

                if next_down > 4:

                    ep_after = -calc_ep(
                        1,
                        10,
                        max(
                            1,
                            100 - new_ytg
                        )
                    )

                else:

                    ep_after = calc_ep(
                        next_down,
                        new_dist,
                        new_ytg
                    )

        return ep_after - ep_before

    except Exception:
        return 0.0


# =============================================================================
# PLAY NORMALIZATION
# =============================================================================

def normalize_play(raw):
    """
    Convert newer camelCase CFBD fields into the snake_case names
    our existing model expects.
    """

    return {
        **raw,

        "game_id": first_value(
            raw,
            "gameId",
            "game_id"
        ),

        "play_type": first_value(
            raw,
            "playType",
            "play_type",
            default=""
        ),

        "yards_gained": first_value(
            raw,
            "yardsGained",
            "yards_gained",
            default=0
        ),

        "yards_to_goal": first_value(
            raw,
            "yardsToGoal",
            "yards_to_goal",
            default=50
        ),

        "home_score": first_value(
            raw,
            "homeScore",
            "home_score",
            default=0
        ),

        "away_score": first_value(
            raw,
            "awayScore",
            "away_score",
            default=0
        ),

        "period": first_value(
            raw,
            "period",
            default=1
        ),

        "down": first_value(
            raw,
            "down"
        ),

        "distance": first_value(
            raw,
            "distance"
        ),

        "offense": first_value(
            raw,
            "offense"
        ),

        "defense": first_value(
            raw,
            "defense"
        ),
    }


# =============================================================================
# PLAY FILTERS
# =============================================================================

def is_garbage_time(play):

    try:
        period = int(
            safe_float(
                play.get("period"),
                1
            )
        )

        score_diff = abs(
            safe_float(
                play.get("home_score"),
                0
            )
            -
            safe_float(
                play.get("away_score"),
                0
            )
        )

        if period >= 4 and score_diff >= 28:
            return True

        if period >= 3 and score_diff >= 38:
            return True

        return False

    except Exception:
        return False


def is_success(row):

    try:
        yards = safe_float(
            row.get("yards_gained"),
            0
        )

        distance = safe_float(
            row.get("distance"),
            10
        )

        down = int(
            safe_float(
                row.get("down"),
                1
            )
        )

        if down == 1:
            return yards >= distance * 0.5

        if down == 2:
            return yards >= distance * 0.7

        return yards >= distance

    except Exception:
        return False


# =============================================================================
# TEAM METRICS
# =============================================================================

def team_metrics(
    plays_df,
    team,
    side="offense"
):
    column = (
        "offense"
        if side == "offense"
        else "defense"
    )

    team_plays = plays_df[
        plays_df[column] == team
    ]

    if len(team_plays) < 5:
        return {}

    pass_plays = team_plays[
        team_plays["is_pass"]
    ]

    rush_plays = team_plays[
        team_plays["is_rush"]
    ]

    def mean(series):
        if len(series) == 0:
            return 0.0

        return float(series.mean())

    return {
        "n_plays": len(team_plays),

        "epa_play":
            mean(team_plays["epa"]),

        "success_rate":
            mean(team_plays["success"]) * 100,

        "explosive_rate":
            mean(team_plays["explosive"]) * 100,

        "havoc_rate":
            mean(team_plays["havoc"]) * 100,

        "epa_pass": (
            mean(pass_plays["epa"])
            if len(pass_plays) > 3
            else 0.0
        ),

        "epa_rush": (
            mean(rush_plays["epa"])
            if len(rush_plays) > 3
            else 0.0
        ),

        "pass_sr": (
            mean(pass_plays["success"]) * 100
            if len(pass_plays) > 3
            else 0.0
        ),

        "rush_sr": (
            mean(rush_plays["success"]) * 100
            if len(rush_plays) > 3
            else 0.0
        ),

        "yds_play":
            mean(
                team_plays[
                    "yards_gained"
                ].abs()
            ),
    }


# =============================================================================
# MAIN
# =============================================================================

def main():

    print("=" * 70)
    print("🏈 CFB ANALYTICS — WEEKLY TEAM UPDATE")
    print("=" * 70)

    print(f"Season: {YEAR}")
    print(
        f"Timestamp: "
        f"{datetime.now().isoformat()}"
    )

    # -------------------------------------------------------------------------
    # TEST CONNECTION FIRST
    # -------------------------------------------------------------------------

    validate_cfbd()

    # -------------------------------------------------------------------------
    # LOAD EXISTING BASELINE
    # -------------------------------------------------------------------------

    print("")
    print(
        f"📂 Loading existing metrics from "
        f"{DATA_PATH}..."
    )

    try:
        with open(
            DATA_PATH,
            "r",
            encoding="utf-8"
        ) as file:
            existing = json.load(file)

        print(
            f"✅ Loaded data for "
            f"{len(existing.get('teams', {}))} teams"
        )

    except FileNotFoundError:

        print(
            "❌ Existing cfb_metrics.json "
            "was not found."
        )

        print(
            "   Refusing to overwrite the baseline "
            "with an empty dataset."
        )

        sys.exit(1)

    # -------------------------------------------------------------------------
    # DETECT COMPLETED WEEK
    # -------------------------------------------------------------------------

    print("")
    print("📅 Detecting completed weeks...")

    completed_week = 0

    games_by_week = {}

    # Include Week 0 because college football sometimes has it.
    for week in range(0, 17):

        games = cfbd(
            "/games",
            {
                "year": YEAR,
                "week": week,
                "seasonType": "regular",
                "classification": "fbs",
            },
            required=True
        )

        games_by_week[week] = games

        completed = []

        for game in games:

            home_points = first_value(
                game,
                "homePoints",
                "home_points"
            )

            away_points = first_value(
                game,
                "awayPoints",
                "away_points"
            )

            is_completed = first_value(
                game,
                "completed",
                default=None
            )

            if (
                is_completed is True
                or (
                    home_points is not None
                    and away_points is not None
                )
            ):
                completed.append(game)

        if completed:

            completed_week = max(
                completed_week,
                week
            )

            print(
                f"   Week {week}: "
                f"{len(completed)} completed games"
            )

    # -------------------------------------------------------------------------
    # NO COMPLETED FBS WEEK YET
    # -------------------------------------------------------------------------

    if completed_week == 0:

        week_zero_completed = []

        for game in games_by_week.get(
            0,
            []
        ):

            hp = first_value(
                game,
                "homePoints",
                "home_points"
            )

            ap = first_value(
                game,
                "awayPoints",
                "away_points"
            )

            if hp is not None and ap is not None:
                week_zero_completed.append(
                    game
                )

        if not week_zero_completed:

            print("")
            print(
                "ℹ️ No completed FBS games are "
                "available to blend yet."
            )

            print(
                "   Keeping the current preseason "
                "baseline unchanged."
            )

            print(
                "✅ CFBD connection is healthy."
            )

            return

    print("")
    print(
        f"✅ Most recent completed week: "
        f"{completed_week}"
    )

    # -------------------------------------------------------------------------
    # FBS TEAMS
    # -------------------------------------------------------------------------

    print("")
    print("🏫 Fetching FBS team list...")

    teams_data = cfbd(
        "/teams/fbs",
        {
            "year": YEAR
        },
        required=True
    )

    if not teams_data:
        print(
            "❌ CFBD returned zero FBS teams."
        )
        sys.exit(1)

    fbs_teams = set()

    team_conferences = {}

    for team in teams_data:

        school = first_value(
            team,
            "school"
        )

        if not school:
            continue

        fbs_teams.add(school)

        team_conferences[school] = (
            first_value(
                team,
                "conference",
                default="Ind"
            )
        )

    print(
        f"✅ FBS teams found: "
        f"{len(fbs_teams)}"
    )

    # -------------------------------------------------------------------------
    # GAME SCORE CONTEXT
    # -------------------------------------------------------------------------

    all_game_scores = {}

    for week in range(
        0,
        completed_week + 1
    ):

        games = games_by_week.get(week)

        if games is None:

            games = cfbd(
                "/games",
                {
                    "year": YEAR,
                    "week": week,
                    "seasonType": "regular",
                    "classification": "fbs",
                },
                required=True
            )

        for game in games:

            home_points = first_value(
                game,
                "homePoints",
                "home_points"
            )

            away_points = first_value(
                game,
                "awayPoints",
                "away_points"
            )

            if (
                home_points is None
                or away_points is None
            ):
                continue

            game_id = first_value(
                game,
                "id"
            )

            if game_id is None:
                continue

            all_game_scores[
                game_id
            ] = {
                "home": first_value(
                    game,
                    "homeTeam",
                    "home_team"
                ),

                "away": first_value(
                    game,
                    "awayTeam",
                    "away_team"
                ),

                "home_score":
                    home_points,

                "away_score":
                    away_points,
            }

    # -------------------------------------------------------------------------
    # PLAY BY PLAY
    # -------------------------------------------------------------------------

    print("")
    print(
        f"🎮 Fetching 2026 play-by-play "
        f"through Week {completed_week}..."
    )

    all_plays = []

    for week in range(
        0,
        completed_week + 1
    ):

        raw_plays = cfbd(
            "/plays",
            {
                "year": YEAR,
                "week": week,
                "seasonType": "regular",
                "classification": "fbs",
            },
            required=True
        )

        filtered = []

        for raw in raw_plays:

            play = normalize_play(raw)

            offense = play.get(
                "offense"
            )

            defense = play.get(
                "defense"
            )

            if offense not in fbs_teams:
                continue

            if defense not in fbs_teams:
                continue

            play_type = str(
                play.get(
                    "play_type",
                    ""
                )
            ).lower()

            if any(
                excluded in play_type
                for excluded in (
                    "kickoff",
                    "extra point",
                    "timeout",
                    "end of",
                    "coin toss",
                    "penalty",
                )
            ):
                continue

            game_id = play.get(
                "game_id"
            )

            if game_id in all_game_scores:

                score = all_game_scores[
                    game_id
                ]

                play[
                    "home_score"
                ] = score["home_score"]

                play[
                    "away_score"
                ] = score["away_score"]

            filtered.append(play)

        all_plays.extend(filtered)

        print(
            f"   Week {week}: "
            f"{len(filtered):,} qualifying plays"
        )

        time.sleep(0.25)

    print(
        f"   Total qualifying plays: "
        f"{len(all_plays):,}"
    )

    # -------------------------------------------------------------------------
    # NO PLAY DATA
    # -------------------------------------------------------------------------

    if not all_plays:

        print("")
        print(
            "ℹ️ CFBD returned no qualifying "
            "play-by-play yet."
        )

        print(
            "   Keeping existing preseason "
            "metrics unchanged."
        )

        return

    # -------------------------------------------------------------------------
    # BUILD DATAFRAME
    # -------------------------------------------------------------------------

    df = pd.DataFrame(
        all_plays
    )

    required_columns = [
        "play_type",
        "yards_gained",
        "offense",
        "defense",
    ]

    for column in required_columns:

        if column not in df.columns:

            print(
                f"❌ Required play field missing: "
                f"{column}"
            )

            print(
                "   CFBD response format may have changed."
            )

            sys.exit(1)

    df["yards_gained"] = pd.to_numeric(
        df["yards_gained"],
        errors="coerce"
    ).fillna(0)

    df["epa"] = df.apply(
        calc_epa,
        axis=1
    )

    df["garbage"] = df.apply(
        is_garbage_time,
        axis=1
    )

    play_types = (
        df["play_type"]
        .astype(str)
        .str.lower()
    )

    df["is_pass"] = play_types.str.contains(
        "pass|sack|interception",
        na=False
    )

    df["is_rush"] = play_types.str.contains(
        "rush|run",
        na=False
    )

    df["success"] = df.apply(
        is_success,
        axis=1
    )

    df["explosive"] = (
        (
            df["is_pass"]
            & (
                df["yards_gained"]
                >= 15
            )
        )
        |
        (
            df["is_rush"]
            & (
                df["yards_gained"]
                >= 10
            )
        )
    )

    df["havoc"] = play_types.str.contains(
        (
            "sack|interception|fumble|"
            "tackle for loss|tfl|"
            "pass breakup|pbu"
        ),
        na=False
    )

    clean = df[
        ~df["garbage"]
    ].copy()

    print(
        f"✅ Clean non-garbage plays: "
        f"{len(clean):,}"
    )

    # -------------------------------------------------------------------------
    # TEAM STATS
    # -------------------------------------------------------------------------

    team_stats_2026 = {}

    for team in sorted(
        fbs_teams
    ):

        offense = team_metrics(
            clean,
            team,
            "offense"
        )

        defense = team_metrics(
            clean,
            team,
            "defense"
        )

        if offense and defense:

            team_stats_2026[
                team
            ] = {
                "offense": offense,
                "defense": defense,
            }

    print(
        f"✅ Teams with qualifying live data: "
        f"{len(team_stats_2026)}"
    )

    # -------------------------------------------------------------------------
    # METRIC DATAFRAME
    # -------------------------------------------------------------------------

    rows = []

    for team, team_data in (
        team_stats_2026.items()
    ):

        offense = team_data[
            "offense"
        ]

        defense = team_data[
            "defense"
        ]

        rows.append({
            "team": team,

            "off_epa":
                offense.get(
                    "epa_play",
                    0
                ),

            "off_sr":
                offense.get(
                    "success_rate",
                    0
                ),

            "off_epa_pass":
                offense.get(
                    "epa_pass",
                    0
                ),

            "off_epa_rush":
                offense.get(
                    "epa_rush",
                    0
                ),

            "off_pass_sr":
                offense.get(
                    "pass_sr",
                    0
                ),

            "off_rush_sr":
                offense.get(
                    "rush_sr",
                    0
                ),

            "off_havoc_allowed":
                offense.get(
                    "havoc_rate",
                    0
                ),

            "off_expl":
                offense.get(
                    "explosive_rate",
                    0
                ),

            "def_epa":
                defense.get(
                    "epa_play",
                    0
                ),

            "def_sr":
                defense.get(
                    "success_rate",
                    0
                ),

            "def_epa_pass":
                defense.get(
                    "epa_pass",
                    0
                ),

            "def_epa_rush":
                defense.get(
                    "epa_rush",
                    0
                ),

            "def_pass_sr":
                defense.get(
                    "pass_sr",
                    0
                ),

            "def_rush_sr":
                defense.get(
                    "rush_sr",
                    0
                ),

            "def_havoc_created":
                defense.get(
                    "havoc_rate",
                    0
                ),

            "def_expl":
                defense.get(
                    "explosive_rate",
                    0
                ),
        })

    if not rows:

        print(
            "ℹ️ No teams have enough live "
            "plays to update ratings yet."
        )

        return

    mdf = (
        pd.DataFrame(rows)
        .set_index("team")
    )

    mdf["net_epa"] = (
        mdf["off_epa"]
        - mdf["def_epa"]
    )

    mdf["net_sr"] = (
        mdf["off_sr"]
        - mdf["def_sr"]
    )

    mdf["net_epa_pass"] = (
        mdf["off_epa_pass"]
        - mdf["def_epa_pass"]
    )

    mdf["net_epa_rush"] = (
        mdf["off_epa_rush"]
        - mdf["def_epa_rush"]
    )

    # -------------------------------------------------------------------------
    # POWER RATING
    # -------------------------------------------------------------------------

    z = pd.DataFrame(
        index=mdf.index
    )

    for column in WEIGHTS:

        if column in mdf.columns:
            series = mdf[column]

        else:
            series = pd.Series(
                0,
                index=mdf.index
            )

        # Less havoc allowed is better.
        if column == "off_havoc_allowed":
            series = -series

        z[column] = z_score(
            series
        )

    mdf["power_rating"] = sum(
        z[column] * weight
        for column, weight
        in WEIGHTS.items()
    )

    # -------------------------------------------------------------------------
    # RECORDS
    # -------------------------------------------------------------------------

    print("")
    print("📚 Fetching records and SP+ context...")

    records_data = cfbd(
        "/records",
        {
            "year": YEAR
        },
        required=True
    )

    records_2026 = {
        item.get("team"): item
        for item in records_data
        if item.get("team")
    }

    # 2025 SP+ is contextual / baseline support.
    sp_data = cfbd(
        "/ratings/sp",
        {
            "year": 2025
        },
        required=False
    )

    sp_lookup = {
        item.get("team"): item
        for item in sp_data
        if item.get("team")
    }

    # -------------------------------------------------------------------------
    # BLEND
    # -------------------------------------------------------------------------

    print("")
    print(
        "🔀 Blending preseason baseline "
        "with 2026 live performance..."
    )

    blend_weight = min(
        1.0,
        completed_week / 10
    )

    print(
        f"   Live 2026 data weight: "
        f"{blend_weight:.0%}"
    )

    output = {
        "meta": {
            "year": YEAR,

            "generated":
                datetime.now().isoformat(),

            "through_week":
                completed_week,

            "total_plays_2026":
                len(clean),

            "blend_weight":
                blend_weight,

            "type":
                "weekly_update",
        },

        "teams": {}
    }

    # -------------------------------------------------------------------------
    # BUILD FINAL TEAM OUTPUT
    # -------------------------------------------------------------------------

    for team in fbs_teams:

        baseline = (
            existing.get(
                "teams",
                {}
            )
            .get(
                team,
                {}
            )
        )

        live_row = (
            mdf.loc[team]
            if team in mdf.index
            else None
        )

        live_team_stats = (
            team_stats_2026.get(
                team,
                {}
            )
        )

        record = (
            records_2026.get(
                team,
                {}
            )
        )

        sp = (
            sp_lookup.get(
                team,
                {}
            )
        )

        total_record = (
            record.get(
                "total",
                {}
            )
            or {}
        )

        conference_record = (
            record.get(
                "conferenceGames",
                {}
            )
            or {}
        )

        wins = total_record.get(
            "wins",
            0
        )

        losses = total_record.get(
            "losses",
            0
        )

        # ---------------------------------------------------------------------
        # LIVE DATA AVAILABLE
        # ---------------------------------------------------------------------

        if live_row is not None:

            base_pr = safe_float(
                baseline.get(
                    "power_rating"
                ),
                0
            )

            live_pr = safe_float(
                live_row.get(
                    "power_rating"
                ),
                0
            )

            blended_pr = (
                base_pr
                * (
                    1 - blend_weight
                )
                +
                live_pr
                * blend_weight
            )

            def blend(
                section,
                live_value,
                key
            ):
                base_value = safe_float(
                    (
                        baseline.get(
                            section,
                            {}
                        )
                        or {}
                    ).get(
                        key
                    ),
                    0
                )

                return round(
                    base_value
                    * (
                        1 - blend_weight
                    )
                    +
                    safe_float(
                        live_value,
                        0
                    )
                    * blend_weight,
                    3
                )

            output[
                "teams"
            ][team] = {

                "team":
                    team,

                "conference":
                    team_conferences.get(
                        team,
                        "Ind"
                    ),

                "record": {
                    "wins":
                        wins,

                    "losses":
                        losses,

                    "conf_wins":
                        conference_record.get(
                            "wins",
                            0
                        ),

                    "conf_losses":
                        conference_record.get(
                            "losses",
                            0
                        ),
                },

                "sp_plus": {
                    "overall":
                        sp.get(
                            "rating",
                            (
                                baseline.get(
                                    "sp_plus",
                                    {}
                                )
                                or {}
                            ).get(
                                "overall"
                            )
                        ),

                    "offense":
                        (
                            sp.get(
                                "offense",
                                {}
                            )
                            or {}
                        ).get(
                            "rating",
                            (
                                baseline.get(
                                    "sp_plus",
                                    {}
                                )
                                or {}
                            ).get(
                                "offense"
                            )
                        ),

                    "defense":
                        (
                            sp.get(
                                "defense",
                                {}
                            )
                            or {}
                        ).get(
                            "rating",
                            (
                                baseline.get(
                                    "sp_plus",
                                    {}
                                )
                                or {}
                            ).get(
                                "defense"
                            )
                        ),
                },

                "power_rating":
                    round(
                        blended_pr,
                        3
                    ),

                "power_rating_rank":
                    0,

                "offense": {
                    "epa_play":
                        blend(
                            "offense",
                            live_row.get(
                                "off_epa",
                                0
                            ),
                            "epa_play"
                        ),

                    "success_rate":
                        blend(
                            "offense",
                            live_row.get(
                                "off_sr",
                                0
                            ),
                            "success_rate"
                        ),

                    "explosive_rate":
                        blend(
                            "offense",
                            live_row.get(
                                "off_expl",
                                0
                            ),
                            "explosive_rate"
                        ),

                    "epa_pass":
                        blend(
                            "offense",
                            live_row.get(
                                "off_epa_pass",
                                0
                            ),
                            "epa_pass"
                        ),

                    "epa_rush":
                        blend(
                            "offense",
                            live_row.get(
                                "off_epa_rush",
                                0
                            ),
                            "epa_rush"
                        ),

                    "pass_sr":
                        blend(
                            "offense",
                            live_row.get(
                                "off_pass_sr",
                                0
                            ),
                            "pass_sr"
                        ),

                    "rush_sr":
                        blend(
                            "offense",
                            live_row.get(
                                "off_rush_sr",
                                0
                            ),
                            "rush_sr"
                        ),

                    "havoc_allowed":
                        blend(
                            "offense",
                            live_row.get(
                                "off_havoc_allowed",
                                0
                            ),
                            "havoc_allowed"
                        ),

                    "n_plays":
                        int(
                            (
                                live_team_stats.get(
                                    "offense",
                                    {}
                                )
                                or {}
                            ).get(
                                "n_plays",
                                0
                            )
                        ),
                },

                "defense": {
                    "epa_play":
                        blend(
                            "defense",
                            live_row.get(
                                "def_epa",
                                0
                            ),
                            "epa_play"
                        ),

                    "success_rate":
                        blend(
                            "defense",
                            live_row.get(
                                "def_sr",
                                0
                            ),
                            "success_rate"
                        ),

                    "explosive_rate":
                        blend(
                            "defense",
                            live_row.get(
                                "def_expl",
                                0
                            ),
                            "explosive_rate"
                        ),

                    "epa_pass":
                        blend(
                            "defense",
                            live_row.get(
                                "def_epa_pass",
                                0
                            ),
                            "epa_pass"
                        ),

                    "epa_rush":
                        blend(
                            "defense",
                            live_row.get(
                                "def_epa_rush",
                                0
                            ),
                            "epa_rush"
                        ),

                    "pass_sr":
                        blend(
                            "defense",
                            live_row.get(
                                "def_pass_sr",
                                0
                            ),
                            "pass_sr"
                        ),

                    "rush_sr":
                        blend(
                            "defense",
                            live_row.get(
                                "def_rush_sr",
                                0
                            ),
                            "rush_sr"
                        ),

                    "havoc_created":
                        blend(
                            "defense",
                            live_row.get(
                                "def_havoc_created",
                                0
                            ),
                            "havoc_created"
                        ),

                    "n_plays":
                        int(
                            (
                                live_team_stats.get(
                                    "defense",
                                    {}
                                )
                                or {}
                            ).get(
                                "n_plays",
                                0
                            )
                        ),
                },

                "net": {
                    "epa":
                        round(
                            safe_float(
                                live_row.get(
                                    "net_epa"
                                )
                            ),
                            3
                        ),

                    "sr":
                        round(
                            safe_float(
                                live_row.get(
                                    "net_sr"
                                )
                            ),
                            1
                        ),

                    "epa_pass":
                        round(
                            safe_float(
                                live_row.get(
                                    "net_epa_pass"
                                )
                            ),
                            3
                        ),

                    "epa_rush":
                        round(
                            safe_float(
                                live_row.get(
                                    "net_epa_rush"
                                )
                            ),
                            3
                        ),
                }
            }

        # ---------------------------------------------------------------------
        # NO LIVE DATA — KEEP PRESEASON BASELINE
        # ---------------------------------------------------------------------

        else:

            if baseline:

                preserved = dict(
                    baseline
                )

                preserved[
                    "record"
                ] = {
                    "wins":
                        wins,

                    "losses":
                        losses,

                    "conf_wins":
                        conference_record.get(
                            "wins",
                            0
                        ),

                    "conf_losses":
                        conference_record.get(
                            "losses",
                            0
                        ),
                }

                output[
                    "teams"
                ][team] = preserved

    # -------------------------------------------------------------------------
    # SAFETY CHECK
    # -------------------------------------------------------------------------

    if len(
        output["teams"]
    ) < 100:

        print("")
        print(
            "❌ SAFETY CHECK FAILED"
        )

        print(
            f"   Only "
            f"{len(output['teams'])} "
            f"teams would be written."
        )

        print(
            "   Refusing to overwrite "
            "cfb_metrics.json."
        )

        sys.exit(1)

    # -------------------------------------------------------------------------
    # RANK TEAMS
    # -------------------------------------------------------------------------

    all_ratings = []

    for team, team_data in (
        output["teams"].items()
    ):

        if not team_data:
            continue

        rating = safe_float(
            team_data.get(
                "power_rating"
            ),
            0
        )

        all_ratings.append(
            (team, rating)
        )

    all_ratings.sort(
        key=lambda item: item[1],
        reverse=True
    )

    for rank, (
        team,
        _
    ) in enumerate(
        all_ratings,
        start=1
    ):

        output[
            "teams"
        ][team][
            "power_rating_rank"
        ] = rank

    # -------------------------------------------------------------------------
    # SAVE
    # -------------------------------------------------------------------------

    os.makedirs(
        "data",
        exist_ok=True
    )

    temp_path = (
        DATA_PATH
        + ".tmp"
    )

    # Write temporary file first.
    with open(
        temp_path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            indent=2,
            ensure_ascii=False,
            default=str
        )

    # Make sure it can be read back.
    try:

        with open(
            temp_path,
            "r",
            encoding="utf-8"
        ) as file:

            validation = json.load(
                file
            )

        if len(
            validation.get(
                "teams",
                {}
            )
        ) < 100:

            raise ValueError(
                "Generated dataset failed team-count validation."
            )

    except Exception as error:

        print(
            f"❌ Generated JSON failed validation: "
            f"{error}"
        )

        if os.path.exists(
            temp_path
        ):
            os.remove(
                temp_path
            )

        sys.exit(1)

    # Only replace the real data after validation succeeds.
    os.replace(
        temp_path,
        DATA_PATH
    )

    size_kb = (
        os.path.getsize(
            DATA_PATH
        )
        / 1024
    )

    print("")
    print("=" * 70)
    print("✅ WEEKLY UPDATE COMPLETE")
    print("=" * 70)

    print(
        f"Teams written: "
        f"{len(output['teams'])}"
    )

    print(
        f"Through week: "
        f"{completed_week}"
    )

    print(
        f"Live plays: "
        f"{len(clean):,}"
    )

    print(
        f"File size: "
        f"{size_kb:.1f} KB"
    )

    print(
        f"Saved: "
        f"{DATA_PATH}"
    )


if __name__ == "__main__":
    main()
