"""
HAMMER TIME CFB ANALYTICS
build_projections.py

Reads the existing Hammer Time team ratings and builds:
    - schedule.json
    - odds.json
    - projections.json

The public website NEVER calls CFBD or The Odds API directly.
GitHub Actions fetches the data, saves static JSON, and the
GitHub Pages frontend simply reads those files.
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

# Standard home-field advantage.
# This is intentionally easy to change later after we backtest.
HOME_FIELD_ADVANTAGE = 2.0

# Conservative cap on matchup adjustments.
# We do NOT want matchup stats overpowering the actual power rating.
MAX_MATCHUP_ADJUSTMENT = 3.0

# Default college football scoring environment.
BASE_TOTAL = 52.5


# =============================================================================
# TEAM NAME NORMALIZATION
# =============================================================================

# Different APIs occasionally use slightly different school names.
# This converts known variations into the names used by CFBD / our metrics file.

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
    "Appalachian State": "Appalachian State",
    "App State": "Appalachian State",
    "San José State": "San Jose State",
    "San Jose State": "San Jose State",
}


def normalize_team_name(name):
    """Normalize team names for matching between data providers."""
    if not name:
        return ""

    name = str(name).strip()

    if name in TEAM_ALIASES:
        return TEAM_ALIASES[name]

    return name


def safe_number(value, default=0.0):
    """Convert a value safely to float."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def round_half(value):
    """Round football numbers to the nearest half point."""
    return round(value * 2) / 2


# =============================================================================
# API HELPERS
# =============================================================================

def cfbd_get(endpoint, params=None):
    """Make a CFBD API request."""
    if not CFBD_API_KEY:
        print("❌ CFBD_API_KEY is missing.")
        return []

    headers = {
        "Authorization": f"Bearer {CFBD_API_KEY}"
    }

    try:
        response = requests.get(
            f"{CFBD_BASE}{endpoint}",
            headers=headers,
            params=params,
            timeout=30
        )

        response.raise_for_status()
        return response.json()

    except Exception as e:
        print(f"⚠ CFBD request failed: {endpoint}")
        print(f"   {e}")
        return []


def odds_get(endpoint, params=None):
    """Make a The Odds API request."""
    if not ODDS_API_KEY:
        print("⚠ ODDS_API_KEY is missing. Continuing without market odds.")
        return []

    try:
        response = requests.get(
            f"{ODDS_BASE}{endpoint}",
            params=params,
            timeout=30
        )

        response.raise_for_status()

        # Helpful information for debugging API usage.
        remaining = response.headers.get("x-requests-remaining")
        used = response.headers.get("x-requests-used")

        if remaining is not None:
            print(f"   Odds API requests remaining: {remaining}")

        if used is not None:
            print(f"   Odds API requests used: {used}")

        return response.json()

    except Exception as e:
        print("⚠ Odds API request failed.")
        print(f"   {e}")
        return []


# =============================================================================
# LOAD EXISTING MODEL
# =============================================================================

def load_metrics():
    """Load the existing Hammer Time team ratings."""

    if not os.path.exists(METRICS_PATH):
        print(f"❌ Could not find {METRICS_PATH}")
        sys.exit(1)

    with open(METRICS_PATH, "r", encoding="utf-8") as file:
        data = json.load(file)

    teams = data.get("teams", {})

    if not teams:
        print("❌ No teams found in cfb_metrics.json")
        sys.exit(1)

    print(f"✅ Loaded existing ratings for {len(teams)} teams")

    return data, teams


# =============================================================================
# POWER RATING CALIBRATION
# =============================================================================

def calculate_rating_scale(teams):
    """
    Your power_rating is normalized.

    We calibrate its scale against SP+ point values when available,
    rather than arbitrarily multiplying ratings by a made-up number.

    This creates a conversion:

        normalized power rating difference
                    ↓
            expected point margin
    """

    x_values = []
    y_values = []

    for _, team in teams.items():
        power = team.get("power_rating")
        sp_plus = team.get("sp_plus", {}).get("overall")

        if power is None or sp_plus is None:
            continue

        power = safe_number(power, None)
        sp_plus = safe_number(sp_plus, None)

        if power is None or sp_plus is None:
            continue

        x_values.append(power)
        y_values.append(sp_plus)

    # Fallback if insufficient data exists.
    if len(x_values) < 10:
        print("⚠ Not enough SP+ data for calibration.")
        print("   Using fallback rating multiplier: 7.5")
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

    if denominator == 0:
        slope = 7.5
    else:
        slope = numerator / denominator

    intercept = y_mean - slope * x_mean

    print("📐 Power rating calibration:")
    print(f"   Point conversion slope: {slope:.3f}")
    print(f"   Method: regression against SP+ scale")

    return {
        "slope": slope,
        "intercept": intercept,
        "method": "sp_plus_regression"
    }


