"""
HAMMER TIME CFB ANALYTICS
build_projections.py

Builds:
    data/schedule.json
    data/odds.json
    data/projections.json

Architecture:
    APIs
      ↓
    GitHub Actions
      ↓
    Static JSON
      ↓
    GitHub Pages

API keys are used only inside GitHub Actions.
They are never sent to the browser.
"""

import json
import os
import statistics
import sys
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
MAX_MATCHUP_ADJUSTMENT = 3.0
BASE_TOTAL = 52.5


# =============================================================================
# API KEY CLEANING
# =============================================================================

def clean_api_key(raw_key):
    if raw_key is None:
        return ""

    key = str(raw_key).strip()

    if (
        len(key) >= 2
        and key[0] == key[-1]
        and key[0] in ("'", '"')
    ):
        key = key[1:-1].strip()

    if key.lower().startswith("bearer "):
        key = key[7:].strip()

    key = (
        key
        .replace("\r", "")
        .replace("\n", "")
        .replace("\t", "")
        .strip()
    )

    return key


CFBD_API_KEY = clean_api_key(
    os.environ.get("CFBD_API_KEY", "")
)

ODDS_API_KEY = clean_api_key(
    os.environ.get("ODDS_API_KEY", "")
)


# =============================================================================
# BASIC HELPERS
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
    """
    Accept both old snake_case and newer camelCase API fields.
    """

    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)

    return default


def canonical_name(value):
    """
    Converts provider team names to a comparison-friendly string.

    Example:
        "Ohio State Buckeyes" -> "ohio state buckeyes"
        "San José State"      -> "san jose state"
    """

    if not value:
        return ""

    text = str(value).strip().lower()

    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ñ": "n",
        "’": "",
        "'": "",
        ".": "",
        ",": "",
        "&": "and",
        "-": " ",
        "_": " ",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return " ".join(
        text.split()
    )


# =============================================================================
# TEAM NAME ALIASES
# =============================================================================

TEAM_ALIASES = {
    # Miami
    "miami fl": "Miami",
    "miami florida": "Miami",
    "miami hurricanes": "Miami",

    # Connecticut
    "uconn": "Connecticut",
    "uconn huskies": "Connecticut",
    "connecticut huskies": "Connecticut",

    # Massachusetts
    "umass": "Massachusetts",
    "umass minutemen": "Massachusetts",

    # Southern Miss
    "southern miss": "Southern Mississippi",
    "southern miss golden eagles": "Southern Mississippi",

    # UTSA
    "utsa": "UT San Antonio",
    "utsa roadrunners": "UT San Antonio",
    "texas san antonio": "UT San Antonio",
    "texas san antonio roadrunners": "UT San Antonio",

    # UTEP
    "utep miners": "UTEP",

    # FIU
    "fiu": "Florida International",
    "fiu panthers": "Florida International",

    # FAU
    "fau": "Florida Atlantic",
    "fau owls": "Florida Atlantic",

    # Appalachian State
    "app state": "Appalachian State",
    "app state mountaineers": "Appalachian State",

    # NC State
    "n c state": "NC State",
    "nc state wolfpack": "NC State",

    # San Jose State
    "san jose state spartans": "San Jose State",

    # Hawaii
    "hawaii": "Hawai'i",
    "hawaii rainbow warriors": "Hawai'i",

    # Ole Miss
    "mississippi rebels": "Ole Miss",
    "ole miss rebels": "Ole Miss",

    # Louisiana
    "louisiana lafayette": "Louisiana",
    "ul lafayette": "Louisiana",
    "louisiana ragin cajuns": "Louisiana",

    # Louisiana Monroe
    "ul monroe": "Louisiana Monroe",
    "ulm": "Louisiana Monroe",
    "louisiana monroe warhawks": "Louisiana Monroe",

    # Middle Tennessee
    "middle tennessee state": "Middle Tennessee",
    "middle tennessee blue raiders": "Middle Tennessee",

    # Bowling Green
    "bowling green falcons": "Bowling Green",

    # Western Kentucky
    "western kentucky hilltoppers": "Western Kentucky",

    # Eastern Michigan
    "eastern michigan eagles": "Eastern Michigan",

    # Central Michigan
    "central michigan chippewas": "Central Michigan",

    # Western Michigan
    "western michigan broncos": "Western Michigan",

    # Georgia Southern
    "georgia southern eagles": "Georgia Southern",

    # Georgia State
    "georgia state panthers": "Georgia State",

    # Coastal Carolina
    "coastal carolina chanticleers": "Coastal Carolina",

    # James Madison
    "james madison dukes": "James Madison",

    # Jacksonville State
    "jacksonville state gamecocks": "Jacksonville State",

    # Kennesaw State
    "kennesaw state owls": "Kennesaw State",

    # Sam Houston
    "sam houston state": "Sam Houston",
    "sam houston bearkats": "Sam Houston",

    # New Mexico State
    "new mexico state aggies": "New Mexico State",

    # Liberty
    "liberty flames": "Liberty",

    # Army
    "army black knights": "Army",

    # Navy
    "navy midshipmen": "Navy",

    # Air Force
    "air force falcons": "Air Force",

    # Notre Dame
    "notre dame fighting irish": "Notre Dame",

    # BYU
    "byu cougars": "BYU",

    # TCU
    "tcu horned frogs": "TCU",

    # SMU
    "smu mustangs": "SMU",

    # UCF
    "ucf knights": "UCF",

    # USC
    "usc trojans": "USC",

    # UCLA
    "ucla bruins": "UCLA",

    # LSU
    "lsu tigers": "LSU",

    # UNLV
    "unlv rebels": "UNLV",
}


