#!/usr/bin/env python3
"""
Fetch completed FBS college-football results without CFBD.

Primary source:
    NCAA scoreboard data through the open-source ncaa-api proxy.

Why this exists:
    ESPN's public scoreboard endpoint can return HTTP 403 from GitHub-hosted
    Actions runners. This collector avoids ESPN and does not consume CFBD quota.

Behavior:
    - scans regular-season and postseason/playoff weeks
    - keeps completed/final games only
    - preserves previously collected results
    - writes data/results.json
    - does NOT modify projections, ratings, snapshots, or market data

Environment:
    CFB_SEASON (default: 2026)
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

# NCAA's current football scoreboard uses week numbers. Scan broadly enough
# to include the complete regular season, conference championships, bowls,
# CFP rounds, and the national championship.
WEEKS = range(1, 21)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "Accept": "application/json",
        "User-Agent": "cfb-analytics-results-settlement/1.0",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_existing() -> dict[str, Any]:
    if not OUTPUT_PATH.exists():
        return {"games": []}

    try:
        payload = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"games": []}

    if isinstance(payload, list):
        return {"games": payload}
    if isinstance(payload, dict):
        return payload
    return {"games": []}


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

    raise RuntimeError(
        f"Unable to fetch NCAA scoreboard for season={SEASON}, week={week}"
    ) from last_error


def first_nonempty(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def unwrap_games(payload: Any) -> list[dict[str, Any]]:
    """
    ncaa-api normally returns the NCAA-compatible scoreboard shape:
      {"games": [{"game": {...}}, ...]}

    Keep a few fallbacks so small upstream wrapper changes do not require a
    total rewrite.
    """
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
    return first_nonempty(
        team.get("names", {}).get("full") if isinstance(team.get("names"), dict) else None,
        team.get("name"),
        team.get("displayName"),
        team.get("shortName"),
        team.get("seo"),
    )


def team_id(team: Any) -> str | None:
    if not isinstance(team, dict):
        return None
    value = first_nonempty(
        team.get("id"),
        team.get("teamId"),
        team.get("team_id"),
        team.get("seo"),
    )
    return str(value) if value is not None else None


def team_score(team: Any) -> int | None:
    if not isinstance(team, dict):
        return None
    return as_int(
        first_nonempty(
            team.get("score"),
            team.get("points"),
            team.get("scoreValue"),
        )
    )


def is_final(game: dict[str, Any]) -> bool:
    status = first_nonempty(
        game.get("gameState"),
        game.get("game_state"),
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

    text = str(status or "").strip().lower()
    return text in {"f", "final", "post", "completed", "complete"} or "final" in text


def normalize_entry(entry: dict[str, Any], week: int) -> dict[str, Any] | None:
    game = entry.get("game") if isinstance(entry.get("game"), dict) else entry

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

    if not isinstance(home, dict) or not isinstance(away, dict):
        teams = game.get("teams")
        if isinstance(teams, list):
            for team in teams:
                if not isinstance(team, dict):
                    continue
                designation = str(
                    first_nonempty(
                        team.get("homeAway"),
                        team.get("designation"),
                        team.get("location"),
                    )
                    or ""
                ).lower()
                if designation == "home":
                    home = team
                elif designation == "away":
                    away = team

    if not isinstance(home, dict) or not isinstance(away, dict):
        return None

    home_points = team_score(home)
    away_points = team_score(away)

    if home_points is None or away_points is None:
        return None

    # A completed score is the strongest final-state signal. NCAA sometimes
    # changes status field naming between scoreboard generations.
    if not is_final(game):
        state_candidates = json.dumps(game, default=str).lower()
        if '"gameState": "F"'.lower() not in state_candidates and '"final"' not in state_candidates:
            return None

    home_name = team_name(home)
    away_name = team_name(away)
    if not home_name or not away_name:
        return None

    game_id = first_nonempty(
        game.get("gameID"),
        game.get("gameId"),
        game.get("id"),
        game.get("contestId"),
        game.get("contest_id"),
    )

    # If NCAA omits a numeric game ID, retain a deterministic join-safe key.
    if game_id is None:
        game_id = f"ncaa-{SEASON}-{week}-{away_name}-{home_name}".lower().replace(" ", "-")

    neutral = bool(
        first_nonempty(
            game.get("neutralSite"),
            game.get("neutral_site"),
            False,
        )
    )

    return {
        "game_id": str(game_id),
        "season": SEASON,
        "week": week,
        "season_type": "postseason" if week >= 16 else "regular",
        "home_team": home_name,
        "away_team": away_name,
        "home_team_id": team_id(home),
        "away_team_id": team_id(away),
        "home_points": home_points,
        "away_points": away_points,
        "neutral_site": neutral,
        "status": "completed",
        "source": "NCAA",
    }


def merge_games(existing: list[dict[str, Any]], fetched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    for game in existing:
        if not isinstance(game, dict):
            continue
        key = str(first_nonempty(game.get("game_id"), game.get("id"), ""))
        if key:
            merged[key] = game

    for game in fetched:
        key = str(game["game_id"])
        merged[key] = game

    return sorted(
        merged.values(),
        key=lambda g: (
            int(g.get("season", SEASON) or SEASON),
            int(g.get("week", 0) or 0),
            str(g.get("away_team", "")),
            str(g.get("home_team", "")),
        ),
    )


def main() -> None:
    existing_payload = load_existing()
    existing_games = existing_payload.get("games", [])
    if not isinstance(existing_games, list):
        existing_games = []

    fetched_games: list[dict[str, Any]] = []
    scan_log: list[dict[str, Any]] = []

    print(f"Season: {SEASON}")
    print("Results source: NCAA scoreboard (no CFBD, no ESPN)")

    for week in WEEKS:
        try:
            payload = fetch_week(week)
            entries = unwrap_games(payload)
            completed = []

            for entry in entries:
                normalized = normalize_entry(entry, week)
                if normalized is not None:
                    completed.append(normalized)

            fetched_games.extend(completed)
            scan_log.append(
                {
                    "week": week,
                    "status": "ok",
                    "scoreboard_games": len(entries),
                    "completed_games": len(completed),
                }
            )
            print(
                f"Week {week:02d}: {len(entries)} scoreboard games, "
                f"{len(completed)} completed"
            )
        except Exception as exc:
            # Future/postseason weeks can legitimately be unavailable before
            # games are scheduled. Do not destroy an otherwise successful run.
            scan_log.append(
                {
                    "week": week,
                    "status": "unavailable",
                    "error": str(exc),
                }
            )
            print(f"Week {week:02d}: unavailable ({exc})")

        # Stay comfortably below the public proxy's 5 req/sec limit.
        time.sleep(0.3)

    merged = merge_games(existing_games, fetched_games)

    output = {
        "meta": {
            "season": SEASON,
            "generated_at": utc_now(),
            "source": "NCAA via ncaa-api",
            "source_type": "public_scoreboard_no_auth",
            "completed_games": len(merged),
            "coverage": [
                "regular season",
                "weekday games",
                "conference championship games",
                "bowls",
                "College Football Playoff",
                "national championship",
            ],
            "notes": [
                "Evaluation/results settlement only.",
                "Does not modify Model A projections or ratings.",
                "Previously collected completed games are preserved.",
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
