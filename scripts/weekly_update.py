"""
CFB ANALYTICS
weekly_update.py

Updates the 2026 team efficiency data used by the model.

2026 metrics-quality version.

Fixes:
- Uses CFBD play-level PPA as our EPA-style play value
- Uses score AT THE TIME OF THE PLAY for garbage-time filtering
- Calculates a true explosive-play rate
    Pass: 15+ yards
    Rush: 10+ yards
- Keeps pass/rush splits separate
- Does not publish impossible percentage rates
- Freezes a baseline so repeated workflow runs do not compound blends
- Preserves teams that have not played yet
- Normalizes provider team names before they enter the model
- Repairs legacy team keys in both the frozen baseline and current team data
- Uses calendar-based week bounds so future weeks are never probed
- Uses 5-request retries, 75s timeout, exponential backoff, and /plays fallback

IMPORTANT:
The public/model name for San Jose State is always "San Jose State".
"""

import copy
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

MIN_TEAM_PLAYS = 5
MIN_SPLIT_PLAYS = 4


# =============================================================================
# TEAM NAME NORMALIZATION
# =============================================================================

TEAM_NAME_ALIASES = {
    # Fix the bad/legacy provider spelling that leaked into the model.
    "Sam José State": "San Jose State",
    "Sam Jose State": "San Jose State",
    "San José State": "San Jose State",

    # Keep our preferred public names stable if providers use alternatives.
    "Appalachian State": "App State",
    "Connecticut": "UConn",
    "Louisiana Monroe": "UL Monroe",
    "Southern Mississippi": "Southern Miss",
    "UT San Antonio": "UTSA",
}


def normalize_team_name(value):
    if value is None:
        return None

    name = str(value).strip()
    return TEAM_NAME_ALIASES.get(name, name)


def normalize_team_dict(source):
    """
    Re-key an existing team dictionary using our preferred model/public names.

    This repairs old keys in:
    - teams
    - baseline_snapshot

    It also updates the nested "team" field when present.
    """
    if not isinstance(source, dict):
        return {}

    normalized = {}

    for raw_name, raw_data in source.items():
        name = normalize_team_name(raw_name)
        data = copy.deepcopy(raw_data)

        if isinstance(data, dict):
            data["team"] = name

        if name in normalized:
            print(
                f"❌ Team normalization collision: "
                f"{raw_name} -> {name}"
            )
            sys.exit(1)

        normalized[name] = data

    return normalized


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


API_KEY = clean_api_key(
    os.environ.get(
        "CFBD_API_KEY",
        ""
    )
)

if not API_KEY:
    print("❌ CFBD_API_KEY is missing.")
    sys.exit(1)


HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json",
}


# =============================================================================
# GENERAL HELPERS
# =============================================================================

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


def safe_float(
    value,
    default=0.0
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


def optional_float(value):
    try:
        if value is None:
            return None

        return float(value)

    except (
        TypeError,
        ValueError
    ):
        return None


def valid_rate(value):
    value = optional_float(value)

    return (
        value is not None
        and 0 <= value <= 100
    )


def clean_rate(value):
    """
    Percentage values must be between 0 and 100.

    Anything outside that range is considered invalid legacy data.
    """
    value = optional_float(value)

    if value is None:
        return None

    if not 0 <= value <= 100:
        return None

    return round(
        value,
        3
    )


def z_score(series):
    s = (
        series
        .copy()
        .astype(float)
    )

    mean = s.mean()
    std = s.std()

    if (
        std == 0
        or pd.isna(std)
    ):
        return pd.Series(
            0.0,
            index=s.index
        )

    return (
        s - mean
    ) / std


# =============================================================================
# CFBD REQUEST
# =============================================================================

def cfbd(
    endpoint,
    params=None,
    required=True
):
    url = (
        f"{BASE_URL}"
        f"{endpoint}"
    )

    max_attempts = 5

    for attempt in range(
        1,
        max_attempts + 1
    ):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                params=params,
                timeout=75
            )

        except requests.RequestException as error:

            print(
                f"⚠ CFBD request error "
                f"{endpoint} "
                f"({attempt}/{max_attempts}): {error}"
            )

            if attempt < max_attempts:
                time.sleep(min(2 ** attempt, 20))
                continue

            if required:
                sys.exit(1)

            return []

        if response.status_code in (
            401,
            403
        ):
            print("")
            print(
                "❌ CFBD AUTHENTICATION FAILED"
            )
            print(
                f"HTTP "
                f"{response.status_code}"
            )

            sys.exit(1)

        if not response.ok:

            print(
                f"⚠ CFBD HTTP "
                f"{response.status_code} "
                f"for {endpoint}"
            )

            print(
                f"Params: {params}"
            )

            if attempt < max_attempts:
                time.sleep(min(2 ** attempt, 20))
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


