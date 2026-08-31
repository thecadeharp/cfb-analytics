"""
HAMMER TIME CFB ANALYTICS
build_projections.py

Builds the public data files used by the website:

    data/schedule.json
    data/odds.json
    data/projections.json

Architecture:

    APIs
      ↓
    GitHub Actions
      ↓
    Static JSON files
      ↓
    GitHub Pages frontend

API keys NEVER go to the browser.
"""

import os
import sys
import json
import math
import statistics
from datetime import datetime

import requests


# =============================================================================
# CONFIG
# =============================================================================

YEAR = 2026

CFBD_API_KEY = os.environ.get("CFBD_API_KEY", "")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")

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
# TEAM NAME NORMALIZATION
# =============================================================================

TEAM_ALIASES = {
    "Miami (FL)": "Miami",
    "Miami Florida": "Miami",
    "Miami Hurricanes": "Miami",

    "Hawai'i": "Hawai'i",
    "Hawaii": "Hawai'i",

    "UConn": "Connecticut",
    "Connecticut Huskies": "Connecticut",

    "UMass": "Massachusetts",
    "UMass Minutemen": "Massachusetts",

    "Ole Miss": "Ole Miss",

    "Southern Miss": "Southern Mississippi",

    "UTSA": "UT San Antonio",
    "UTEP": "UTEP",

    "UCF": "UCF",
    "USC": "USC",
    "UCLA": "UCLA",

    "BYU": "BYU",
    "SMU": "SMU",
    "TCU": "TCU",
    "LSU": "LSU",
    "UNLV": "UNLV",

    "FIU": "Florida International",
    "FAU": "Florida Atlantic",

    "NC State": "NC State",
    "N.C. State": "NC State",

    "App State": "Appalachian State",

    "San José State": "San Jose State",
    "San Jose State": "San Jose State",

    "UT Arlington": "UTSA",

    "Texas-San Antonio": "UT San Antonio",
}


def normalize_team_name(name):
    """Normalize team names between data providers."""

    if not name:
        return ""

    name = str(name).strip()

    if name in TEAM_ALIASES:
        return TEAM_ALIASES[name]

    return name


def safe_number(value, default=0.0):
    """Safely convert a value to float."""

    try:
        if value is None:
            return default

        return float(value)

    except (TypeError, ValueError):
        return default


def round_half(value):
    """Round football numbers to nearest half point."""

    return round(value * 2) / 2


# =============================================================================
# API HELPERS
# =============================================================================

def cfbd_get(endpoint, params=None):
    """
    Make a CFBD request.

    IMPORTANT:
    We return None on a request failure so the schedule fetcher can
    distinguish between:

        []     = successful request, zero games
        None   = API request failed
    """

    if not CFBD_API_KEY:
        print("❌ CFBD_API_KEY is missing.")
        return None

    headers = {
        "Authorization": f"Bearer {CFBD_API_KEY}",
        "Accept": "application/json"
    }

    try:
        response = requests.get(
            f"{CFBD_BASE}{endpoint}",
            headers=headers,
            params=params,
            timeout=45
        )

        if response.status_code != 200:
            print(
                f"⚠ CFBD {endpoint} returned "
                f"{response.status_code}"
            )

            try:
                print(
                    f"   Response: "
                    f"{response.text[:500]}"
                )
            except Exception:
                pass

            return None

        return response.json()

    except Exception as error:
        print(f"⚠ CFBD request failed: {endpoint}")
        print(f"   {error}")
        return None


def odds_get(endpoint, params=None):
    """Make a The Odds API request."""

    if not ODDS_API_KEY:
        print(
            "⚠ ODDS_API_KEY is missing. "
            "Continuing without market odds."
        )
        return []

    try:
        response = requests.get(
            f"{ODDS_BASE}{endpoint}",
            params=params,
            timeout=45
        )

        if response.status_code != 200:
            print(
                f"⚠ Odds API returned "
                f"{response.status_code}"
            )
            print(f"   Response: {response.text[:500]}")
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

    except Exception as error:
        print("⚠ Odds API request failed.")
        print(f"   {error}")
        return []


# =============================================================================
# LOAD MODEL
# =============================================================================

