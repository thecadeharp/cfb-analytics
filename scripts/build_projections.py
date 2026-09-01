"""
CFB ANALYTICS
build_projections.py

Builds:
    data/schedule.json
    data/odds.json
    data/projections.json

Core principles
---------------
1. CFBD schedule matching is STRICT.
2. FCS schools are never prefix-matched into FBS schools.
3. The team power rating remains the foundation of every projection.
4. Matchup adjustments are deliberately small.
5. LIVE matchup adjustments require comparable samples from BOTH teams.
6. A team does not gain a matchup edge merely because it has played while
   its opponent has not.
7. Every projection stores its components so the frontend can explain
   how the number was created.
"""

import json
import math
import os
import statistics
import sys
import unicodedata
from datetime import datetime

import requests


# =============================================================================
# CONFIG
# =============================================================================

YEAR = 2026

CFBD_BASE = "https://api.collegefootballdata.com"
ODDS_BASE = "https://api.the-odds-api.com/v4"

METRICS_PATH = "data/cfb_metrics.json"
SCHEDULE_PATH = "data/schedule.json"
ODDS_PATH = "data/odds.json"
PROJECTIONS_PATH = "data/projections.json"

HOME_FIELD_ADVANTAGE = 2.0

# Matchup information is a modifier, never the model foundation.
MAX_MATCHUP_ADJUSTMENT = 3.0

BASE_TOTAL = 52.5

# Minimum LIVE samples before we allow head-to-head matchup adjustments.
MIN_LIVE_PLAYS = 35
MIN_LIVE_PASS_PLAYS = 15
MIN_LIVE_RUSH_PLAYS = 15

# Margin standard deviation used for game win probabilities.
# This is intentionally conservative.
WIN_PROB_STD_DEV = 16.0


# =============================================================================
# API KEYS
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

ODDS_API_KEY = clean_api_key(
    os.environ.get(
        "ODDS_API_KEY",
        ""
    )
)


# =============================================================================
# GENERAL HELPERS
# =============================================================================

def safe_number(
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


def optional_number(value):
    try:
        if value is None:
            return None

        return float(value)

    except (
        TypeError,
        ValueError
    ):
        return None


def round_half(value):
    return round(
        value * 2
    ) / 2


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


def canonical_name(value):
    if not value:
        return ""

    text = unicodedata.normalize(
        "NFKD",
        str(value)
    )

    text = "".join(
        character
        for character in text
        if not unicodedata.combining(
            character
        )
    )

    text = text.lower().strip()

    replacements = {
        "&": "and",
        "'": "",
        "’": "",
        ".": "",
        ",": "",
        "-": " ",
        "_": " ",
        "(": " ",
        ")": " ",
    }

    for old, new in replacements.items():
        text = text.replace(
            old,
            new
        )

    return " ".join(
        text.split()
    )


# =============================================================================
# SCHOOL ALIASES
# =============================================================================

ALIASES = {
    "miami fl": "Miami",
    "miami florida": "Miami",

    "uconn": "Connecticut",

    "umass": "Massachusetts",

    "southern miss":
        "Southern Mississippi",

    "utsa":
        "UT San Antonio",

    "texas san antonio":
        "UT San Antonio",

    "fiu":
        "Florida International",

    "fau":
        "Florida Atlantic",

    "app state":
        "Appalachian State",

    "nc state":
        "NC State",

    "n c state":
        "NC State",

    "north carolina state":
        "NC State",

    "hawaii":
        "Hawai'i",

    "mississippi":
        "Ole Miss",

    "ul lafayette":
        "Louisiana",

    "louisiana lafayette":
        "Louisiana",

    "ulm":
        "Louisiana Monroe",

    "ul monroe":
        "Louisiana Monroe",

    "middle tennessee state":
        "Middle Tennessee",

    "sam houston state":
        "Sam Houston",

    "miami ohio":
        "Miami (OH)",

    "miami oh":
        "Miami (OH)",
}


# =============================================================================
# TEAM MATCHING
# =============================================================================

def build_team_lookup(teams):
    return {
        canonical_name(team): team
        for team in teams
    }


def resolve_cfbd_team(
    provider_name,
    valid_teams,
    lookup
):
    """
    CFBD already supplies school names.

    Therefore matching is intentionally strict.

    Indiana State != Indiana
    Florida State != Florida
    South Carolina State != South Carolina
    """

    if not provider_name:
        return None

    canon = canonical_name(
        provider_name
    )

    if canon in lookup:
        return lookup[canon]

    alias = ALIASES.get(
        canon
    )

    if alias in valid_teams:
        return alias

    return None


SCHOOL_STRUCTURE_WORDS = {
    "state",
    "tech",
    "technical",
    "international",
    "christian",
    "southern",
    "northern",
    "western",
    "eastern",
    "central",
    "university",
    "college",
    "aandm",
    "ohio",
}


def resolve_odds_team(
    provider_name,
    valid_teams,
    lookup
):
    """
    Sportsbooks append mascots.

    Ohio State Buckeyes -> Ohio State

    But:
    Indiana State Sycamores != Indiana
    Florida State Seminoles != Florida
    """

    if not provider_name:
        return None

    canon = canonical_name(
        provider_name
    )

    # Exact model school name.
    if canon in lookup:
        return lookup[canon]

    # Explicit alias.
    alias = ALIASES.get(
        canon
    )

    if alias in valid_teams:
        return alias

    candidates = []

    for (
        model_canon,
        model_name
    ) in lookup.items():

        prefix = (
            model_canon
            + " "
        )

        if not canon.startswith(
            prefix
        ):
            continue

        remainder = canon[
            len(prefix):
        ].strip()

        if not remainder:
            continue

        first_word = (
            remainder
            .split()[0]
        )

        if (
            first_word
            in
            SCHOOL_STRUCTURE_WORDS
        ):
            continue

        candidates.append(
            (
                len(model_canon),
                model_name
            )
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: item[0],
        reverse=True
    )

    return candidates[0][1]


# =============================================================================
# API REQUESTS
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
            timeout=45
        )

    except requests.RequestException as error:

        print(
            f"❌ CFBD request failed: "
            f"{error}"
        )

        if required:
            sys.exit(1)

        return []

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

        if required:
            sys.exit(1)

        return []

    try:
        return response.json()

    except ValueError:

        print(
            "❌ CFBD returned invalid JSON."
        )

        if required:
            sys.exit(1)

        return []