def validate_cfbd():

    print("")
    print(
        "🔐 Validating CFBD connection..."
    )

    result = cfbd(
        "/games",
        {
            "year": YEAR,
            "week": 1,
            "seasonType": "regular",
            "classification": "fbs",
        },
        required=True
    )

    if not isinstance(
        result,
        list
    ):
        print(
            "❌ Unexpected CFBD "
            "response format."
        )

        sys.exit(1)

    print(
        "✅ CFBD authentication successful"
    )


def current_calendar_week():
    """
    Determine the latest regular-season week that could possibly contain
    completed games from the calendar instead of probing all future CFBD weeks.

    2026 Week 0 begins Saturday, August 22.
    Week numbers advance every seven days from that anchor.

    Examples:
    - Aug 22-28 -> Week 0
    - Aug 29-Sep 4 -> Week 1
    - Sep 5-11 -> Week 2

    The value is capped to the normal regular-season range.
    """
    anchor = datetime(YEAR, 8, 22).date()
    today = datetime.now().date()

    if today < anchor:
        return 0

    week = (today - anchor).days // 7
    return max(0, min(16, int(week)))


def fetch_week_plays(week):
    """
    Fetch one week's play-by-play with a fallback strategy.

    First try classification=fbs. If CFBD repeatedly fails or returns no data,
    retry without classification and filter to FBS-vs-FBS locally.
    """
    primary_params = {
        "year": YEAR,
        "week": week,
        "seasonType": "regular",
        "classification": "fbs",
    }

    print(
        f"   Fetching Week {week} plays "
        "(FBS-filtered request)..."
    )

    plays = cfbd(
        "/plays",
        primary_params,
        required=False
    )

    if plays:
        return plays

    print(
        f"   ⚠ Week {week} FBS-filtered play request "
        "failed or returned no data."
    )
    print(
        "   Retrying without classification; "
        "FBS-vs-FBS filtering will happen locally."
    )

    fallback_params = {
        "year": YEAR,
        "week": week,
        "seasonType": "regular",
    }

    plays = cfbd(
        "/plays",
        fallback_params,
        required=False
    )

    if plays:
        return plays

    print(
        f"❌ Unable to retrieve Week {week} play-by-play "
        "after both request strategies."
    )
    sys.exit(1)


# =============================================================================
# PLAY NORMALIZATION
# =============================================================================

def normalize_play(raw):
    """
    Normalize CFBD fields and team names once here so bad provider labels
    cannot propagate through the model.
    """

    return {
        "game_id":
            first_value(
                raw,
                "gameId",
                "game_id"
            ),

        "offense":
            normalize_team_name(
                first_value(
                    raw,
                    "offense"
                )
            ),

        "defense":
            normalize_team_name(
                first_value(
                    raw,
                    "defense"
                )
            ),

        "home":
            normalize_team_name(
                first_value(
                    raw,
                    "home"
                )
            ),

        "away":
            normalize_team_name(
                first_value(
                    raw,
                    "away"
                )
            ),

        "offense_score":
            first_value(
                raw,
                "offenseScore",
                "offense_score",
                default=0
            ),

        "defense_score":
            first_value(
                raw,
                "defenseScore",
                "defense_score",
                default=0
            ),

        "period":
            first_value(
                raw,
                "period",
                default=1
            ),

        "down":
            first_value(
                raw,
                "down"
            ),

        "distance":
            first_value(
                raw,
                "distance"
            ),

        "yards_to_goal":
            first_value(
                raw,
                "yardsToGoal",
                "yards_to_goal"
            ),

        "yards_gained":
            first_value(
                raw,
                "yardsGained",
                "yards_gained",
                default=0
            ),

        "play_type":
            first_value(
                raw,
                "playType",
                "play_type",
                default=""
            ),

        "play_text":
            first_value(
                raw,
                "playText",
                "play_text",
                default=""
            ),

        # CFBD's play-level Predicted Points Added.
        # This is the value we use as our EPA-style play metric.
        "ppa":
            first_value(
                raw,
                "ppa"
            ),
    }


# =============================================================================
# PLAY CLASSIFICATION
# =============================================================================

def play_description(play):
    return (
        f"{play.get('play_type', '')} "
        f"{play.get('play_text', '')}"
    ).lower()


def is_pass_play(play):
    text = play_description(
        play
    )

    return any(
        word in text
        for word in (
            "pass",
            "sack",
            "interception",
        )
    )