# =============================================================================
# SCHEDULE
# =============================================================================

def fetch_schedule():
    """
    Fetch all FBS games.

    We store the complete schedule independently from odds because
    sportsbooks only provide games currently available to bet.
    """

    print("\n📅 Fetching 2026 FBS schedule...")

    all_games = []

    # Week 0 through conference championship week.
    for week in range(0, 16):

        games = cfbd_get(
            "/games",
            {
                "year": YEAR,
                "week": week,
                "division": "fbs",
                "seasonType": "regular"
            }
        )

        if not games:
            continue

        for game in games:

            home_team = normalize_team_name(game.get("home_team"))
            away_team = normalize_team_name(game.get("away_team"))

            if not home_team or not away_team:
                continue

            game_record = {
                "id": game.get("id"),
                "week": game.get("week", week),
                "season_type": game.get("season_type", "regular"),
                "start_date": game.get("start_date"),
                "start_time_tbd": game.get("start_time_tbd", False),

                "home_team": home_team,
                "home_conference": game.get("home_conference"),

                "away_team": away_team,
                "away_conference": game.get("away_conference"),

                "venue": game.get("venue"),
                "neutral_site": game.get("neutral_site", False),

                "home_points": game.get("home_points"),
                "away_points": game.get("away_points"),

                "status": (
                    "completed"
                    if game.get("home_points") is not None
                    else "scheduled"
                )
            }

            all_games.append(game_record)

    all_games.sort(
        key=lambda game: (
            game.get("week", 99),
            game.get("start_date") or ""
        )
    )

    print(f"✅ Schedule games found: {len(all_games)}")

    schedule_output = {
        "meta": {
            "year": YEAR,
            "generated": datetime.now().isoformat(),
            "games": len(all_games),
            "source": "CollegeFootballData"
        },
        "games": all_games
    }

    return schedule_output


# =============================================================================
# ODDS
# =============================================================================

def extract_best_market(game):
    """
    Extract a representative spread and total.

    Preference:
        1. DraftKings
        2. FanDuel
        3. Consensus average

    We preserve all bookmaker information separately so we can
    build a consensus display later if desired.
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

            outcomes = market.get("outcomes", [])

            for outcome in outcomes:
                if outcome.get("name") == game.get("home_team"):
                    spread_value = safe_number(
                        outcome.get("point"),
                        None
                    )
                    break

        if market_key == "totals":

            outcomes = market.get("outcomes", [])

            for outcome in outcomes:
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
    Fetch NCAAF odds.

    IMPORTANT:
    This is ONE Odds API request for the entire board.

    The frontend does NOT call the API.
    Visitors to your website therefore consume zero API requests.
    """

    print("\n💰 Fetching current NCAAF market odds...")

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

        home_team = normalize_team_name(game.get("home_team"))
        away_team = normalize_team_name(game.get("away_team"))

        market = extract_best_market(game)

        processed_games.append({
            "id": game.get("id"),
            "commence_time": game.get("commence_time"),

            "home_team": home_team,
            "away_team": away_team,

            "spread_home": market.get("spread"),
            "total": market.get("total"),
            "bookmaker": market.get("bookmaker"),

            "last_update": game.get("last_update")
        })

    print(f"✅ Market games found: {len(processed_games)}")

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
# MATCHUP ADJUSTMENTS
# =============================================================================

def metric_advantage(
    offense_value,
    defense_value,
    scale,
    max_points
):
    """
    Convert an offense-vs-defense difference into a conservative
    point adjustment.

    Example:
        Strong passing offense
        vs
        weak opposing pass defense
            =
        positive adjustment
    """

    off = safe_number(offense_value)
    defense = safe_number(defense_value)

    # Don't manufacture adjustments from missing data.
    if off == 0 and defense == 0:
        return 0.0

    advantage = (off - defense) * scale

    return max(
        -max_points,
        min(max_points, advantage)
    )