# =============================================================================
# TEAM MATCHING
# =============================================================================

def build_team_matcher(valid_teams):
    """
    Build canonical lookup from the exact names contained in
    data/cfb_metrics.json.
    """

    lookup = {}

    for team_name in valid_teams:
        lookup[
            canonical_name(team_name)
        ] = team_name

    return lookup


def resolve_team_name(
    provider_name,
    valid_teams,
    team_lookup
):
    """
    Resolve CFBD / sportsbook names to our model team names.

    Strategy:
    1. Explicit aliases.
    2. Exact canonical match.
    3. Remove common sportsbook mascot suffixes automatically by
       checking whether the provider name begins with one of our
       model team names.
    4. A few directional/state-name compatibility checks.
    """

    if not provider_name:
        return None

    raw = str(provider_name).strip()
    canon = canonical_name(raw)

    # -------------------------------------------------------------------------
    # EXPLICIT ALIAS
    # -------------------------------------------------------------------------

    if canon in TEAM_ALIASES:
        alias = TEAM_ALIASES[canon]

        if alias in valid_teams:
            return alias

    # -------------------------------------------------------------------------
    # EXACT MATCH
    # -------------------------------------------------------------------------

    if canon in team_lookup:
        return team_lookup[canon]

    # -------------------------------------------------------------------------
    # PROVIDER NAME MAY INCLUDE MASCOT
    #
    # Example:
    # Ohio State Buckeyes
    #
    # Model:
    # Ohio State
    # -------------------------------------------------------------------------

    candidate_matches = []

    for model_canon, model_name in (
        team_lookup.items()
    ):
        if canon.startswith(
            model_canon + " "
        ):
            candidate_matches.append(
                (
                    len(model_canon),
                    model_name
                )
            )

    if candidate_matches:
        candidate_matches.sort(
            reverse=True
        )

        return candidate_matches[0][1]

    # -------------------------------------------------------------------------
    # REVERSE CHECK
    # -------------------------------------------------------------------------

    candidate_matches = []

    for model_canon, model_name in (
        team_lookup.items()
    ):
        if model_canon.startswith(
            canon + " "
        ):
            candidate_matches.append(
                (
                    len(canon),
                    model_name
                )
            )

    if candidate_matches:
        candidate_matches.sort(
            reverse=True
        )

        return candidate_matches[0][1]

    return None


# =============================================================================
# CFBD API
# =============================================================================

def cfbd_get(
    endpoint,
    params=None,
    required=True
):
    if not CFBD_API_KEY:
        print("")
        print("❌ CFBD_API_KEY is missing.")
        sys.exit(1)

    headers = {
        "Authorization": (
            f"Bearer {CFBD_API_KEY}"
        ),
        "Accept": "application/json",
    }

    try:
        response = requests.get(
            f"{CFBD_BASE}{endpoint}",
            headers=headers,
            params=params,
            timeout=45
        )

    except requests.RequestException as error:
        print("")
        print(
            f"❌ CFBD request error: "
            f"{endpoint}"
        )
        print(f"   {error}")

        if required:
            sys.exit(1)

        return None

    if response.status_code in (
        401,
        403
    ):
        print("")
        print(
            "❌ CFBD AUTHENTICATION FAILED"
        )
        print(
            f"   HTTP {response.status_code}"
        )
        print(
            "   Check the CFBD_API_KEY "
            "GitHub Secret."
        )

        sys.exit(1)

    if not response.ok:
        print("")
        print(
            f"⚠ CFBD {endpoint} returned "
            f"HTTP {response.status_code}"
        )

        try:
            print(
                f"   {response.text[:500]}"
            )
        except Exception:
            pass

        if required:
            sys.exit(1)

        return None

    try:
        return response.json()

    except ValueError:
        print("")
        print(
            f"❌ CFBD returned invalid JSON "
            f"for {endpoint}"
        )

        if required:
            sys.exit(1)

        return None


