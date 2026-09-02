"""
CFB ANALYTICS
build_projections.py

Production projection engine.

Builds:
    data/schedule.json
    data/odds.json
    data/projections.json

Production rules:
- Strict FBS school matching; no dangerous prefix matching for CFBD schedules
- Team-specific 2026 HFA from data/hfa_2026.json
- Neutral-site HFA = 0.0
- Current blended power ratings are converted to points with a historically
  learned production scale, not a same-season SP+ regression
- Current SP+ regression is retained only as a diagnostic
- Live matchup adjustments require comparable samples on both teams
- Completed results are locked in season-win distributions
- Full schedules include FCS opponents through a transparent fallback
"""

import json
import math
import os
import statistics
import sys
import time
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
HFA_PATH = "data/hfa_2026.json"
SCHEDULE_PATH = "data/schedule.json"
ODDS_PATH = "data/odds.json"
PROJECTIONS_PATH = "data/projections.json"

MAX_MATCHUP_ADJUSTMENT = 3.0
BASE_TOTAL = 52.5

MIN_LIVE_PLAYS = 35
MIN_LIVE_PASS_PLAYS = 15
MIN_LIVE_RUSH_PLAYS = 15

WIN_PROB_STD_DEV = 16.0

# Leakage-safe historical yearly rating-to-points slopes from the composite
# backtest. Production uses their simple mean.
HISTORICAL_SCALE_BY_YEAR = {
    "2022": 11.194,
    "2023": 10.392,
    "2024": 10.162,
    "2025": 9.950,
}
HISTORICAL_RATING_SCALE = (
    sum(HISTORICAL_SCALE_BY_YEAR.values())
    / len(HISTORICAL_SCALE_BY_YEAR)
)

# FCS fallback is only for season-win probability calculations.
FCS_BASE_MARGIN = 24.0
FCS_POWER_MULTIPLIER = 0.60
FCS_MIN_WIN_PROB = 0.65
FCS_MAX_WIN_PROB = 0.995


# =============================================================================
# KEYS
# =============================================================================

def clean_api_key(raw):
    if raw is None:
        return ""

    key = str(raw).strip()

    if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
        key = key[1:-1].strip()

    if key.lower().startswith("bearer "):
        key = key[7:].strip()

    return (
        key.replace("\r", "")
        .replace("\n", "")
        .replace("\t", "")
        .strip()
    )


CFBD_API_KEY = clean_api_key(os.environ.get("CFBD_API_KEY", ""))
ODDS_API_KEY = clean_api_key(os.environ.get("ODDS_API_KEY", ""))


# =============================================================================
# GENERAL HELPERS
# =============================================================================

