#!/usr/bin/env python3
"""
CFB ANALYTICS
fetch_results_no_cfbd.py

Fetch live + completed FBS college-football scoreboard data without CFBD.

Source:
    NCAA scoreboard data through the public ncaa-api proxy.

Outputs:
    data/results.json
        Completed games only. Existing finals are preserved so settlement
        has a durable season-long results ledger.

    data/live_scores.json
        Current in-progress games only. Rebuilt on every run.

Important:
    - no CFBD
    - no ESPN
    - no model rebuild
    - live games NEVER enter data/results.json
    - only explicit NCAA "final" games can be settled

2026-09-04 hardening:
    - normalize several NCAA abbreviated FCS school names to the names used
      by the projection board
    - treat delayed / suspended / interrupted games as live presentation state
    - recognize halftime / quarter / OT status text as live
    - infer live state from period/clock only when the scoreboard supplies
      actual scores and no explicit final state exists
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = ROOT / "data" / "results.json"
LIVE_PATH = ROOT / "data" / "live_scores.json"

SEASON = int(os.getenv("CFB_SEASON", "2026"))
BASE_URL = "https://ncaa-api.henrygd.me/scoreboard/football/fbs"
ALL_WEEKS = list(range(1, 21))

SESSION = requests.Session()
SESSION.headers.update(
    {
        "Accept": "application/json",
        "User-Agent": "the-hammer-index-scoreboard/3.1",
    }
)

# Exact provider-name cleanup. Keep this conservative: only names we know the
# NCAA scoreboard abbreviates differently from the public projection board.
TEAM_NAME_ALIASES = {
    "Ark.-Pine Bluff": "Arkansas Pine Bluff",
    "Ark.-Pine Bluff.": "Arkansas Pine Bluff",
    "Ark. Pine Bluff": "Arkansas Pine Bluff",
    "Eastern Ill.": "Eastern Illinois",
    "West Ga.": "West Georgia",
    "UAlbany": "Albany",
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


def fetch_week(week: int) -> dict[str, Any]:
    url = f"{BASE_URL}/{SEASON}/{week:02d}/all-conf"
    last_error: Exception | None = None

    for attempt in range(1, 4):
        try:
            response = SESSION.get(url, timeout=30)
            response.raise_for_status()

            payload = response.json()

            if not isinstance(payload, dict):
                raise ValueError("scoreboard response was not a JSON object")

            return payload

        except (requests.RequestException, ValueError) as exc:
            last_error = exc

            if attempt < 3:
                time.sleep(attempt * 2)

    raise RuntimeError(
        f"Unable to fetch NCAA scoreboard season={SEASON}, week={week}"
    ) from last_error


def unwrap_games(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [
            item
            for item in payload
            if isinstance(item, dict)
        ]

    if not isinstance(payload, dict):
        return []

    for key in ("games", "contests", "events"):
        value = payload.get(key)

        if isinstance(value, list):
            return [
                item
                for item in value
                if isinstance(item, dict)
            ]

    data = payload.get("data")

    if isinstance(data, dict):
        for key in ("games", "contests", "events"):
            value = data.get(key)

            if isinstance(value, list):
                return [
                    item
                    for item in value
                    if isinstance(item, dict)
                ]

    return []


def unwrap_game(entry: dict[str, Any]) -> dict[str, Any]:
    nested = entry.get("game")

    return (
        nested
        if isinstance(nested, dict)
        else entry
    )


def clean_team_name(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    return TEAM_NAME_ALIASES.get(text, text)


def team_name(team: Any) -> str | None:
    if not isinstance(team, dict):
        return None

    names = team.get("names")

    if isinstance(names, dict):
        # The NCAA conversion frequently has names.short even when full is blank.
        value = first_nonempty(
            names.get("full"),
            names.get("short"),
            names.get("char6"),
            names.get("seo"),
        )

        cleaned = clean_team_name(value)
        if cleaned:
            return cleaned

    value = first_nonempty(
        team.get("name"),
        team.get("displayName"),
        team.get("shortName"),
        team.get("nameShort"),
        team.get("seo"),
    )

    return clean_team_name(value)


def team_id(team: Any) -> str | None:
    if not isinstance(team, dict):
        return None

    value = first_nonempty(
        team.get("id"),
        team.get("teamId"),
        team.get("team_id"),
        team.get("seo"),
        team.get("seoname"),
    )

    return (
        str(value)
        if value is not None
        else None
    )


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


def home_away(
    game: dict[str, Any],
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any] | None,
]:
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

    if (
        isinstance(home, dict)
        and isinstance(away, dict)
    ):
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

        if (
            isinstance(home, dict)
            and isinstance(away, dict)
        ):
            return home, away

    return None, None


def status_value(game: dict[str, Any]) -> Any:
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


def period_value(game: dict[str, Any]) -> Any:
    return first_nonempty(
        game.get("currentPeriod"),
        game.get("period"),
        game.get("quarter"),
    )


def clock_value(game: dict[str, Any]) -> Any:
    return first_nonempty(
        game.get("contestClock"),
        game.get("clock"),
        game.get("displayClock"),
    )


def normalized_state(
    game: dict[str, Any],
) -> str:
    """
    Return one of: final, live, pre.

    Settlement remains conservative: FINAL is still only accepted from explicit
    provider final/completed state.

    Presentation is intentionally more tolerant. NCAA has used delayed and
    suspended states during active games, and some entries expose quarter /
    halftime information even when gameState is not the normal "I".
    """
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

    text = str(raw or "").strip().lower()
    compact = re.sub(r"[^a-z0-9]+", "", text)

    # Explicit final states only.
    if compact in {
        "f",
        "final",
        "post",
        "completed",
        "complete",
        "closed",
        "finalot",
        "final2ot",
        "final3ot",
    } or compact.startswith("final"):
        return "final"

    # Standard in-progress plus active interruption states.
    if compact in {
        "i",
        "in",
        "live",
        "inprogress",
        "d",
        "delay",
        "delayed",
        "weatherdelay",
        "suspended",
        "suspend",
        "interrupted",
        "halftime",
        "half",
        "ot",
        "overtime",
    }:
        return "live"

    if compact in {
        "p",
        "pre",
        "pregame",
        "scheduled",
    }:
        explicit_pre = True
    else:
        explicit_pre = False

    status = status_value(game)
    status_text = str(status or "").strip().lower()
    status_compact = re.sub(r"[^a-z0-9]+", "", status_text)

    if any(
        word in status_text
        for word in (
            "final",
            "completed",
            "complete",
        )
    ):
        return "final"

    if any(
        word in status_text
        for word in (
            "live",
            "in progress",
            "in-progress",
            "delay",
            "suspend",
            "interrupted",
            "halftime",
            "half time",
            "overtime",
        )
    ):
        return "live"

    # Some NCAA scoreboard records use short quarter/OT detail rather than a
    # stable live state token.
    if re.search(
        r"\b(?:1st|2nd|3rd|4th)\b",
        status_text,
    ) or re.search(
        r"\bq[1-4]\b",
        status_text,
    ) or status_compact in {
        "1st",
        "2nd",
        "3rd",
        "4th",
        "1q",
        "2q",
        "3q",
        "4q",
        "ot",
        "2ot",
        "3ot",
        "4ot",
    }:
        return "live"

    # Final fallback for presentation only: if the provider gives actual scores
    # plus period/clock information, the contest has clearly started.
    #
    # Do not use this to infer FINAL; only explicit final state can settle.
    home, away = home_away(game)
    home_points = team_score(home)
    away_points = team_score(away)

    has_scores = (
        home_points is not None
        and away_points is not None
    )

    period = period_value(game)
    clock = clock_value(game)

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

    if explicit_pre:
        return "pre"

    return "pre"


def clean_period(
    value: Any,
) -> str | None:
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    if not re.fullmatch(r"\d+", text):
        return text.upper()

    return text


def clean_clock(
    value: Any,
) -> str | None:
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    return text


def game_identity(
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

    slug = (
        f"ncaa-{SEASON}-{week}-"
        f"{away_name}-{home_name}"
    ).lower()

    return re.sub(
        r"[^a-z0-9]+",
        "-",
        slug,
    ).strip("-")


def normalize_entry(
    entry: dict[str, Any],
    week: int,
) -> dict[str, Any] | None:
    game = unwrap_game(entry)

    home, away = home_away(game)

    if (
        not isinstance(home, dict)
        or not isinstance(away, dict)
    ):
        return None

    home_name = team_name(home)
    away_name = team_name(away)

    if (
        not home_name
        or not away_name
    ):
        return None

    state = normalized_state(game)

    # Pregame entries do not belong in either status output.
    if state == "pre":
        return None

    home_points = team_score(home)
    away_points = team_score(away)

    # A LIVE or FINAL game should have a scoreboard value. Zero is valid.
    if (
        home_points is None
        or away_points is None
    ):
        return None

    game_id = game_identity(
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
        "home_team_id": team_id(home),
        "away_team_id": team_id(away),
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
                or status_value(game)
                or "Final"
            ),
        }

    return {
        **base,
        "status": "live",
        "game_state": "live",
        "period": clean_period(period_value(game)),
        "clock": clean_clock(clock_value(game)),
        "network": first_nonempty(
            game.get("network"),
            game.get("broadcasterName"),
        ),
        "provider_status": (
            str(status_value(game)).strip()
            if status_value(game) is not None
            else None
        ),
    }


def merge_completed(
    existing: list[dict[str, Any]],
    fetched: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    for game in existing + fetched:
        if not isinstance(game, dict):
            continue

        if str(
            game.get("status") or ""
        ).lower() not in {
            "completed",
            "final",
        }:
            continue

        key = str(
            first_nonempty(
                game.get("game_id"),
                game.get("id"),
                "",
            )
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


def infer_active_week(
    existing_payload: dict[str, Any],
) -> int:
    completed_weeks = [
        as_int(game.get("week"))
        for game
        in existing_payload.get("games", [])
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

            if int(
                row.get("scoreboard_games", 0) or 0
            ) <= 0:
                continue

            week = as_int(row.get("week"))

            if week is not None:
                candidates.append(week)

    return min(candidates) if candidates else 1


def choose_weeks(
    existing_payload: dict[str, Any],
) -> tuple[list[int], str]:
    now = utc_now()

    # Once each UTC morning, reconcile every NCAA week.
    if (
        now.hour == 8
        and now.minute < 15
    ):
        return (
            ALL_WEEKS,
            "daily_full_reconciliation",
        )

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

    return (
        weeks,
        "targeted_live_refresh",
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

    fetched_completed: list[dict[str, Any]] = []
    fetched_live: list[dict[str, Any]] = []
    scan_log: list[dict[str, Any]] = []

    print(f"Season: {SEASON}")
    print(
        "NCAA scoreboard "
        f"mode={scan_mode} "
        f"weeks={weeks}"
    )

    for week in weeks:
        try:
            payload = fetch_week(week)
            entries = unwrap_games(payload)

            completed_count = 0
            live_count = 0

            for entry in entries:
                normalized = normalize_entry(
                    entry,
                    week,
                )

                if normalized is None:
                    continue

                if normalized["game_state"] == "final":
                    fetched_completed.append(
                        normalized
                    )
                    completed_count += 1

                elif normalized["game_state"] == "live":
                    fetched_live.append(
                        normalized
                    )
                    live_count += 1

            scan_log.append(
                {
                    "week": week,
                    "status": "ok",
                    "scoreboard_games": len(entries),
                    "completed_games": completed_count,
                    "live_games": live_count,
                }
            )

            print(
                f"Week {week:02d}: "
                f"{len(entries)} games, "
                f"{live_count} live, "
                f"{completed_count} completed"
            )

        except Exception as exc:
            scan_log.append(
                {
                    "week": week,
                    "status": "unavailable",
                    "error": str(exc),
                }
            )

            print(
                f"Week {week:02d}: "
                f"unavailable ({exc})"
            )

        # Public API is rate limited.
        time.sleep(0.3)

    merged_completed = merge_completed(
        existing_games,
        fetched_completed,
    )

    results_output = {
        "meta": {
            "season": SEASON,
            "generated_at": iso_now(),
            "source": "NCAA via ncaa-api",
            "source_type": "public_scoreboard_no_auth",
            "scan_mode": scan_mode,
            "weeks_scanned": weeks,
            "completed_games": len(
                merged_completed
            ),
            "notes": [
                "Completed games only.",
                "Previously collected finals are preserved.",
                "Only explicit NCAA final states enter the settlement ledger.",
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
            "source": "NCAA via ncaa-api",
            "source_type": "public_scoreboard_no_auth",
            "scan_mode": scan_mode,
            "weeks_scanned": weeks,
            "live_games": len(
                fetched_live
            ),
            "notes": [
                "Live games only.",
                "Rebuilt on every refresh.",
                "Delayed/suspended/interrupted active games are included.",
                "Never used by settlement.",
                "Pregame Hammer Index projections remain frozen while games are live.",
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