def odds_get():
    if not ODDS_API_KEY:

        print(
            "⚠ ODDS_API_KEY missing."
        )

        return []

    try:

        response = requests.get(
            (
                f"{ODDS_BASE}/sports/"
                "americanfootball_ncaaf/odds"
            ),
            params={
                "apiKey":
                    ODDS_API_KEY,

                "regions":
                    "us",

                "markets":
                    "spreads,totals",

                "oddsFormat":
                    "american",

                "dateFormat":
                    "iso",
            },
            timeout=45
        )

    except requests.RequestException as error:

        print(
            f"⚠ Odds API request failed: "
            f"{error}"
        )

        return []

    if not response.ok:

        print(
            f"⚠ Odds API HTTP "
            f"{response.status_code}"
        )

        return []

    remaining = response.headers.get(
        "x-requests-remaining"
    )

    if remaining is not None:

        print(
            f"   Odds requests remaining: "
            f"{remaining}"
        )

    return response.json()


# =============================================================================
# LOAD METRICS
# =============================================================================

def load_metrics():
    if not os.path.exists(
        METRICS_PATH
    ):
        print(
            f"❌ Missing "
            f"{METRICS_PATH}"
        )

        sys.exit(1)

    with open(
        METRICS_PATH,
        "r",
        encoding="utf-8"
    ) as file:

        data = json.load(
            file
        )

    teams = data.get(
        "teams",
        {}
    )

    if len(teams) < 100:

        print(
            "❌ Metrics file contains "
            "too few teams."
        )

        sys.exit(1)

    print(
        f"✅ Loaded ratings for "
        f"{len(teams)} teams"
    )

    return (
        data,
        teams
    )


# =============================================================================
# POWER RATING -> POINT SCALE
# =============================================================================

def calculate_rating_scale(
    teams
):
    x_values = []
    y_values = []

    for team in teams.values():

        power = optional_number(
            team.get(
                "power_rating"
            )
        )

        sp = optional_number(
            (
                team.get(
                    "sp_plus",
                    {}
                )
                or {}
            ).get(
                "overall"
            )
        )

        if (
            power is None
            or sp is None
        ):
            continue

        x_values.append(
            power
        )

        y_values.append(
            sp
        )

    if len(x_values) < 10:

        return {
            "slope": 7.5,
            "intercept": 0.0,
            "method": "fallback",
        }

    x_mean = statistics.mean(
        x_values
    )

    y_mean = statistics.mean(
        y_values
    )

    numerator = sum(
        (
            x - x_mean
        )
        *
        (
            y - y_mean
        )
        for x, y
        in zip(
            x_values,
            y_values
        )
    )

    denominator = sum(
        (
            x - x_mean
        ) ** 2
        for x
        in x_values
    )

    slope = (
        numerator
        /
        denominator
        if denominator
        else 7.5
    )

    intercept = (
        y_mean
        -
        slope
        *
        x_mean
    )

    print("")
    print(
        "📐 Power rating calibration"
    )

    print(
        f"   1 rating unit = "
        f"{slope:.3f} points"
    )

    return {
        "slope":
            slope,

        "intercept":
            intercept,

        "method":
            "regression against SP+ scale",
    }


# =============================================================================
# MARKET ODDS
# =============================================================================

def extract_market(raw_game):
    preferred_books = [
        "draftkings",
        "fanduel",
        "betmgm",
        "caesars",
        "betonlineag",
    ]

    bookmakers = raw_game.get(
        "bookmakers",
        []
    )

    selected = None

    for key in preferred_books:

        for book in bookmakers:

            if book.get(
                "key"
            ) == key:

                selected = book
                break

        if selected:
            break

    if (
        selected is None
        and bookmakers
    ):
        selected = bookmakers[0]

    if selected is None:

        return {
            "spread": None,
            "total": None,
            "bookmaker": None,
        }

    raw_home = canonical_name(
        raw_game.get(
            "home_team"
        )
    )

    spread = None
    total = None

    for market in selected.get(
        "markets",
        []
    ):

        if (
            market.get("key")
            == "spreads"
        ):

            for outcome in market.get(
                "outcomes",
                []
            ):

                if (
                    canonical_name(
                        outcome.get(
                            "name"
                        )
                    )
                    ==
                    raw_home
                ):

                    spread = optional_number(
                        outcome.get(
                            "point"
                        )
                    )

        elif (
            market.get("key")
            == "totals"
        ):

            for outcome in market.get(
                "outcomes",
                []
            ):

                if (
                    str(
                        outcome.get(
                            "name",
                            ""
                        )
                    ).lower()
                    ==
                    "over"
                ):

                    total = optional_number(
                        outcome.get(
                            "point"
                        )
                    )

    return {
        "spread":
            spread,

        "total":
            total,

        "bookmaker":
            selected.get(
                "title"
            ),
    }


