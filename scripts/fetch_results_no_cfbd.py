"""
CFB ANALYTICS
fetch_results_no_cfbd.py

Season-long completed-results collector WITHOUT CFBD.

Source:
    ESPN public college-football scoreboard endpoint

Coverage:
    - Regular season
    - Conference championship week
    - Bowls
    - College Football Playoff
    - National championship

Output:
    data/results.json

This script is evaluation-only. It does NOT modify:
    - ratings
    - projections
    - prospective snapshots
    - closing-line snapshots
    - Model A

It safely re-fetches the season and merges completed games into one
persistent results file. Existing finals are preserved unless ESPN
returns the same game ID with updated final information.
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

# ESPN season types:
#   2 = regular season
#   3 = postseason
REGULAR_SEASON_TYPE = 2
POSTSEASON_TYPE = 3

# Deliberately wider than the normal CFB calendar.
# Empty ESPN responses are harmless, and this avoids hard-coding the
# exact final regular-season/postseason week structure.
REGULAR_WEEKS = range(1, 18)
POSTSEASON_WEEKS = range(1, 12)

ESPN_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/"
    "football/college-football/scoreboard"
)

TIMEOUT = 30
MAX_ATTEMPTS = 3
REQUEST_PAUSE_SECONDS = 0.20


def fetch_scoreboard(season_type: int, week: int):
    params = {
        "dates": str(SEASON),
        "seasontype": str(season_type),
        "week": str(week),
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
                    f"ESPN season_type={season_type} week={week} "
                    f"attempt {attempt}/{MAX_ATTEMPTS} failed: {exc}"
                )
                print(f"Retrying in {wait}s...")
                time.sleep(wait)

    raise RuntimeError(
        f"Unable to fetch ESPN scoreboard for season_type={season_type}, "
        f"week={week} after {MAX_ATTEMPTS} attempts."
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


def parse_event(event, season_type: int, week: int):
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
        "week": week,
        "season_type": season_type,
        "phase": (
            "regular_season"
            if season_type == REGULAR_SEASON_TYPE
            else "postseason"
        ),
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


def collect_completed_games():
    fetched = {}
    scan_log = []

    passes = [
        ("regular_season", REGULAR_SEASON_TYPE, REGULAR_WEEKS),
        ("postseason", POSTSEASON_TYPE, POSTSEASON_WEEKS),
    ]

    for phase, season_type, weeks in passes:
        for week in weeks:
            payload = fetch_scoreboard(season_type, week)
            events = payload.get("events") or []

            completed_count = 0

            for event in events:
                if not isinstance(event, dict):
                    continue

                game = parse_event(event, season_type, week)
                if game is None:
                    continue

                fetched[str(game["game_id"])] = game
                completed_count += 1

            scan_log.append({
                "phase": phase,
                "season_type": season_type,
                "week": week,
                "events_returned": len(events),
                "completed_games_found": completed_count,
            })

            print(
                f"{phase} | week {week:>2} | "
                f"events {len(events):>3} | finals {completed_count:>3}"
            )

            time.sleep(REQUEST_PAUSE_SECONDS)

    return fetched, scan_log


def main():
    print("=" * 72)
    print("FETCH COMPLETED RESULTS — SEASON LONG — NO CFBD")
    print("=" * 72)
    print(f"Season: {SEASON}")

    existing = load_existing()
    fetched, scan_log = collect_completed_games()

    # Keep all previously stored finals and replace only matching game IDs
    # when the newest ESPN response contains updated final information.
    merged = dict(existing)
    merged.update(fetched)

    games = sorted(
        merged.values(),
        key=lambda g: (
            int(g.get("season_type") or 0),
            int(g.get("week") or 0),
            str(g.get("start_date") or ""),
            str(g.get("game_id") or ""),
        ),
    )

    regular_count = sum(
        1 for game in games
        if game.get("season_type") == REGULAR_SEASON_TYPE
    )
    postseason_count = sum(
        1 for game in games
        if game.get("season_type") == POSTSEASON_TYPE
    )

    output = {
        "meta": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": "ESPN public scoreboard",
            "source_type": "season_long_results_only_no_cfbd",
            "season": SEASON,
            "completed_games_fetched_this_run": len(fetched),
            "completed_games_in_file": len(games),
            "regular_season_completed_games": regular_count,
            "postseason_completed_games": postseason_count,
            "coverage": [
                "regular season",
                "conference championship week",
                "bowls",
                "College Football Playoff",
                "national championship",
            ],
            "note": (
                "Completed results only. Evaluation input. Never use final "
                "results as predictive features for previously frozen "
                "prospective projections."
            ),
            "scan_log": scan_log,
        },
        "games": games,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(output, indent=2),
        encoding="utf-8",
    )

    print("=" * 72)
    print(f"Completed games fetched this run: {len(fetched)}")
    print(f"Completed games stored total: {len(games)}")
    print(f"Regular-season finals: {regular_count}")
    print(f"Postseason finals: {postseason_count}")
    print(f"Wrote: {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