# =============================================================================
# ODDS API
# =============================================================================

def odds_get(
    endpoint,
    params=None
):
    if not ODDS_API_KEY:
        print("")
        print(
            "⚠ ODDS_API_KEY missing."
        )
        print(
            "   Continuing without market odds."
        )

        return []

    try:
        response = requests.get(
            f"{ODDS_BASE}{endpoint}",
            params=params,
            timeout=45
        )

    except requests.RequestException as error:
        print("")
        print(
            "⚠ Odds API request failed."
        )
        print(f"   {error}")

        return []

    if not response.ok:
        print("")
        print(
            f"⚠ Odds API returned "
            f"HTTP {response.status_code}"
        )

        try:
            print(
                f"   {response.text[:500]}"
            )
        except Exception:
            pass

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

    try:
        return response.json()

    except ValueError:
        print(
            "⚠ Odds API returned invalid JSON."
        )

        return []


# =============================================================================
# LOAD MODEL DATA
# =============================================================================

def load_metrics():
    if not os.path.exists(
        METRICS_PATH
    ):
        print(
            f"❌ Could not find "
            f"{METRICS_PATH}"
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

    if not teams:
        print(
            "❌ No teams found in "
            "cfb_metrics.json"
        )
        sys.exit(1)

    print(
        f"✅ Loaded existing ratings for "
        f"{len(teams)} teams"
    )

    return data, teams


# =============================================================================
# POWER RATING CALIBRATION
# =============================================================================

def calculate_rating_scale(teams):
    """
    Convert our normalized model rating scale into approximate
    football points by regressing against SP+.
    """

    x_values = []
    y_values = []

    for team in teams.values():

        power = safe_number(
            team.get(
                "power_rating"
            ),
            None
        )

        sp_plus = safe_number(
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

        if (
            power is None
            or sp_plus is None
        ):
            continue

        x_values.append(
            power
        )

        y_values.append(
            sp_plus
        )

    if len(x_values) < 10:
        print("")
        print(
            "⚠ Not enough SP+ values "
            "for calibration."
        )
        print(
            "   Using fallback slope 7.5."
        )

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
        for x in x_values
    )

    if denominator == 0:
        slope = 7.5
    else:
        slope = (
            numerator
            / denominator
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

    print(
        "   Method: regression against "
        "SP+ scale"
    )

    return {
        "slope": slope,
        "intercept": intercept,
        "method": (
            "sp_plus_regression"
        ),
    }


# =============================================================================
# ODDS MARKET EXTRACTION
# =============================================================================

def extract_best_market(raw_game):
    """
    Choose a representative sportsbook.

    Preference:
        DraftKings
        FanDuel
        BetMGM
        Caesars
        BetOnline
        first available
    """

    bookmakers = raw_game.get(
        "bookmakers",
        []
    )

    if not bookmakers:
        return {
            "spread": None,
            "total": None,
            "bookmaker": None,
        }

    preference = [
        "draftkings",
        "fanduel",
        "betmgm",
        "caesars",
        "betonlineag",
    ]

    selected = None

    for key in preference:
        for book in bookmakers:
            if book.get("key") == key:
                selected = book
                break

        if selected:
            break

    if not selected:
        selected = bookmakers[0]

    raw_home = raw_game.get(
        "home_team"
    )

    spread = None
    total = None

    for market in selected.get(
        "markets",
        []
    ):

        market_key = market.get(
            "key"
        )

        if market_key == "spreads":

            for outcome in market.get(
                "outcomes",
                []
            ):

                if (
                    canonical_name(
                        outcome.get("name")
                    )
                    ==
                    canonical_name(
                        raw_home
                    )
                ):
                    spread = safe_number(
                        outcome.get("point"),
                        None
                    )
                    break

        elif market_key == "totals":

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
                        outcome.get("point"),
                        None
                    )
                    break

    return {
        "spread": spread,
        "total": total,
        "bookmaker": selected.get(
            "title"
        ),
    }


# =============================================================================
# FETCH ODDS
# =============================================================================

def fetch_odds(
    valid_teams,
    team_lookup
):
    print("")
    print(
        "💰 Fetching current NCAAF "
        "market odds..."
    )

    raw_odds = odds_get(
        (
            "/sports/"
            "americanfootball_ncaaf/"
            "odds"
        ),
        {
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": (
                "spreads,totals"
            ),
            "oddsFormat": "american",
            "dateFormat": "iso",
        }
    )

    games = []

    unmatched = set()

    for raw_game in raw_odds:

        raw_home = raw_game.get(
            "home_team"
        )

        raw_away = raw_game.get(
            "away_team"
        )

        home = resolve_team_name(
            raw_home,
            valid_teams,
            team_lookup
        )

        away = resolve_team_name(
            raw_away,
            valid_teams,
            team_lookup
        )

        if not home and raw_home:
            unmatched.add(
                str(raw_home)
            )

        if not away and raw_away:
            unmatched.add(
                str(raw_away)
            )

        market = extract_best_market(
            raw_game
        )

        games.append({
            "id": raw_game.get("id"),

            "commence_time":
                raw_game.get(
                    "commence_time"
                ),

            "home_team": home,

            "away_team": away,

            "provider_home_team":
                raw_home,

            "provider_away_team":
                raw_away,

            "spread_home":
                market.get(
                    "spread"
                ),

            "total":
                market.get(
                    "total"
                ),

            "bookmaker":
                market.get(
                    "bookmaker"
                ),

            "last_update":
                raw_game.get(
                    "last_update"
                ),
        })

    print(
        f"✅ Market games found: "
        f"{len(games)}"
    )

    matched_games = sum(
        1
        for game in games
        if (
            game.get("home_team")
            and game.get("away_team")
        )
    )

    print(
        f"✅ Market games matched to "
        f"model teams: {matched_games}"
    )

    if unmatched:
        print("")
        print(
            "🔎 Example unmatched "
            "Odds API team names:"
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
            "games": len(games),
            "matched_games":
                matched_games,
            "source": "The Odds API",
        },

        "games": games,
    }


