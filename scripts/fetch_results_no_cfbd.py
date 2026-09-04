#!/usr/bin/env python3
"""
CFB ANALYTICS
fetch_results_no_cfbd.py

Live + completed FBS scoreboard refresh without CFBD.

PRIMARY SOURCE
    NCAA scoreboard via the public ncaa-api proxy.

FALLBACK SOURCE
    ESPN public scoreboard endpoint, used only to fill games that the NCAA
    scoreboard does not currently expose as LIVE or FINAL.

OUTPUTS
    data/results.json
        Completed games only. Existing finals are preserved.

    data/live_scores.json
        Current in-progress games only. Rebuilt every run.

SAFETY
    - no CFBD
    - no model rebuild
    - live games never enter results.json
    - a final is accepted only when a provider explicitly marks it completed/post
    - NCAA wins when both providers contain the same matchup/state
    - ESPN is a coverage fallback, not a model input
    - provider team names are aligned to exact projection-board names
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = ROOT / "data" / "results.json"
LIVE_PATH = ROOT / "data" / "live_scores.json"
PROJECTIONS_PATH = ROOT / "data" / "projections.json"

SEASON = int(os.getenv("CFB_SEASON", "2026"))
NCAA_BASE_URL = "https://ncaa-api.henrygd.me/scoreboard/football/fbs"
ESPN_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/"
    "college-football/scoreboard"
)
ALL_WEEKS = list(range(1, 21))

SESSION = requests.Session()
SESSION.headers.update(
    {
        "Accept": "application/json",
        "User-Agent": "the-hammer-index-scoreboard/4.0",
    }
)

# Conservative provider-name cleanup into the naming used by the public board.
TEAM_NAME_ALIASES = {
    "Ark.-Pine Bluff": "Arkansas Pine Bluff",
    "Ark.-Pine Bluff.": "Arkansas Pine Bluff",
    "Ark. Pine Bluff": "Arkansas Pine Bluff",
    "Arkansas-Pine Bluff": "Arkansas Pine Bluff",
    "Eastern Ill.": "Eastern Illinois",
    "West Ga.": "West Georgia",
    "UAlbany": "Albany",
    "Miami (FL)": "Miami",
    "Miami (Fla.)": "Miami",
    "Southern California": "USC",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return fallback

    return payload if isinstance(payload, dict) else fallback


def first_nonempty(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def as_int(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def clean_team_name(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    return TEAM_NAME_ALIASES.get(text, text)


def canonical_team(value: Any) -> str:
    text = clean_team_name(value) or ""
    text = text.lower().replace("&", "and")
    text = re.sub(r"\buniversity\b", "", text)
    text = re.sub(r"\bst\.?\b", "state", text)
    text = re.sub(r"\bmich\.?\b", "michigan", text)
    text = re.sub(r"[^a-z0-9]+", "", text)

    aliases = {
        "miamifla": "miami",
        "miamiflorida": "miami",
        "olemiss": "mississippi",
        "southernmiss": "southernmississippi",
        "utsa": "texassanantonio",
        "utep": "texaselpaso",
        "ucf": "centralflorida",
        "byu": "brighamyoung",
        "lsu": "louisianastate",
        "smu": "southernmethodist",
        "tcu": "texaschristian",
        "southerncalifornia": "usc",
        "arkpinebluff": "arkansaspinebluff",
        "ualbany": "albany",
    }
    return aliases.get(text, text)


def matchup_key(game: dict[str, Any]) -> str:
    away = canonical_team(game.get("away_team"))
    home = canonical_team(game.get("home_team"))
    return f"{away}@{home}" if away and home else ""


def request_json(url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(1, 4):
        try:
            response = SESSION.get(url, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()

            if not isinstance(payload, dict):
                raise ValueError("scoreboard response was not a JSON object")

            return payload

        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt * 2)

    raise RuntimeError(f"Unable to fetch scoreboard URL: {url}") from last_error


def projection_matchups() -> dict[str, tuple[str, str]]:
    """
    Build a lookup from canonical away@home to the EXACT team names currently
    rendered by the projection board.

    This removes the need for the scoreboard layer to guess whether a school is
    displayed as Albany/UAlbany, Arkansas Pine Bluff/Ark.-Pine Bluff, etc.
    """
    payload = load_json(PROJECTIONS_PATH, {"games": []})

    if isinstance(payload, dict):
        games = payload.get("games") or payload.get("projections") or []
    elif isinstance(payload, list):
        games = payload
    else:
        games = []

    lookup: dict[str, tuple[str, str]] = {}

    for game in games:
        if not isinstance(game, dict):
            continue

        away_obj = game.get("away") or {}
        home_obj = game.get("home") or {}

        away = (
            away_obj.get("team")
            if isinstance(away_obj, dict)
            else None
        ) or game.get("away_team") or game.get("awayTeam")

        home = (
            home_obj.get("team")
            if isinstance(home_obj, dict)
            else None
        ) or game.get("home_team") or game.get("homeTeam")

        away = str(away or "").strip()
        home = str(home or "").strip()

        if not away or not home:
            continue

        key = f"{canonical_team(away)}@{canonical_team(home)}"
        if key and "@" in key:
            lookup[key] = (away, home)

    return lookup


def align_to_projection_names(
    game: dict[str, Any],
    known_matchups: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    """
    Rewrite provider team names to the exact names used in projections.json
    whenever the matchup can be resolved canonically.
    """
    key = matchup_key(game)
    exact = known_matchups.get(key)

    if not exact:
        return game

    away, home = exact
    return {
        **game,
        "away_team": away,
        "home_team": home,
    }


# ============================================================================
# NCAA
# ============================================================================

def fetch_ncaa_week(week: int) -> dict[str, Any]:
    return request_json(
        f"{NCAA_BASE_URL}/{SEASON}/{week:02d}/all-conf"
    )


def unwrap_games(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("games", "contests", "events"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("games", "contests", "events"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []


def unwrap_game(entry: dict[str, Any]) -> dict[str, Any]:
    nested = entry.get("game")
    return nested if isinstance(nested, dict) else entry


def ncaa_team_name(team: Any) -> str | None:
    if not isinstance(team, dict):
        return None

    names = team.get("names")
    if isinstance(names, dict):
        value = first_nonempty(
            names.get("full"),
            names.get("short"),
            names.get("char6"),
            names.get("seo"),
        )
        cleaned = clean_team_name(value)
        if cleaned:
            return cleaned

    return clean_team_name(
        first_nonempty(
            team.get("name"),
            team.get("displayName"),
            team.get("shortName"),
            team.get("nameShort"),
            team.get("seo"),
        )
    )


def ncaa_team_id(team: Any) -> str | None:
    if not isinstance(team, dict):
        return None

    value = first_nonempty(
        team.get("id"),
        team.get("teamId"),
        team.get("team_id"),
        team.get("seo"),
        team.get("seoname"),
    )
    return str(value) if value is not None else None


def ncaa_team_score(team: Any) -> int | None:
    if not isinstance(team, dict):
        return None

    return as_int(
        first_nonempty(
            team.get("score"),
            team.get("points"),
            team.get("scoreValue"),
        )
    )


def ncaa_home_away(
    game: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    home = first_nonempty(
        game.get("home"),
        game.get("homeTeam"),
        game.get("home_team"),
    )
    away = first_nonempty(
        game.get("away"),
        game.get("awayTeam"),
        game.get("away_team"),
    )

    if isinstance(home, dict) and isinstance(away, dict):
        return home, away

    teams = game.get("teams")
    if isinstance(teams, list):
        home = None
        away = None

        for team in teams:
            if not isinstance(team, dict):
                continue

            if team.get("isHome") is True:
                home = team
                continue
            if team.get("isHome") is False:
                away = team
                continue

            designation = str(
                first_nonempty(
                    team.get("homeAway"),
                    team.get("designation"),
                    team.get("location"),
                )
                or ""
            ).strip().lower()

            if designation == "home":
                home = team
            elif designation == "away":
                away = team

        if isinstance(home, dict) and isinstance(away, dict):
            return home, away

    return None, None


def ncaa_status_value(game: dict[str, Any]) -> Any:
    status = first_nonempty(
        game.get("status"),
        game.get("statusText"),
        game.get("finalMessage"),
    )

    if isinstance(status, dict):
        status = first_nonempty(
            status.get("state"),
            status.get("type"),
            status.get("name"),
            status.get("description"),
            status.get("detail"),
        )

    return status


def ncaa_period_value(game: dict[str, Any]) -> Any:
    return first_nonempty(
        game.get("currentPeriod"),
        game.get("period"),
        game.get("quarter"),
    )


def ncaa_clock_value(game: dict[str, Any]) -> Any:
    return first_nonempty(
        game.get("contestClock"),
        game.get("clock"),
        game.get("displayClock"),
    )


def ncaa_state(game: dict[str, Any]) -> str:
    raw = first_nonempty(
        game.get("gameState"),
        game.get("game_state"),
        game.get("state"),
    )

    if isinstance(raw, dict):
        raw = first_nonempty(
            raw.get("state"),
            raw.get("type"),
            raw.get("name"),
            raw.get("description"),
            raw.get("detail"),
        )

    compact = re.sub(
        r"[^a-z0-9]+",
        "",
        str(raw or "").strip().lower(),
    )

    if compact in {
        "f", "final", "post", "completed", "complete", "closed",
        "finalot", "final2ot", "final3ot",
    } or compact.startswith("final"):
        return "final"

    if compact in {
        "i", "in", "live", "inprogress",
        "d", "delay", "delayed", "weatherdelay",
        "suspended", "suspend", "interrupted",
        "halftime", "half", "ot", "overtime",
    }:
        return "live"

    status_text = str(
        ncaa_status_value(game) or ""
    ).strip().lower()

    if any(
        word in status_text
        for word in ("final", "completed", "complete")
    ):
        return "final"

    if any(
        word in status_text
        for word in (
            "live", "in progress", "in-progress",
            "delay", "suspend", "interrupted",
            "halftime", "half time", "overtime",
        )
    ):
        return "live"

    if re.search(r"\b(?:1st|2nd|3rd|4th)\b", status_text):
        return "live"

    if re.search(r"\bq[1-4]\b", status_text):
        return "live"

    home, away = ncaa_home_away(game)
    has_scores = (
        ncaa_team_score(home) is not None
        and ncaa_team_score(away) is not None
    )

    period = ncaa_period_value(game)
    clock = ncaa_clock_value(game)

    has_period = (
        period is not None
        and str(period).strip() not in {"", "0"}
    )
    has_clock = (
        clock is not None
        and str(clock).strip() not in {"", "0", "0:00", "00:00"}
    )

    if has_scores and (has_period or has_clock):
        return "live"

    return "pre"


def clean_period(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text.upper() if text else None


def clean_clock(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text if text else None


def ncaa_game_identity(
    game: dict[str, Any],
    week: int,
    away_name: str,
    home_name: str,
) -> str:
    value = first_nonempty(
        game.get("gameID"),
        game.get("gameId"),
        game.get("id"),
        game.get("contestId"),
        game.get("contest_id"),
    )

    if value is not None:
        return str(value)

    slug = f"ncaa-{SEASON}-{week}-{away_name}-{home_name}".lower()
    return re.sub(r"[^a-z0-9]+", "-", slug).strip("-")


def normalize_ncaa_entry(
    entry: dict[str, Any],
    week: int,
) -> dict[str, Any] | None:
    game = unwrap_game(entry)
    home, away = ncaa_home_away(game)

    if not isinstance(home, dict) or not isinstance(away, dict):
        return None

    home_name = ncaa_team_name(home)
    away_name = ncaa_team_name(away)

    if not home_name or not away_name:
        return None

    state = ncaa_state(game)
    if state == "pre":
        return None

    home_points = ncaa_team_score(home)
    away_points = ncaa_team_score(away)

    if home_points is None or away_points is None:
        return None

    game_id = ncaa_game_identity(
        game,
        week,
        away_name,
        home_name,
    )

    start_date = first_nonempty(
        game.get("startDate"),
        game.get("start_date"),
        game.get("startTimeEpoch"),
        game.get("date"),
    )

    base = {
        "game_id": game_id,
        "season": SEASON,
        "week": week,
        "home_team": home_name,
        "away_team": away_name,
        "home_team_id": ncaa_team_id(home),
        "away_team_id": ncaa_team_id(away),
        "home_points": home_points,
        "away_points": away_points,
        "start_date": start_date,
        "neutral_site": bool(
            first_nonempty(
                game.get("neutralSite"),
                game.get("neutral_site"),
                False,
            )
        ),
        "source": "NCAA",
        "source_updated_at": iso_now(),
    }

    if state == "final":
        return {
            **base,
            "status": "completed",
            "game_state": "final",
            "final_message": str(
                game.get("finalMessage")
                or ncaa_status_value(game)
                or "FINAL"
            ).upper(),
        }

    return {
        **base,
        "status": "live",
        "game_state": "live",
        "period": clean_period(ncaa_period_value(game)),
        "clock": clean_clock(ncaa_clock_value(game)),
        "network": first_nonempty(
            game.get("network"),
            game.get("broadcasterName"),
        ),
        "provider_status": (
            str(ncaa_status_value(game)).strip()
            if ncaa_status_value(game) is not None
            else None
        ),
    }


# ============================================================================
# ESPN FALLBACK
# ============================================================================

def espn_dates() -> list[str]:
    now = utc_now()
    return [
        (now + timedelta(days=offset)).strftime("%Y%m%d")
        for offset in (-1, 0, 1)
    ]


def fetch_espn_date(date_string: str) -> dict[str, Any]:
    return request_json(
        ESPN_SCOREBOARD_URL,
        params={
            "dates": date_string,
            "groups": "80",
            "limit": "1000",
        },
    )


def espn_competitors(
    competition: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    home = None
    away = None

    for competitor in competition.get("competitors") or []:
        if not isinstance(competitor, dict):
            continue

        side = str(
            competitor.get("homeAway") or ""
        ).strip().lower()

        if side == "home":
            home = competitor
        elif side == "away":
            away = competitor

    return home, away


def espn_team_name(competitor: Any) -> str | None:
    if not isinstance(competitor, dict):
        return None

    team = competitor.get("team") or {}
    if not isinstance(team, dict):
        team = {}

    return clean_team_name(
        first_nonempty(
            team.get("displayName"),
            team.get("shortDisplayName"),
            team.get("name"),
            team.get("location"),
            competitor.get("name"),
        )
    )


def espn_team_id(competitor: Any) -> str | None:
    if not isinstance(competitor, dict):
        return None

    team = competitor.get("team") or {}
    if not isinstance(team, dict):
        return None

    value = team.get("id")
    return str(value) if value is not None else None


def espn_score(competitor: Any) -> int | None:
    if not isinstance(competitor, dict):
        return None
    return as_int(competitor.get("score"))


def espn_state(event: dict[str, Any], competition: dict[str, Any]) -> str:
    status = competition.get("status") or event.get("status") or {}
    if not isinstance(status, dict):
        status = {}

    status_type = status.get("type") or {}
    if not isinstance(status_type, dict):
        status_type = {}

    state = str(
        first_nonempty(
            status_type.get("state"),
            status.get("state"),
            "",
        )
    ).strip().lower()

    completed = bool(
        first_nonempty(
            status_type.get("completed"),
            status.get("completed"),
            False,
        )
    )

    name = str(
        first_nonempty(
            status_type.get("name"),
            status_type.get("description"),
            status_type.get("detail"),
            status.get("displayClock"),
            "",
        )
    ).strip().lower()

    if completed or state == "post" or "final" in name:
        return "final"

    if state == "in":
        return "live"

    if any(
        word in name
        for word in (
            "delay", "suspend", "halftime",
            "overtime", "1st", "2nd", "3rd", "4th",
        )
    ):
        return "live"

    return "pre"


def espn_week(
    payload: dict[str, Any],
    event: dict[str, Any],
    default_week: int,
) -> int:
    candidates = [
        event.get("week"),
        payload.get("week"),
    ]

    season = event.get("season")
    if isinstance(season, dict):
        candidates.append(season.get("week"))

    for candidate in candidates:
        if isinstance(candidate, dict):
            number = as_int(
                first_nonempty(
                    candidate.get("number"),
                    candidate.get("value"),
                )
            )
        else:
            number = as_int(candidate)

        if number is not None:
            return number

    return default_week


def normalize_espn_event(
    payload: dict[str, Any],
    event: dict[str, Any],
    default_week: int,
) -> dict[str, Any] | None:
    competitions = event.get("competitions") or []
    if not competitions or not isinstance(competitions[0], dict):
        return None

    competition = competitions[0]
    home, away = espn_competitors(competition)

    home_name = espn_team_name(home)
    away_name = espn_team_name(away)

    if not home_name or not away_name:
        return None

    state = espn_state(event, competition)
    if state == "pre":
        return None

    home_points = espn_score(home)
    away_points = espn_score(away)

    if home_points is None or away_points is None:
        return None

    status = competition.get("status") or event.get("status") or {}
    if not isinstance(status, dict):
        status = {}
    status_type = status.get("type") or {}
    if not isinstance(status_type, dict):
        status_type = {}

    detail = first_nonempty(
        status_type.get("shortDetail"),
        status_type.get("detail"),
        status_type.get("description"),
    )

    period = first_nonempty(
        status.get("period"),
        competition.get("status", {}).get("period")
        if isinstance(competition.get("status"), dict)
        else None,
    )

    clock = first_nonempty(
        status.get("displayClock"),
        status_type.get("displayClock"),
    )

    broadcasts = competition.get("broadcasts") or []
    network = None
    if broadcasts and isinstance(broadcasts[0], dict):
        names = broadcasts[0].get("names") or []
        if names:
            network = names[0]

    week = espn_week(
        payload,
        event,
        default_week,
    )

    base = {
        "game_id": str(
            first_nonempty(
                event.get("id"),
                competition.get("id"),
                f"espn-{SEASON}-{week}-{away_name}-{home_name}",
            )
        ),
        "season": SEASON,
        "week": week,
        "home_team": home_name,
        "away_team": away_name,
        "home_team_id": espn_team_id(home),
        "away_team_id": espn_team_id(away),
        "home_points": home_points,
        "away_points": away_points,
        "start_date": first_nonempty(
            event.get("date"),
            competition.get("date"),
        ),
        "neutral_site": bool(
            competition.get("neutralSite", False)
        ),
        "source": "ESPN fallback",
        "source_updated_at": iso_now(),
    }

    if state == "final":
        return {
            **base,
            "status": "completed",
            "game_state": "final",
            "final_message": str(detail or "FINAL").upper(),
        }

    return {
        **base,
        "status": "live",
        "game_state": "live",
        "period": clean_period(period),
        "clock": clean_clock(clock),
        "network": network,
        "provider_status": str(detail).strip() if detail else None,
    }


# ============================================================================
# MERGE / WEEK SELECTION
# ============================================================================

def infer_active_week(
    existing_payload: dict[str, Any],
) -> int:
    completed_weeks = [
        as_int(game.get("week"))
        for game in existing_payload.get("games", [])
        if (
            isinstance(game, dict)
            and as_int(game.get("week")) is not None
        )
    ]

    if completed_weeks:
        return max(completed_weeks)

    scan_log = existing_payload.get("scan_log", [])
    candidates: list[int] = []

    if isinstance(scan_log, list):
        for row in scan_log:
            if not isinstance(row, dict):
                continue
            if row.get("status") != "ok":
                continue
            if int(row.get("scoreboard_games", 0) or 0) <= 0:
                continue

            week = as_int(row.get("week"))
            if week is not None:
                candidates.append(week)

    return min(candidates) if candidates else 1


def choose_weeks(
    existing_payload: dict[str, Any],
) -> tuple[list[int], str]:
    now = utc_now()

    if now.hour == 8 and now.minute < 15:
        return ALL_WEEKS, "daily_full_reconciliation"

    active = infer_active_week(existing_payload)

    weeks = sorted(
        {
            week
            for week in (
                active - 1,
                active,
                active + 1,
            )
            if 1 <= week <= 20
        }
    )

    return weeks, "targeted_live_refresh"


def combine_provider_rows(
    ncaa_rows: list[dict[str, Any]],
    espn_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    NCAA is primary. ESPN fills only matchups NCAA did not return in this state.
    """
    merged: dict[str, dict[str, Any]] = {}

    for game in ncaa_rows:
        key = matchup_key(game)
        if key:
            merged[key] = game

    for game in espn_rows:
        key = matchup_key(game)
        if key and key not in merged:
            merged[key] = game

    return list(merged.values())


