#!/usr/bin/env python3
"""Capture licensed Owls Insight splits with a synchronized sharp-book spread.

The adapter stays dormant until OWLS_INSIGHT_API_KEY is configured. It prefers
DraftKings ticket/handle splits, uses BetMGM tickets as a fallback, and accepts
Pinnacle (then BetOnline) as the line reference. A snapshot is published only
when the split and price timestamps are within five minutes of one another.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://api.owlsinsight.com"
SPORTS = {"ncaaf": "cfb", "ncaab": "cbb"}
PUBLIC_BOOK_PRIORITY = {"dk": 0, "draftkings": 0, "betmgm": 1}
SHARP_BOOK_PRIORITY = {"pinnacle": 0, "betonline": 1}


def parsed_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def fetch(path: str, api_key: str, query: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    request = Request(url, headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json", "User-Agent": "THI-RLM/2.0"})
    with urlopen(request, timeout=45) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected Owls response from {path}")
    return payload


def event_key(sport: str, event: dict) -> str:
    existing = event.get("event_id") or event.get("eventId")
    if existing:
        return str(existing)
    start = parsed_time(event.get("commence_time"))
    day = start.strftime("%Y%m%d") if start else "unknown"
    return f"{sport}:{event.get('away_team')}@{event.get('home_team')}-{day}"


def home_spread(event: dict) -> tuple[float | None, str | None]:
    home = str(event.get("home_team") or "")
    for book in event.get("bookmakers") or []:
        for market in book.get("markets") or []:
            if market.get("key") != "spreads" or market.get("suspended") is True:
                continue
            for outcome in market.get("outcomes") or []:
                if str(outcome.get("name") or "") == home:
                    try:
                        return float(outcome["point"]), market.get("last_update") or book.get("last_update")
                    except (KeyError, TypeError, ValueError):
                        return None, market.get("last_update") or book.get("last_update")
    return None, None


def flatten_odds(payload: dict, sport: str) -> dict[str, dict]:
    data = payload.get("data") or {}
    candidates: dict[str, tuple[int, dict]] = {}
    if not isinstance(data, dict):
        return {}
    for book_key, events in data.items():
        priority = SHARP_BOOK_PRIORITY.get(str(book_key).lower())
        if priority is None:
            continue
        for event in events or []:
            key = event_key(sport, event)
            current = candidates.get(key)
            if current is None or priority < current[0]:
                candidates[key] = (priority, {**event, "sharp_book": str(book_key).lower()})
    return {key: row for key, (_, row) in candidates.items()}


def choose_public_split(event: dict) -> dict | None:
    rows = [row for row in event.get("splits") or [] if str(row.get("book") or "").lower() in PUBLIC_BOOK_PRIORITY and row.get("spread")]
    return min(rows, key=lambda row: PUBLIC_BOOK_PRIORITY[str(row.get("book") or "").lower()]) if rows else None


def build_capture(state: dict, sport_key: str, odds_payload: dict, splits_payload: dict, captured_at: str) -> tuple[dict, list[dict]]:
    sport = SPORTS[sport_key]
    events = dict(state.get("events") or {})
    sharp = flatten_odds(odds_payload, sport_key)
    snapshots = []
    for split_event in splits_payload.get("data") or []:
        provider_id = str(split_event.get("event_id") or split_event.get("eventId") or "")
        market = sharp.get(provider_id)
        if market is None:
            candidates = [row for row in sharp.values() if row.get("home_team") == split_event.get("home_team") and row.get("away_team") == split_event.get("away_team")]
            market = candidates[0] if len(candidates) == 1 else None
        public = choose_public_split(split_event)
        if market is None or public is None:
            continue
        spread = public.get("spread") or {}
        home_bets = spread.get("home_bets_pct")
        away_bets = spread.get("away_bets_pct")
        if home_bets is None or away_bets is None:
            continue
        current, odds_time_raw = home_spread(market)
        odds_time = parsed_time(odds_time_raw)
        split_time = parsed_time(public.get("as_of"))
        if current is None or odds_time is None or split_time is None or abs((odds_time - split_time).total_seconds()) > 300:
            continue
        key = f"{sport}:{provider_id}"
        previous = events.get(key) or {}
        opening = previous.get("opening_home_spread", current)
        state_row = {
            "sport": sport,
            "event_id": provider_id,
            "start_date": market.get("commence_time"),
            "away_team": split_event.get("away_team"),
            "home_team": split_event.get("home_team"),
            "sharp_book": market.get("sharp_book"),
            "source": "owls_insight_licensed",
            "first_seen_at_utc": previous.get("first_seen_at_utc") or captured_at,
            "last_seen_at_utc": captured_at,
            "book_last_update_utc": odds_time_raw,
            "opening_home_spread": opening,
            "current_home_spread": current,
            "observations": int(previous.get("observations") or 0) + 1,
        }
        events[key] = state_row
        public_side = "home" if float(home_bets) >= float(away_bets) else "away"
        snapshots.append({
            **state_row,
            "captured_at_utc": captured_at,
            "odds_captured_at_utc": odds_time_raw,
            "splits_captured_at_utc": public.get("as_of"),
            "provider_event_id": provider_id,
            "public_source": public.get("title") or public.get("book"),
            "public_book_key": public.get("book"),
            "public_side": public_side,
            "public_ticket_pct": float(home_bets if public_side == "home" else away_bets),
            "public_handle_pct": spread.get(f"{public_side}_handle_pct"),
        })
    state["events"] = events
    state["meta"] = {
        "version": "thi-sharp-lines-v1.1",
        "generated_at_utc": captured_at,
        "source": "The Odds API free tier plus Owls Insight licensed feed",
        "event_count": len(events),
        "signal_policy": "RLM requires synchronized licensed ticket splits and a Pinnacle or BetOnline spread.",
    }
    return state, snapshots


def main() -> None:
    api_key = os.environ.get("OWLS_INSIGHT_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OWLS_INSIGHT_API_KEY is required")
    state_path = ROOT / "data/market/sharp_line_state.json"
    snapshot_path = ROOT / "data/market/rlm_snapshots.jsonl"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"events": {}}
    captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    all_snapshots = []
    for sport_key in SPORTS:
        odds = fetch(f"/api/v1/{sport_key}/odds", api_key, {"books": "pinnacle,betonline"})
        splits = fetch(f"/api/v1/{sport_key}/splits", api_key)
        state, snapshots = build_capture(state, sport_key, odds, splits, captured_at)
        all_snapshots.extend(snapshots)
    atomic_json(state_path, state)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    if all_snapshots:
        with snapshot_path.open("a", encoding="utf-8") as handle:
            for row in all_snapshots:
                handle.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
    print(f"Owls licensed RLM capture: {len(all_snapshots)} synchronized snapshots")


if __name__ == "__main__":
    main()
