#!/usr/bin/env python3
"""Enrich the rolling CBB board with confirmed ESPN times and broadcasts.

CBBD remains the schedule authority and supplies the game identifiers. ESPN's
team schedule feed is used only to fill confirmed tip times and broadcast
designations for already-known games. Raw ESPN responses are never stored.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
BOARD_PATH = ROOT / "data" / "cbb" / "game_board.json"
PROFILES_PATH = ROOT / "data" / "cbb" / "team_profiles.json"
ESPN_SCHEDULE_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/"
    "mens-college-basketball/teams/{team_id}/schedule"
)


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def iso_millis(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def extract_events(payload: dict[str, Any], espn_to_cbb: dict[str, int]) -> list[dict[str, Any]]:
    rows = []
    for event in payload.get("events") or []:
        competitions = event.get("competitions") or []
        competition = competitions[0] if competitions else {}
        competitors = competition.get("competitors") or []
        ids = []
        for competitor in competitors:
            espn_id = str((competitor.get("team") or {}).get("id") or "")
            if espn_id in espn_to_cbb:
                ids.append(espn_to_cbb[espn_id])
        if len(ids) != 2 or ids[0] == ids[1]:
            continue
        start = parse_time(event.get("date") or competition.get("date"))
        if start is None:
            continue
        broadcasts = sorted({
            str(((item.get("media") or {}).get("shortName") or "")).strip()
            for item in competition.get("broadcasts") or []
            if str(((item.get("media") or {}).get("shortName") or "")).strip()
        })
        rows.append({
            "event_id": str(event.get("id") or ""),
            "pair": tuple(sorted(ids)),
            "start": start,
            "time_valid": bool(competition.get("timeValid")),
            "broadcasts": broadcasts,
        })
    return rows


def enrich(
    board: dict[str, Any],
    profiles: dict[str, Any],
    fetcher: Callable[[str], dict[str, Any] | None],
) -> dict[str, Any]:
    espn_to_cbb = {
        str(row.get("espn_id")): int(row["team_id"])
        for row in profiles.get("teams") or []
        if row.get("espn_id") is not None and row.get("team_id") is not None
    }
    events: dict[str, dict[str, Any]] = {}
    requests_made = 0
    fetch_errors = 0
    for espn_id in sorted(espn_to_cbb, key=lambda value: int(value)):
        requests_made += 1
        payload = fetcher(espn_id)
        if not isinstance(payload, dict):
            fetch_errors += 1
            continue
        for event in extract_events(payload, espn_to_cbb):
            key = event["event_id"] or f"{event['pair']}:{event['start'].isoformat()}"
            events[key] = event

    by_pair: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for event in events.values():
        by_pair.setdefault(event["pair"], []).append(event)

    times_updated = 0
    broadcasts_updated = 0
    matched_games = 0
    for game in board.get("games") or []:
        try:
            pair = tuple(sorted((int(game["home"]["team_id"]), int(game["away"]["team_id"]))))
        except (KeyError, TypeError, ValueError):
            continue
        current = parse_time(game.get("start_date"))
        if current is None:
            continue
        candidates = by_pair.get(pair) or []
        if not candidates:
            continue
        event = min(candidates, key=lambda row: abs((row["start"] - current).total_seconds()))
        if abs((event["start"] - current).total_seconds()) > 3 * 86400:
            continue
        matched_games += 1
        if event["time_valid"] and (
            bool(game.get("start_time_tbd"))
            or abs((event["start"] - current).total_seconds()) >= 60
        ):
            game["start_date"] = iso_millis(event["start"])
            game["start_time_tbd"] = False
            times_updated += 1
        merged_broadcasts = sorted(set(game.get("broadcasts") or []) | set(event["broadcasts"]))
        if merged_broadcasts != (game.get("broadcasts") or []):
            game["broadcasts"] = merged_broadcasts
            broadcasts_updated += 1

    meta = board.setdefault("meta", {})
    meta["schedule_enrichment"] = {
        "source": "ESPN public team schedule metadata",
        "policy": "Existing CBBD games only; ESPN time must be marked valid; broadcasts are merged.",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "team_requests": requests_made,
        "fetch_errors": fetch_errors,
        "unique_events": len(events),
        "matched_games": matched_games,
        "times_updated": times_updated,
        "broadcasts_updated": broadcasts_updated,
        "raw_api_data_stored": False,
    }
    meta["games_with_broadcasts"] = sum(bool(row.get("broadcasts")) for row in board.get("games") or [])
    meta["games_with_confirmed_time"] = sum(not row.get("start_time_tbd") for row in board.get("games") or [])
    return board


def fetch_schedule(team_id: str) -> dict[str, Any] | None:
    url = ESPN_SCHEDULE_URL.format(team_id=team_id) + "?" + urlencode({"season": 2027, "seasontype": 2})
    try:
        request = Request(url, headers={"User-Agent": "The Hammer Index schedule enrichment/1.0"})
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", type=Path, default=BOARD_PATH)
    parser.add_argument("--profiles", type=Path, default=PROFILES_PATH)
    args = parser.parse_args()
    board = json.loads(args.board.read_text())
    profiles = json.loads(args.profiles.read_text())
    output = enrich(board, profiles, fetch_schedule)
    atomic_write(args.board, output)
    status = output["meta"]["schedule_enrichment"]
    print(
        "CBB schedule enrichment: "
        f"{status['matched_games']} matched, {status['times_updated']} times, "
        f"{status['broadcasts_updated']} broadcasts, {status['fetch_errors']} fetch errors"
    )


if __name__ == "__main__":
    main()
