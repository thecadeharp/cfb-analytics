#!/usr/bin/env python3
"""
Fetch completed FBS college-football results without CFBD.

Source:
    NCAA scoreboard data through the public ncaa-api proxy.

Production behavior:
    - no CFBD
    - no ESPN
    - preserves every previously collected completed game
    - scans only the relevant week window on normal hourly runs
    - periodically performs a full-season reconciliation scan
    - covers regular season, weekday games, conference championships,
      bowls, CFP rounds, and the national championship
    - writes data/results.json only
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "data" / "results.json"

SEASON = int(os.getenv("CFB_SEASON", "2026"))
BASE_URL = "https://ncaa-api.henrygd.me/scoreboard/football/fbs"
ALL_WEEKS = list(range(1, 21))

SESSION = requests.Session()
SESSION.headers.update({
    "Accept": "application/json",
    "User-Agent": "cfb-analytics-results-settlement/2.0",
})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def load_existing() -> dict[str, Any]:
    if not OUTPUT_PATH.exists():
        return {"games": []}
    try:
        payload = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"games": []}
    if isinstance(payload, list):
        return {"games": payload}
    return payload if isinstance(payload, dict) else {"games": []}


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


def fetch_week(week: int) -> dict[str, Any]:
    url = f"{BASE_URL}/{SEASON}/{week:02d}/all-conf"
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = SESSION.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to fetch NCAA scoreboard season={SEASON}, week={week}") from last_error


def unwrap_games(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("games", "contests", "events"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("games", "contests", "events"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def team_name(team: Any) -> str | None:
    if not isinstance(team, dict):
        return None
    names = team.get("names")
    return first_nonempty(
        names.get("full") if isinstance(names, dict) else None,
        team.get("name"),
        team.get("displayName"),
        team.get("shortName"),
        team.get("seo"),
    )


def team_id(team: Any) -> str | None:
    if not isinstance(team, dict):
        return None
    value = first_nonempty(team.get("id"), team.get("teamId"), team.get("team_id"), team.get("seo"))
    return str(value) if value is not None else None


def team_score(team: Any) -> int | None:
    if not isinstance(team, dict):
        return None
    return as_int(first_nonempty(team.get("score"), team.get("points"), team.get("scoreValue")))


def is_final(game: dict[str, Any]) -> bool:
    status = first_nonempty(
        game.get("gameState"), game.get("game_state"), game.get("status"),
        game.get("statusText"), game.get("finalMessage")
    )
    if isinstance(status, dict):
        status = first_nonempty(
            status.get("state"), status.get("type"), status.get("name"),
            status.get("description"), status.get("detail")
        )
    text = str(status or "").strip().lower()
    if text in {"f", "final", "post", "completed", "complete"} or "final" in text:
        return True
    raw = json.dumps(game, default=str).lower()
    return '"gamestate": "f"' in raw or '"final"' in raw


def normalize_entry(entry: dict[str, Any], week: int) -> dict[str, Any] | None:
    game = entry.get("game") if isinstance(entry.get("game"), dict) else entry
    home = first_nonempty(game.get("home"), game.get("homeTeam"), game.get("home_team"))
    away = first_nonempty(game.get("away"), game.get("awayTeam"), game.get("away_team"))

    if not isinstance(home, dict) or not isinstance(away, dict):
        teams = game.get("teams")
        if isinstance(teams, list):
            for team in teams:
                if not isinstance(team, dict):
                    continue
                designation = str(first_nonempty(
                    team.get("homeAway"), team.get("designation"), team.get("location")
                ) or "").lower()
                if designation == "home":
                    home = team
                elif designation == "away":
                    away = team

    if not isinstance(home, dict) or not isinstance(away, dict):
        return None

    hp, ap = team_score(home), team_score(away)
    hn, an = team_name(home), team_name(away)
    if hp is None or ap is None or not hn or not an or not is_final(game):
        return None

    game_id = first_nonempty(
        game.get("gameID"), game.get("gameId"), game.get("id"),
        game.get("contestId"), game.get("contest_id")
    )
    if game_id is None:
        game_id = f"ncaa-{SEASON}-{week}-{an}-{hn}".lower().replace(" ", "-")

    start_date = first_nonempty(
        game.get("startDate"), game.get("start_date"), game.get("startTime"),
        game.get("start_time"), game.get("date")
    )

    return {
        "game_id": str(game_id),
        "season": SEASON,
        "week": week,
        "home_team": hn,
        "away_team": an,
        "home_team_id": team_id(home),
        "away_team_id": team_id(away),
        "home_points": hp,
        "away_points": ap,
        "start_date": start_date,
        "neutral_site": bool(first_nonempty(game.get("neutralSite"), game.get("neutral_site"), False)),
        "status": "completed",
        "source": "NCAA",
    }


def merge_games(existing: list[dict[str, Any]], fetched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for game in existing + fetched:
        if not isinstance(game, dict):
            continue
        key = str(first_nonempty(game.get("game_id"), game.get("id"), ""))
        if key:
            merged[key] = game
    return sorted(merged.values(), key=lambda g: (
        int(g.get("week", 0) or 0), str(g.get("away_team", "")), str(g.get("home_team", ""))
    ))


def infer_active_week(existing_payload: dict[str, Any]) -> int:
    """
    Prefer the most recently successful NCAA scan with scheduled games.
    If none exists, default to Week 1. This advances naturally because the
    reconciliation scan discovers future weeks as NCAA publishes them.
    """
    scan_log = existing_payload.get("scan_log", [])
    candidates = []
    if isinstance(scan_log, list):
        for row in scan_log:
            if not isinstance(row, dict):
                continue
            if row.get("status") == "ok" and int(row.get("scoreboard_games", 0) or 0) > 0:
                week = as_int(row.get("week"))
                if week is not None:
                    candidates.append(week)
    if not candidates:
        return 1

    # Do not jump to the last future scheduled week. Use the highest week that
    # has at least one completed game, otherwise Week 1.
    completed_weeks = [
        as_int(g.get("week")) for g in existing_payload.get("games", [])
        if isinstance(g, dict) and as_int(g.get("week")) is not None
    ]
    return max(completed_weeks) if completed_weeks else 1


def choose_weeks(existing_payload: dict[str, Any]) -> tuple[list[int], str]:
    now = utc_now()

    # Full reconciliation once per UTC day at 08:xx. This guarantees that
    # reschedules, conference championships, bowls and CFP games are eventually
    # discovered without hammering all 20 endpoints every hour.
    if now.hour == 8:
        return ALL_WEEKS, "daily_full_reconciliation"

    active = infer_active_week(existing_payload)
    # Current week + next week catches newly posted schedules; previous week
    # catches late finals/corrections.
    weeks = sorted({w for w in (active - 1, active, active + 1) if 1 <= w <= 20})
    return weeks, "targeted_hourly"


def main() -> None:
    existing_payload = load_existing()
    existing_games = existing_payload.get("games", [])
    if not isinstance(existing_games, list):
        existing_games = []

    weeks, scan_mode = choose_weeks(existing_payload)
    fetched_games: list[dict[str, Any]] = []
    scan_log: list[dict[str, Any]] = []

    print(f"Season: {SEASON}")
    print(f"Results source: NCAA scoreboard | mode={scan_mode} | weeks={weeks}")

    for week in weeks:
        try:
            payload = fetch_week(week)
            entries = unwrap_games(payload)
            completed = [
                normalized for entry in entries
                if (normalized := normalize_entry(entry, week)) is not None
            ]
            fetched_games.extend(completed)
            scan_log.append({
                "week": week, "status": "ok",
                "scoreboard_games": len(entries), "completed_games": len(completed)
            })
            print(f"Week {week:02d}: {len(entries)} games, {len(completed)} completed")
        except Exception as exc:
            scan_log.append({"week": week, "status": "unavailable", "error": str(exc)})
            print(f"Week {week:02d}: unavailable ({exc})")
        time.sleep(0.3)

    merged = merge_games(existing_games, fetched_games)
    output = {
        "meta": {
            "season": SEASON,
            "generated_at": iso_now(),
            "source": "NCAA via ncaa-api",
            "source_type": "public_scoreboard_no_auth",
            "scan_mode": scan_mode,
            "weeks_scanned": weeks,
            "completed_games": len(merged),
            "coverage": [
                "regular season", "weekday games", "conference championships",
                "bowls", "College Football Playoff", "national championship"
            ],
            "notes": [
                "Previously collected finals are preserved.",
                "Targeted hourly scans reduce unnecessary requests.",
                "Daily full reconciliation preserves complete season coverage.",
                "Evaluation only; Model A is untouched."
            ],
        },
        "scan_log": scan_log,
        "games": merged,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(merged)} completed games to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
