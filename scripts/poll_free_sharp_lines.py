#!/usr/bin/env python3
"""Capture free-tier Pinnacle spreads from The Odds API.

This collector records line movement only. It never labels a move as reverse
line movement because the free feed does not include public ticket or handle
percentages.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
STATE_VERSION = "thi-free-sharp-lines-v1.0"
SPORTS = {
    "cfb": "americanfootball_ncaaf",
    "cbb": "basketball_ncaab",
}


def utc(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def home_spread(event: dict) -> tuple[float | None, str | None]:
    home = str(event.get("home_team") or "")
    for book in event.get("bookmakers") or []:
        if str(book.get("key") or "").lower() != "pinnacle":
            continue
        for market in book.get("markets") or []:
            if market.get("key") != "spreads":
                continue
            for outcome in market.get("outcomes") or []:
                if str(outcome.get("name") or "") == home:
                    try:
                        return float(outcome["point"]), book.get("last_update")
                    except (KeyError, TypeError, ValueError):
                        return None, book.get("last_update")
    return None, None


def merge_events(state: dict, sport: str, payload: list[dict], captured_at: str) -> tuple[dict, list[dict]]:
    events = dict(state.get("events") or {})
    changes: list[dict] = []
    for event in payload:
        spread, book_time = home_spread(event)
        if spread is None:
            continue
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        key = f"{sport}:{event_id}"
        previous = events.get(key) or {}
        opening = previous.get("opening_home_spread", spread)
        changed = previous.get("current_home_spread") != spread
        row = {
            "sport": sport,
            "event_id": event_id,
            "start_date": event.get("commence_time"),
            "away_team": event.get("away_team"),
            "home_team": event.get("home_team"),
            "sharp_book": "pinnacle",
            "source": "the_odds_api_free",
            "first_seen_at_utc": previous.get("first_seen_at_utc") or captured_at,
            "last_seen_at_utc": captured_at,
            "book_last_update_utc": book_time,
            "opening_home_spread": opening,
            "current_home_spread": spread,
            "last_change_at_utc": captured_at if changed else previous.get("last_change_at_utc") or captured_at,
            "observations": int(previous.get("observations") or 0) + 1,
        }
        events[key] = row
        if not previous or changed:
            changes.append(row)

    now = utc(captured_at) or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=12)
    ceiling = now + timedelta(days=21)
    events = {
        key: row for key, row in events.items()
        if (start := utc(row.get("start_date"))) is not None and cutoff <= start <= ceiling
    }
    return {
        "meta": {
            "version": STATE_VERSION,
            "generated_at_utc": captured_at,
            "source": "The Odds API free tier",
            "book": "Pinnacle",
            "sport_count": len({row["sport"] for row in events.values()}),
            "event_count": len(events),
            "polling_policy": "Six polls per day across CFB and CBB to remain within the 500-credit monthly free tier.",
            "signal_policy": "Line movement only. Public splits are absent, so no RLM or sharp-money claim is permitted.",
        },
        "events": events,
    }, changes


def fetch_sport(api_key: str, sport_key: str) -> list[dict]:
    query = urlencode({
        "apiKey": api_key,
        "bookmakers": "pinnacle",
        "markets": "spreads",
        "oddsFormat": "american",
        "dateFormat": "iso",
    })
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds?{query}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "THI-Free-Sharp-Lines/1.0"})
    with urlopen(request, timeout=45) as response:
        payload = json.load(response)
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected odds response for {sport_key}")
    return payload


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=ROOT / "data/market/sharp_line_state.json")
    parser.add_argument("--history", type=Path, default=ROOT / "data/market/sharp_line_history.jsonl")
    args = parser.parse_args()
    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("ODDS_API_KEY is required")
    state = json.loads(args.state.read_text()) if args.state.exists() else {"events": {}}
    captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    all_changes: list[dict] = []
    for sport, sport_key in SPORTS.items():
        state, changes = merge_events(state, sport, fetch_sport(api_key, sport_key), captured_at)
        all_changes.extend(changes)
    atomic_json(args.state, state)
    args.history.parent.mkdir(parents=True, exist_ok=True)
    if all_changes:
        with args.history.open("a", encoding="utf-8") as handle:
            for row in all_changes:
                handle.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
    print(f"Free sharp-line capture: {state['meta']['event_count']} events, {len(all_changes)} changes")


if __name__ == "__main__":
    main()