def is_rush_play(play):
    text = play_description(
        play
    )

    # Sacks count with passing,
    # not rushing.
    if "sack" in text:
        return False

    return any(
        word in text
        for word in (
            "rush",
            "run ",
            "rushed",
        )
    )


def is_excluded_play(play):
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


def is_garbage_time(play):
    """
    Uses offenseScore and defenseScore from the actual play.

    IMPORTANT:
    We do NOT use the game's final score here.
    """

    period = int(
        safe_float(
            play.get(
                "period"
            ),
            1
        )
    )

    score_difference = abs(
        safe_float(
            play.get(
                "offense_score"
            ),
            0
        )
        -
        safe_float(
            play.get(
                "defense_score"
            ),
            0
        )
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


def is_success(play):
    yards = safe_float(
        play.get(
            "yards_gained"
        ),
        0
    )

    distance = safe_float(
        play.get(
            "distance"
        ),
        10
    )

    down = int(
        safe_float(
            play.get(
                "down"
            ),
            1
        )
    )

    if distance <= 0:
        return False

    if down == 1:
        return (
            yards
            >= distance * 0.50
        )

    if down == 2:
        return (
            yards
            >= distance * 0.70
        )

    if down in (
        3,
        4
    ):
        return (
            yards >= distance
        )

    return False


def is_havoc(play):
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
# TEAM METRICS
# =============================================================================

def mean_or_none(series):
    if len(series) == 0:
        return None

    clean = pd.to_numeric(
        series,
        errors="coerce"
    ).dropna()

    if len(clean) == 0:
        return None

    return float(
        clean.mean()
    )


def team_metrics(
    df,
    team,
    side
):
    column = (
        "offense"
        if side == "offense"
        else "defense"
    )

    team_plays = df[
        df[column] == team
    ].copy()

    if (
        len(team_plays)
        < MIN_TEAM_PLAYS
    ):
        return {}

    pass_plays = team_plays[
        team_plays[
            "is_pass"
        ]
    ]

    rush_plays = team_plays[
        team_plays[
            "is_rush"
        ]
    ]

    epa_play = mean_or_none(
        team_plays["epa"]
    )

    success_rate = (
        float(
            team_plays[
                "success"
            ].mean()
        )
        * 100
    )

    explosive_rate = (
        float(
            team_plays[
                "explosive"
            ].mean()
        )
        * 100
    )

    havoc_rate = (
        float(
            team_plays[
                "havoc"
            ].mean()
        )
        * 100
    )

    epa_pass = (
        mean_or_none(
            pass_plays[
                "epa"
            ]
        )
        if len(pass_plays)
        >= MIN_SPLIT_PLAYS
        else None
    )

    epa_rush = (
        mean_or_none(
            rush_plays[
                "epa"
            ]
        )
        if len(rush_plays)
        >= MIN_SPLIT_PLAYS
        else None
    )

    pass_sr = (
        float(
            pass_plays[
                "success"
            ].mean()
        )
        * 100
        if len(pass_plays)
        >= MIN_SPLIT_PLAYS
        else None
    )

    rush_sr = (
        float(
            rush_plays[
                "success"
            ].mean()
        )
        * 100
        if len(rush_plays)
        >= MIN_SPLIT_PLAYS
        else None
    )

    return {
        "n_plays":
            int(
                len(team_plays)
            ),

        "pass_plays":
            int(
                len(pass_plays)
            ),

        "rush_plays":
            int(
                len(rush_plays)
            ),

        "epa_play":
            epa_play,

        "epa_pass":
            epa_pass,

        "epa_rush":
            epa_rush,

        "success_rate":
            success_rate,

        "pass_sr":
            pass_sr,

        "rush_sr":
            rush_sr,

        "explosive_rate":
            explosive_rate,

        "havoc_rate":
            havoc_rate,
    }


# =============================================================================
# BASELINE HANDLING
# =============================================================================

def sanitize_baseline_team(team_data):
    """
    Preserve the existing preseason/model baseline,
    but kill impossible legacy explosive percentages.
    """

    cleaned = copy.deepcopy(
        team_data
    )

    for section in (
        "offense",
        "defense"
    ):
        section_data = (
            cleaned.get(
                section,
                {}
            )
            or {}
        )

        explosive = section_data.get(
            "explosive_rate"
        )

        if not valid_rate(
            explosive
        ):
            section_data[
                "explosive_rate"
            ] = None

        for rate_key in (
            "success_rate",
            "pass_sr",
            "rush_sr",
            "havoc_allowed",
            "havoc_created",
        ):
            if rate_key not in section_data:
                continue

            value = section_data.get(
                rate_key
            )

            if (
                value is not None
                and not valid_rate(value)
            ):
                section_data[
                    rate_key
                ] = None

        cleaned[
            section
        ] = section_data

    return cleaned


def get_frozen_baseline(existing):
    """
    Once this updater has a frozen baseline, reuse that same baseline instead
    of treating the previous blended output as a new preseason starting point.

    Existing baseline keys are normalized here so legacy names cannot survive
    indefinitely.
    """

    snapshot = normalize_team_dict(
        existing.get(
            "baseline_snapshot"
        )
    )

    if (
        isinstance(snapshot, dict)
        and len(snapshot) >= 100
    ):
        print(
            "✅ Using frozen model baseline"
        )

        return copy.deepcopy(
            snapshot
        )

    print(
        "🧊 Creating frozen baseline snapshot"
    )

    snapshot = {}

    normalized_existing = normalize_team_dict(
        existing.get(
            "teams",
            {}
        )
    )

    for team, data in (
        normalized_existing.items()
    ):
        snapshot[team] = (
            sanitize_baseline_team(
                data
            )
        )

    return snapshot


# =============================================================================
# BLENDING
# =============================================================================

def blend_number(
    baseline_value,
    live_value,
    weight
):
    base = optional_float(
        baseline_value
    )

    live = optional_float(
        live_value
    )

    if live is None:
        return (
            round(base, 3)
            if base is not None
            else None
        )

    if base is None:
        return round(
            live,
            3
        )

    return round(
        base * (
            1 - weight
        )
        +
        live * weight,
        3
    )


def blended_section(
    baseline_section,
    live_stats,
    weight,
    side
):
    base = (
        baseline_section
        or {}
    )

    live = (
        live_stats
        or {}
    )

    havoc_key = (
        "havoc_allowed"
        if side == "offense"
        else "havoc_created"
    )

    result = {
        "epa_play":
            blend_number(
                base.get(
                    "epa_play"
                ),
                live.get(
                    "epa_play"
                ),
                weight
            ),

        "success_rate":
            blend_number(
                base.get(
                    "success_rate"
                ),
                live.get(
                    "success_rate"
                ),
                weight
            ),

        "epa_pass":
            blend_number(
                base.get(
                    "epa_pass"
                ),
                live.get(
                    "epa_pass"
                ),
                weight
            ),

        "epa_rush":
            blend_number(
                base.get(
                    "epa_rush"
                ),
                live.get(
                    "epa_rush"
                ),
                weight
            ),

        "pass_sr":
            blend_number(
                base.get(
                    "pass_sr"
                ),
                live.get(
                    "pass_sr"
                ),
                weight
            ),

        "rush_sr":
            blend_number(
                base.get(
                    "rush_sr"
                ),
                live.get(
                    "rush_sr"
                ),
                weight
            ),

        havoc_key:
            blend_number(
                base.get(
                    havoc_key
                ),
                live.get(
                    "havoc_rate"
                ),
                weight
            ),

        "n_plays":
            int(
                live.get(
                    "n_plays",
                    0
                )
            ),
    }

    # Legacy baseline explosiveness was not a true percentage, so do not blend.
    if live.get(
        "n_plays",
        0
    ) > 0:
        result[
            "explosive_rate"
        ] = clean_rate(
            live.get(
                "explosive_rate"
            )
        )

    else:
        result[
            "explosive_rate"
        ] = None

    result[
        "live_2026"
    ] = {
        "epa_play":
            (
                round(
                    live["epa_play"],
                    3
                )
                if live.get(
                    "epa_play"
                ) is not None
                else None
            ),

        "epa_pass":
            (
                round(
                    live["epa_pass"],
                    3
                )
                if live.get(
                    "epa_pass"
                ) is not None
                else None
            ),

        "epa_rush":
            (
                round(
                    live["epa_rush"],
                    3
                )
                if live.get(
                    "epa_rush"
                ) is not None
                else None
            ),

        "success_rate":
            clean_rate(
                live.get(
                    "success_rate"
                )
            ),

        "pass_sr":
            clean_rate(
                live.get(
                    "pass_sr"
                )
            ),

        "rush_sr":
            clean_rate(
                live.get(
                    "rush_sr"
                )
            ),

        "explosive_rate":
            clean_rate(
                live.get(
                    "explosive_rate"
                )
            ),

        "havoc_rate":
            clean_rate(
                live.get(
                    "havoc_rate"
                )
            ),

        "n_plays":
            int(
                live.get(
                    "n_plays",
                    0
                )
            ),

        "pass_plays":
            int(
                live.get(
                    "pass_plays",
                    0
                )
            ),

        "rush_plays":
            int(
                live.get(
                    "rush_plays",
                    0
                )
            ),
    }

    return result


# =============================================================================
# MAIN
# =============================================================================

def main():

    print("=" * 70)
    print(
        "🏈 CFB ANALYTICS — "
        "2026 METRICS UPDATE"
    )
    print("=" * 70)

    print(
        f"Season: {YEAR}"
    )

    print(
        f"Generated: "
        f"{datetime.now().isoformat()}"
    )

    validate_cfbd()

    # -------------------------------------------------------------------------
    # LOAD CURRENT DATA
    # -------------------------------------------------------------------------

    print("")
    print(
        f"📂 Loading {DATA_PATH}..."
    )

    try:
        with open(
            DATA_PATH,
            "r",
            encoding="utf-8"
        ) as file:
            existing = json.load(
                file
            )

    except FileNotFoundError:

        print(
            "❌ Existing baseline "
            "was not found."
        )

        sys.exit(1)

    existing_teams = normalize_team_dict(
        existing.get(
            "teams",
            {}
        )
    )

    if len(
        existing_teams
    ) < 100:
        print(
            "❌ Existing dataset has "
            "too few teams."
        )

        sys.exit(1)

    print(
        f"✅ Existing teams: "
        f"{len(existing_teams)}"
    )

    baseline_snapshot = (
        get_frozen_baseline(
            existing
        )
    )

    # -------------------------------------------------------------------------
    # DETECT COMPLETED GAMES/WEEK
    # -------------------------------------------------------------------------

    print("")
    print(
        "📅 Detecting completed games..."
    )

    games_by_week = {}

    completed_week = 0
    completed_games = 0

    max_week_to_check = current_calendar_week()

    print(
        f"   Calendar allows checks through Week "
        f"{max_week_to_check}"
    )

    for week in range(
        0,
        max_week_to_check + 1
    ):
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

        games_by_week[
            week
        ] = games

        completed_this_week = 0

        for game in games:
            completed = first_value(
                game,
                "completed",
                default=False
            )

            if completed is True:
                completed_this_week += 1

        if completed_this_week:
            completed_week = max(
                completed_week,
                week
            )

            completed_games += (
                completed_this_week
            )

        print(
            f"   Week {week}: "
            f"{completed_this_week} completed"
        )

    if completed_games == 0:
        print("")
        print(
            "ℹ️ No completed games yet."
        )
        print(
            "Keeping baseline unchanged."
        )
        return

    print("")
    print(
        f"✅ Through Week "
        f"{completed_week}"
    )

    # -------------------------------------------------------------------------
    # FBS TEAMS
    # -------------------------------------------------------------------------

    print("")
    print(
        "🏫 Fetching FBS teams..."
    )

    teams_data = cfbd(
        "/teams/fbs",
        {
            "year": YEAR
        },
        required=True
    )

    fbs_teams = set()

    conference_lookup = {}

    for team in teams_data:

        school = normalize_team_name(
            first_value(
                team,
                "school"
            )
        )

        if not school:
            continue

        fbs_teams.add(
            school
        )

        conference_lookup[
            school
        ] = first_value(
            team,
            "conference",
            default="Ind"
        )

    print(
        f"✅ FBS teams: "
        f"{len(fbs_teams)}"
    )

    # Guard the exact public/model spelling we care about.
    if "Sam José State" in fbs_teams or "Sam Jose State" in fbs_teams:
        print(
            "❌ Team-name normalization failed for San Jose State."
        )
        sys.exit(1)

    if "San Jose State" not in fbs_teams:
        print(
            "❌ San Jose State missing after team-name normalization."
        )
        sys.exit(1)

    print(
        "✅ Team-name normalization: San Jose State"
    )

    # -------------------------------------------------------------------------
    # PLAY BY PLAY
    # -------------------------------------------------------------------------

    print("")
    print(
        "🎮 Fetching play-by-play..."
    )

    all_plays = []

    raw_play_count = 0
    missing_ppa = 0

    for week in range(
        0,
        completed_week + 1
    ):
        raw_plays = fetch_week_plays(
            week
        )

        raw_play_count += len(
            raw_plays
        )

        accepted = 0

        for raw in raw_plays:

            play = normalize_play(
                raw
            )

            offense = play.get(
                "offense"
            )

            defense = play.get(
                "defense"
            )

            # Require BOTH teams to be FBS.
            if offense not in fbs_teams:
                continue

            if defense not in fbs_teams:
                continue

            if is_excluded_play(
                play
            ):
                continue

            ppa = optional_float(
                play.get(
                    "ppa"
                )
            )

            if ppa is None:
                missing_ppa += 1
                continue

            if is_garbage_time(
                play
            ):
                continue

            is_pass = is_pass_play(
                play
            )

            is_rush = is_rush_play(
                play
            )

            # We only want meaningful scrimmage plays.
            if (
                not is_pass
                and not is_rush
            ):
                continue

            yards = safe_float(
                play.get(
                    "yards_gained"
                ),
                0
            )

            play[
                "epa"
            ] = ppa

            play[
                "is_pass"
            ] = is_pass

            play[
                "is_rush"
            ] = is_rush

            play[
                "success"
            ] = is_success(
                play
            )

            play[
                "explosive"
            ] = (
                (
                    is_pass
                    and yards >= 15
                )
                or
                (
                    is_rush
                    and yards >= 10
                )
            )

            play[
                "havoc"
            ] = is_havoc(
                play
            )

            all_plays.append(
                play
            )

            accepted += 1

        print(
            f"   Week {week}: "
            f"{accepted:,} "
            f"qualifying plays"
        )

        time.sleep(
            0.20
        )

    print("")
    print(
        f"Raw plays received: "
        f"{raw_play_count:,}"
    )

    print(
        f"Qualifying FBS plays: "
        f"{len(all_plays):,}"
    )

    print(
        f"Plays missing PPA: "
        f"{missing_ppa:,}"
    )

    if not all_plays:

        print(
            "❌ No usable play data."
        )

        sys.exit(1)

    # -------------------------------------------------------------------------
    # DATAFRAME
    # -------------------------------------------------------------------------

    df = pd.DataFrame(
        all_plays
    )

    print("")
    print(
        "📊 Calculating team metrics..."
    )

    team_live = {}

    rows = []

    for team in sorted(
        fbs_teams
    ):
        offense = team_metrics(
            df,
            team,
            "offense"
        )

        defense = team_metrics(
            df,
            team,
            "defense"
        )

        team_live[
            team
        ] = {
            "offense":
                offense,

            "defense":
                defense,
        }

        if (
            not offense
            or not defense
        ):
            continue

        row = {
            "team":
                team,

            "off_epa":
                safe_float(
                    offense.get(
                        "epa_play"
                    )
                ),

            "off_epa_pass":
                safe_float(
                    offense.get(
                        "epa_pass"
                    )
                ),

            "off_epa_rush":
                safe_float(
                    offense.get(
                        "epa_rush"
                    )
                ),

            "off_sr":
                safe_float(
                    offense.get(
                        "success_rate"
                    )
                ),

            "off_havoc_allowed":
                safe_float(
                    offense.get(
                        "havoc_rate"
                    )
                ),

            "def_epa":
                safe_float(
                    defense.get(
                        "epa_play"
                    )
                ),

            "def_epa_pass":
                safe_float(
                    defense.get(
                        "epa_pass"
                    )
                ),

            "def_epa_rush":
                safe_float(
                    defense.get(
                        "epa_rush"
                    )
                ),

            "def_sr":
                safe_float(
                    defense.get(
                        "success_rate"
                    )
                ),

            "def_havoc_created":
                safe_float(
                    defense.get(
                        "havoc_rate"
                    )
                ),
        }

        row[
            "net_epa"
        ] = (
            row["off_epa"]
            -
            row["def_epa"]
        )

        row[
            "net_epa_pass"
        ] = (
            row["off_epa_pass"]
            -
            row["def_epa_pass"]
        )

        row[
            "net_epa_rush"
        ] = (
            row["off_epa_rush"]
            -
            row["def_epa_rush"]
        )

        row[
            "net_sr"
        ] = (
            row["off_sr"]
            -
            row["def_sr"]
        )

        rows.append(
            row
        )

    if not rows:

        print(
            "❌ No teams had enough "
            "qualifying plays."
        )

        sys.exit(1)

    metrics_df = (
        pd.DataFrame(
            rows
        )
        .set_index(
            "team"
        )
    )

    # -------------------------------------------------------------------------
    # LIVE POWER RATING
    # -------------------------------------------------------------------------

    z = pd.DataFrame(
        index=metrics_df.index
    )

    for column in WEIGHTS:

        series = metrics_df[
            column
        ].copy()

        if (
            column
            == "off_havoc_allowed"
        ):
            series = -series

        z[
            column
        ] = z_score(
            series
        )

    metrics_df[
        "power_rating"
    ] = sum(
        z[column] * weight
        for column, weight
        in WEIGHTS.items()
    )

    # -------------------------------------------------------------------------
    # RECORDS
    # -------------------------------------------------------------------------

    print("")
    print(
        "📚 Fetching records..."
    )

    records_data = cfbd(
        "/records",
        {
            "year": YEAR
        },
        required=True
    )

    records_lookup = {
        normalize_team_name(
            item.get(
                "team"
            )
        ): item

        for item in records_data

        if item.get(
            "team"
        )
    }

    # -------------------------------------------------------------------------
    # BLEND WEIGHT
    # -------------------------------------------------------------------------

    blend_weight = min(
        1.0,
        completed_week / 10
    )

    print("")
    print(
        f"🔀 Live 2026 model weight: "
        f"{blend_weight:.0%}"
    )

    output = {
        "meta": {
            "year":
                YEAR,

            "generated":
                datetime.now().isoformat(),

            "through_week":
                completed_week,

            "completed_games":
                completed_games,

            "total_plays_2026":
                len(df),

            "blend_weight":
                blend_weight,

            "type":
                "weekly_update_v3_team_names",

            "epa_source":
                "CFBD PPA",

            "explosive_definition":
                (
                    "15+ yard pass / "
                    "10+ yard rush"
                ),

            "garbage_time":
                (
                    "play-level score, "
                    "not final score"
                ),

            "team_name_standard":
                "preferred_public_names",
        },

        # Frozen model baseline.
        "baseline_snapshot":
            baseline_snapshot,

        "teams":
            {},
    }

    # -------------------------------------------------------------------------
    # OUTPUT TEAMS
    # -------------------------------------------------------------------------

    for team in sorted(
        fbs_teams
    ):
        baseline = (
            baseline_snapshot.get(
                team
            )
            or existing_teams.get(
                team
            )
            or {}
        )

        if not baseline:
            continue

        live_stats = (
            team_live.get(
                team,
                {}
            )
            or {}
        )

        live_offense = (
            live_stats.get(
                "offense"
            )
            or {}
        )

        live_defense = (
            live_stats.get(
                "defense"
            )
            or {}
        )

        record_data = (
            records_lookup.get(
                team,
                {}
            )
            or {}
        )

        total_record = (
            record_data.get(
                "total",
                {}
            )
            or {}
        )

        conference_record = (
            record_data.get(
                "conferenceGames",
                {}
            )
            or {}
        )

        base_power = safe_float(
            baseline.get(
                "power_rating"
            ),
            0
        )

        if team in metrics_df.index:

            live_power = safe_float(
                metrics_df.loc[
                    team,
                    "power_rating"
                ],
                0
            )

            blended_power = (
                base_power
                * (
                    1 - blend_weight
                )
                +
                live_power
                * blend_weight
            )

        else:
            live_power = None
            blended_power = (
                base_power
            )

        offense = blended_section(
            baseline.get(
                "offense",
                {}
            ),
            live_offense,
            blend_weight,
            "offense"
        )

        defense = blended_section(
            baseline.get(
                "defense",
                {}
            ),
            live_defense,
            blend_weight,
            "defense"
        )

        off_epa = optional_float(
            offense.get(
                "epa_play"
            )
        )

        def_epa = optional_float(
            defense.get(
                "epa_play"
            )
        )

        off_sr = optional_float(
            offense.get(
                "success_rate"
            )
        )

        def_sr = optional_float(
            defense.get(
                "success_rate"
            )
        )

        off_pass = optional_float(
            offense.get(
                "epa_pass"
            )
        )

        def_pass = optional_float(
            defense.get(
                "epa_pass"
            )
        )

        off_rush = optional_float(
            offense.get(
                "epa_rush"
            )
        )

        def_rush = optional_float(
            defense.get(
                "epa_rush"
            )
        )

        team_output = {
            "team":
                team,

            "conference":
                conference_lookup.get(
                    team,
                    baseline.get(
                        "conference",
                        "Ind"
                    )
                ),

            "record": {
                "wins":
                    total_record.get(
                        "wins",
                        0
                    ),

                "losses":
                    total_record.get(
                        "losses",
                        0
                    ),

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

            "sp_plus":
                copy.deepcopy(
                    baseline.get(
                        "sp_plus",
                        {}
                    )
                ),

            "power_rating":
                round(
                    blended_power,
                    3
                ),

            "power_rating_rank":
                0,

            "offense":
                offense,

            "defense":
                defense,

            "net": {
                "epa":
                    (
                        round(
                            off_epa
                            -
                            def_epa,
                            3
                        )
                        if (
                            off_epa
                            is not None
                            and def_epa
                            is not None
                        )
                        else None
                    ),

                "sr":
                    (
                        round(
                            off_sr
                            -
                            def_sr,
                            1
                        )
                        if (
                            off_sr
                            is not None
                            and def_sr
                            is not None
                        )
                        else None
                    ),

                "epa_pass":
                    (
                        round(
                            off_pass
                            -
                            def_pass,
                            3
                        )
                        if (
                            off_pass
                            is not None
                            and def_pass
                            is not None
                        )
                        else None
                    ),

                "epa_rush":
                    (
                        round(
                            off_rush
                            -
                            def_rush,
                            3
                        )
                        if (
                            off_rush
                            is not None
                            and def_rush
                            is not None
                        )
                        else None
                    ),
            },

            "live_2026_power_rating":
                (
                    round(
                        live_power,
                        3
                    )
                    if live_power
                    is not None
                    else None
                ),
        }

        output[
            "teams"
        ][team] = team_output

    # -------------------------------------------------------------------------
    # TEAM COUNT SAFETY
    # -------------------------------------------------------------------------

    if len(
        output[
            "teams"
        ]
    ) < 100:

        print(
            "❌ SAFETY CHECK FAILED: "
            "too few teams."
        )

        sys.exit(1)

    # San Jose State must publish under its correct name.
    if "San Jose State" not in output["teams"]:
        print(
            "❌ SAFETY CHECK FAILED: "
            "San Jose State missing from output."
        )
        sys.exit(1)

    if any(
        bad_name in output["teams"]
        for bad_name in (
            "Sam José State",
            "Sam Jose State",
            "San José State",
        )
    ):
        print(
            "❌ SAFETY CHECK FAILED: "
            "bad San Jose State alias survived."
        )
        sys.exit(1)

    # -------------------------------------------------------------------------
    # RATE SAFETY CHECK
    # -------------------------------------------------------------------------

    invalid_rates = []

    for team, data in (
        output[
            "teams"
        ].items()
    ):

        for section in (
            "offense",
            "defense"
        ):

            section_data = (
                data.get(
                    section,
                    {}
                )
                or {}
            )

            for field in (
                "success_rate",
                "explosive_rate",
                "pass_sr",
                "rush_sr",
            ):

                value = section_data.get(
                    field
                )

                if value is None:
                    continue

                if not valid_rate(
                    value
                ):

                    invalid_rates.append(
                        (
                            team,
                            section,
                            field,
                            value
                        )
                    )

    if invalid_rates:

        print("")
        print(
            "❌ RATE SANITY CHECK FAILED"
        )

        for item in (
            invalid_rates[:20]
        ):
            print(
                "   ",
                item
            )

        print(
            "Refusing to publish "
            "impossible percentage values."
        )

        sys.exit(1)

    print("")
    print(
        "✅ All percentage sanity "
        "checks passed"
    )

    # -------------------------------------------------------------------------
    # RANK
    # -------------------------------------------------------------------------

    ranking = sorted(
        output[
            "teams"
        ].items(),

        key=lambda item:
            safe_float(
                item[1].get(
                    "power_rating"
                ),
                0
            ),

        reverse=True
    )

    for rank, (
        team,
        _
    ) in enumerate(
        ranking,
        start=1
    ):
        output[
            "teams"
        ][team][
            "power_rating_rank"
        ] = rank

    # -------------------------------------------------------------------------
    # DIAGNOSTICS
    # -------------------------------------------------------------------------

    teams_with_live = sum(
        1
        for stats in team_live.values()
        if (
            stats.get(
                "offense"
            )
            and stats.get(
                "defense"
            )
        )
    )

    teams_with_explosive = sum(
        1
        for data in output[
            "teams"
        ].values()
        if (
            (
                data.get(
                    "offense",
                    {}
                )
                or {}
            ).get(
                "explosive_rate"
            )
            is not None
        )
    )

    print("")
    print(
        f"Teams with live data: "
        f"{teams_with_live}"
    )

    print(
        f"Teams with true explosive "
        f"rate: {teams_with_explosive}"
    )

    # -------------------------------------------------------------------------
    # SAVE SAFELY
    # -------------------------------------------------------------------------

    os.makedirs(
        "data",
        exist_ok=True
    )

    temp_path = (
        DATA_PATH
        + ".tmp"
    )

    with open(
        temp_path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            indent=2,
            ensure_ascii=False
        )

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
                "Too few teams "
                "in generated file."
            )

        if "San Jose State" not in validation.get("teams", {}):
            raise ValueError(
                "San Jose State missing "
                "from generated file."
            )

    except Exception as error:

        print(
            f"❌ Generated JSON "
            f"failed validation: {error}"
        )

        if os.path.exists(
            temp_path
        ):
            os.remove(
                temp_path
            )

        sys.exit(1)

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
    print(
        "✅ METRICS UPDATE COMPLETE"
    )
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
        f"Qualifying plays: "
        f"{len(df):,}"
    )

    print(
        f"Live weight: "
        f"{blend_weight:.0%}"
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