def fetch_odds(
    valid_teams,
    lookup
):
    print("")
    print(
        "💰 Fetching current "
        "NCAAF odds..."
    )

    raw_games = odds_get()

    games = []
    unmatched = set()

    for raw in raw_games:

        raw_home = raw.get(
            "home_team"
        )

        raw_away = raw.get(
            "away_team"
        )

        home = resolve_odds_team(
            raw_home,
            valid_teams,
            lookup
        )

        away = resolve_odds_team(
            raw_away,
            valid_teams,
            lookup
        )

        if (
            raw_home
            and not home
        ):
            unmatched.add(
                raw_home
            )

        if (
            raw_away
            and not away
        ):
            unmatched.add(
                raw_away
            )

        market = extract_market(
            raw
        )

        games.append({
            "id":
                raw.get("id"),

            "commence_time":
                raw.get(
                    "commence_time"
                ),

            "home_team":
                home,

            "away_team":
                away,

            "provider_home_team":
                raw_home,

            "provider_away_team":
                raw_away,

            "spread_home":
                market["spread"],

            "total":
                market["total"],

            "bookmaker":
                market["bookmaker"],
        })

    matched = sum(
        1
        for game in games
        if (
            game["home_team"]
            and
            game["away_team"]
        )
    )

    print(
        f"✅ Market games found: "
        f"{len(games)}"
    )

    print(
        f"✅ Market games matched: "
        f"{matched}"
    )

    if unmatched:

        print("")
        print(
            "🔎 Unmatched sportsbook "
            "examples:"
        )

        for team in sorted(
            unmatched
        )[:15]:

            print(
                f"   - {team}"
            )

    return {
        "meta": {
            "year":
                YEAR,

            "generated":
                datetime.now()
                .isoformat(),

            "games":
                len(games),

            "matched_games":
                matched,

            "source":
                "The Odds API",
        },

        "games":
            games,
    }


# =============================================================================
# SCHEDULE
# =============================================================================

def fetch_schedule(
    valid_teams,
    lookup
):
    print("")
    print(
        f"📅 Fetching "
        f"{YEAR} FBS schedule..."
    )

    raw_games = cfbd_get(
        "/games",
        {
            "year":
                YEAR,

            "seasonType":
                "regular",

            "classification":
                "fbs",
        }
    )

    print(
        f"   Raw CFBD games returned: "
        f"{len(raw_games)}"
    )

    games = []
    rejected = 0
    rejected_examples = set()
    seen = set()

    for raw in raw_games:

        raw_home = first_value(
            raw,
            "homeTeam",
            "home_team"
        )

        raw_away = first_value(
            raw,
            "awayTeam",
            "away_team"
        )

        home = resolve_cfbd_team(
            raw_home,
            valid_teams,
            lookup
        )

        away = resolve_cfbd_team(
            raw_away,
            valid_teams,
            lookup
        )

        if (
            not home
            or not away
        ):
            rejected += 1

            if (
                raw_home
                and not home
            ):
                rejected_examples.add(
                    str(raw_home)
                )

            if (
                raw_away
                and not away
            ):
                rejected_examples.add(
                    str(raw_away)
                )

            continue

        game_id = first_value(
            raw,
            "id"
        )

        start_date = first_value(
            raw,
            "startDate",
            "start_date"
        )

        unique_key = (
            str(game_id)
            if game_id is not None
            else (
                home,
                away,
                start_date
            )
        )

        if unique_key in seen:
            continue

        seen.add(
            unique_key
        )

        home_points = first_value(
            raw,
            "homePoints",
            "home_points"
        )

        away_points = first_value(
            raw,
            "awayPoints",
            "away_points"
        )

        completed = first_value(
            raw,
            "completed",
            default=False
        )

        games.append({
            "id":
                game_id,

            "week":
                first_value(
                    raw,
                    "week"
                ),

            "start_date":
                start_date,

            "home_team":
                home,

            "away_team":
                away,

            "home_conference":
                first_value(
                    raw,
                    "homeConference",
                    "home_conference"
                ),

            "away_conference":
                first_value(
                    raw,
                    "awayConference",
                    "away_conference"
                ),

            "venue":
                first_value(
                    raw,
                    "venue"
                ),

            "neutral_site":
                bool(
                    first_value(
                        raw,
                        "neutralSite",
                        "neutral_site",
                        default=False
                    )
                ),

            "home_points":
                home_points,

            "away_points":
                away_points,

            "status":
                (
                    "completed"
                    if (
                        completed is True
                        or (
                            home_points
                            is not None
                            and
                            away_points
                            is not None
                        )
                    )
                    else
                    "scheduled"
                ),
        })

    games.sort(
        key=lambda game: (
            game.get(
                "week"
            )
            if game.get(
                "week"
            ) is not None
            else 99,

            game.get(
                "start_date"
            )
            or "",
        )
    )

    print(
        f"✅ TRUE FBS-vs-FBS games: "
        f"{len(games)}"
    )

    print(
        f"🚫 Rejected games: "
        f"{rejected}"
    )

    if rejected_examples:

        print(
            "🔎 Correctly rejected examples:"
        )

        for name in sorted(
            rejected_examples
        )[:20]:

            print(
                f"   - {name}"
            )

    if len(games) < 400:

        print(
            "❌ Too few FBS-vs-FBS games. "
            "Refusing to publish."
        )

        sys.exit(1)

    return {
        "meta": {
            "year":
                YEAR,

            "generated":
                datetime.now()
                .isoformat(),

            "games":
                len(games),

            "source":
                "CollegeFootballData",

            "matching":
                "strict_fbs_school_names",
        },

        "games":
            games,
    }