# =============================================================================
# CFBD SCHEDULE PARSER
# =============================================================================

def process_cfbd_games(
    raw_games,
    valid_teams,
    team_lookup
):
    """
    Parse either old CFBD snake_case fields or new camelCase fields.
    """

    processed = []

    unmatched = set()

    seen = set()

    if not isinstance(
        raw_games,
        list
    ):
        return processed, unmatched

    for game in raw_games:

        raw_home = first_value(
            game,
            "homeTeam",
            "home_team"
        )

        raw_away = first_value(
            game,
            "awayTeam",
            "away_team"
        )

        home = resolve_team_name(
            raw_home,
            valid_teams,
            team_lookup
        )

        away = resolve_team_name(
            raw_away,
            valid_teams,
            team_lookup
        )

        if not home:
            if raw_home:
                unmatched.add(
                    str(raw_home)
                )
            continue

        if not away:
            if raw_away:
                unmatched.add(
                    str(raw_away)
                )
            continue

        game_id = first_value(
            game,
            "id"
        )

        start_date = first_value(
            game,
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
            game,
            "homePoints",
            "home_points"
        )

        away_points = first_value(
            game,
            "awayPoints",
            "away_points"
        )

        completed = first_value(
            game,
            "completed",
            default=False
        )

        status = (
            "completed"
            if (
                completed is True
                or (
                    home_points is not None
                    and away_points is not None
                )
            )
            else "scheduled"
        )

        processed.append({
            "id":
                game_id,

            "week":
                first_value(
                    game,
                    "week"
                ),

            "season_type":
                first_value(
                    game,
                    "seasonType",
                    "season_type",
                    default="regular"
                ),

            "start_date":
                start_date,

            "start_time_tbd":
                first_value(
                    game,
                    "startTimeTBD",
                    "start_time_tbd",
                    default=False
                ),

            "home_team":
                home,

            "home_conference":
                first_value(
                    game,
                    "homeConference",
                    "home_conference"
                ),

            "away_team":
                away,

            "away_conference":
                first_value(
                    game,
                    "awayConference",
                    "away_conference"
                ),

            "venue":
                first_value(
                    game,
                    "venue"
                ),

            "neutral_site":
                first_value(
                    game,
                    "neutralSite",
                    "neutral_site",
                    default=False
                ),

            "home_points":
                home_points,

            "away_points":
                away_points,

            "status":
                status,
        })

    return processed, unmatched


# =============================================================================
# FETCH CFBD SCHEDULE
# =============================================================================

