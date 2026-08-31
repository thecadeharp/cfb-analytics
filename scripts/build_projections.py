"""
CFB ANALYTICS
build_projections.py

Builds:
    data/schedule.json
    data/odds.json
    data/projections.json

IMPORTANT:
CFBD schedule matching is STRICT.

Indiana State != Indiana
Florida State != Florida
South Carolina State != South Carolina

Sportsbook names may include mascots, so sportsbook matching has a
separate, carefully guarded matcher.
"""

import json
import os
import statistics
import sys
import unicodedata
from datetime import datetime

import requests


YEAR = 2026

CFBD_BASE = "https://api.collegefootballdata.com"
ODDS_BASE = "https://api.the-odds-api.com/v4"

METRICS_PATH = "data/cfb_metrics.json"
SCHEDULE_PATH = "data/schedule.json"
ODDS_PATH = "data/odds.json"
PROJECTIONS_PATH = "data/projections.json"

HOME_FIELD_ADVANTAGE = 2.0
MAX_MATCHUP_ADJUSTMENT = 3.0
BASE_TOTAL = 52.5


# =============================================================================
# KEYS
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
    os.environ.get("CFBD_API_KEY", "")
)

ODDS_API_KEY = clean_api_key(
    os.environ.get("ODDS_API_KEY", "")
)


# =============================================================================
# HELPERS
# =============================================================================

def safe_number(value, default=0.0):
    try:
        if value is None:
            return default

        return float(value)

    except (TypeError, ValueError):
        return default


def round_half(value):
    return round(value * 2) / 2


def first_value(data, *keys, default=None):
    for key in keys:
        if key in data and data.get(key) is not None:
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
        if not unicodedata.combining(character)
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
        text = text.replace(old, new)

    return " ".join(text.split())


# =============================================================================
# APPROVED SCHOOL ALIASES
# =============================================================================

ALIASES = {
    "miami fl": "Miami",
    "miami florida": "Miami",

    "uconn": "Connecticut",
    "connecticut": "Connecticut",

    "umass": "Massachusetts",

    "southern miss": "Southern Mississippi",

    "utsa": "UT San Antonio",
    "texas san antonio": "UT San Antonio",

    "fiu": "Florida International",

    "fau": "Florida Atlantic",

    "app state": "Appalachian State",

    "nc state": "NC State",
    "n c state": "NC State",

    "hawaii": "Hawai'i",

    "mississippi": "Ole Miss",

    "ul lafayette": "Louisiana",
    "louisiana lafayette": "Louisiana",

    "ulm": "Louisiana Monroe",
    "ul monroe": "Louisiana Monroe",

    "middle tennessee state": "Middle Tennessee",

    "sam houston state": "Sam Houston",
}