# =============================================================================
# KNOWN SCHEDULE GUARDS
# =============================================================================

def verify_known_schedule_errors(
    schedule
):
    bad = []

    for game in schedule.get(
        "games",
        []
    ):

        home = game.get(
            "home_team"
        )

        away = game.get(
            "away_team"
        )

        date = str(
            game.get(
                "start_date",
                ""
            )
        )

        if {
            home,
            away
        } == {
            "Indiana",
            "Purdue"
        }:

            if not date.startswith(
                "2026-11-28"
            ):
                bad.append(
                    (
                        "Indiana/Purdue",
                        date
                    )
                )

        if {
            home,
            away
        } == {
            "Florida",
            "South Carolina"
        }:

            if not date.startswith(
                "2026-10-10"
            ):
                bad.append(
                    (
                        "Florida/South Carolina",
                        date
                    )
                )

    if bad:

        print(
            "❌ Known schedule "
            "sanity check failed."
        )

        for matchup, date in bad:

            print(
                f"   {matchup}: "
                f"{date}"
            )

        sys.exit(1)

    print(
        "✅ Known schedule sanity "
        "checks passed"
    )


# =============================================================================
# LIVE DATA HELPERS
# =============================================================================

def live_section(
    team,
    side
):
    return (
        (
            team.get(
                side,
                {}
            )
            or {}
        ).get(
            "live_2026",
            {}
        )
        or {}
    )


def live_has_general_sample(
    team
):
    offense = live_section(
        team,
        "offense"
    )

    defense = live_section(
        team,
        "defense"
    )

    return (
        safe_number(
            offense.get(
                "n_plays"
            )
        )
        >= MIN_LIVE_PLAYS
        and
        safe_number(
            defense.get(
                "n_plays"
            )
        )
        >= MIN_LIVE_PLAYS
    )


def both_have_general_sample(
    home,
    away
):
    return (
        live_has_general_sample(
            home
        )
        and
        live_has_general_sample(
            away
        )
    )


def both_have_pass_sample(
    home,
    away
):
    for team in (
        home,
        away
    ):

        offense = live_section(
            team,
            "offense"
        )

        defense = live_section(
            team,
            "defense"
        )

        if (
            safe_number(
                offense.get(
                    "pass_plays"
                )
            )
            <
            MIN_LIVE_PASS_PLAYS
        ):
            return False

        if (
            safe_number(
                defense.get(
                    "pass_plays"
                )
            )
            <
            MIN_LIVE_PASS_PLAYS
        ):
            return False

    return True


def both_have_rush_sample(
    home,
    away
):
    for team in (
        home,
        away
    ):

        offense = live_section(
            team,
            "offense"
        )

        defense = live_section(
            team,
            "defense"
        )

        if (
            safe_number(
                offense.get(
                    "rush_plays"
                )
            )
            <
            MIN_LIVE_RUSH_PLAYS
        ):
            return False

        if (
            safe_number(
                defense.get(
                    "rush_plays"
                )
            )
            <
            MIN_LIVE_RUSH_PLAYS
        ):
            return False

    return True


# =============================================================================
# MATCHUP ADJUSTMENTS
# =============================================================================

def bounded(
    value,
    cap
):
    return max(
        -cap,
        min(
            cap,
            value
        )
    )