def load_metrics():
    """Load existing Hammer Time team ratings."""

    if not os.path.exists(METRICS_PATH):
        print(f"❌ Could not find {METRICS_PATH}")
        sys.exit(1)

    with open(
        METRICS_PATH,
        "r",
        encoding="utf-8"
    ) as file:

        data = json.load(file)

    teams = data.get("teams", {})

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
    Calibrate normalized power ratings against SP+ values.

    This creates a conversion between our internal rating scale
    and an approximate point-based football scale.
    """

    x_values = []
    y_values = []

    for team in teams.values():

        power = team.get("power_rating")

        sp_plus = (
            team.get("sp_plus", {})
            .get("overall")
        )

        if power is None or sp_plus is None:
            continue

        power = safe_number(power, None)
        sp_plus = safe_number(sp_plus, None)

        if power is None or sp_plus is None:
            continue

        x_values.append(power)
        y_values.append(sp_plus)

    if len(x_values) < 10:

        print(
            "⚠ Not enough SP+ data for calibration."
        )

        print(
            "   Using fallback rating multiplier: "
            "7.5"
        )

        return {
            "slope": 7.5,
            "intercept": 0.0,
            "method": "fallback"
        }

    x_mean = statistics.mean(x_values)
    y_mean = statistics.mean(y_values)

    numerator = sum(
        (x - x_mean) * (y - y_mean)
        for x, y in zip(x_values, y_values)
    )

    denominator = sum(
        (x - x_mean) ** 2
        for x in x_values
    )

    slope = (
        numerator / denominator
        if denominator != 0
        else 7.5
    )

    intercept = y_mean - slope * x_mean

    print("\n📐 Power rating calibration:")
    print(
        f"   Point conversion slope: "
        f"{slope:.3f}"
    )
    print(
        "   Method: regression against SP+ scale"
    )

    return {
        "slope": slope,
        "intercept": intercept,
        "method": "sp_plus_regression"
    }


# =============================================================================
# SCHEDULE
# =============================================================================

def process_cfbd_games(raw_games, valid_teams):
    """
    Convert raw CFBD games into our website schedule format.

    We filter against teams already present in cfb_metrics.json.
    This avoids relying entirely on CFBD's classification fields.
    """

    processed = []
    seen = set()

    if not isinstance(raw_games, list):
        return processed

    for game in raw_games:

        home_team = normalize_team_name(
            game.get("home_team")
        )

        away_team = normalize_team_name(
            game.get("away_team")
        )

        if not home_team or not away_team:
            continue

        # Only include games where both teams exist
        # in our model ratings.
        if (
            home_team not in valid_teams
            or away_team not in valid_teams
        ):
            continue

        game_id = game.get("id")

        # Prevent duplicates.
        unique_key = (
            game_id
            if game_id is not None
            else (
                home_team,
                away_team,
                game.get("start_date")
            )
        )

        if unique_key in seen:
            continue

        seen.add(unique_key)

        processed.append({
            "id": game_id,

            "week": game.get("week"),

            "season_type": (
                game.get("season_type")
                or "regular"
            ),

            "start_date": game.get("start_date"),

            "start_time_tbd": game.get(
                "start_time_tbd",
                False
            ),

            "home_team": home_team,

            "home_conference": game.get(
                "home_conference"
            ),

            "away_team": away_team,

            "away_conference": game.get(
                "away_conference"
            ),

            "venue": game.get("venue"),

            "neutral_site": game.get(
                "neutral_site",
                False
            ),

            "home_points": game.get(
                "home_points"
            ),

            "away_points": game.get(
                "away_points"
            ),

            "status": (
                "completed"
                if game.get("home_points") is not None
                else "scheduled"
            )
        })

    return processed


def fetch_schedule(valid_teams):
    """
    Fetch the 2026 schedule.

    Strategy:

    1. Try a full-season CFBD request.
    2. If that doesn't work, try week-by-week.
    3. Print real API failures instead of silently
       converting them into zero games.
    """

    print(
        "\n📅 Fetching 2026 college football schedule..."
    )

    all_games = []

    # -------------------------------------------------------------------------
    # ATTEMPT 1
    # Full season request
    # -------------------------------------------------------------------------

    print(
        "   Attempt 1: full-season schedule request..."
    )

    raw_games = cfbd_get(
        "/games",
        {
            "year": YEAR,
            "seasonType": "regular"
        }
    )

    if raw_games is not None:

        processed = process_cfbd_games(
            raw_games,
            valid_teams
        )

        print(
            f"   Raw games returned: "
            f"{len(raw_games) if isinstance(raw_games, list) else 0}"
        )

        print(
            f"   Model-team games matched: "
            f"{len(processed)}"
        )

        if processed:
            all_games = processed

    # -------------------------------------------------------------------------
    # ATTEMPT 2
    # Week-by-week fallback
    # -------------------------------------------------------------------------

    if not all_games:

        print(
            "   Attempt 2: week-by-week fallback..."
        )

        for week in range(0, 17):

            raw_week = cfbd_get(
                "/games",
                {
                    "year": YEAR,
                    "week": week,
                    "seasonType": "regular"
                }
            )

            if raw_week is None:
                print(
                    f"   Week {week}: API request failed"
                )
                continue

            processed = process_cfbd_games(
                raw_week,
                valid_teams
            )

            if processed:

                print(
                    f"   Week {week}: "
                    f"{len(processed)} games"
                )

                all_games.extend(processed)

    # -------------------------------------------------------------------------
    # REMOVE DUPLICATES
    # -------------------------------------------------------------------------

    unique_games = {}
    seen_pairs = set()

    for game in all_games:

        game_id = game.get("id")

        if game_id is not None:

            unique_games[
                str(game_id)
            ] = game

        else:

            pair_key = (
                game.get("home_team"),
                game.get("away_team"),
                game.get("start_date")
            )

            if pair_key not in seen_pairs:

                seen_pairs.add(pair_key)

                unique_games[
                    str(pair_key)
                ] = game

    all_games = list(
        unique_games.values()
    )

    all_games.sort(
        key=lambda game: (
            game.get("week")
            if game.get("week") is not None
            else 99,

            game.get("start_date") or ""
        )
    )

    print(
        f"✅ Schedule games found: "
        f"{len(all_games)}"
    )

    return {
        "meta": {
            "year": YEAR,
            "generated": datetime.now().isoformat(),
            "games": len(all_games),
            "source": "CollegeFootballData"
        },

        "games": all_games
    }


# =============================================================================
# ODDS
# =============================================================================

def extract_best_market(game):
    """
    Extract one representative sportsbook market.

    Preference:
        DraftKings
        FanDuel
        BetMGM
        Caesars
        First available
    """

    bookmakers = game.get("bookmakers", [])

    if not bookmakers:
        return {
            "spread": None,
            "total": None,
            "bookmaker": None
        }

    preferred_names = [
        "draftkings",
        "fanduel",
        "betmgm",
        "caesars",
        "betonlineag"
    ]

    selected = None

    for preferred in preferred_names:

        for bookmaker in bookmakers:

            if bookmaker.get("key") == preferred:

                selected = bookmaker
                break

        if selected:
            break

    if not selected:
        selected = bookmakers[0]

    spread_value = None
    total_value = None

    for market in selected.get("markets", []):

        market_key = market.get("key")

        if market_key == "spreads":

            for outcome in market.get(
                "outcomes",
                []
            ):

                if (
                    outcome.get("name")
                    == game.get("home_team")
                ):

                    spread_value = safe_number(
                        outcome.get("point"),
                        None
                    )

                    break

        elif market_key == "totals":

            for outcome in market.get(
                "outcomes",
                []
            ):

                if outcome.get("name") == "Over":

                    total_value = safe_number(
                        outcome.get("point"),
                        None
                    )

                    break

    return {
        "spread": spread_value,
        "total": total_value,
        "bookmaker": selected.get("title")
    }


def fetch_odds():
    """
    Fetch the entire current NCAAF odds board.

    This is ONE API request.

    Website visitors consume zero API requests because
    GitHub Actions saves the result as static JSON.
    """

    print(
        "\n💰 Fetching current NCAAF market odds..."
    )

    odds_data = odds_get(
        "/sports/americanfootball_ncaaf/odds",
        {
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": "spreads,totals",
            "oddsFormat": "american",
            "dateFormat": "iso"
        }
    )

    if not odds_data:

        print("⚠ No odds returned.")

        return {
            "meta": {
                "year": YEAR,
                "generated": datetime.now().isoformat(),
                "games": 0,
                "source": "The Odds API"
            },

            "games": []
        }

    processed_games = []

    for game in odds_data:

        home_team = normalize_team_name(
            game.get("home_team")
        )

        away_team = normalize_team_name(
            game.get("away_team")
        )

        market = extract_best_market(game)

        processed_games.append({
            "id": game.get("id"),

            "commence_time": game.get(
                "commence_time"
            ),

            "home_team": home_team,
            "away_team": away_team,

            "spread_home": market.get(
                "spread"
            ),

            "total": market.get(
                "total"
            ),

            "bookmaker": market.get(
                "bookmaker"
            ),

            "last_update": game.get(
                "last_update"
            )
        })

    print(
        f"✅ Market games found: "
        f"{len(processed_games)}"
    )

    return {
        "meta": {
            "year": YEAR,
            "generated": datetime.now().isoformat(),
            "games": len(processed_games),
            "source": "The Odds API"
        },

        "games": processed_games
    }


# =============================================================================
# ODDS SCHEDULE FALLBACK
# =============================================================================

def schedule_from_odds(odds, valid_teams):
    """
    Emergency fallback.

    If CFBD's schedule endpoint fails, we can still project
    every currently posted market game.

    The Odds API does not provide official CFBD week numbers,
    so fallback games are grouped by calendar date and assigned
    week=None.

    This keeps the model functional instead of publishing
    an empty projections board.
    """

    print(
        "\n🛟 Building temporary schedule from odds..."
    )

    games = []

    for odds_game in odds.get("games", []):

        home_team = normalize_team_name(
            odds_game.get("home_team")
        )

        away_team = normalize_team_name(
            odds_game.get("away_team")
        )

        if (
            home_team not in valid_teams
            or away_team not in valid_teams
        ):
            continue

        games.append({
            "id": odds_game.get("id"),

            "week": None,

            "season_type": "regular",

            "start_date": odds_game.get(
                "commence_time"
            ),

            "start_time_tbd": False,

            "home_team": home_team,

            "home_conference": (
                valid_teams
                .get(home_team, {})
                .get("conference")
            ),

            "away_team": away_team,

            "away_conference": (
                valid_teams
                .get(away_team, {})
                .get("conference")
            ),

            "venue": None,

            "neutral_site": False,

            "home_points": None,
            "away_points": None,

            "status": "scheduled"
        })

    games.sort(
        key=lambda game: (
            game.get("start_date") or ""
        )
    )

    print(
        f"🛟 Fallback schedule games: "
        f"{len(games)}"
    )

    return {
        "meta": {
            "year": YEAR,
            "generated": datetime.now().isoformat(),
            "games": len(games),
            "source": "The Odds API fallback"
        },

        "games": games
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
    """Convert an efficiency advantage into points."""

    off = safe_number(offense_value)
    defense = safe_number(defense_value)

    if off == 0 and defense == 0:
        return 0.0

    advantage = (
        (off - defense) * scale
    )

    return max(
        -max_points,
        min(max_points, advantage)
    )


def calculate_matchup_adjustment(
    team_a,
    team_b
):
    """
    Calculate conservative matchup adjustments.

    Power rating remains the foundation.
    Matchup metrics provide smaller context adjustments.
    """

    a_off = team_a.get("offense", {})
    a_def = team_a.get("defense", {})

    b_off = team_b.get("offense", {})
    b_def = team_b.get("defense", {})

    adjustments = {}

    # Passing
    a_pass = metric_advantage(
        a_off.get("epa_pass"),
        b_def.get("epa_pass"),
        scale=2.0,
        max_points=1.25
    )

    b_pass = metric_advantage(
        b_off.get("epa_pass"),
        a_def.get("epa_pass"),
        scale=2.0,
        max_points=1.25
    )

    adjustments["passing"] = (
        a_pass - b_pass
    )

    # Rushing
    a_rush = metric_advantage(
        a_off.get("epa_rush"),
        b_def.get("epa_rush"),
        scale=1.5,
        max_points=1.0
    )

    b_rush = metric_advantage(
        b_off.get("epa_rush"),
        a_def.get("epa_rush"),
        scale=1.5,
        max_points=1.0
    )

    adjustments["rushing"] = (
        a_rush - b_rush
    )

    # Overall efficiency
    a_epa = metric_advantage(
        a_off.get("epa_play"),
        b_def.get("epa_play"),
        scale=1.5,
        max_points=1.0
    )

    b_epa = metric_advantage(
        b_off.get("epa_play"),
        a_def.get("epa_play"),
        scale=1.5,
        max_points=1.0
    )

    adjustments["overall_efficiency"] = (
        a_epa - b_epa
    )

    # Success rate
    a_sr = metric_advantage(
        a_off.get("success_rate"),
        b_def.get("success_rate"),
        scale=0.08,
        max_points=0.75
    )

    b_sr = metric_advantage(
        b_off.get("success_rate"),
        a_def.get("success_rate"),
        scale=0.08,
        max_points=0.75
    )

    adjustments["success_rate"] = (
        a_sr - b_sr
    )

    raw_adjustment = sum(
        adjustments.values()
    )

    total_adjustment = max(
        -MAX_MATCHUP_ADJUSTMENT,
        min(
            MAX_MATCHUP_ADJUSTMENT,
            raw_adjustment
        )
    )

    return {
        "total": round(
            total_adjustment,
            2
        ),

        "components": {
            key: round(value, 2)
            for key, value in adjustments.items()
        }
    }


# =============================================================================
# TOTAL PROJECTION
# =============================================================================

def calculate_projected_total(
    home,
    away
):
    """
    V1 total model.

    Intentionally conservative until we add reliable
    tempo/possession data.
    """

    home_off = home.get("offense", {})
    home_def = home.get("defense", {})

    away_off = away.get("offense", {})
    away_def = away.get("defense", {})

    home_off_epa = safe_number(
        home_off.get("epa_play")
    )

    away_off_epa = safe_number(
        away_off.get("epa_play")
    )

    home_def_epa = safe_number(
        home_def.get("epa_play")
    )

    away_def_epa = safe_number(
        away_def.get("epa_play")
    )

    home_sr = safe_number(
        home_off.get("success_rate")
    )

    away_sr = safe_number(
        away_off.get("success_rate")
    )

    efficiency_signal = (
        home_off_epa
        + away_off_epa
        - home_def_epa
        - away_def_epa
    )

    success_signal = (
        home_sr + away_sr - 85
    )

    total = (
        BASE_TOTAL
        + efficiency_signal * 5.0
        + success_signal * 0.15
    )

    total = max(
        35,
        min(80, total)
    )

    return round_half(total)


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
    """
    Generate deterministic explanations tied to model inputs.
    """

    insights = []

    home_rating = safe_number(
        home.get("power_rating")
    )

    away_rating = safe_number(
        away.get("power_rating")
    )

    rating_diff = (
        home_rating - away_rating
    )

    # Power rating edge
    if abs(rating_diff) > 0.10:

        stronger = (
            home_name
            if rating_diff > 0
            else away_name
        )

        stronger_team = (
            home
            if rating_diff > 0
            else away
        )

        weaker_team = (
            away
            if rating_diff > 0
            else home
        )

        insights.append({
            "type": "power_rating",

            "title": "POWER RATING EDGE",

            "text": (
                f"{stronger} owns the stronger "
                f"underlying team profile "
                f"({rank_text(stronger_team)} vs "
                f"{rank_text(weaker_team)} in the "
                f"model's power ratings)."
            )
        })

    # Passing
    passing_component = (
        matchup["components"]
        .get("passing", 0)
    )

    if abs(passing_component) >= 0.30:

        team = (
            home_name
            if passing_component > 0
            else away_name
        )

        insights.append({
            "type": "passing",

            "title": "PASSING MATCHUP",

            "text": (
                f"{team} owns the more favorable "
                f"passing efficiency matchup, which "
                f"contributes to the projected margin."
            )
        })

    # Rushing
    rushing_component = (
        matchup["components"]
        .get("rushing", 0)
    )

    if abs(rushing_component) >= 0.30:

        team = (
            home_name
            if rushing_component > 0
            else away_name
        )

        insights.append({
            "type": "rushing",

            "title": "GROUND GAME EDGE",

            "text": (
                f"{team} grades better in the rushing "
                f"matchup, providing additional support "
                f"to the model's number."
            )
        })

    # Market disagreement
    if market_home_spread is not None:

        disagreement = (
            projected_home_spread
            - market_home_spread
        )

        favored_by_model = (
            home_name
            if projected_home_spread < 0
            else away_name
        )

        if abs(disagreement) >= 1.5:

            insights.append({
                "type": "market",

                "title": "MARKET VS MODEL",

                "text": (
                    f"The model differs from the current "
                    f"market on {favored_by_model} by "
                    f"{abs(disagreement):.1f} points."
                )
            })

    # Fallback
    if not insights:

        insights.append({
            "type": "balanced",

            "title": "BALANCED MATCHUP",

            "text": (
                "The model sees no single efficiency "
                "factor large enough to dominate the "
                "projection."
            )
        })

    return insights[:4]


# =============================================================================
# PROJECTION ENGINE
# =============================================================================

def build_projections(
    teams,
    schedule,
    odds,
    calibration
):
    """Build model projections for every rated matchup."""

    print(
        "\n🧮 Building projections..."
    )

    projections = []
    skipped = 0

    # Build fast odds lookup.
    odds_lookup = {}

    for market_game in odds.get(
        "games",
        []
    ):

        home_name = normalize_team_name(
            market_game.get("home_team")
        )

        away_name = normalize_team_name(
            market_game.get("away_team")
        )

        odds_lookup[
            (home_name, away_name)
        ] = market_game

    slope = safe_number(
        calibration.get("slope"),
        7.5
    )

    for game in schedule.get(
        "games",
        []
    ):

        home_name = normalize_team_name(
            game.get("home_team")
        )

        away_name = normalize_team_name(
            game.get("away_team")
        )

        home = teams.get(home_name)
        away = teams.get(away_name)

        if not home or not away:

            skipped += 1
            continue

        home_rating = safe_number(
            home.get("power_rating")
        )

        away_rating = safe_number(
            away.get("power_rating")
        )

        rating_difference = (
            home_rating - away_rating
        )

        # Convert rating difference into points.
        point_difference = (
            rating_difference * slope
        )

        hfa = (
            0.0
            if game.get("neutral_site")
            else HOME_FIELD_ADVANTAGE
        )

        base_home_spread = (
            -point_difference - hfa
        )

        matchup = calculate_matchup_adjustment(
            home,
            away
        )

        projected_home_spread = (
            base_home_spread
            - matchup["total"]
        )

        projected_home_spread = round_half(
            projected_home_spread
        )

        projected_total = calculate_projected_total(
            home,
            away
        )

        # Market
        market = odds_lookup.get(
            (home_name, away_name)
        )

        market_home_spread = None
        market_total = None
        bookmaker = None

        if market:

            market_home_spread = market.get(
                "spread_home"
            )

            market_total = market.get(
                "total"
            )

            bookmaker = market.get(
                "bookmaker"
            )

        # Disagreement
        disagreement = None
        side = None
        status = "NO MARKET"

        if market_home_spread is not None:

            disagreement = (
                projected_home_spread
                - safe_number(
                    market_home_spread
                )
            )

            absolute_disagreement = abs(
                disagreement
            )

            if disagreement < 0:
                side = home_name

            elif disagreement > 0:
                side = away_name

            if absolute_disagreement >= 7:
                status = "PLAY"

            elif absolute_disagreement >= 4:
                status = "WATCH"

            else:
                status = "IN LINE"

        # Confidence
        confidence = 50

        confidence += min(
            20,
            abs(rating_difference) * 5
        )

        if disagreement is not None:

            confidence += min(
                20,
                abs(disagreement) * 2
            )

        confidence = int(
            max(
                35,
                min(95, confidence)
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

            "game_id": game.get("id"),

            "week": game.get("week"),

            "start_date": game.get(
                "start_date"
            ),

            "neutral_site": game.get(
                "neutral_site",
                False
            ),

            "venue": game.get("venue"),

            "home": {
                "team": home_name,

                "conference": home.get(
                    "conference"
                ),

                "power_rating": round(
                    home_rating,
                    3
                ),

                "power_rating_rank": home.get(
                    "power_rating_rank"
                )
            },

            "away": {
                "team": away_name,

                "conference": away.get(
                    "conference"
                ),

                "power_rating": round(
                    away_rating,
                    3
                ),

                "power_rating_rank": away.get(
                    "power_rating_rank"
                )
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
                    confidence
            },

            "market": {

                "home_spread":
                    market_home_spread,

                "total":
                    market_total,

                "bookmaker":
                    bookmaker
            },

            "comparison": {

                "disagreement": (
                    round(
                        abs(disagreement),
                        1
                    )
                    if disagreement is not None
                    else None
                ),

                "preferred_side":
                    side,

                "status":
                    status
            },

            "insights": insights
        })

    projections.sort(
        key=lambda projection: (

            projection.get("week")
            if projection.get("week") is not None
            else 99,

            -(
                projection["comparison"]
                ["disagreement"]

                if projection["comparison"]
                ["disagreement"] is not None

                else -1
            )
        )
    )

    print(
        f"✅ Projections built: "
        f"{len(projections)}"
    )

    print(
        f"⚠ Games skipped without ratings: "
        f"{skipped}"
    )

    return projections


# =============================================================================
# SAVE
# =============================================================================

def save_json(path, data):
    """Save JSON with readable formatting."""

    directory = os.path.dirname(path)

    if directory:
        os.makedirs(
            directory,
            exist_ok=True
        )

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False
        )

    size_kb = (
        os.path.getsize(path)
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

    print(f"Season: {YEAR}")

    print(
        f"Generated: "
        f"{datetime.now().isoformat()}"
    )

    # -------------------------------------------------------------------------
    # LOAD MODEL
    # -------------------------------------------------------------------------

    _, teams = load_metrics()

    # -------------------------------------------------------------------------
    # CALIBRATE
    # -------------------------------------------------------------------------

    calibration = calculate_rating_scale(
        teams
    )

    # -------------------------------------------------------------------------
    # FETCH ODDS FIRST
    # -------------------------------------------------------------------------
    #
    # We intentionally fetch odds before schedule.
    #
    # If CFBD's schedule endpoint has an issue, the odds
    # board gives us a fallback schedule so projections
    # don't go completely empty.
    # -------------------------------------------------------------------------

    odds = fetch_odds()

    save_json(
        ODDS_PATH,
        odds
    )

    # -------------------------------------------------------------------------
    # FETCH SCHEDULE
    # -------------------------------------------------------------------------

    schedule = fetch_schedule(
        teams
    )

    # -------------------------------------------------------------------------
    # FALLBACK TO ODDS SCHEDULE
    # -------------------------------------------------------------------------

    if not schedule.get("games"):

        print(
            "\n⚠ CFBD schedule returned zero usable games."
        )

        print(
            "   Using posted market games as "
            "temporary schedule fallback."
        )

        schedule = schedule_from_odds(
            odds,
            teams
        )

    save_json(
        SCHEDULE_PATH,
        schedule
    )

    # -------------------------------------------------------------------------
    # BUILD PROJECTIONS
    # -------------------------------------------------------------------------

    projections = build_projections(
        teams,
        schedule,
        odds,
        calibration
    )

    output = {

        "meta": {

            "year": YEAR,

            "generated":
                datetime.now().isoformat(),

            "games":
                len(projections),

            "model":
                "Hammer Time CFB Analytics",

            "version": "1.1",

            "calibration":
                calibration,

            "home_field_advantage":
                HOME_FIELD_ADVANTAGE,

            "notes": (
                "Power rating is the foundation of the "
                "projection. Matchup adjustments are "
                "intentionally conservative."
            )
        },

        "games": projections
    }

    save_json(
        PROJECTIONS_PATH,
        output
    )

    print("\n" + "=" * 70)
    print(
        "🎉 PROJECTION BUILD COMPLETE"
    )
    print("=" * 70)

    print(
        f"\nSchedule games: "
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