def safe_number(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def optional_number(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


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

    text = unicodedata.normalize("NFKD", str(value))
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
# TEAM ALIASES
# =============================================================================

# Values MUST match the preferred keys in data/cfb_metrics.json.
ALIASES = {
    "miami fl": "Miami",
    "miami florida": "Miami",

    "uconn": "UConn",
    "connecticut": "UConn",

    "umass": "Massachusetts",

    "southern miss": "Southern Miss",
    "southern mississippi": "Southern Miss",

    "utsa": "UTSA",
    "ut san antonio": "UTSA",
    "texas san antonio": "UTSA",

    "fiu": "Florida International",
    "fau": "Florida Atlantic",

    "app state": "App State",
    "appalachian state": "App State",

    "nc state": "NC State",
    "n c state": "NC State",
    "north carolina state": "NC State",

    "hawaii": "Hawai'i",

    "mississippi": "Ole Miss",

    "ul lafayette": "Louisiana",
    "louisiana lafayette": "Louisiana",

    "ulm": "UL Monroe",
    "ul monroe": "UL Monroe",
    "louisiana monroe": "UL Monroe",

    "middle tennessee state": "Middle Tennessee",
    "sam houston state": "Sam Houston",

    "miami ohio": "Miami (OH)",
    "miami oh": "Miami (OH)",

    "san jose state": "San Jose State",
    "san josé state": "San Jose State",
    "sam jose state": "San Jose State",
    "sam josé state": "San Jose State",
}

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


# =============================================================================
# TEAM MATCHING
# =============================================================================

def build_team_lookup(teams):
    return {canonical_name(team): team for team in teams}


def resolve_cfbd_team(provider_name, valid_teams, lookup):
    """Strict school matching. No prefix matching."""
    if not provider_name:
        return None

    canon = canonical_name(provider_name)

    if canon in lookup:
        return lookup[canon]

    alias = ALIASES.get(canon)
    if alias in valid_teams:
        return alias

    return None


def resolve_odds_team(provider_name, valid_teams, lookup):
    """
    Sportsbooks can append mascots. Exact names/aliases are preferred.
    A guarded prefix fallback is allowed only for sportsbook labels.
    """
    if not provider_name:
        return None

    canon = canonical_name(provider_name)

    if canon in lookup:
        return lookup[canon]

    alias = ALIASES.get(canon)
    if alias in valid_teams:
        return alias

    candidates = []

    for model_canon, model_name in lookup.items():
        prefix = model_canon + " "

        if not canon.startswith(prefix):
            continue

        remainder = canon[len(prefix):].strip()
        if not remainder:
            continue

        first_word = remainder.split()[0]
        if first_word in SCHOOL_STRUCTURE_WORDS:
            continue

        candidates.append((len(model_canon), model_name))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


# =============================================================================
# REQUESTS
# =============================================================================

def cfbd_get(endpoint, params=None, required=True):
    if not CFBD_API_KEY:
        print("❌ CFBD_API_KEY missing.")
        sys.exit(1)

    max_attempts = 5

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(
                f"{CFBD_BASE}{endpoint}",
                headers={
                    "Authorization": f"Bearer {CFBD_API_KEY}",
                    "Accept": "application/json",
                },
                params=params,
                timeout=75,
            )
        except requests.RequestException as error:
            print(
                f"⚠ CFBD request error {endpoint} "
                f"({attempt}/{max_attempts}): {error}"
            )

            if attempt < max_attempts:
                time.sleep(min(2 ** attempt, 20))
                continue

            if required:
                sys.exit(1)
            return []

        if response.status_code in (401, 403):
            print("❌ CFBD authentication failed.")
            sys.exit(1)

        if not response.ok:
            print(
                f"⚠ CFBD {endpoint}: HTTP {response.status_code} "
                f"({attempt}/{max_attempts})"
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
            print(f"⚠ Invalid JSON from CFBD {endpoint}")

            if attempt < max_attempts:
                time.sleep(min(2 ** attempt, 20))
                continue

            if required:
                sys.exit(1)
            return []

    return []


def odds_get():
    if not ODDS_API_KEY:
        print("⚠ ODDS_API_KEY missing.")
        return []

    try:
        response = requests.get(
            f"{ODDS_BASE}/sports/americanfootball_ncaaf/odds",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "us",
                "markets": "spreads,totals",
                "oddsFormat": "american",
                "dateFormat": "iso",
            },
            timeout=45,
        )
    except requests.RequestException as error:
        print(f"⚠ Odds API request failed: {error}")
        return []

    if not response.ok:
        print(f"⚠ Odds API HTTP {response.status_code}")
        return []

    remaining = response.headers.get("x-requests-remaining")
    if remaining is not None:
        print(f"   Odds requests remaining: {remaining}")

    return response.json()


# =============================================================================
# LOAD DATA
# =============================================================================

def load_metrics():
    if not os.path.exists(METRICS_PATH):
        print(f"❌ Missing {METRICS_PATH}")
        sys.exit(1)

    with open(METRICS_PATH, "r", encoding="utf-8") as file:
        data = json.load(file)

    teams = data.get("teams", {})

    if len(teams) < 100:
        print("❌ Metrics file contains too few teams.")
        sys.exit(1)

    print(f"✅ Loaded ratings for {len(teams)} teams")
    return data, teams


def load_hfa(valid_teams):
    if not os.path.exists(HFA_PATH):
        print(f"❌ Missing {HFA_PATH}")
        sys.exit(1)

    with open(HFA_PATH, "r", encoding="utf-8") as file:
        data = json.load(file)

    meta = data.get("meta", {}) or {}
    ratings = data.get("teams", {}) or {}

    missing = sorted(set(valid_teams) - set(ratings))
    extra = sorted(set(ratings) - set(valid_teams))

    if missing:
        print("❌ Production HFA table is missing model teams:")
        for team in missing:
            print(f"   - {team}")
        sys.exit(1)

    minimum = safe_number(meta.get("minimum_hfa"), 1.0)
    maximum = safe_number(meta.get("maximum_hfa"), 3.5)

    invalid = []

    for team in valid_teams:
        value = optional_number(ratings.get(team))
        if value is None or value < minimum or value > maximum:
            invalid.append((team, ratings.get(team)))

    if invalid:
        print("❌ Production HFA table contains invalid values:")
        for team, value in invalid:
            print(f"   - {team}: {value}")
        sys.exit(1)

    print(f"✅ Loaded production HFA for {len(valid_teams)} model teams")
    print(
        f"   Range: {minimum:.1f} to {maximum:.1f} | "
        f"Neutral: {safe_number(meta.get('neutral_site_hfa'), 0.0):.1f}"
    )

    if extra:
        print(
            f"⚠ HFA file contains {len(extra)} extra team(s) "
            "not in the current model"
        )

    return data


def get_team_hfa(team_name, hfa_data, neutral=False):
    meta = hfa_data.get("meta", {}) or {}

    if neutral:
        return safe_number(meta.get("neutral_site_hfa"), 0.0)

    ratings = hfa_data.get("teams", {}) or {}
    default = safe_number(meta.get("default_hfa"), 2.0)
    return safe_number(ratings.get(team_name), default)


# =============================================================================
# RATING SCALE
# =============================================================================

def current_sp_diagnostic_scale(teams):
    """
    Cross-sectional 2026 power-rating -> SP+ slope.

    This is diagnostic only. It is intentionally NOT used as the production
    point conversion because it is same-season and can over-expand extremes.
    """
    x_values = []
    y_values = []

    for team in teams.values():
        power = optional_number(team.get("power_rating"))
        sp = optional_number((team.get("sp_plus", {}) or {}).get("overall"))

        if power is None or sp is None:
            continue

        x_values.append(power)
        y_values.append(sp)

    if len(x_values) < 10:
        return {
            "slope": None,
            "intercept": None,
            "sample": len(x_values),
        }

    x_mean = statistics.mean(x_values)
    y_mean = statistics.mean(y_values)

    numerator = sum(
        (x - x_mean) * (y - y_mean)
        for x, y in zip(x_values, y_values)
    )
    denominator = sum((x - x_mean) ** 2 for x in x_values)

    slope = numerator / denominator if denominator else None
    intercept = (
        y_mean - slope * x_mean
        if slope is not None
        else None
    )

    return {
        "slope": slope,
        "intercept": intercept,
        "sample": len(x_values),
    }


def calculate_rating_scale(teams):
    """
    Production point conversion.

    Historical yearly scales came from the leakage-safe composite backtest:
        2022  11.194
        2023  10.392
        2024  10.162
        2025   9.950

    Their mean (10.4245) is the 2026 production conversion.

    The live 2026 SP+ regression is still calculated and published as a
    diagnostic, but it no longer determines fair lines.
    """
    diagnostic = current_sp_diagnostic_scale(teams)
    slope = HISTORICAL_RATING_SCALE

    print("")
    print("📐 Power rating calibration")
    print(
        f"   Production historical scale: "
        f"{slope:.3f} points per rating unit"
    )

    if diagnostic["slope"] is not None:
        print(
            f"   Current SP+ diagnostic scale: "
            f"{diagnostic['slope']:.3f}"
        )
        print(
            f"   Compression vs SP+ diagnostic: "
            f"{diagnostic['slope'] - slope:.3f} points/unit"
        )

    return {
        "slope": slope,
        "intercept": 0.0,
        "method": "historical_leakage_safe_composite_mean",
        "historical_yearly_slopes": HISTORICAL_SCALE_BY_YEAR,
        "historical_mean": round(HISTORICAL_RATING_SCALE, 6),
        "current_sp_plus_diagnostic": {
            "slope": (
                round(diagnostic["slope"], 6)
                if diagnostic["slope"] is not None
                else None
            ),
            "intercept": (
                round(diagnostic["intercept"], 6)
                if diagnostic["intercept"] is not None
                else None
            ),
            "sample": diagnostic["sample"],
            "used_for_production_lines": False,
        },
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

    bookmakers = raw_game.get("bookmakers", [])
    selected = None

    for key in preferred_books:
        for book in bookmakers:
            if book.get("key") == key:
                selected = book
                break
        if selected:
            break

    if selected is None and bookmakers:
        selected = bookmakers[0]

    if selected is None:
        return {
            "spread": None,
            "total": None,
            "bookmaker": None,
        }

    raw_home = canonical_name(raw_game.get("home_team"))
    spread = None
    total = None

    for market in selected.get("markets", []):
        if market.get("key") == "spreads":
            for outcome in market.get("outcomes", []):
                if canonical_name(outcome.get("name")) == raw_home:
                    spread = optional_number(outcome.get("point"))

        elif market.get("key") == "totals":
            for outcome in market.get("outcomes", []):
                if str(outcome.get("name", "")).lower() == "over":
                    total = optional_number(outcome.get("point"))

    return {
        "spread": spread,
        "total": total,
        "bookmaker": selected.get("title"),
    }


def fetch_odds(valid_teams, lookup):
    print("")
    print("💰 Fetching current NCAAF odds...")

    raw_games = odds_get()
    games = []

    for raw in raw_games:
        raw_home = raw.get("home_team")
        raw_away = raw.get("away_team")

        home = resolve_odds_team(
            raw_home,
            valid_teams,
            lookup,
        )
        away = resolve_odds_team(
            raw_away,
            valid_teams,
            lookup,
        )
        market = extract_market(raw)

        games.append({
            "id": raw.get("id"),
            "commence_time": raw.get("commence_time"),
            "home_team": home,
            "away_team": away,
            "provider_home_team": raw_home,
            "provider_away_team": raw_away,
            "spread_home": market["spread"],
            "total": market["total"],
            "bookmaker": market["bookmaker"],
        })

    matched = sum(
        1
        for game in games
        if game["home_team"] and game["away_team"]
    )

    print(f"✅ Market games found: {len(games)}")
    print(f"✅ Market games matched: {matched}")

    return {
        "meta": {
            "year": YEAR,
            "generated": datetime.now().isoformat(),
            "games": len(games),
            "matched_games": matched,
            "source": "The Odds API",
        },
        "games": games,
    }


# =============================================================================
# SCHEDULE
# =============================================================================

def fetch_schedule(valid_teams, lookup):
    print("")
    print(f"📅 Fetching {YEAR} schedule...")

    raw_games = cfbd_get(
        "/games",
        {
            "year": YEAR,
            "seasonType": "regular",
            "classification": "fbs",
        },
    )

    print(f"   Raw CFBD games returned: {len(raw_games)}")

    fbs_fbs_games = []
    full_team_schedule = {
        team: []
        for team in valid_teams
    }

    rejected_non_fbs = 0
    seen = set()

    for raw in raw_games:
        raw_home = first_value(
            raw,
            "homeTeam",
            "home_team",
        )
        raw_away = first_value(
            raw,
            "awayTeam",
            "away_team",
        )

        home_fbs = resolve_cfbd_team(
            raw_home,
            valid_teams,
            lookup,
        )
        away_fbs = resolve_cfbd_team(
            raw_away,
            valid_teams,
            lookup,
        )

        game_id = first_value(raw, "id")
        start_date = first_value(
            raw,
            "startDate",
            "start_date",
        )
        week = first_value(raw, "week")

        neutral_site = bool(
            first_value(
                raw,
                "neutralSite",
                "neutral_site",
                default=False,
            )
        )

        venue = first_value(raw, "venue")
        home_points = first_value(
            raw,
            "homePoints",
            "home_points",
        )
        away_points = first_value(
            raw,
            "awayPoints",
            "away_points",
        )
        completed = first_value(
            raw,
            "completed",
            default=False,
        )

        # IMPORTANT:
        # Future CFBD games can carry 0-0 score fields. Only the explicit
        # completed flag determines game status.
        is_completed = completed is True

        unique_key = (
            str(game_id)
            if game_id is not None
            else (
                raw_home,
                raw_away,
                start_date,
            )
        )

        if unique_key in seen:
            continue

        seen.add(unique_key)

        if home_fbs and away_fbs:
            game = {
                "id": game_id,
                "week": week,
                "start_date": start_date,
                "home_team": home_fbs,
                "away_team": away_fbs,
                "raw_home_team": raw_home,
                "raw_away_team": raw_away,
                "home_conference": first_value(
                    raw,
                    "homeConference",
                    "home_conference",
                ),
                "away_conference": first_value(
                    raw,
                    "awayConference",
                    "away_conference",
                ),
                "venue": venue,
                "neutral_site": neutral_site,
                "home_points": home_points,
                "away_points": away_points,
                "status": (
                    "completed"
                    if is_completed
                    else "scheduled"
                ),
                "opponent_type": "FBS",
            }

            fbs_fbs_games.append(game)

            full_team_schedule[home_fbs].append({
                **game,
                "team": home_fbs,
                "opponent": away_fbs,
                "location": (
                    "neutral"
                    if neutral_site
                    else "home"
                ),
            })

            full_team_schedule[away_fbs].append({
                **game,
                "team": away_fbs,
                "opponent": home_fbs,
                "location": (
                    "neutral"
                    if neutral_site
                    else "away"
                ),
            })

            continue

        if home_fbs and not away_fbs:
            full_team_schedule[home_fbs].append({
                "id": game_id,
                "week": week,
                "start_date": start_date,
                "team": home_fbs,
                "opponent": raw_away,
                "home_team": home_fbs,
                "away_team": raw_away,
                "location": (
                    "neutral"
                    if neutral_site
                    else "home"
                ),
                "venue": venue,
                "neutral_site": neutral_site,
                "home_points": home_points,
                "away_points": away_points,
                "status": (
                    "completed"
                    if is_completed
                    else "scheduled"
                ),
                "opponent_type": "FCS",
            })
            continue

        if away_fbs and not home_fbs:
            full_team_schedule[away_fbs].append({
                "id": game_id,
                "week": week,
                "start_date": start_date,
                "team": away_fbs,
                "opponent": raw_home,
                "home_team": raw_home,
                "away_team": away_fbs,
                "location": (
                    "neutral"
                    if neutral_site
                    else "away"
                ),
                "venue": venue,
                "neutral_site": neutral_site,
                "home_points": home_points,
                "away_points": away_points,
                "status": (
                    "completed"
                    if is_completed
                    else "scheduled"
                ),
                "opponent_type": "FCS",
            })
            continue

        rejected_non_fbs += 1

    fbs_fbs_games.sort(
        key=lambda game: (
            (
                game.get("week")
                if game.get("week") is not None
                else 99
            ),
            game.get("start_date") or "",
        )
    )

    for team in full_team_schedule:
        full_team_schedule[team].sort(
            key=lambda game: (
                (
                    game.get("week")
                    if game.get("week") is not None
                    else 99
                ),
                game.get("start_date") or "",
            )
        )

    full_entries = sum(
        len(games)
        for games in full_team_schedule.values()
    )

    fcs_entries = sum(
        1
        for games in full_team_schedule.values()
        for game in games
        if game.get("opponent_type") == "FCS"
    )

    print(
        f"✅ TRUE FBS-vs-FBS games: "
        f"{len(fbs_fbs_games)}"
    )
    print(
        f"✅ Team schedule entries: "
        f"{full_entries}"
    )
    print(
        f"✅ FBS-vs-FCS team entries: "
        f"{fcs_entries}"
    )

    if len(fbs_fbs_games) < 400:
        print("❌ Too few FBS-vs-FBS games.")
        sys.exit(1)

    return {
        "meta": {
            "year": YEAR,
            "generated": datetime.now().isoformat(),
            "fbs_fbs_games": len(fbs_fbs_games),
            "team_schedule_entries": full_entries,
            "fbs_fcs_entries": fcs_entries,
            "rejected_non_fbs": rejected_non_fbs,
            "source": "CollegeFootballData",
            "matching": "strict_fbs_school_names",
        },
        "games": fbs_fbs_games,
        "team_schedules": full_team_schedule,
    }


# =============================================================================
# KNOWN SCHEDULE GUARDS
# =============================================================================

def verify_known_schedule_errors(schedule):
    bad = []

    for game in schedule.get("games", []):
        home = game.get("home_team")
        away = game.get("away_team")
        date = str(game.get("start_date", ""))

        if {home, away} == {"Indiana", "Purdue"}:
            if not date.startswith("2026-11-28"):
                bad.append(("Indiana/Purdue", date))

        if {home, away} == {"Florida", "South Carolina"}:
            if not date.startswith("2026-10-10"):
                bad.append(("Florida/South Carolina", date))

    if bad:
        print("❌ Known schedule sanity check failed.")
        print(bad[:10])
        sys.exit(1)

    print("✅ Known schedule sanity checks passed")


# =============================================================================
# LIVE SAMPLE HELPERS
# =============================================================================

def live_section(team, side):
    return (
        (team.get(side, {}) or {})
        .get("live_2026", {})
        or {}
    )


def live_has_general_sample(team):
    offense = live_section(team, "offense")
    defense = live_section(team, "defense")

    return (
        safe_number(offense.get("n_plays"))
        >= MIN_LIVE_PLAYS
        and safe_number(defense.get("n_plays"))
        >= MIN_LIVE_PLAYS
    )


def both_have_general_sample(home, away):
    return (
        live_has_general_sample(home)
        and live_has_general_sample(away)
    )


def both_have_pass_sample(home, away):
    for team in (home, away):
        offense = live_section(team, "offense")
        defense = live_section(team, "defense")

        if (
            safe_number(offense.get("pass_plays"))
            < MIN_LIVE_PASS_PLAYS
        ):
            return False

        if (
            safe_number(defense.get("pass_plays"))
            < MIN_LIVE_PASS_PLAYS
        ):
            return False

    return True


def both_have_rush_sample(home, away):
    for team in (home, away):
        offense = live_section(team, "offense")
        defense = live_section(team, "defense")

        if (
            safe_number(offense.get("rush_plays"))
            < MIN_LIVE_RUSH_PLAYS
        ):
            return False

        if (
            safe_number(defense.get("rush_plays"))
            < MIN_LIVE_RUSH_PLAYS
        ):
            return False

    return True


# =============================================================================
# MATCHUP ADJUSTMENT
# =============================================================================

def bounded(value, cap):
    return max(-cap, min(cap, value))


def calculate_matchup_adjustment(home, away):
    components = {
        "passing": 0.0,
        "rushing": 0.0,
        "success_rate": 0.0,
        "explosiveness": 0.0,
        "havoc": 0.0,
    }

    availability = {
        key: False
        for key in components
    }

    home_off = live_section(home, "offense")
    home_def = live_section(home, "defense")
    away_off = live_section(away, "offense")
    away_def = live_section(away, "defense")

    if both_have_pass_sample(home, away):
        values = [
            optional_number(home_off.get("epa_pass")),
            optional_number(away_def.get("epa_pass")),
            optional_number(away_off.get("epa_pass")),
            optional_number(home_def.get("epa_pass")),
        ]

        if all(value is not None for value in values):
            (
                home_pass,
                away_pass_def,
                away_pass,
                home_pass_def,
            ) = values

            home_edge = home_pass - away_pass_def
            away_edge = away_pass - home_pass_def

            components["passing"] = bounded(
                (home_edge - away_edge) * 1.25,
                1.0,
            )
            availability["passing"] = True

    if both_have_rush_sample(home, away):
        values = [
            optional_number(home_off.get("epa_rush")),
            optional_number(away_def.get("epa_rush")),
            optional_number(away_off.get("epa_rush")),
            optional_number(home_def.get("epa_rush")),
        ]

        if all(value is not None for value in values):
            (
                home_rush,
                away_rush_def,
                away_rush,
                home_rush_def,
            ) = values

            components["rushing"] = bounded(
                (
                    (home_rush - away_rush_def)
                    - (away_rush - home_rush_def)
                ),
                0.75,
            )
            availability["rushing"] = True

    if both_have_general_sample(home, away):
        success_values = [
            optional_number(home_off.get("success_rate")),
            optional_number(away_def.get("success_rate")),
            optional_number(away_off.get("success_rate")),
            optional_number(home_def.get("success_rate")),
        ]

        if all(
            value is not None
            for value in success_values
        ):
            (
                home_sr,
                away_def_sr,
                away_sr,
                home_def_sr,
            ) = success_values

            components["success_rate"] = bounded(
                (
                    (home_sr - away_def_sr)
                    - (away_sr - home_def_sr)
                )
                * 0.035,
                0.75,
            )
            availability["success_rate"] = True

        explosive_values = [
            optional_number(
                home_off.get("explosive_rate")
            ),
            optional_number(
                away_def.get("explosive_rate")
            ),
            optional_number(
                away_off.get("explosive_rate")
            ),
            optional_number(
                home_def.get("explosive_rate")
            ),
        ]

        if all(
            value is not None
            for value in explosive_values
        ):
            (
                home_explosive,
                away_def_explosive,
                away_explosive,
                home_def_explosive,
            ) = explosive_values

            components["explosiveness"] = bounded(
                (
                    (
                        home_explosive
                        - away_def_explosive
                    )
                    - (
                        away_explosive
                        - home_def_explosive
                    )
                )
                * 0.025,
                0.50,
            )
            availability["explosiveness"] = True

        # live_2026 stores "havoc_rate"
        havoc_values = [
            optional_number(home_off.get("havoc_rate")),
            optional_number(home_def.get("havoc_rate")),
            optional_number(away_off.get("havoc_rate")),
            optional_number(away_def.get("havoc_rate")),
        ]

        if all(
            value is not None
            for value in havoc_values
        ):
            (
                home_allowed,
                home_created,
                away_allowed,
                away_created,
            ) = havoc_values

            components["havoc"] = bounded(
                (
                    (home_created - away_allowed)
                    - (away_created - home_allowed)
                )
                * 0.025,
                0.50,
            )
            availability["havoc"] = True

    total = bounded(
        sum(components.values()),
        MAX_MATCHUP_ADJUSTMENT,
    )

    comparable = any(
        availability.values()
    )

    return {
        "total": round(total, 2),
        "components": {
            key: round(value, 2)
            for key, value in components.items()
        },
        "available": availability,
        "comparable_live_sample": comparable,
        "note": (
            "Live matchup adjustments active."
            if comparable
            else (
                "No comparable 2026 live sample; "
                "matchup adjustment held at zero."
            )
        ),
    }


# =============================================================================
# TOTAL MODEL
# =============================================================================

def calculate_total(home, away):
    ho = home.get("offense", {}) or {}
    hd = home.get("defense", {}) or {}
    ao = away.get("offense", {}) or {}
    ad = away.get("defense", {}) or {}

    efficiency = (
        safe_number(ho.get("epa_play"))
        + safe_number(ao.get("epa_play"))
        - safe_number(hd.get("epa_play"))
        - safe_number(ad.get("epa_play"))
    )

    success = (
        safe_number(ho.get("success_rate"))
        + safe_number(ao.get("success_rate"))
        - 85
    )

    total = (
        BASE_TOTAL
        + efficiency * 5.0
        + success * 0.15
    )

    total = max(35, min(80, total))
    return round_half(total)


# =============================================================================
# WIN PROBABILITY
# =============================================================================

def normal_cdf(value):
    return (
        1.0
        + math.erf(
            value / math.sqrt(2.0)
        )
    ) / 2.0


def calculate_win_probability(home_spread):
    home_margin = -safe_number(home_spread)

    probability = normal_cdf(
        home_margin / WIN_PROB_STD_DEV
    )

    probability = max(
        0.01,
        min(0.99, probability),
    )

    return {
        "home": round(
            probability * 100,
            1,
        ),
        "away": round(
            (1.0 - probability) * 100,
            1,
        ),
        "method": (
            "Normal margin distribution, "
            f"sigma={WIN_PROB_STD_DEV:.1f}"
        ),
    }


def fcs_win_probability(
    team_power_rating,
    rating_slope,
    hfa_points=0.0,
):
    """
    Transparent FCS fallback.

    This is not an FCS team rating. A generic 24-point FBS advantage is
    adjusted by FBS team strength. If the FBS team is the true home team,
    its production HFA is added. Neutral/away FBS games receive 0.0.
    """
    power_points = (
        safe_number(team_power_rating)
        * rating_slope
        * FCS_POWER_MULTIPLIER
    )

    expected_margin = (
        FCS_BASE_MARGIN
        + power_points
        + safe_number(hfa_points)
    )

    probability = normal_cdf(
        expected_margin / WIN_PROB_STD_DEV
    )

    probability = max(
        FCS_MIN_WIN_PROB,
        min(
            FCS_MAX_WIN_PROB,
            probability,
        ),
    )

    return {
        "probability": round(
            probability * 100,
            1,
        ),
        "expected_margin": round(
            expected_margin,
            1,
        ),
        "home_field_advantage": round(
            safe_number(hfa_points),
            1,
        ),
        "method": "generic_fcs_fallback",
    }


# =============================================================================
# MARKET STATUS
# =============================================================================

def classify_market_status(disagreement):
    """
    V1 model-vs-market status ladder.

    0.0-2.5   AGREE W/ MARKET
    3.0-5.0   LEAN
    5.5-7.0   EDGE
    7.5-10.0  PLAY
    10.5+     OUTLIER

    Spreads and fair lines are rounded to half-points, so these buckets are
    exhaustive without overlapping boundaries.
    """
    if disagreement <= 2.5:
        return "AGREE W/ MARKET"
    if disagreement <= 5.0:
        return "LEAN"
    if disagreement <= 7.0:
        return "EDGE"
    if disagreement <= 10.0:
        return "PLAY"
    return "OUTLIER"


def compare_to_market(
    model_spread,
    market_spread,
    home_name,
    away_name,
):
    if market_spread is None:
        return {
            "disagreement": None,
            "preferred_side": None,
            "status": "NO MARKET",
            "status_system": "v1_market_disagreement",
            "status_thresholds": {
                "agree_market_max": 2.5,
                "lean_max": 5.0,
                "edge_max": 7.0,
                "play_max": 10.0,
                "outlier_min": 10.5,
            },
            "play_threshold": 7.5,
            "watch_threshold": 3.0,
        }

    difference = model_spread - market_spread
    disagreement = round(abs(difference) * 2) / 2

    if difference < 0:
        preferred = home_name
    elif difference > 0:
        preferred = away_name
    else:
        preferred = None

    status = classify_market_status(disagreement)

    return {
        "disagreement": round(disagreement, 1),
        "preferred_side": preferred,
        "status": status,
        "status_system": "v1_market_disagreement",
        "status_thresholds": {
            "agree_market_max": 2.5,
            "lean_max": 5.0,
            "edge_max": 7.0,
            "play_max": 10.0,
            "outlier_min": 10.5,
        },
        # Legacy fields retained so the current frontend/data consumers do not
        # break while the labels themselves use the new five-tier system.
        "play_threshold": 7.5,
        "watch_threshold": 3.0,
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
    market_spread,
):
    insights = []

    home_rank = home.get("power_rating_rank")
    away_rank = away.get("power_rating_rank")

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
            "title": "OVERALL TEAM STRENGTH",
            "text": (
                f"{stronger} owns the stronger "
                "overall blended power rating."
            ),
            "source": "power_rating",
        })

    if not matchup["comparable_live_sample"]:
        insights.append({
            "title": "LIVE MATCHUP DATA",
            "text": (
                "No live matchup adjustment is being applied "
                "because both teams do not yet have comparable "
                "2026 samples."
            ),
            "source": "sample_guard",
        })
    else:
        usable = [
            (key, value)
            for key, value
            in matchup["components"].items()
            if (
                matchup["available"].get(key)
                and abs(value) >= 0.15
            )
        ]

        usable.sort(
            key=lambda item: abs(item[1]),
            reverse=True,
        )

        labels = {
            "passing": "PASSING MATCHUP",
            "rushing": "RUSHING MATCHUP",
            "success_rate": "EFFICIENCY MATCHUP",
            "explosiveness": "EXPLOSIVENESS",
            "havoc": "HAVOC MATCHUP",
        }

        for key, value in usable[:2]:
            favored = (
                home_name
                if value > 0
                else away_name
            )

            insights.append({
                "title": labels.get(
                    key,
                    key.upper(),
                ),
                "text": (
                    "The comparable 2026 sample "
                    f"leans toward {favored}."
                ),
                "source": key,
            })

    if market_spread is not None:
        difference = (
            model_spread
            - market_spread
        )

        if abs(difference) >= 1.5:
            favored = (
                home_name
                if difference < 0
                else away_name
            )

            insights.append({
                "title": "MARKET VS MODEL",
                "text": (
                    f"The model is {abs(difference):.1f} "
                    f"points more favorable to {favored} "
                    "than the current market."
                ),
                "source": "market",
            })

    return insights[:4]


# =============================================================================
# BUILD FBS PROJECTIONS
# =============================================================================

def build_odds_lookup(odds):
    lookup = {}

    for game in odds.get("games", []):
        home = game.get("home_team")
        away = game.get("away_team")

        if home and away:
            lookup[
                (home, away)
            ] = game

    return lookup


def build_projections(
    teams,
    schedule,
    odds,
    calibration,
    hfa_data,
):
    print("")
    print("🧮 Building game projections...")

    projections = []
    odds_lookup = build_odds_lookup(odds)

    market_matches = 0
    comparable_matchups = 0

    slope = calibration["slope"]

    for game in schedule["games"]:
        home_name = game["home_team"]
        away_name = game["away_team"]

        home = teams[home_name]
        away = teams[away_name]

        home_rating = safe_number(
            home.get("power_rating")
        )
        away_rating = safe_number(
            away.get("power_rating")
        )

        rating_difference = (
            home_rating
            - away_rating
        )

        rating_points = (
            rating_difference
            * slope
        )

        rating_home_spread = (
            -rating_points
        )

        neutral = bool(
            game.get(
                "neutral_site",
                False,
            )
        )

        hfa = get_team_hfa(
            home_name,
            hfa_data,
            neutral=neutral,
        )

        spread_after_hfa = (
            rating_home_spread
            - hfa
        )

        matchup = calculate_matchup_adjustment(
            home,
            away,
        )

        if matchup["comparable_live_sample"]:
            comparable_matchups += 1

        model_spread = round_half(
            spread_after_hfa
            - matchup["total"]
        )

        model_total = calculate_total(
            home,
            away,
        )

        win_probability = (
            calculate_win_probability(
                model_spread
            )
        )

        market = odds_lookup.get(
            (home_name, away_name)
        )

        market_spread = None
        market_total = None
        bookmaker = None

        if market:
            market_matches += 1
            market_spread = market.get(
                "spread_home"
            )
            market_total = market.get(
                "total"
            )
            bookmaker = market.get(
                "bookmaker"
            )

        comparison = compare_to_market(
            model_spread,
            market_spread,
            home_name,
            away_name,
        )

        projections.append({
            "game_id": game.get("id"),
            "week": game.get("week"),
            "start_date": game.get("start_date"),
            "neutral_site": neutral,
            "venue": game.get("venue"),
            "status": game.get("status"),

            "home": {
                "team": home_name,
                "conference": home.get("conference"),
                "power_rating": home_rating,
                "power_rating_rank": (
                    home.get("power_rating_rank")
                ),
            },

            "away": {
                "team": away_name,
                "conference": away.get("conference"),
                "power_rating": away_rating,
                "power_rating_rank": (
                    away.get("power_rating_rank")
                ),
            },

            "projection": {
                "home_spread": model_spread,
                "total": model_total,
                "win_probability": win_probability,

                "components": {
                    "home_power_rating": round(
                        home_rating,
                        3,
                    ),
                    "away_power_rating": round(
                        away_rating,
                        3,
                    ),
                    "rating_difference": round(
                        rating_difference,
                        3,
                    ),
                    "rating_points_home_edge": round(
                        rating_points,
                        2,
                    ),
                    "rating_only_home_spread": (
                        round_half(
                            rating_home_spread
                        )
                    ),
                    "home_field_advantage": round(
                        hfa,
                        1,
                    ),
                    "home_field_source": (
                        "neutral_site"
                        if neutral
                        else "team_specific_2026"
                    ),
                    "spread_after_home_field": (
                        round_half(
                            spread_after_hfa
                        )
                    ),
                    "matchup_adjustment": matchup,
                    "final_home_spread": (
                        model_spread
                    ),
                },

                "base_home_spread": (
                    round_half(
                        spread_after_hfa
                    )
                ),
                "home_field_advantage": round(
                    hfa,
                    1,
                ),
                "home_field_source": (
                    "neutral_site"
                    if neutral
                    else "team_specific_2026"
                ),
                "matchup_adjustment": matchup,
            },

            "market": {
                "home_spread": market_spread,
                "total": market_total,
                "bookmaker": bookmaker,
            },

            "comparison": comparison,

            "insights": generate_insights(
                home_name,
                away_name,
                home,
                away,
                matchup,
                model_spread,
                market_spread,
            ),
        })

    print(
        f"✅ Projections built: "
        f"{len(projections)}"
    )
    print(
        f"✅ Projections with market match: "
        f"{market_matches}"
    )
    print(
        "✅ Games with comparable live "
        f"matchup samples: {comparable_matchups}"
    )

    return projections


# =============================================================================
# SEASON PROJECTIONS
# =============================================================================

def completed_team_result(team, game):
    if game.get("status") != "completed":
        return None

    home = game.get("home_team")
    away = game.get("away_team")

    home_points = optional_number(
        game.get("home_points")
    )
    away_points = optional_number(
        game.get("away_points")
    )

    if (
        home_points is None
        or away_points is None
    ):
        return None

    if home_points == away_points:
        return None

    winner = (
        home
        if home_points > away_points
        else away
    )

    return (
        1.0
        if winner == team
        else 0.0
    )


def probability_distribution(probabilities):
    distribution = [1.0]

    for probability in probabilities:
        p = max(
            0.0,
            min(
                1.0,
                probability,
            ),
        )

        next_distribution = [
            0.0
            for _ in range(
                len(distribution) + 1
            )
        ]

        for wins, current_probability in enumerate(
            distribution
        ):
            next_distribution[wins] += (
                current_probability
                * (1.0 - p)
            )

            next_distribution[wins + 1] += (
                current_probability
                * p
            )

        distribution = next_distribution

    return distribution


def probability_at_least(
    distribution,
    wins,
):
    if wins <= 0:
        return 1.0

    if wins >= len(distribution):
        return 0.0

    return sum(
        distribution[wins:]
    )


def alt_total_probabilities(distribution):
    output = {}
    max_wins = len(distribution) - 1

    for wins in range(
        4,
        max_wins + 1,
    ):
        line = wins + 0.5

        over_probability = sum(
            distribution[
                wins + 1:
            ]
        )
        under_probability = (
            1.0
            - over_probability
        )

        output[f"{line:.1f}"] = {
            "over": round(
                over_probability * 100,
                1,
            ),
            "under": round(
                under_probability * 100,
                1,
            ),
        }

    return output


def build_projection_lookup(projections):
    return {
        str(game.get("game_id")): game
        for game in projections
    }


def build_season_projections(
    teams,
    schedule,
    projections,
    calibration,
    hfa_data,
):
    print("")
    print(
        "📈 Building season win "
        "distributions..."
    )

    game_lookup = build_projection_lookup(
        projections
    )

    slope = calibration["slope"]
    season_output = {}

    for team_name, team in teams.items():
        games = (
            schedule
            .get(
                "team_schedules",
                {},
            )
            .get(
                team_name,
                [],
            )
        )

        if not games:
            continue

        game_probabilities = []
        schedule_projection = []

        actual_wins = 0
        actual_losses = 0

        for game in games:
            completed_result = (
                completed_team_result(
                    team_name,
                    game,
                )
            )

            hfa_used = None

            if completed_result is not None:
                probability = completed_result
                source = "completed_result"

                if probability == 1.0:
                    actual_wins += 1
                else:
                    actual_losses += 1

                model_line = None

            elif (
                game.get("opponent_type")
                == "FBS"
            ):
                projection = game_lookup.get(
                    str(game.get("id"))
                )

                if projection is None:
                    continue

                if (
                    projection["home"]["team"]
                    == team_name
                ):
                    probability = (
                        projection[
                            "projection"
                        ][
                            "win_probability"
                        ][
                            "home"
                        ]
                        / 100.0
                    )

                    model_line = (
                        projection[
                            "projection"
                        ][
                            "home_spread"
                        ]
                    )
                else:
                    probability = (
                        projection[
                            "projection"
                        ][
                            "win_probability"
                        ][
                            "away"
                        ]
                        / 100.0
                    )

                    model_line = -(
                        projection[
                            "projection"
                        ][
                            "home_spread"
                        ]
                    )

                hfa_used = (
                    projection[
                        "projection"
                    ].get(
                        "home_field_advantage"
                    )
                )

                source = "fbs_model"

            else:
                neutral = bool(
                    game.get(
                        "neutral_site",
                        False,
                    )
                )

                is_true_home = (
                    game.get("location")
                    == "home"
                    and not neutral
                )

                hfa_used = (
                    get_team_hfa(
                        team_name,
                        hfa_data,
                        neutral=False,
                    )
                    if is_true_home
                    else 0.0
                )

                fallback = (
                    fcs_win_probability(
                        team.get(
                            "power_rating"
                        ),
                        slope,
                        hfa_points=hfa_used,
                    )
                )

                probability = (
                    fallback[
                        "probability"
                    ]
                    / 100.0
                )

                source = "fcs_fallback"

                model_line = -(
                    fallback[
                        "expected_margin"
                    ]
                )

            game_probabilities.append(
                probability
            )

            schedule_projection.append({
                "game_id": game.get("id"),
                "week": game.get("week"),
                "start_date": (
                    game.get("start_date")
                ),
                "opponent": (
                    game.get("opponent")
                ),
                "opponent_type": (
                    game.get(
                        "opponent_type"
                    )
                ),
                "location": (
                    game.get("location")
                ),
                "status": (
                    game.get("status")
                ),
                "win_probability": round(
                    probability * 100,
                    1,
                ),
                "team_line": (
                    round_half(
                        model_line
                    )
                    if model_line
                    is not None
                    else None
                ),
                "home_field_advantage_used": (
                    hfa_used
                ),
                "probability_source": source,
            })

        if not game_probabilities:
            continue

        distribution = (
            probability_distribution(
                game_probabilities
            )
        )

        exact_wins = {
            str(wins): round(
                probability * 100,
                1,
            )
            for wins, probability
            in enumerate(distribution)
        }

        expected_wins = sum(
            game_probabilities
        )

        most_likely_wins = max(
            range(
                len(distribution)
            ),
            key=lambda wins: (
                distribution[wins]
            ),
        )

        games_count = len(
            game_probabilities
        )

        most_likely_losses = (
            games_count
            - most_likely_wins
        )

        at_least = {}

        for target in (
            6,
            8,
            9,
            10,
            11,
            12,
        ):
            at_least[
                str(target)
            ] = round(
                probability_at_least(
                    distribution,
                    target,
                )
                * 100,
                1,
            )

        season_output[team_name] = {
            "team": team_name,
            "games": games_count,
            "actual_wins": actual_wins,
            "actual_losses": actual_losses,
            "expected_wins": round(
                expected_wins,
                2,
            ),
            "expected_losses": round(
                games_count
                - expected_wins,
                2,
            ),
            "most_likely_record": (
                f"{most_likely_wins}-"
                f"{most_likely_losses}"
            ),
            "most_likely_wins": (
                most_likely_wins
            ),
            "most_likely_probability": round(
                distribution[
                    most_likely_wins
                ]
                * 100,
                1,
            ),
            "exact_win_distribution": (
                exact_wins
            ),
            "at_least": {
                "6_wins": at_least["6"],
                "8_wins": at_least["8"],
                "9_wins": at_least["9"],
                "10_wins": at_least["10"],
                "11_wins": at_least["11"],
                "12_wins": at_least["12"],
            },
            "bowl_eligible_probability": (
                at_least["6"]
            ),
            "alt_win_totals": (
                alt_total_probabilities(
                    distribution
                )
            ),
            "schedule": (
                schedule_projection
            ),
        }

    print(
        f"✅ Season projections built: "
        f"{len(season_output)} teams"
    )

    return season_output


# =============================================================================
# VALIDATION
# =============================================================================

def validate_projection_output(
    projections,
    season_projections,
):
    if len(projections) < 400:
        print(
            "❌ Too few game projections."
        )
        sys.exit(1)

    if len(season_projections) < 100:
        print(
            "❌ Too few season projections."
        )
        sys.exit(1)

    bad_distributions = []

    for team, data in (
        season_projections.items()
    ):
        distribution = (
            data.get(
                "exact_win_distribution",
                {},
            )
        )

        total = sum(
            safe_number(value)
            for value
            in distribution.values()
        )

        if abs(total - 100) > 0.5:
            bad_distributions.append(
                (
                    team,
                    total,
                )
            )

    if bad_distributions:
        print(
            "❌ Win distribution sanity "
            "check failed."
        )
        print(
            bad_distributions[:10]
        )
        sys.exit(1)

    print(
        "✅ Projection sanity checks passed"
    )


# =============================================================================
# SAVE
# =============================================================================

def save_json(path, data):
    os.makedirs(
        os.path.dirname(path),
        exist_ok=True,
    )

    temp = path + ".tmp"

    with open(
        temp,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False,
        )

    with open(
        temp,
        "r",
        encoding="utf-8",
    ) as file:
        json.load(file)

    os.replace(
        temp,
        path,
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
    print(f"Season: {YEAR}")

    metrics_data, teams = (
        load_metrics()
    )

    valid_teams = set(
        teams.keys()
    )

    lookup = build_team_lookup(
        valid_teams
    )

    hfa_data = load_hfa(
        valid_teams
    )

    calibration = (
        calculate_rating_scale(
            teams
        )
    )

    odds = fetch_odds(
        valid_teams,
        lookup,
    )

    save_json(
        ODDS_PATH,
        odds,
    )

    schedule = fetch_schedule(
        valid_teams,
        lookup,
    )

    verify_known_schedule_errors(
        schedule
    )

    save_json(
        SCHEDULE_PATH,
        schedule,
    )

    projections = build_projections(
        teams,
        schedule,
        odds,
        calibration,
        hfa_data,
    )

    season_projections = (
        build_season_projections(
            teams,
            schedule,
            projections,
            calibration,
            hfa_data,
        )
    )

    validate_projection_output(
        projections,
        season_projections,
    )

    hfa_meta = (
        hfa_data.get(
            "meta",
            {},
        )
        or {}
    )

    output = {
        "meta": {
            "year": YEAR,
            "generated": (
                datetime.now().isoformat()
            ),
            "games": len(
                projections
            ),
            "teams_with_season_projection": (
                len(season_projections)
            ),
            "version": (
                "3.2-historical-rating-scale"
            ),
            "calibration": (
                calibration
            ),
            "home_field_advantage": {
                "type": "team_specific",
                "source": HFA_PATH,
                "version": (
                    hfa_meta.get(
                        "version"
                    )
                ),
                "default": safe_number(
                    hfa_meta.get(
                        "default_hfa"
                    ),
                    2.0,
                ),
                "minimum": safe_number(
                    hfa_meta.get(
                        "minimum_hfa"
                    ),
                    1.0,
                ),
                "maximum": safe_number(
                    hfa_meta.get(
                        "maximum_hfa"
                    ),
                    3.5,
                ),
                "neutral_site": safe_number(
                    hfa_meta.get(
                        "neutral_site_hfa"
                    ),
                    0.0,
                ),
                "situational_modifiers_included": (
                    False
                ),
            },
            "max_matchup_adjustment": (
                MAX_MATCHUP_ADJUSTMENT
            ),
            "win_probability_std_dev": (
                WIN_PROB_STD_DEV
            ),
            "fcs_model": {
                "base_margin": (
                    FCS_BASE_MARGIN
                ),
                "power_multiplier": (
                    FCS_POWER_MULTIPLIER
                ),
                "minimum_win_probability": (
                    FCS_MIN_WIN_PROB
                    * 100
                ),
                "maximum_win_probability": (
                    FCS_MAX_WIN_PROB
                    * 100
                ),
                "home_hfa_rule": (
                    "FBS team-specific HFA added only "
                    "when the FBS team is the true home "
                    "team; neutral/away receives 0.0."
                ),
                "note": (
                    "Generic fallback used only for "
                    "season-win projections."
                ),
            },
            "live_matchup_rules": {
                "minimum_plays": (
                    MIN_LIVE_PLAYS
                ),
                "minimum_pass_plays": (
                    MIN_LIVE_PASS_PLAYS
                ),
                "minimum_rush_plays": (
                    MIN_LIVE_RUSH_PLAYS
                ),
                "requires_both_teams": True,
            },
            "metrics_through_week": (
                metrics_data
                .get(
                    "meta",
                    {},
                )
                .get(
                    "through_week"
                )
            ),
        },
        "games": projections,
        "season_projections": (
            season_projections
        ),
    }

    save_json(
        PROJECTIONS_PATH,
        output,
    )

    print("")
    print("=" * 70)
    print(
        "🎉 PROJECTION BUILD COMPLETE"
    )
    print("=" * 70)
    print(
        f"FBS-vs-FBS games: "
        f"{len(projections)}"
    )
    print(
        f"Season projections: "
        f"{len(season_projections)} teams"
    )


if __name__ == "__main__":
    main()