def calculate_matchup_adjustment(
    home,
    away
):
    """
    IMPORTANT:

    These are LIVE matchup modifiers.

    If Stanford has played and Miami has not, Stanford receives ZERO passing,
    rushing, success-rate, explosiveness, or havoc matchup adjustment.

    We require comparable live samples from BOTH teams.
    """

    components = {
        "passing": 0.0,
        "rushing": 0.0,
        "success_rate": 0.0,
        "explosiveness": 0.0,
        "havoc": 0.0,
    }

    availability = {
        "passing": False,
        "rushing": False,
        "success_rate": False,
        "explosiveness": False,
        "havoc": False,
    }

    home_off = live_section(
        home,
        "offense"
    )

    home_def = live_section(
        home,
        "defense"
    )

    away_off = live_section(
        away,
        "offense"
    )

    away_def = live_section(
        away,
        "defense"
    )

    # -------------------------------------------------------------------------
    # PASSING
    # -------------------------------------------------------------------------

    if both_have_pass_sample(
        home,
        away
    ):
        values = [
            optional_number(
                home_off.get(
                    "epa_pass"
                )
            ),
            optional_number(
                away_def.get(
                    "epa_pass"
                )
            ),
            optional_number(
                away_off.get(
                    "epa_pass"
                )
            ),
            optional_number(
                home_def.get(
                    "epa_pass"
                )
            ),
        ]

        if all(
            value is not None
            for value in values
        ):
            (
                home_pass,
                away_pass_def,
                away_pass,
                home_pass_def
            ) = values

            home_edge = (
                home_pass
                -
                away_pass_def
            )

            away_edge = (
                away_pass
                -
                home_pass_def
            )

            components[
                "passing"
            ] = bounded(
                (
                    home_edge
                    -
                    away_edge
                )
                * 1.25,
                1.0
            )

            availability[
                "passing"
            ] = True

    # -------------------------------------------------------------------------
    # RUSHING
    # -------------------------------------------------------------------------

    if both_have_rush_sample(
        home,
        away
    ):
        values = [
            optional_number(
                home_off.get(
                    "epa_rush"
                )
            ),
            optional_number(
                away_def.get(
                    "epa_rush"
                )
            ),
            optional_number(
                away_off.get(
                    "epa_rush"
                )
            ),
            optional_number(
                home_def.get(
                    "epa_rush"
                )
            ),
        ]

        if all(
            value is not None
            for value in values
        ):
            (
                home_rush,
                away_rush_def,
                away_rush,
                home_rush_def
            ) = values

            home_edge = (
                home_rush
                -
                away_rush_def
            )

            away_edge = (
                away_rush
                -
                home_rush_def
            )

            components[
                "rushing"
            ] = bounded(
                (
                    home_edge
                    -
                    away_edge
                )
                * 1.0,
                0.75
            )

            availability[
                "rushing"
            ] = True

    # -------------------------------------------------------------------------
    # SUCCESS RATE
    # -------------------------------------------------------------------------

    if both_have_general_sample(
        home,
        away
    ):
        values = [
            optional_number(
                home_off.get(
                    "success_rate"
                )
            ),
            optional_number(
                away_def.get(
                    "success_rate"
                )
            ),
            optional_number(
                away_off.get(
                    "success_rate"
                )
            ),
            optional_number(
                home_def.get(
                    "success_rate"
                )
            ),
        ]

        if all(
            value is not None
            for value in values
        ):
            (
                home_sr,
                away_sr_def,
                away_sr,
                home_sr_def
            ) = values

            home_edge = (
                home_sr
                -
                away_sr_def
            )

            away_edge = (
                away_sr
                -
                home_sr_def
            )

            components[
                "success_rate"
            ] = bounded(
                (
                    home_edge
                    -
                    away_edge
                )
                * 0.035,
                0.75
            )

            availability[
                "success_rate"
            ] = True

    # -------------------------------------------------------------------------
    # EXPLOSIVENESS
    # -------------------------------------------------------------------------

    if both_have_general_sample(
        home,
        away
    ):
        values = [
            optional_number(
                home_off.get(
                    "explosive_rate"
                )
            ),
            optional_number(
                away_def.get(
                    "explosive_rate"
                )
            ),
            optional_number(
                away_off.get(
                    "explosive_rate"
                )
            ),
            optional_number(
                home_def.get(
                    "explosive_rate"
                )
            ),
        ]

        if all(
            value is not None
            for value in values
        ):
            (
                home_expl,
                away_expl_def,
                away_expl,
                home_expl_def
            ) = values

            home_edge = (
                home_expl
                -
                away_expl_def
            )

            away_edge = (
                away_expl
                -
                home_expl_def
            )

            components[
                "explosiveness"
            ] = bounded(
                (
                    home_edge
                    -
                    away_edge
                )
                * 0.025,
                0.50
            )

            availability[
                "explosiveness"
            ] = True

    # -------------------------------------------------------------------------
    # HAVOC
    # -------------------------------------------------------------------------

    if both_have_general_sample(
        home,
        away
    ):
        home_havoc_allowed = (
            optional_number(
                home_off.get(
                    "havoc_rate"
                )
            )
        )

        home_havoc_created = (
            optional_number(
                home_def.get(
                    "havoc_rate"
                )
            )
        )

        away_havoc_allowed = (
            optional_number(
                away_off.get(
                    "havoc_rate"
                )
            )
        )

        away_havoc_created = (
            optional_number(
                away_def.get(
                    "havoc_rate"
                )
            )
        )

        values = [
            home_havoc_allowed,
            home_havoc_created,
            away_havoc_allowed,
            away_havoc_created,
        ]

        if all(
            value is not None
            for value in values
        ):
            home_pressure_edge = (
                home_havoc_created
                -
                away_havoc_allowed
            )

            away_pressure_edge = (
                away_havoc_created
                -
                home_havoc_allowed
            )

            components[
                "havoc"
            ] = bounded(
                (
                    home_pressure_edge
                    -
                    away_pressure_edge
                )
                * 0.025,
                0.50
            )

            availability[
                "havoc"
            ] = True

    raw_total = sum(
        components.values()
    )

    total = bounded(
        raw_total,
        MAX_MATCHUP_ADJUSTMENT
    )

    comparable = any(
        availability.values()
    )

    return {
        "total":
            round(
                total,
                2
            ),

        "components": {
            key:
                round(
                    value,
                    2
                )
            for (
                key,
                value
            ) in components.items()
        },

        "available": availability,

        "comparable_live_sample":
            comparable,

        "note":
            (
                "Live matchup adjustments active."
                if comparable
                else
                "No comparable 2026 live sample; "
                "matchup adjustment held at zero."
            ),
    }


# =============================================================================
# TOTAL MODEL
# =============================================================================

def calculate_total(
    home,
    away
):
    """
    Total remains based on the blended MODEL profile.

    It does not directly compare Stanford live data to Miami missing data.
    """

    home_off = (
        home.get(
            "offense",
            {}
        )
        or {}
    )

    home_def = (
        home.get(
            "defense",
            {}
        )
        or {}
    )

    away_off = (
        away.get(
            "offense",
            {}
        )
        or {}
    )

    away_def = (
        away.get(
            "defense",
            {}
        )
        or {}
    )

    efficiency = (
        safe_number(
            home_off.get(
                "epa_play"
            )
        )
        +
        safe_number(
            away_off.get(
                "epa_play"
            )
        )
        -
        safe_number(
            home_def.get(
                "epa_play"
            )
        )
        -
        safe_number(
            away_def.get(
                "epa_play"
            )
        )
    )

    success = (
        safe_number(
            home_off.get(
                "success_rate"
            )
        )
        +
        safe_number(
            away_off.get(
                "success_rate"
            )
        )
        -
        85
    )

    total = (
        BASE_TOTAL
        +
        efficiency
        * 5.0
        +
        success
        * 0.15
    )

    total = bounded(
        total - BASE_TOTAL,
        27.5
    ) + BASE_TOTAL

    total = max(
        35,
        min(
            80,
            total
        )
    )

    return round_half(
        total
    )


