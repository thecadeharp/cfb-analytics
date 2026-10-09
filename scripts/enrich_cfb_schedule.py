#!/usr/bin/env python3
"""Add confirmed ESPN kickoff, broadcast and venue metadata to CFB games.

CFBD remains the schedule authority. ESPN is matched to already-known games by
the shared event ID and is used only for display metadata. Raw responses are
never written to the repository.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_PATH = ROOT / "data" / "schedule.json"
PROJECTIONS_PATH = ROOT / "data" / "projections.json"
METRICS_PATH = ROOT / "data" / "cfb_metrics.json"
ESPN_TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=1000"
ESPN_SCHEDULE_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/"
    "college-football/teams/{team_id}/schedule"
)


def normalize(value: Any) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())


def iso_millis(value: Any) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def team_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sport in payload.get("sports") or []:
        for league in sport.get("leagues") or []:
            rows.extend((item.get("team") or {}) for item in league.get("teams") or [])
    return rows


def extract_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for event in payload.get("events") or []:
        competition = (event.get("competitions") or [{}])[0]
        game_id = str(event.get("id") or "").strip()
        if not game_id:
            continue
        networks = sorted({
            str((broadcast.get("media") or {}).get("shortName") or "").strip()
            for broadcast in competition.get("broadcasts") or []
            if str((broadcast.get("media") or {}).get("shortName") or "").strip()
        })
        rows.append({
            "id": game_id,
            "start_date": iso_millis(event.get("date") or competition.get("date")),
            "time_valid": bool(competition.get("timeValid", True)),
            "network": " / ".join(networks),
            "venue": str((competition.get("venue") or {}).get("fullName") or "").strip(),
        })
    return rows


def enrich(
    schedule: dict[str, Any],
    projections: dict[str, Any],
    metrics: dict[str, Any],
    directory: dict[str, Any],
    fetcher: Callable[[str], dict[str, Any] | None],
) -> tuple[dict[str, Any], dict[str, Any]]:
    teams = metrics.get("teams") or {}
    team_names = list(teams) if isinstance(teams, dict) else [row.get("team") for row in teams]
    directory_lookup = {
        normalize(row.get("location")): str(row.get("id"))
        for row in team_rows(directory)
        if row.get("id") and row.get("location")
    }
    espn_ids = sorted({directory_lookup[normalize(name)] for name in team_names if normalize(name) in directory_lookup}, key=int)
    events: dict[str, dict[str, Any]] = {}
    fetch_errors = 0
    with ThreadPoolExecutor(max_workers=12) as pool:
        fetched = zip(espn_ids, pool.map(fetcher, espn_ids))
        for _espn_id, payload in fetched:
            if not isinstance(payload, dict):
                fetch_errors += 1
                continue
            for event in extract_events(payload):
                current = events.setdefault(event["id"], event)
                if not current.get("network") and event.get("network"):
                    current["network"] = event["network"]
                if not current.get("venue") and event.get("venue"):
                    current["venue"] = event["venue"]

    stats = {"matched_games": 0, "times_updated": 0, "broadcasts_updated": 0, "venues_updated": 0}

    def update_game(game: dict[str, Any], id_key: str) -> None:
        event = events.get(str(game.get(id_key) or ""))
        if not event:
            return
        stats["matched_games"] += 1
        if event.get("time_valid") and event.get("start_date") and game.get("start_date") != event["start_date"]:
            game["start_date"] = event["start_date"]
            stats["times_updated"] += 1
        if event.get("network") and game.get("network") != event["network"]:
            game["network"] = event["network"]
            stats["broadcasts_updated"] += 1
        if event.get("venue") and game.get("venue") != event["venue"]:
            game["venue"] = event["venue"]
            stats["venues_updated"] += 1

    for game in schedule.get("games") or []:
        update_game(game, "id")
    for rows in (schedule.get("team_schedules") or {}).values():
        for game in rows or []:
            update_game(game, "id")
    for game in projections.get("games") or []:
        update_game(game, "game_id")
    for season in (projections.get("season_projections") or {}).values():
        for game in season.get("schedule") or []:
            update_game(game, "game_id")

    schedule.setdefault("meta", {})["display_metadata_enrichment"] = {
        "source": "ESPN public team schedule metadata",
        "policy": "Existing CFBD games only; exact event-ID match; display metadata only.",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "team_requests": len(espn_ids),
        "unmatched_team_names": sorted(name for name in team_names if normalize(name) not in directory_lookup),
        "fetch_errors": fetch_errors,
        "unique_events": len(events),
        **stats,
        "raw_api_data_stored": False,
        "model_a_touched": False,
    }
    return schedule, projections


def fetch_json(url: str) -> dict[str, Any] | None:
    try:
        request = Request(url, headers={"User-Agent": "The Hammer Index schedule enrichment/1.0"})
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None


def fetch_schedule(team_id: str) -> dict[str, Any] | None:
    query = urlencode({"season": 2026, "seasontype": 2})
    return fetch_json(ESPN_SCHEDULE_URL.format(team_id=team_id) + "?" + query)


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule", type=Path, default=SCHEDULE_PATH)
    parser.add_argument("--projections", type=Path, default=PROJECTIONS_PATH)
    parser.add_argument("--metrics", type=Path, default=METRICS_PATH)
    args = parser.parse_args()
    schedule = json.loads(args.schedule.read_text())
    projections = json.loads(args.projections.read_text())
    metrics = json.loads(args.metrics.read_text())
    directory = fetch_json(ESPN_TEAMS_URL)
    if not isinstance(directory, dict):
        print("CFB schedule enrichment skipped: ESPN team directory unavailable; existing files left unchanged.")
        return
    schedule, projections = enrich(schedule, projections, metrics, directory, fetch_schedule)
    atomic_write(args.schedule, schedule)
    atomic_write(args.projections, projections)
    status = schedule["meta"]["display_metadata_enrichment"]
    print(
        "CFB schedule enrichment: "
        f"{status['unique_events']} events, {status['broadcasts_updated']} broadcasts, "
        f"{status['venues_updated']} venues, {status['times_updated']} times, "
        f"{status['fetch_errors']} fetch errors"
    )


if __name__ == "__main__":
    main()