def calculate_matchup_adjustment(team_a, team_b):
    """
    Calculate conservative matchup adjustments.

    These are intentionally capped because your POWER RATING is
    the foundation of the model.

    Matchup stats add context.
    They do not replace team strength.
    """

    a_off = team_a.get("offense", {})
    a_def = team_a.get("defense", {})

    b_off = team_b.get("offense", {})
    b_def = team_b.get("defense", {})

    adjustments = {}

    # Passing matchup.
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

    adjustments["passing"] = a_pass - b_pass

    # Rushing matchup.
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

    adjustments["rushing"] = a_rush - b_rush

    # Overall EPA matchup.
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

    adjustments["overall_efficiency"] = a_epa - b_epa

    # Success rate.
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

    adjustments["success_rate"] = a_sr - b_sr

    raw_adjustment = sum(adjustments.values())

    total_adjustment = max(
        -MAX_MATCHUP_ADJUSTMENT,
        min(MAX_MATCHUP_ADJUSTMENT, raw_adjustment)
    )

    return {
        "total": round(total_adjustment, 2),
        "components": {
            key: round(value, 2)
            for key, value in adjustments.items()
        }
    }


# =============================================================================
# TOTAL PROJECTION
# =============================================================================

def calculate_projected_total(home, away):
    """
    V1 projected total.

    We intentionally keep this simpler than the spread model.
    Later we can add possessions/game and tempo when we have a
    reliable live data source for them.
    """

    home_off = home.get("offense", {})
    home_def = home.get("defense", {})

    away_off = away.get("offense", {})
    away_def = away.get("defense", {})

    home_off_epa = safe_number(home_off.get("epa_play"))
    away_off_epa = safe_number(away_off.get("epa_play"))

    home_def_epa = safe_number(home_def.get("epa_play"))
    away_def_epa = safe_number(away_def.get("epa_play"))

    home_sr = safe_number(home_off.get("success_rate"))
    away_sr = safe_number(away_off.get("success_rate"))

    # EPA scoring environment.
    efficiency_signal = (
        home_off_epa +
        away_off_epa -
        home_def_epa -
        away_def_epa
    )

    # Success-rate scoring environment.
    success_signal = (
        (home_sr + away_sr) - 85
    )

    total = (
        BASE_TOTAL
        + efficiency_signal * 5.0
        + success_signal * 0.15
    )

    # Keep projections in a realistic CFB range.
    total = max(35, min(80, total))

    return round_half(total)


# =============================================================================
# WRITTEN MATCHUP INSIGHTS
# =============================================================================