def fetch_schedule(
    valid_teams,
    team_lookup
):
    print("")
    print(
        f"📅 Fetching {YEAR} college "
        f"football schedule..."
    )

    print(
        "   Attempt 1: full-season "
        "schedule request..."
    )

    raw_games = cfbd_get(
        "/games",
        {
            "year": YEAR,
            "seasonType": "regular",
        },
        required=True
    )

    if not isinstance(
        raw_games,
        list
    ):
        print(
            "❌ CFBD schedule response "
            "was not a list."
        )
        sys.exit(1)

    print(
        f"   Raw games returned: "
        f"{len(raw_games)}"
    )

    games, unmatched = (
        process_cfbd_games(
            raw_games,
            valid_teams,
            team_lookup
        )
    )

    print(
        f"   Model-team games matched: "
        f"{len(games)}"
    )

    # -------------------------------------------------------------------------
    # DIAGNOSTICS
    # -------------------------------------------------------------------------

    if unmatched:
        print("")
        print(
            "🔎 Example unmatched CFBD "
            "team names:"
        )

        for team in sorted(
            unmatched
        )[:20]:
            print(
                f"   - {team}"
            )

    # -------------------------------------------------------------------------
    # IF FULL-SEASON RETURNED DATA BUT NONE MATCHED,
    # DO NOT SILENTLY PRETEND THAT IS OK.
    # -------------------------------------------------------------------------

    if raw_games and not games:
        print("")
        print(
            "❌ CFBD returned games, but "
            "ZERO matched our team ratings."
        )

        print(
            "   This means the schedule "
            "parser/team-name matcher is broken."
        )

        sys.exit(1)

    # -------------------------------------------------------------------------
    # DEDUPE
    # -------------------------------------------------------------------------

    unique = {}

    for game in games:

        if game.get("id") is not None:
            key = str(
                game.get("id")
            )

        else:
            key = str((
                game.get(
                    "home_team"
                ),
                game.get(
                    "away_team"
                ),
                game.get(
                    "start_date"
                ),
            ))

        unique[key] = game

    games = list(
        unique.values()
    )

    games.sort(
        key=lambda game: (
            (
                game.get("week")
                if game.get("week")
                is not None
                else 99
            ),
            game.get(
                "start_date"
            ) or "",
        )
    )

    print(
        f"✅ Schedule games found: "
        f"{len(games)}"
    )

    return {
        "meta": {
            "year": YEAR,
            "generated":
                datetime.now().isoformat(),
            "games":
                len(games),
            "source":
                "CollegeFootballData",
        },

        "games": games,
    }


# =============================================================================
# ODDS FALLBACK SCHEDULE
# =============================================================================

def schedule_from_odds(
    odds,
    valid_teams
):
    print("")
    print(
        "🛟 Building temporary "
        "schedule from odds..."
    )

    games = []

    for market_game in odds.get(
        "games",
        []
    ):

        home = market_game.get(
            "home_team"
        )

        away = market_game.get(
            "away_team"
        )

        if (
            not home
            or not away
            or home not in valid_teams
            or away not in valid_teams
        ):
            continue

        games.append({
            "id":
                market_game.get(
                    "id"
                ),

            "week":
                None,

            "season_type":
                "regular",

            "start_date":
                market_game.get(
                    "commence_time"
                ),

            "start_time_tbd":
                False,

            "home_team":
                home,

            "home_conference":
                (
                    valid_teams
                    .get(
                        home,
                        {}
                    )
                    .get(
                        "conference"
                    )
                ),

            "away_team":
                away,

            "away_conference":
                (
                    valid_teams
                    .get(
                        away,
                        {}
                    )
                    .get(
                        "conference"
                    )
                ),

            "venue":
                None,

            "neutral_site":
                False,

            "home_points":
                None,

            "away_points":
                None,

            "status":
                "scheduled",
        })

    games.sort(
        key=lambda game: (
            game.get(
                "start_date"
            )
            or ""
        )
    )

    print(
        f"🛟 Fallback schedule games: "
        f"{len(games)}"
    )

    return {
        "meta": {
            "year": YEAR,
            "generated":
                datetime.now().isoformat(),
            "games":
                len(games),
            "source":
                "The Odds API fallback",
        },

        "games": games,
    }


# =============================================================================
# MATCHUP ADJUSTMENTS
# =============================================================================

def metric_advantage(
    offense_value,
    defense_value,
    scale,
    max_points
):
    offense = safe_number(
        offense_value
    )

    defense = safe_number(
        defense_value
    )

    if (
        offense == 0
        and defense == 0
    ):
        return 0.0

    advantage = (
        offense
        - defense
    ) * scale

    return max(
        -max_points,
        min(
            max_points,
            advantage
        )
    )


