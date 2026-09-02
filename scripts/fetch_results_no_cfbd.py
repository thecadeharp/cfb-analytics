"""
CFB ANALYTICS
fetch_results_no_cfbd.py

Fetch completed college-football results WITHOUT CFBD.

Source:
    ESPN public scoreboard endpoint

Purpose:
    Give settle_results.py a clean completed-game file during the CFBD outage.

Environment:
    CFB_SEASON   default: 2026
    CFB_WEEK     default: 1
    CFB_SEASON_TYPE default: 2 (regular season)

Output:
    data/results.json

This script:
- does NOT touch projections
- does NOT touch ratings
- does NOT touch prospective snapshots
- does NOT touch closing lines
- writes completed game results only
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "results.json"

SEASON = int(os.getenv("CFB_SEASON", "2026"))
WEEK = int(os.getenv("CFB_WEEK", "1"))
SEASON_TYPE = int(os.getenv("CFB_SEASON_TYPE", "2"))

ESPN_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/"
    "football/college-football/scoreboard"
)

TIMEOUT = 30
MAX_ATTEMPTS = 3


def fetch_scoreboard():
    params = {
        "dates": str(SEASON),
        "seasontype": str(SEASON_TYPE),
        "week": str(WEEK),
        "limit": "1000",
    }

    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(
                ESPN_URL,
                params=params,
                timeout=TIMEOUT,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 CFB-Analytics/1.0 "
                        "(prospective model evaluation)"
                    )
                },
            )
            response.raise_for_status()
            payload = response.json()

            if not isinstance(payload, dict):
                raise RuntimeError("ESPN scoreboard returned a non-object payload.")

            return payload

        except Exception as exc:
            last_error = exc
            if attempt < MAX_ATTEMPTS:
                wait = 2 ** attempt
                print(
                    f"ESPN attempt {attempt}/{MAX_ATTEMPTS} failed: {exc}"
                )
                print(f"Retrying in {wait}s...")
                time.sleep(wait)

    raise RuntimeError(
        f"Unable to fetch ESPN scoreboard after {MAX_ATTEMPTS} attempts."
    ) from last_error


def parse_int(value):
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def competitor_name(competitor):
    team = competitor.get("team") or {}
    return (
        team.get("displayName")
        or team.get("shortDisplayName")
        or team.get("name")
    )


def competitor_id(competitor):
    team = competitor.get("team") or {}
    value = team.get("id")
    return str(value) if value is not None else None


def parse_event(event):
    competitions = event.get("competitions") or []
    if not competitions:
        return None

    competition = competitions[0]
    competitors = competition.get("competitors") or []

    home = next(
        (c for c in competitors if c.get("homeAway") == "home"),
        None,
    )
    away = next(
        (c for c in competitors if c.get("homeAway") == "away"),
        None,
    )

    if not home or not away:
        return None

    status = event.get("status") or {}
    status_type = status.get("type") or {}

    completed = bool(status_type.get("completed"))
    state = str(status_type.get("state") or "").lower()
    name = str(status_type.get("name") or "").lower()
    description = str(status_type.get("description") or "").lower()

    is_final = completed or state == "post" or any(
        token in f"{name} {description}"
        for token in ["final", "completed"]
    )

    if not is_final:
        return None

    home_points = parse_int(home.get("score"))
    away_points = parse_int(away.get("score"))

    if home_points is None or away_points is None:
        return None

    game_id = event.get("id")
    if game_id is None:
        return None

    neutral_site = bool(
        competition.get("neutralSite")
        or competition.get("neutral_site")
    )

    return {
        "game_id": int(game_id) if str(game_id).isdigit() else str(game_id),
        "espn_game_id": str(game_id),
        "season": SEASON,
        "week": WEEK,
        "season_type": SEASON_TYPE,
        "start_date": event.get("date"),
        "home_team": competitor_name(home),
        "away_team": competitor_name(away),
        "home_team_id": competitor_id(home),
        "away_team_id": competitor_id(away),
        "home_points": home_points,
        "away_points": away_points,
        "actual_home_margin": home_points - away_points,
        "neutral_site": neutral_site,
        "completed": True,
        "status": (
            status_type.get("shortDetail")
            or status_type.get("description")
            or "Final"
        ),
    }


def load_existing():
    if not OUTPUT.exists():
        return {}

    try:
        data = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except Exception:
        return {}

    games = data.get("games") if isinstance(data, dict) else None
    if not isinstance(games, list):
        return {}

    existing = {}
    for game in games:
        if not isinstance(game, dict):
            continue
        gid = game.get("game_id")
        if gid is not None:
            existing[str(gid)] = game

    return existing


def main():
    print("=" * 72)
    print("FETCH COMPLETED RESULTS — NO CFBD")
    print("=" * 72)
    print(f"Season: {SEASON}")
    print(f"Week: {WEEK}")
    print(f"Season type: {SEASON_TYPE}")

    payload = fetch_scoreboard()
    events = payload.get("events") or []

    existing = load_existing()
    fetched = {}

    for event in events:
        if not isinstance(event, dict):
            continue

        game = parse_event(event)
        if game is None:
            continue

        fetched[str(game["game_id"])] = game

    # Preserve previously captured completed results and merge new finals.
    merged = dict(existing)
    merged.update(fetched)

    games = sorted(
        merged.values(),
        key=lambda g: (
            int(g.get("week") or 0),
            str(g.get("start_date") or ""),
            str(g.get("game_id") or ""),
        ),
    )

    output = {
        "meta": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": "ESPN public scoreboard",
            "source_type": "results_only_no_cfbd",
            "season": SEASON,
            "requested_week": WEEK,
            "season_type": SEASON_TYPE,
            "completed_games_in_requested_week": len(fetched),
            "completed_games_in_file": len(games),
            "note": (
                "Completed results only. This file is evaluation input and "
                "must never be used as a predictive feature for already-frozen "
                "prospective projections."
            ),
        },
        "games": games,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(output, indent=2),
        encoding="utf-8",
    )

    print(f"ESPN events returned: {len(events)}")
    print(f"Completed games found for Week {WEEK}: {len(fetched)}")
    print(f"Completed games stored total: {len(games)}")
    print(f"Wrote: {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