# =============================================================================
# WIN PROBABILITY
# =============================================================================

def normal_cdf(value):
    return (
        1.0
        +
        math.erf(
            value
            /
            math.sqrt(2.0)
        )
    ) / 2.0


def calculate_win_probability(
    home_spread
):
    """
    home_spread:
        negative = home favored
        positive = away favored

    Convert to projected home margin and apply a conservative normal
    margin distribution.
    """

    projected_home_margin = (
        -safe_number(
            home_spread
        )
    )

    z = (
        projected_home_margin
        /
        WIN_PROB_STD_DEV
    )

    home_probability = (
        normal_cdf(z)
    )

    home_probability = max(
        0.01,
        min(
            0.99,
            home_probability
        )
    )

    away_probability = (
        1.0
        -
        home_probability
    )

    return {
        "home":
            round(
                home_probability
                * 100,
                1
            ),

        "away":
            round(
                away_probability
                * 100,
                1
            ),

        "method":
            (
                "Normal margin distribution, "
                f"σ={WIN_PROB_STD_DEV:.1f}"
            ),
    }


# =============================================================================
# MARKET COMPARISON
# =============================================================================

def adjusted_status_threshold(
    market_spread
):
    """
    A seven-point disagreement near pick'em means more than seven points
    when the market spread is -50.

    Large spreads therefore require a larger raw disagreement.
    """

    if market_spread is None:

        return {
            "play":
                None,

            "watch":
                None,
        }

    magnitude = abs(
        market_spread
    )

    if magnitude >= 35:

        return {
            "play": 10.0,
            "watch": 6.0,
        }

    if magnitude >= 21:

        return {
            "play": 8.5,
            "watch": 5.0,
        }

    return {
        "play": 7.0,
        "watch": 4.0,
    }


def compare_to_market(
    model_spread,
    market_spread,
    home_name,
    away_name
):
    if market_spread is None:

        return {
            "disagreement":
                None,

            "preferred_side":
                None,

            "status":
                "NO MARKET",

            "play_threshold":
                None,

            "watch_threshold":
                None,
        }

    difference = (
        model_spread
        -
        market_spread
    )

    disagreement = abs(
        difference
    )

    if difference < 0:

        preferred = home_name

    elif difference > 0:

        preferred = away_name

    else:

        preferred = None

    thresholds = (
        adjusted_status_threshold(
            market_spread
        )
    )

    if (
        disagreement
        >=
        thresholds["play"]
    ):

        status = "PLAY"

    elif (
        disagreement
        >=
        thresholds["watch"]
    ):

        status = "WATCH"

    else:

        status = "IN LINE"

    return {
        "disagreement":
            round(
                disagreement,
                1
            ),

        "preferred_side":
            preferred,

        "status":
            status,

        "play_threshold":
            thresholds["play"],

        "watch_threshold":
            thresholds["watch"],
    }


# =============================================================================
# INSIGHTS
# =============================================================================

def generate_insights(
    home_name,
    away_name,
    home,
    away,
    matchup,
    model_spread,
    market_spread
):
    insights = []

    home_rank = home.get(
        "power_rating_rank"
    )

    away_rank = away.get(
        "power_rating_rank"
    )

    if (
        home_rank
        and away_rank
        and home_rank != away_rank
    ):
        stronger = (
            home_name
            if home_rank < away_rank
            else away_name
        )

        insights.append({
            "title":
                "OVERALL TEAM STRENGTH",

            "text":
                (
                    f"{stronger} owns the stronger "
                    f"overall blended power rating."
                ),

            "source":
                "power_rating",
        })

    if not matchup[
        "comparable_live_sample"
    ]:

        insights.append({
            "title":
                "LIVE MATCHUP DATA",

            "text":
                (
                    "No live matchup adjustment is being "
                    "applied because both teams do not yet "
                    "have comparable 2026 samples."
                ),

            "source":
                "sample_guard",
        })

    else:

        components = matchup[
            "components"
        ]

        available = matchup[
            "available"
        ]

        usable = [
            (
                name,
                value
            )
            for (
                name,
                value
            )
            in components.items()
            if available.get(
                name
            )
            and
            abs(value) >= 0.15
        ]

        usable.sort(
            key=lambda item:
                abs(item[1]),
            reverse=True
        )

        for (
            name,
            value
        ) in usable[:2]:

            favored = (
                home_name
                if value > 0
                else away_name
            )

            label_map = {
                "passing":
                    "PASSING MATCHUP",

                "rushing":
                    "RUSHING MATCHUP",

                "success_rate":
                    "EFFICIENCY MATCHUP",

                "explosiveness":
                    "EXPLOSIVENESS",

                "havoc":
                    "HAVOC MATCHUP",
            }

            insights.append({
                "title":
                    label_map.get(
                        name,
                        name.upper()
                    ),

                "text":
                    (
                        f"The comparable 2026 sample "
                        f"leans toward {favored}."
                    ),

                "source":
                    name,
            })

    if market_spread is not None:

        difference = (
            model_spread
            -
            market_spread
        )

        if abs(
            difference
        ) >= 1.5:

            favored = (
                home_name
                if difference < 0
                else away_name
            )

            insights.append({
                "title":
                    "MARKET VS MODEL",

                "text":
                    (
                        f"The model is "
                        f"{abs(difference):.1f} points "
                        f"more favorable to {favored} "
                        f"than the current market."
                    ),

                "source":
                    "market",
            })

    return insights[:4]