def rank_text(team):
    """Create readable power-rating rank text."""
    rank = team.get("power_rating_rank")

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
    Generate readable model explanations.

    These aren't random AI sentences.
    They're deterministic explanations tied directly to the numbers
    used by the model.
    """

    insights = []

    home_rating = safe_number(home.get("power_rating"))
    away_rating = safe_number(away.get("power_rating"))

    rating_diff = home_rating - away_rating

    # -------------------------------------------------------------------------
    # Overall rating edge
    # -------------------------------------------------------------------------

    if abs(rating_diff) > 0.10:

        stronger = (
            home_name
            if rating_diff > 0
            else away_name
        )

        stronger_team = home if rating_diff > 0 else away
        weaker_team = away if rating_diff > 0 else home

        insights.append({
            "type": "power_rating",
            "title": "POWER RATING EDGE",
            "text": (
                f"{stronger} owns the stronger underlying team profile "
                f"({rank_text(stronger_team)} vs {rank_text(weaker_team)} "
                f"in the model's power ratings)."
            )
        })

    # -------------------------------------------------------------------------
    # Passing edge
    # -------------------------------------------------------------------------

    passing_component = matchup["components"].get("passing", 0)

    if abs(passing_component) >= 0.30:

        team = home_name if passing_component > 0 else away_name

        insights.append({
            "type": "passing",
            "title": "PASSING MATCHUP",
            "text": (
                f"{team} owns the more favorable passing efficiency matchup, "
                f"which contributes to the projected margin."
            )
        })

    # -------------------------------------------------------------------------
    # Rushing edge
    # -------------------------------------------------------------------------

    rushing_component = matchup["components"].get("rushing", 0)

    if abs(rushing_component) >= 0.30:

        team = home_name if rushing_component > 0 else away_name

        insights.append({
            "type": "rushing",
            "title": "GROUND GAME EDGE",
            "text": (
                f"{team} grades better in the rushing matchup, providing "
                f"additional support to the model's number."
            )
        })

    # -------------------------------------------------------------------------
    # Market disagreement
    # -------------------------------------------------------------------------

    if market_home_spread is not None:

        disagreement = (
            projected_home_spread -
            market_home_spread
        )

        favored_by_model = (
            home_name
            if projected_home_spread < 0
            else away_name
        )

        if abs(disagreement) >= 1.5:

            direction = (
                "more bullish"
                if (
                    disagreement < 0 and projected_home_spread < 0
                ) or (
                    disagreement > 0 and projected_home_spread > 0
                )
                else "less bullish"
            )

            insights.append({
                "type": "market",
                "title": "MARKET VS MODEL",
                "text": (
                    f"The model is {direction} on {favored_by_model} "
                    f"than the current market by {abs(disagreement):.1f} points."
                )
            })

    # -------------------------------------------------------------------------
    # Fallback
    # -------------------------------------------------------------------------

    if not insights:

        insights.append({
            "type": "balanced",
            "title": "BALANCED MATCHUP",
            "text": (
                "The underlying profiles are relatively close, with no "
                "single efficiency matchup creating a major separation."
            )
        })

    return insights[:4]


# =============================================================================
# BUILD PROJECTIONS
# =============================================================================

def build_projections(
    teams,
    schedule,
    odds,
    calibration
):
    """Combine ratings + schedule + odds into game projections."""

    print("\n🧮 Building projections...")

    # Create instant odds lookup.
    odds_lookup = {}

    for odd in odds.get("games", []):

        key = (
            normalize_team_name(odd.get("home_team")),
            normalize_team_name(odd.get("away_team"))
        )

        odds_lookup[key] = odd

    projections = []
    skipped = 0

    for game in schedule.get("games", []):

        home_name = normalize_team_name(game.get("home_team"))
        away_name = normalize_team_name(game.get("away_team"))

        home = teams.get(home_name)
        away = teams.get(away_name)

        # We cannot project a matchup without ratings for both teams.
        # This naturally excludes most FCS opponents.
        if not home or not away:
            skipped += 1
            continue

        home_rating = safe_number(home.get("power_rating"))
        away_rating = safe_number(away.get("power_rating"))

        # ---------------------------------------------------------------------
        # BASE POWER RATING MARGIN
        #
        # Negative = home team favored
        # Positive = away team favored
        # ---------------------------------------------------------------------

        rating_difference = home_rating - away_rating

        point_difference = (
            rating_difference *
            calibration["slope"]
        )

        # Neutral-site games receive no home-field advantage.
        hfa = (
            0.0
            if game.get("neutral_site")
            else HOME_FIELD_ADVANTAGE
        )

        # Positive point difference means home team stronger.
        # Convert into conventional sportsbook notation.
        base_home_spread = (
            -point_difference - hfa
        )

        # ---------------------------------------------------------------------
        # MATCHUP ADJUSTMENTS
        # ---------------------------------------------------------------------

        matchup = calculate_matchup_adjustment(
            home,
            away
        )

        # Positive matchup adjustment favors home.
        projected_home_spread = (
            base_home_spread -
            matchup["total"]
        )

        projected_home_spread = round_half(
            projected_home_spread
        )

        projected_total = calculate_projected_total(
            home,
            away
        )

        # ---------------------------------------------------------------------
        # MARKET
        # ---------------------------------------------------------------------

        odds_key = (home_name, away_name)
        market = odds_lookup.get(odds_key)

        market_home_spread = None
        market_total = None
        bookmaker = None

        if market:
            market_home_spread = market.get("spread_home")
            market_total = market.get("total")
            bookmaker = market.get("bookmaker")

        # ---------------------------------------------------------------------
        # DISAGREEMENT
        # ---------------------------------------------------------------------

        disagreement = None
        side = None
        status = "NO MARKET"

        if market_home_spread is not None:

            disagreement = (
                projected_home_spread -
                safe_number(market_home_spread)
            )

            absolute_disagreement = abs(disagreement)

            # Determine which side the model prefers.
            if disagreement < 0:
                side = home_name
            elif disagreement > 0:
                side = away_name
            else:
                side = None

            # Conservative thresholds for V1.
            if absolute_disagreement >= 7:
                status = "PLAY"
            elif absolute_disagreement >= 4:
                status = "WATCH"
            else:
                status = "IN LINE"

        # ---------------------------------------------------------------------
        # CONFIDENCE
        # ---------------------------------------------------------------------

        confidence = 50

        # More separation between teams = more model confidence.
        confidence += min(
            20,
            abs(rating_difference) * 5
        )

        # Market disagreement adds confidence only when significant.
        if disagreement is not None:
            confidence += min(
                20,
                abs(disagreement) * 2
            )

        confidence = int(
            max(35, min(95, confidence))
        )

        # ---------------------------------------------------------------------
        # INSIGHTS
        # ---------------------------------------------------------------------

        insights = generate_insights(
            home_name,
            away_name,
            home,
            away,
            matchup,
            projected_home_spread,
            market_home_spread
        )

        projection = {
            "game_id": game.get("id"),
            "week": game.get("week"),
            "start_date": game.get("start_date"),

            "neutral_site": game.get("neutral_site", False),
            "venue": game.get("venue"),

            "home": {
                "team": home_name,
                "conference": home.get("conference"),
                "power_rating": round(home_rating, 3),
                "power_rating_rank": home.get("power_rating_rank")
            },

            "away": {
                "team": away_name,
                "conference": away.get("conference"),
                "power_rating": round(away_rating, 3),
                "power_rating_rank": away.get("power_rating_rank")
            },

            "projection": {
                "home_spread": projected_home_spread,
                "total": projected_total,

                "base_home_spread": round_half(
                    base_home_spread
                ),

                "home_field_advantage": hfa,

                "matchup_adjustment": matchup,

                "confidence": confidence
            },

            "market": {
                "home_spread": market_home_spread,
                "total": market_total,
                "bookmaker": bookmaker
            },

            "comparison": {
                "disagreement": (
                    round(abs(disagreement), 1)
                    if disagreement is not None
                    else None
                ),

                "preferred_side": side,

                "status": status
            },

            "insights": insights
        }

        projections.append(projection)

    # Sort by week then disagreement.
    projections.sort(
        key=lambda projection: (
            projection.get("week", 99),
            -(
                projection["comparison"]["disagreement"]
                if projection["comparison"]["disagreement"] is not None
                else -1
            )
        )
    )

    print(f"✅ Projections built: {len(projections)}")
    print(f"⚠ Games skipped without ratings: {skipped}")

    return projections


# =============================================================================
# SAVE FILES
# =============================================================================

def save_json(path, data):
    """Save JSON with readable formatting."""

    os.makedirs(
        os.path.dirname(path),
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

    size_kb = os.path.getsize(path) / 1024

    print(
        f"💾 Saved {path} "
        f"({size_kb:.1f} KB)"
    )


# =============================================================================
# MAIN
# =============================================================================

def main():

    print("=" * 70)
    print("🏈 HAMMER TIME CFB PROJECTION ENGINE")
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
    # CALIBRATE RATING SCALE
    # -------------------------------------------------------------------------

    calibration = calculate_rating_scale(
        teams
    )

    # -------------------------------------------------------------------------
    # FETCH SCHEDULE
    # -------------------------------------------------------------------------

    schedule = fetch_schedule()

    save_json(
        SCHEDULE_PATH,
        schedule
    )

    # -------------------------------------------------------------------------
    # FETCH ODDS
    # -------------------------------------------------------------------------

    odds = fetch_odds()

    save_json(
        ODDS_PATH,
        odds
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

            "generated": datetime.now().isoformat(),

            "games": len(projections),

            "model": "Hammer Time CFB Analytics",

            "version": "1.0",

            "calibration": calibration,

            "home_field_advantage":
                HOME_FIELD_ADVANTAGE,

            "notes": (
                "Power rating is the foundation of the projection. "
                "Matchup adjustments are intentionally conservative."
            )
        },

        "games": projections
    }

    save_json(
        PROJECTIONS_PATH,
        output
    )

    print("\n" + "=" * 70)
    print("🎉 PROJECTION BUILD COMPLETE")
    print("=" * 70)

    print(
        f"\nFiles created:"
        f"\n  • {SCHEDULE_PATH}"
        f"\n  • {ODDS_PATH}"
        f"\n  • {PROJECTIONS_PATH}"
    )


if __name__ == "__main__":
    main()