def calculate_matchup_adjustment(
    team_a,
    team_b
):
    """
    team_a = home
    team_b = away

    Power rating is the main engine.
    Matchup adjustments remain intentionally capped.
    """

    a_off = team_a.get(
        "offense",
        {}
    ) or {}

    a_def = team_a.get(
        "defense",
        {}
    ) or {}

    b_off = team_b.get(
        "offense",
        {}
    ) or {}

    b_def = team_b.get(
        "defense",
        {}
    ) or {}

    adjustments = {}

    # Passing
    home_pass = metric_advantage(
        a_off.get(
            "epa_pass"
        ),
        b_def.get(
            "epa_pass"
        ),
        2.0,
        1.25
    )

    away_pass = metric_advantage(
        b_off.get(
            "epa_pass"
        ),
        a_def.get(
            "epa_pass"
        ),
        2.0,
        1.25
    )

    adjustments[
        "passing"
    ] = (
        home_pass
        - away_pass
    )

    # Rushing
    home_rush = metric_advantage(
        a_off.get(
            "epa_rush"
        ),
        b_def.get(
            "epa_rush"
        ),
        1.5,
        1.0
    )

    away_rush = metric_advantage(
        b_off.get(
            "epa_rush"
        ),
        a_def.get(
            "epa_rush"
        ),
        1.5,
        1.0
    )

    adjustments[
        "rushing"
    ] = (
        home_rush
        - away_rush
    )

    # EPA/play
    home_epa = metric_advantage(
        a_off.get(
            "epa_play"
        ),
        b_def.get(
            "epa_play"
        ),
        1.5,
        1.0
    )

    away_epa = metric_advantage(
        b_off.get(
            "epa_play"
        ),
        a_def.get(
            "epa_play"
        ),
        1.5,
        1.0
    )

    adjustments[
        "overall_efficiency"
    ] = (
        home_epa
        - away_epa
    )

    # Success rate
    home_sr = metric_advantage(
        a_off.get(
            "success_rate"
        ),
        b_def.get(
            "success_rate"
        ),
        0.08,
        0.75
    )

    away_sr = metric_advantage(
        b_off.get(
            "success_rate"
        ),
        a_def.get(
            "success_rate"
        ),
        0.08,
        0.75
    )

    adjustments[
        "success_rate"
    ] = (
        home_sr
        - away_sr
    )

    raw_total = sum(
        adjustments.values()
    )

    total = max(
        -MAX_MATCHUP_ADJUSTMENT,
        min(
            MAX_MATCHUP_ADJUSTMENT,
            raw_total
        )
    )

    return {
        "total": round(
            total,
            2
        ),

        "components": {
            key: round(
                value,
                2
            )
            for key, value
            in adjustments.items()
        },
    }


# =============================================================================
# TOTAL PROJECTION
# =============================================================================