# =============================================================================
# ODDS LOOKUP
# =============================================================================

def build_odds_lookup(
    odds
):
    lookup = {}

    for game in odds.get(
        "games",
        []
    ):

        home = game.get(
            "home_team"
        )

        away = game.get(
            "away_team"
        )

        if (
            home
            and away
        ):
            lookup[
                (
                    home,
                    away
                )
            ] = game

    return lookup


# =============================================================================
# BUILD PROJECTIONS
# =============================================================================

def build_projections(
    teams,
    schedule,
    odds,
    calibration
):
    print("")
    print(
        "🧮 Building projections..."
    )

    projections = []

    odds_lookup = (
        build_odds_lookup(
            odds
        )
    )

    market_matches = 0
    comparable_matchups = 0

    slope = calibration[
        "slope"
    ]

    for game in schedule[
        "games"
    ]:

        home_name = game[
            "home_team"
        ]

        away_name = game[
            "away_team"
        ]

        home = teams[
            home_name
        ]

        away = teams[
            away_name
        ]

        # ---------------------------------------------------------------------
        # POWER RATING FOUNDATION
        # ---------------------------------------------------------------------

        home_rating = safe_number(
            home.get(
                "power_rating"
            )
        )

        away_rating = safe_number(
            away.get(
                "power_rating"
            )
        )

        rating_difference = (
            home_rating
            -
            away_rating
        )

        rating_points = (
            rating_difference
            *
            slope
        )

        # Positive rating_points means home is stronger.
        rating_home_spread = (
            -rating_points
        )

        # ---------------------------------------------------------------------
        # HOME FIELD
        # ---------------------------------------------------------------------

        neutral = bool(
            game.get(
                "neutral_site",
                False
            )
        )

        hfa = (
            0.0
            if neutral
            else
            HOME_FIELD_ADVANTAGE
        )

        spread_after_hfa = (
            rating_home_spread
            -
            hfa
        )

        # ---------------------------------------------------------------------
        # MATCHUP ADJUSTMENT
        # ---------------------------------------------------------------------

        matchup = (
            calculate_matchup_adjustment(
                home,
                away
            )
        )

        if matchup[
            "comparable_live_sample"
        ]:
            comparable_matchups += 1

        model_spread_raw = (
            spread_after_hfa
            -
            matchup["total"]
        )

        model_spread = round_half(
            model_spread_raw
        )

        # ---------------------------------------------------------------------
        # TOTAL / WIN PROBABILITY
        # ---------------------------------------------------------------------

        model_total = (
            calculate_total(
                home,
                away
            )
        )

        win_probability = (
            calculate_win_probability(
                model_spread
            )
        )

        # ---------------------------------------------------------------------
        # MARKET
        # ---------------------------------------------------------------------

        market = odds_lookup.get(
            (
                home_name,
                away_name
            )
        )

        market_spread = None
        market_total = None
        bookmaker = None

        if market:

            market_matches += 1

            market_spread = (
                market.get(
                    "spread_home"
                )
            )

            market_total = (
                market.get(
                    "total"
                )
            )

            bookmaker = (
                market.get(
                    "bookmaker"
                )
            )

        comparison = (
            compare_to_market(
                model_spread,
                market_spread,
                home_name,
                away_name
            )
        )

        # ---------------------------------------------------------------------
        # OUTPUT
        # ---------------------------------------------------------------------

        projections.append({
            "game_id":
                game.get(
                    "id"
                ),

            "week":
                game.get(
                    "week"
                ),

            "start_date":
                game.get(
                    "start_date"
                ),

            "neutral_site":
                neutral,

            "venue":
                game.get(
                    "venue"
                ),

            "status":
                game.get(
                    "status"
                ),

            "home": {
                "team":
                    home_name,

                "conference":
                    home.get(
                        "conference"
                    ),

                "power_rating":
                    home_rating,

                "power_rating_rank":
                    home.get(
                        "power_rating_rank"
                    ),
            },

            "away": {
                "team":
                    away_name,

                "conference":
                    away.get(
                        "conference"
                    ),

                "power_rating":
                    away_rating,

                "power_rating_rank":
                    away.get(
                        "power_rating_rank"
                    ),
            },

            "projection": {
                "home_spread":
                    model_spread,

                "total":
                    model_total,

                "win_probability":
                    win_probability,

                "components": {
                    "home_power_rating":
                        round(
                            home_rating,
                            3
                        ),

                    "away_power_rating":
                        round(
                            away_rating,
                            3
                        ),

                    "rating_difference":
                        round(
                            rating_difference,
                            3
                        ),

                    "rating_points_home_edge":
                        round(
                            rating_points,
                            2
                        ),

                    "rating_only_home_spread":
                        round_half(
                            rating_home_spread
                        ),

                    "home_field_advantage":
                        hfa,

                    "spread_after_home_field":
                        round_half(
                            spread_after_hfa
                        ),

                    "matchup_adjustment":
                        matchup,

                    "final_home_spread":
                        model_spread,
                },

                # Keep these old fields too so the current frontend
                # does not break before we upgrade it.
                "base_home_spread":
                    round_half(
                        spread_after_hfa
                    ),

                "home_field_advantage":
                    hfa,

                "matchup_adjustment":
                    matchup,
            },

            "market": {
                "home_spread":
                    market_spread,

                "total":
                    market_total,

                "bookmaker":
                    bookmaker,
            },

            "comparison":
                comparison,

            "insights":
                generate_insights(
                    home_name,
                    away_name,
                    home,
                    away,
                    matchup,
                    model_spread,
                    market_spread
                ),
        })

    projections.sort(
        key=lambda game: (
            (
                game.get(
                    "week"
                )
                if game.get(
                    "week"
                )
                is not None
                else 99
            ),

            -(
                game[
                    "comparison"
                ].get(
                    "disagreement"
                )
                or -1
            ),

            game.get(
                "start_date"
            )
            or "",
        )
    )

    print(
        f"✅ Projections built: "
        f"{len(projections)}"
    )

    print(
        f"✅ Projections with market "
        f"match: {market_matches}"
    )

    print(
        f"✅ Games with comparable "
        f"live matchup samples: "
        f"{comparable_matchups}"
    )

    return projections