def merge_completed(
    existing: list[dict[str, Any]],
    fetched: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Season-long durable final ledger.

    Dedupe first by matchup when possible, otherwise by provider game id.
    A freshly fetched final replaces an older row for the same matchup so
    provider-name normalization corrections can propagate.
    """
    merged: dict[str, dict[str, Any]] = {}

    for game in existing + fetched:
        if not isinstance(game, dict):
            continue

        if str(game.get("status") or "").lower() not in {
            "completed",
            "final",
        }:
            continue

        matchup = matchup_key(game)
        game_id = str(
            first_nonempty(
                game.get("game_id"),
                game.get("id"),
                "",
            )
        )

        key = (
            f"matchup:{matchup}"
            if matchup
            else f"id:{game_id}"
        )

        if key:
            merged[key] = game

    return sorted(
        merged.values(),
        key=lambda game: (
            int(game.get("week", 0) or 0),
            str(game.get("away_team", "")),
            str(game.get("home_team", "")),
        ),
    )


def main() -> None:
    existing_payload = load_json(
        RESULTS_PATH,
        {"games": []},
    )

    existing_games = existing_payload.get(
        "games",
        [],
    )
    if not isinstance(existing_games, list):
        existing_games = []

    weeks, scan_mode = choose_weeks(
        existing_payload
    )
    known_projection_matchups = projection_matchups()
    active_week = infer_active_week(
        existing_payload
    )

    ncaa_completed: list[dict[str, Any]] = []
    ncaa_live: list[dict[str, Any]] = []
    espn_completed: list[dict[str, Any]] = []
    espn_live: list[dict[str, Any]] = []
    scan_log: list[dict[str, Any]] = []

    print(f"Season: {SEASON}")
    print(
        "NCAA scoreboard "
        f"mode={scan_mode} "
        f"weeks={weeks}"
    )

    for week in weeks:
        try:
            payload = fetch_ncaa_week(week)
            entries = unwrap_games(payload)

            completed_count = 0
            live_count = 0

            for entry in entries:
                normalized = normalize_ncaa_entry(
                    entry,
                    week,
                )

                if normalized is None:
                    continue

                normalized = align_to_projection_names(
                    normalized,
                    known_projection_matchups,
                )

                if normalized["game_state"] == "final":
                    ncaa_completed.append(normalized)
                    completed_count += 1
                elif normalized["game_state"] == "live":
                    ncaa_live.append(normalized)
                    live_count += 1

            scan_log.append(
                {
                    "provider": "NCAA",
                    "week": week,
                    "status": "ok",
                    "scoreboard_games": len(entries),
                    "completed_games": completed_count,
                    "live_games": live_count,
                }
            )

            print(
                f"NCAA Week {week:02d}: "
                f"{len(entries)} games, "
                f"{live_count} live, "
                f"{completed_count} completed"
            )

        except Exception as exc:
            scan_log.append(
                {
                    "provider": "NCAA",
                    "week": week,
                    "status": "unavailable",
                    "error": str(exc),
                }
            )

            print(
                f"NCAA Week {week:02d}: "
                f"unavailable ({exc})"
            )

        time.sleep(0.3)

    # ESPN fallback is date-scoped so delayed games that cross midnight UTC
    # remain visible.
    for date_string in espn_dates():
        try:
            payload = fetch_espn_date(date_string)
            events = payload.get("events") or []

            completed_count = 0
            live_count = 0

            for event in events:
                if not isinstance(event, dict):
                    continue

                normalized = normalize_espn_event(
                    payload,
                    event,
                    active_week,
                )

                if normalized is None:
                    continue

                normalized = align_to_projection_names(
                    normalized,
                    known_projection_matchups,
                )

                if normalized["game_state"] == "final":
                    espn_completed.append(normalized)
                    completed_count += 1
                elif normalized["game_state"] == "live":
                    espn_live.append(normalized)
                    live_count += 1

            scan_log.append(
                {
                    "provider": "ESPN fallback",
                    "date": date_string,
                    "status": "ok",
                    "scoreboard_games": len(events),
                    "completed_games": completed_count,
                    "live_games": live_count,
                }
            )

            print(
                f"ESPN {date_string}: "
                f"{len(events)} games, "
                f"{live_count} live, "
                f"{completed_count} completed"
            )

        except Exception as exc:
            scan_log.append(
                {
                    "provider": "ESPN fallback",
                    "date": date_string,
                    "status": "unavailable",
                    "error": str(exc),
                }
            )

            print(
                f"ESPN {date_string}: "
                f"unavailable ({exc})"
            )

        time.sleep(0.15)

    fetched_completed = combine_provider_rows(
        ncaa_completed,
        espn_completed,
    )
    fetched_live = combine_provider_rows(
        ncaa_live,
        espn_live,
    )

    # If one provider reports a matchup final, never leave the same matchup live.
    final_keys = {
        matchup_key(game)
        for game in fetched_completed
        if matchup_key(game)
    }
    fetched_live = [
        game
        for game in fetched_live
        if matchup_key(game) not in final_keys
    ]

    merged_completed = merge_completed(
        existing_games,
        fetched_completed,
    )

    results_output = {
        "meta": {
            "season": SEASON,
            "generated_at": iso_now(),
            "source": "NCAA primary + ESPN public fallback",
            "source_type": "public_scoreboard_no_auth",
            "scan_mode": scan_mode,
            "weeks_scanned": weeks,
            "completed_games": len(
                merged_completed
            ),
            "notes": [
                "Completed games only.",
                "Previously collected finals are preserved.",
                "NCAA is the primary scoreboard provider.",
                "ESPN public scoreboard fills matchups absent from NCAA.",
                "Only explicit provider final/completed states enter results.",
                "Evaluation only; Model A is untouched.",
            ],
        },
        "scan_log": scan_log,
        "games": merged_completed,
    }

    live_output = {
        "meta": {
            "season": SEASON,
            "generated_at": iso_now(),
            "source": "NCAA primary + ESPN public fallback",
            "source_type": "public_scoreboard_no_auth",
            "scan_mode": scan_mode,
            "weeks_scanned": weeks,
            "live_games": len(
                fetched_live
            ),
            "notes": [
                "Live games only.",
                "Rebuilt on every refresh.",
                "NCAA is primary; ESPN fills missing live matchups.",
                "Delayed/suspended/interrupted active games are included.",
                "Never used by settlement until an explicit final is received.",
                "Pregame Hammer Index projections remain frozen while live.",
            ],
        },
        "games": sorted(
            fetched_live,
            key=lambda game: (
                int(game.get("week", 0) or 0),
                str(game.get("away_team", "")),
                str(game.get("home_team", "")),
            ),
        ),
    }

    RESULTS_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    RESULTS_PATH.write_text(
        json.dumps(
            results_output,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    LIVE_PATH.write_text(
        json.dumps(
            live_output,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"Wrote "
        f"{len(merged_completed)} "
        f"completed games to "
        f"{RESULTS_PATH}"
    )
    print(
        f"Wrote "
        f"{len(fetched_live)} "
        f"live games to "
        f"{LIVE_PATH}"
    )


if __name__ == "__main__":
    main()