def calculate_projected_total(
    home,
    away
):
    home_off = home.get(
        "offense",
        {}
    ) or {}

    home_def = home.get(
        "defense",
        {}
    ) or {}

    away_off = away.get(
        "offense",
        {}
    ) or {}

    away_def = away.get(
        "defense",
        {}
    ) or {}

    efficiency_signal = (
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

    success_signal = (
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
        - 85
    )

    total = (
        BASE_TOTAL
        + efficiency_signal * 5.0
        + success_signal * 0.15
    )

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
# WRITTEN INSIGHTS
# =============================================================================

def rank_text(team):
    rank = team.get(
        "power_rating_rank"
    )

    if rank:
        return f"#{rank}"

    return "unranked"


def generate_insights(
    home_name,
    away_name,
    home,
    away,
    matchup,
    projected_home_spread,
    market_home_spread
):
    insights = []

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

    rating_diff = (
        home_rating
        - away_rating
    )

    # -------------------------------------------------------------------------
    # POWER RATING
    # -------------------------------------------------------------------------

    if abs(
        rating_diff
    ) > 0.10:

        if rating_diff > 0:
            stronger_name = home_name
            stronger_team = home
            weaker_team = away

        else:
            stronger_name = away_name
            stronger_team = away
            weaker_team = home

        insights.append({
            "type":
                "power_rating",

            "title":
                "POWER RATING EDGE",

            "text": (
                f"{stronger_name} owns the stronger "
                f"underlying team profile "
                f"({rank_text(stronger_team)} vs "
                f"{rank_text(weaker_team)} in the "
                f"model's power ratings)."
            ),
        })

    # -------------------------------------------------------------------------
    # PASSING
    # -------------------------------------------------------------------------

    passing = (
        matchup
        .get(
            "components",
            {}
        )
        .get(
            "passing",
            0
        )
    )

    if abs(
        passing
    ) >= 0.30:

        team = (
            home_name
            if passing > 0
            else away_name
        )

        insights.append({
            "type":
                "passing",

            "title":
                "PASSING MATCHUP",

            "text": (
                f"{team} owns the more favorable "
                f"passing efficiency matchup, adding "
                f"support to the model's projected margin."
            ),
        })

    # -------------------------------------------------------------------------
    # RUSHING
    # -------------------------------------------------------------------------

    rushing = (
        matchup
        .get(
            "components",
            {}
        )
        .get(
            "rushing",
            0
        )
    )

    if abs(
        rushing
    ) >= 0.30:

        team = (
            home_name
            if rushing > 0
            else away_name
        )

        insights.append({
            "type":
                "rushing",

            "title":
                "GROUND GAME EDGE",

            "text": (
                f"{team} grades better in the rushing "
                f"matchup and receives an additional "
                f"matchup adjustment."
            ),
        })

    # -------------------------------------------------------------------------
    # MARKET
    # -------------------------------------------------------------------------

    if market_home_spread is not None:

        disagreement = (
            projected_home_spread
            - market_home_spread
        )

        if abs(
            disagreement
        ) >= 1.5:

            preferred = (
                home_name
                if disagreement < 0
                else away_name
            )

            insights.append({
                "type":
                    "market",

                "title":
                    "MARKET VS MODEL",

                "text": (
                    f"The model differs from the current "
                    f"market toward {preferred} by "
                    f"{abs(disagreement):.1f} points."
                ),
            })

    if not insights:
        insights.append({
            "type":
                "balanced",

            "title":
                "BALANCED MATCHUP",

            "text": (
                "No single efficiency matchup creates "
                "a major adjustment beyond the base "
                "power-rating projection."
            ),
        })

    return insights[:4]


# =============================================================================
# BUILD ODDS LOOKUP
# =============================================================================

def build_odds_lookup(odds):
    lookup = {}

    for market_game in odds.get(
        "games",
        []
    ):

        home = market_game.get(
            "home_team"
        )

        away = market_game.get(
            "away_team"
        )

        if not home or not away:
            continue

        lookup[
            (
                home,
                away
            )
        ] = market_game

    return lookup


# =============================================================================
# PROJECTION ENGINE
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

    skipped = 0

    odds_matched = 0

    odds_lookup = build_odds_lookup(
        odds
    )

    slope = safe_number(
        calibration.get(
            "slope"
        ),
        7.5
    )

    for game in schedule.get(
        "games",
        []
    ):

        home_name = game.get(
            "home_team"
        )

        away_name = game.get(
            "away_team"
        )

        home = teams.get(
            home_name
        )

        away = teams.get(
            away_name
        )

        if not home or not away:
            skipped += 1
            continue

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
            - away_rating
        )

        point_difference = (
            rating_difference
            * slope
        )

        neutral = bool(
            game.get(
                "neutral_site",
                False
            )
        )

        hfa = (
            0.0
            if neutral
            else HOME_FIELD_ADVANTAGE
        )

        base_home_spread = (
            -point_difference
            - hfa
        )

        matchup = (
            calculate_matchup_adjustment(
                home,
                away
            )
        )

        projected_home_spread = (
            base_home_spread
            - matchup["total"]
        )

        projected_home_spread = (
            round_half(
                projected_home_spread
            )
        )

        projected_total = (
            calculate_projected_total(
                home,
                away
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

        market_home_spread = None
        market_total = None
        bookmaker = None

        if market:
            odds_matched += 1

            market_home_spread = (
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

        # ---------------------------------------------------------------------
        # MARKET DISAGREEMENT
        # ---------------------------------------------------------------------

        disagreement_signed = None

        disagreement_abs = None

        preferred_side = None

        status = "NO MARKET"

        if (
            market_home_spread
            is not None
        ):

            market_home_spread = (
                safe_number(
                    market_home_spread
                )
            )

            disagreement_signed = (
                projected_home_spread
                - market_home_spread
            )

            disagreement_abs = abs(
                disagreement_signed
            )

            if disagreement_signed < 0:
                preferred_side = (
                    home_name
                )

            elif disagreement_signed > 0:
                preferred_side = (
                    away_name
                )

            if disagreement_abs >= 7:
                status = "PLAY"

            elif disagreement_abs >= 4:
                status = "WATCH"

            else:
                status = "IN LINE"

        # ---------------------------------------------------------------------
        # CONFIDENCE
        # ---------------------------------------------------------------------

        confidence = 50

        confidence += min(
            20,
            abs(
                rating_difference
            ) * 5
        )

        if (
            disagreement_abs
            is not None
        ):

            confidence += min(
                20,
                disagreement_abs * 2
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

        insights = generate_insights(
            home_name,
            away_name,
            home,
            away,
            matchup,
            projected_home_spread,
            market_home_spread
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
                    "status",
                    "scheduled"
                ),

            "home": {
                "team":
                    home_name,

                "conference":
                    home.get(
                        "conference"
                    ),

                "power_rating":
                    round(
                        home_rating,
                        3
                    ),

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
                    round(
                        away_rating,
                        3
                    ),

                "power_rating_rank":
                    away.get(
                        "power_rating_rank"
                    ),
            },

            "projection": {
                "home_spread":
                    projected_home_spread,

                "total":
                    projected_total,

                "base_home_spread":
                    round_half(
                        base_home_spread
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
                    market_home_spread,

                "total":
                    market_total,

                "bookmaker":
                    bookmaker,
            },

            "comparison": {
                "disagreement": (
                    round(
                        disagreement_abs,
                        1
                    )
                    if disagreement_abs
                    is not None
                    else None
                ),

                "preferred_side":
                    preferred_side,

                "status":
                    status,
            },

            "insights":
                insights,
        })

    # -------------------------------------------------------------------------
    # SORT
    # -------------------------------------------------------------------------

    def sort_key(projection):

        week = projection.get(
            "week"
        )

        if week is None:
            week_sort = 99
        else:
            week_sort = week

        disagreement = (
            projection
            .get(
                "comparison",
                {}
            )
            .get(
                "disagreement"
            )
        )

        if disagreement is None:
            disagreement_sort = -1
        else:
            disagreement_sort = (
                disagreement
            )

        return (
            week_sort,
            -disagreement_sort,
            projection.get(
                "start_date"
            ) or "",
        )

    projections.sort(
        key=sort_key
    )

    print(
        f"✅ Projections built: "
        f"{len(projections)}"
    )

    print(
        f"✅ Projections with market "
        f"match: {odds_matched}"
    )

    print(
        f"⚠ Games skipped without "
        f"ratings: {skipped}"
    )

    return projections


# =============================================================================
# SAVE JSON
# =============================================================================

def save_json(
    path,
    data
):
    directory = os.path.dirname(
        path
    )

    if directory:
        os.makedirs(
            directory,
            exist_ok=True
        )

    temp_path = (
        path + ".tmp"
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

    # Validate that we can read it back.
    with open(
        temp_path,
        "r",
        encoding="utf-8"
    ) as file:
        json.load(file)

    os.replace(
        temp_path,
        path
    )

    size_kb = (
        os.path.getsize(
            path
        )
        / 1024
    )

    print(
        f"💾 Saved {path} "
        f"({size_kb:.1f} KB)"
    )


# =============================================================================
# MAIN
# =============================================================================

def main():

    print("=" * 70)

    print(
        "🏈 HAMMER TIME CFB "
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

    # -------------------------------------------------------------------------
    # LOAD MODEL
    # -------------------------------------------------------------------------

    _, teams = load_metrics()

    valid_teams = set(
        teams.keys()
    )

    team_lookup = (
        build_team_matcher(
            valid_teams
        )
    )

    # -------------------------------------------------------------------------
    # CALIBRATION
    # -------------------------------------------------------------------------

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
        team_lookup
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
        team_lookup
    )

    # -------------------------------------------------------------------------
    # FALLBACK
    # -------------------------------------------------------------------------

    if not schedule.get(
        "games"
    ):

        print("")
        print(
            "⚠ CFBD returned zero "
            "usable schedule games."
        )

        print(
            "   Trying Odds API "
            "schedule fallback."
        )

        schedule = (
            schedule_from_odds(
                odds,
                teams
            )
        )

    # -------------------------------------------------------------------------
    # HARD SAFETY CHECK
    # -------------------------------------------------------------------------

    if not schedule.get(
        "games"
    ):
        print("")
        print(
            "❌ PROJECTION BUILD STOPPED"
        )

        print(
            "   Both CFBD and the Odds "
            "fallback produced zero "
            "usable games."
        )

        print(
            "   Refusing to publish "
            "an empty schedule."
        )

        sys.exit(1)

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

    # -------------------------------------------------------------------------
    # HARD SAFETY CHECK
    # -------------------------------------------------------------------------

    if not projections:
        print("")
        print(
            "❌ ZERO PROJECTIONS BUILT"
        )

        print(
            "   The workflow will fail "
            "instead of publishing an "
            "empty projections file."
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

            "model":
                "Hammer Time CFB Analytics",

            "version":
                "1.2",

            "calibration":
                calibration,

            "home_field_advantage":
                HOME_FIELD_ADVANTAGE,

            "notes": (
                "Power rating is the foundation "
                "of the projection. Matchup "
                "adjustments are intentionally "
                "conservative."
            ),
        },

        "games":
            projections,
    }

    save_json(
        PROJECTIONS_PATH,
        output
    )

    # -------------------------------------------------------------------------
    # FINAL REPORT
    # -------------------------------------------------------------------------

    print("")
    print("=" * 70)

    print(
        "🎉 PROJECTION BUILD COMPLETE"
    )

    print("=" * 70)

    print(
        f"Schedule games: "
        f"{len(schedule.get('games', []))}"
    )

    print(
        f"Market games: "
        f"{len(odds.get('games', []))}"
    )

    print(
        f"Projections built: "
        f"{len(projections)}"
    )


if __name__ == "__main__":
    main()