# =============================================================================
# TEAM MATCHERS
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
    STRICT school matching for CFBD.

    We NEVER use prefix matching here.

    Indiana State cannot become Indiana.
    Florida State cannot become Florida.
    """

    if not provider_name:
        return None

    canon = canonical_name(
        provider_name
    )

    # Exact model name.
    if canon in lookup:
        return lookup[canon]

    # Explicitly approved alias.
    alias = ALIASES.get(canon)

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
    "a&m",
}


def resolve_odds_team(
    provider_name,
    valid_teams,
    lookup
):
    """
    Sportsbooks commonly append mascots:

        Ohio State Buckeyes
        Georgia Bulldogs
        Alabama Crimson Tide

    Exact names and aliases are preferred.

    Prefix matching is allowed ONLY when the text immediately after the
    model school name does not look like part of another school's name.
    """

    if not provider_name:
        return None

    canon = canonical_name(
        provider_name
    )

    # Exact.
    if canon in lookup:
        return lookup[canon]

    # Explicit alias.
    if canon in ALIASES:
        alias = ALIASES[canon]

        if alias in valid_teams:
            return alias

    candidates = []

    for model_canon, model_name in lookup.items():

        prefix = model_canon + " "

        if not canon.startswith(prefix):
            continue

        remainder = canon[
            len(prefix):
        ].strip()

        if not remainder:
            continue

        first_word = remainder.split()[0]

        # Important:
        # Indiana State Sycamores must NOT match Indiana.
        if first_word in SCHOOL_STRUCTURE_WORDS:
            continue

        candidates.append(
            (
                len(model_canon),
                model_name
            )
        )

    if not candidates:
        return None

    # Longest legitimate school name wins.
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
        print("❌ CFBD_API_KEY missing.")
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
        print("")
        print(
            "❌ CFBD AUTHENTICATION FAILED"
        )
        print(
            f"HTTP {response.status_code}"
        )

        sys.exit(1)

    if not response.ok:

        print("")
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

    used = response.headers.get(
        "x-requests-used"
    )

    if remaining is not None:
        print(
            f"   Odds API requests remaining: "
            f"{remaining}"
        )

    if used is not None:
        print(
            f"   Odds API requests used: "
            f"{used}"
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
            f"❌ Missing {METRICS_PATH}"
        )

        sys.exit(1)

    with open(
        METRICS_PATH,
        "r",
        encoding="utf-8"
    ) as file:

        data = json.load(file)

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

    return data, teams


# =============================================================================
# RATING CALIBRATION
# =============================================================================

def calculate_rating_scale(teams):

    x_values = []
    y_values = []

    for team in teams.values():

        power = safe_number(
            team.get(
                "power_rating"
            ),
            None
        )

        sp = safe_number(
            (
                team.get(
                    "sp_plus",
                    {}
                )
                or {}
            ).get(
                "overall"
            ),
            None
        )

        if power is None or sp is None:
            continue

        x_values.append(power)
        y_values.append(sp)

    if len(x_values) < 10:

        return {
            "slope": 7.5,
            "intercept": 0,
            "method": "fallback",
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
        numerator / denominator
        if denominator
        else 7.5
    )

    intercept = (
        y_mean
        - slope * x_mean
    )

    print("")
    print(
        "📐 Power rating calibration:"
    )

    print(
        f"   Point conversion slope: "
        f"{slope:.3f}"
    )

    return {
        "slope": slope,
        "intercept": intercept,
        "method":
            "regression against SP+ scale",
    }


# =============================================================================
# ODDS
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

    for bookmaker_key in preferred_books:

        for bookmaker in bookmakers:

            if (
                bookmaker.get("key")
                == bookmaker_key
            ):

                selected = bookmaker
                break

        if selected:
            break

    if not selected and bookmakers:
        selected = bookmakers[0]

    if not selected:

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

        if market.get("key") == "spreads":

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
                    == raw_home
                ):

                    spread = safe_number(
                        outcome.get(
                            "point"
                        ),
                        None
                    )

        elif market.get("key") == "totals":

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
                    == "over"
                ):

                    total = safe_number(
                        outcome.get(
                            "point"
                        ),
                        None
                    )

    return {
        "spread": spread,
        "total": total,
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
        "💰 Fetching current NCAAF "
        "market odds..."
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

        if not home and raw_home:
            unmatched.add(raw_home)

        if not away and raw_away:
            unmatched.add(raw_away)

        market = extract_market(raw)

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
            and game["away_team"]
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
            "team examples:"
        )

        for team in sorted(
            unmatched
        )[:15]:

            print(
                f"   - {team}"
            )

    return {
        "meta": {
            "year": YEAR,

            "generated":
                datetime.now().isoformat(),

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
        f"📅 Fetching {YEAR} FBS "
        f"schedule..."
    )

    raw_games = cfbd_get(
        "/games",
        {
            "year":
                YEAR,

            "seasonType":
                "regular",

            # Important:
            # Ask CFBD specifically for FBS schedule data.
            "classification":
                "fbs",
        }
    )

    print(
        f"   Raw CFBD games returned: "
        f"{len(raw_games)}"
    )

    games = []

    rejected_fcs = 0
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

        # STRICT MATCHER.
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

        # If either side isn't one of our rated FBS teams,
        # exclude the game entirely.
        if not home or not away:

            rejected_fcs += 1

            if not home and raw_home:
                rejected_examples.add(
                    str(raw_home)
                )

            if not away and raw_away:
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

        seen.add(unique_key)

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

            "season_type":
                first_value(
                    raw,
                    "seasonType",
                    "season_type",
                    default="regular"
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
                            and away_points
                            is not None
                        )
                    )
                    else "scheduled"
                ),
        })

    games.sort(
        key=lambda game: (
            (
                game["week"]
                if game["week"]
                is not None
                else 99
            ),

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
        f"🚫 Games rejected because "
        f"one side isn't in our FBS model: "
        f"{rejected_fcs}"
    )

    if rejected_examples:

        print("")
        print(
            "🔎 Correctly rejected examples:"
        )

        for team in sorted(
            rejected_examples
        )[:20]:

            print(
                f"   - {team}"
            )

    # Sanity check.
    if len(games) < 400:

        print("")
        print(
            "❌ SANITY CHECK FAILED"
        )

        print(
            f"Only {len(games)} "
            "FBS-vs-FBS games matched."
        )

        print(
            "Refusing to publish until "
            "team matching is checked."
        )

        sys.exit(1)

    return {
        "meta": {
            "year":
                YEAR,

            "generated":
                datetime.now().isoformat(),

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
# MATCHUP MODEL
# =============================================================================

def metric_advantage(
    offense,
    defense,
    scale,
    cap
):

    advantage = (
        safe_number(offense)
        -
        safe_number(defense)
    ) * scale

    return max(
        -cap,
        min(
            cap,
            advantage
        )
    )


def calculate_matchup_adjustment(
    home,
    away
):

    ho = home.get(
        "offense",
        {}
    ) or {}

    hd = home.get(
        "defense",
        {}
    ) or {}

    ao = away.get(
        "offense",
        {}
    ) or {}

    ad = away.get(
        "defense",
        {}
    ) or {}

    passing = (
        metric_advantage(
            ho.get("epa_pass"),
            ad.get("epa_pass"),
            2.0,
            1.25
        )
        -
        metric_advantage(
            ao.get("epa_pass"),
            hd.get("epa_pass"),
            2.0,
            1.25
        )
    )

    rushing = (
        metric_advantage(
            ho.get("epa_rush"),
            ad.get("epa_rush"),
            1.5,
            1.0
        )
        -
        metric_advantage(
            ao.get("epa_rush"),
            hd.get("epa_rush"),
            1.5,
            1.0
        )
    )

    efficiency = (
        metric_advantage(
            ho.get("epa_play"),
            ad.get("epa_play"),
            1.5,
            1.0
        )
        -
        metric_advantage(
            ao.get("epa_play"),
            hd.get("epa_play"),
            1.5,
            1.0
        )
    )

    success = (
        metric_advantage(
            ho.get("success_rate"),
            ad.get("success_rate"),
            0.08,
            0.75
        )
        -
        metric_advantage(
            ao.get("success_rate"),
            hd.get("success_rate"),
            0.08,
            0.75
        )
    )

    components = {
        "passing":
            passing,

        "rushing":
            rushing,

        "overall_efficiency":
            efficiency,

        "success_rate":
            success,
    }

    raw_total = sum(
        components.values()
    )

    total = max(
        -MAX_MATCHUP_ADJUSTMENT,
        min(
            MAX_MATCHUP_ADJUSTMENT,
            raw_total
        )
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

            for key, value
            in components.items()
        },
    }


def calculate_total(
    home,
    away
):

    ho = home.get(
        "offense",
        {}
    ) or {}

    hd = home.get(
        "defense",
        {}
    ) or {}

    ao = away.get(
        "offense",
        {}
    ) or {}

    ad = away.get(
        "defense",
        {}
    ) or {}

    efficiency = (
        safe_number(
            ho.get("epa_play")
        )
        +
        safe_number(
            ao.get("epa_play")
        )
        -
        safe_number(
            hd.get("epa_play")
        )
        -
        safe_number(
            ad.get("epa_play")
        )
    )

    success = (
        safe_number(
            ho.get("success_rate")
        )
        +
        safe_number(
            ao.get("success_rate")
        )
        - 85
    )

    total = (
        BASE_TOTAL
        + efficiency * 5
        + success * 0.15
    )

    total = max(
        35,
        min(
            80,
            total
        )
    )

    return round_half(total)


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
                "POWER RATING EDGE",

            "text":
                (
                    f"{stronger} owns the "
                    f"stronger overall model profile."
                ),
        })

    passing = matchup[
        "components"
    ].get(
        "passing",
        0
    )

    if abs(passing) >= 0.3:

        favored = (
            home_name
            if passing > 0
            else away_name
        )

        insights.append({
            "title":
                "PASSING MATCHUP",

            "text":
                (
                    f"{favored} has the more "
                    f"favorable passing efficiency matchup."
                ),
        })

    if market_spread is not None:

        difference = (
            model_spread
            -
            market_spread
        )

        if abs(difference) >= 1.5:

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
                        f"The model differs from "
                        f"the market toward "
                        f"{favored} by "
                        f"{abs(difference):.1f} points."
                    ),
            })

    return insights[:4]


# =============================================================================
# BUILD PROJECTIONS
# =============================================================================

def build_odds_lookup(odds):

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

        if home and away:

            lookup[
                (
                    home,
                    away
                )
            ] = game

    return lookup


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

    market_matches = 0

    odds_lookup = build_odds_lookup(
        odds
    )

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

        point_difference = (
            rating_difference
            *
            slope
        )

        neutral = game.get(
            "neutral_site",
            False
        )

        hfa = (
            0
            if neutral
            else HOME_FIELD_ADVANTAGE
        )

        base_spread = (
            -point_difference
            - hfa
        )

        matchup = (
            calculate_matchup_adjustment(
                home,
                away
            )
        )

        model_spread = round_half(
            base_spread
            -
            matchup["total"]
        )

        model_total = calculate_total(
            home,
            away
        )

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

        disagreement = None
        preferred = None
        label = "NO MARKET"

        if market_spread is not None:

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

            if disagreement >= 7:

                label = "PLAY"

            elif disagreement >= 4:

                label = "WATCH"

            else:

                label = "IN LINE"

        confidence = 50

        if disagreement is not None:

            confidence += min(
                30,
                disagreement * 2
            )

        confidence = int(
            max(
                35,
                min(
                    95,
                    confidence
                )
            )
        )

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

                "base_home_spread":
                    round_half(
                        base_spread
                    ),

                "home_field_advantage":
                    hfa,

                "matchup_adjustment":
                    matchup,

                "confidence":
                    confidence,
            },

            "market": {
                "home_spread":
                    market_spread,

                "total":
                    market_total,

                "bookmaker":
                    bookmaker,
            },

            "comparison": {
                "disagreement":
                    (
                        round(
                            disagreement,
                            1
                        )
                        if disagreement
                        is not None
                        else None
                    ),

                "preferred_side":
                    preferred,

                "status":
                    label,
            },

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

    return projections


# =============================================================================
# SANITY CHECKS
# =============================================================================

def verify_known_schedule_errors(
    schedule
):
    """
    Explicit guardrails against the exact false matches we discovered.
    """

    games = schedule.get(
        "games",
        []
    )

    bad_games = []

    for game in games:

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

        # Indiana / Purdue is Nov 28,
        # not Purdue's Indiana State opener.
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

                bad_games.append(
                    (
                        "Indiana/Purdue",
                        date
                    )
                )

        # Florida hosts South Carolina Oct 10.
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

                bad_games.append(
                    (
                        "Florida/South Carolina",
                        date
                    )
                )

    if bad_games:

        print("")
        print(
            "❌ SCHEDULE SANITY CHECK FAILED"
        )

        for matchup, date in bad_games:

            print(
                f"   {matchup}: {date}"
            )

        print(
            "Refusing to publish "
            "known-false schedule data."
        )

        sys.exit(1)

    print("")
    print(
        "✅ Known schedule sanity "
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
        os.path.dirname(path),
        exist_ok=True
    )

    temp = path + ".tmp"

    with open(
        temp,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False
        )

    # Make sure JSON is valid.
    with open(
        temp,
        "r",
        encoding="utf-8"
    ) as file:

        json.load(file)

    os.replace(
        temp,
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

    print("=" * 70)
    print(
        "🏈 CFB ANALYTICS — "
        "PROJECTION ENGINE"
    )
    print("=" * 70)

    print(
        f"Season: {YEAR}"
    )

    print(
        f"Generated: "
        f"{datetime.now().isoformat()}"
    )

    _, teams = load_metrics()

    valid_teams = set(
        teams.keys()
    )

    lookup = build_team_lookup(
        valid_teams
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

    # Explicit checks for the bugs we just found.
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

    projections = build_projections(
        teams,
        schedule,
        odds,
        calibration
    )

    if len(projections) < 400:

        print("")
        print(
            "❌ Too few projections built."
        )

        print(
            "Refusing to publish."
        )

        sys.exit(1)

    output = {
        "meta": {
            "year":
                YEAR,

            "generated":
                datetime.now().isoformat(),

            "games":
                len(projections),

            "version":
                "1.3-strict-schedule",

            "calibration":
                calibration,

            "home_field_advantage":
                HOME_FIELD_ADVANTAGE,

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
    print("=" * 70)
    print(
        "🎉 PROJECTION BUILD COMPLETE"
    )
    print("=" * 70)

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