# =============================================================================
# SANITY CHECKS
# =============================================================================

def validate_projection_output(
    projections
):
    if len(
        projections
    ) < 400:

        print(
            "❌ Too few projections."
        )

        sys.exit(1)

    impossible_probabilities = []

    for game in projections:

        win = (
            game.get(
                "projection",
                {}
            )
            .get(
                "win_probability",
                {}
            )
        )

        home = optional_number(
            win.get(
                "home"
            )
        )

        away = optional_number(
            win.get(
                "away"
            )
        )

        if (
            home is None
            or away is None
        ):
            impossible_probabilities.append(
                game.get(
                    "game_id"
                )
            )

            continue

        if (
            home < 0
            or home > 100
            or away < 0
            or away > 100
            or abs(
                (
                    home + away
                )
                -
                100
            )
            >
            0.2
        ):
            impossible_probabilities.append(
                game.get(
                    "game_id"
                )
            )

    if impossible_probabilities:

        print(
            "❌ Win probability "
            "sanity check failed."
        )

        sys.exit(1)

    print(
        "✅ Projection sanity "
        "checks passed"
    )


# =============================================================================
# SAVE
# =============================================================================

def save_json(
    path,
    data
):
    os.makedirs(
        os.path.dirname(
            path
        ),
        exist_ok=True
    )

    temp_path = (
        path
        +
        ".tmp"
    )

    with open(
        temp_path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False
        )

    with open(
        temp_path,
        "r",
        encoding="utf-8"
    ) as file:

        json.load(
            file
        )

    os.replace(
        temp_path,
        path
    )

    print(
        f"💾 Saved {path} "
        f"({os.path.getsize(path) / 1024:.1f} KB)"
    )


# =============================================================================
# MAIN
# =============================================================================

def main():
    print(
        "=" * 70
    )

    print(
        "🏈 CFB ANALYTICS — "
        "PROJECTION ENGINE"
    )

    print(
        "=" * 70
    )

    print(
        f"Season: {YEAR}"
    )

    print(
        f"Generated: "
        f"{datetime.now().isoformat()}"
    )

    (
        metrics_data,
        teams
    ) = load_metrics()

    valid_teams = set(
        teams.keys()
    )

    lookup = (
        build_team_lookup(
            valid_teams
        )
    )

    calibration = (
        calculate_rating_scale(
            teams
        )
    )

    # -------------------------------------------------------------------------
    # ODDS
    # -------------------------------------------------------------------------

    odds = fetch_odds(
        valid_teams,
        lookup
    )

    save_json(
        ODDS_PATH,
        odds
    )

    # -------------------------------------------------------------------------
    # SCHEDULE
    # -------------------------------------------------------------------------

    schedule = fetch_schedule(
        valid_teams,
        lookup
    )

    verify_known_schedule_errors(
        schedule
    )

    save_json(
        SCHEDULE_PATH,
        schedule
    )

    # -------------------------------------------------------------------------
    # PROJECTIONS
    # -------------------------------------------------------------------------

    projections = (
        build_projections(
            teams,
            schedule,
            odds,
            calibration
        )
    )

    validate_projection_output(
        projections
    )

    output = {
        "meta": {
            "year":
                YEAR,

            "generated":
                datetime.now()
                .isoformat(),

            "games":
                len(projections),

            "version":
                "2.0-explainable",

            "calibration":
                calibration,

            "home_field_advantage":
                HOME_FIELD_ADVANTAGE,

            "max_matchup_adjustment":
                MAX_MATCHUP_ADJUSTMENT,

            "win_probability_std_dev":
                WIN_PROB_STD_DEV,

            "live_matchup_rules": {
                "minimum_plays":
                    MIN_LIVE_PLAYS,

                "minimum_pass_plays":
                    MIN_LIVE_PASS_PLAYS,

                "minimum_rush_plays":
                    MIN_LIVE_RUSH_PLAYS,

                "requires_both_teams":
                    True,
            },

            "metrics_through_week":
                (
                    metrics_data
                    .get(
                        "meta",
                        {}
                    )
                    .get(
                        "through_week"
                    )
                ),

            "schedule_matching":
                (
                    "Strict exact FBS school "
                    "matching; no CFBD prefix matching."
                ),
        },

        "games":
            projections,
    }

    save_json(
        PROJECTIONS_PATH,
        output
    )

    print("")
    print(
        "=" * 70
    )

    print(
        "🎉 PROJECTION BUILD COMPLETE"
    )

    print(
        "=" * 70
    )

    print(
        f"FBS-vs-FBS schedule games: "
        f"{len(schedule['games'])}"
    )

    print(
        f"Market games: "
        f"{len(odds['games'])}"
    )

    print(
        f"Projections built: "
        f"{len(projections)}"
    )


if __name__ == "__main__":
    main()
