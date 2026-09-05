#!/usr/bin/env python3
"""
THE HAMMER INDEX — MARKET LAYER BUILDER

Additive / isolated market-data layer.
- Does NOT call CFBD.
- Does NOT change Model A.
- Reads current THI projections + consensus odds.
- Maintains open/current/close main-line history.
- Optionally fetches alternate spreads from The Odds API one event at a time.
- Only stores alternate spreads for THI's preferred side.
"""

from __future__ import annotations

import json
import os
import sys
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
PROJECTIONS_PATH = ROOT / "data" / "projections.json"
ODDS_PATH = ROOT / "data" / "odds.json"
HISTORY_PATH = ROOT / "data" / "market_history.json"
ALTS_PATH = ROOT / "data" / "alternate_spreads.json"

ODDS_BASE = "https://api.the-odds-api.com/v4"
SPORT_KEY = "americanfootball_ncaaf"

FETCH_ALT_LINES = os.environ.get("FETCH_ALT_LINES", "0") == "1"
ALT_LOOKAHEAD_HOURS = int(os.environ.get("ALT_LOOKAHEAD_HOURS", "48"))
ALT_MAX_GAMES = int(os.environ.get("ALT_MAX_GAMES", "40"))
ALT_MODE = "all_regular_fbs_fbs_with_market_and_preferred_side"

BOOK_ABBR = {
    "draftkings": "DK",
    "fanduel": "FD",
    "betmgm": "MGM",
    "caesars": "CZR",
    "betrivers": "BR",
    "betonlineag": "BOL",
    "bovada": "BOV",
    "fanatics": "FAN",
    "espnbet": "ESPN",
    "hardrockbet": "HR",
    "betus": "BUS",
    "mybookieag": "MB",
    "lowvig": "LV",
}

def now_utc():
    return datetime.now(timezone.utc)

def iso_now():
    return now_utc().isoformat()

def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

def clean_key(raw):
    key = str(raw or "").strip().strip("'\"")
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key.replace("\r", "").replace("\n", "").replace("\t", "").strip()

def canonical(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    for old, new in {
        "&": "and", "'": "", "’": "", ".": "", ",": "",
        "-": " ", "_": " ", "(": " ", ")": " "
    }.items():
        text = text.replace(old, new)
    return " ".join(text.split())

def team_matches(provider_name, model_name):
    p = canonical(provider_name)
    m = canonical(model_name)
    if not p or not m:
        return False
    return p == m or p.startswith(m + " ") or m.startswith(p + " ")

def canonical_signal(value):
    raw = str(value or "").upper().strip()
    aliases = {
        "AGREE W/ MARKET": "ALIGNED",
        "ALIGNED": "ALIGNED",
        "LEAN": "SMALL EDGE",
        "SLIGHT EDGE": "SMALL EDGE",
        "SMALL EDGE": "SMALL EDGE",
        "EDGE": "PLAY",
        "PLAY": "PLAY",
        "STRONG EDGE": "MATERIAL DISAGREEMENT",
        "MATERIAL DISAGREEMENT": "MATERIAL DISAGREEMENT",
        "OUTLIER": "OUTLIER",
    }
    return aliases.get(raw, raw)

def signal_name(game):
    comparison = game.get("comparison") or {}
    return canonical_signal(comparison.get("signal") or comparison.get("status"))

def is_fcs_fallback(game):
    return str(game.get("model_type") or "").lower() == "fcs_fallback"

def preferred_side(game, odds_row=None):
    comparison = game.get("comparison") or {}
    explicit = comparison.get("preferred_side")
    if explicit:
        return explicit

    # ALIGNED games can still have a tiny directional difference even when
    # the public signal is not a "play" tier. Infer the side only when the
    # model and market are actually different.
    home = game.get("home", {}).get("team") or game.get("home_team")
    away = game.get("away", {}).get("team") or game.get("away_team")

    model_home = projection_home_spread(game)
    market_home = None

    if odds_row is not None:
        try:
            market_home = float(odds_row.get("spread_home"))
        except (TypeError, ValueError):
            market_home = None

    if market_home is None:
        market = game.get("market") or {}
        try:
            market_home = float(market.get("home_spread"))
        except (TypeError, ValueError):
            market_home = None

    if model_home is None or market_home is None:
        return None

    delta = model_home - market_home
    if abs(delta) < 0.001:
        return None

    # If THI's home spread is more negative than market, THI is more bullish
    # on the home team. If it is less negative / more positive, THI leans away.
    return home if delta < 0 else away

def projection_home_spread(game):
    projection = game.get("projection") or {}
    value = projection.get("home_spread")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None

def game_start(game):
    return parse_dt(game.get("start_date") or game.get("commence_time"))

def game_id(game):
    return str(game.get("game_id") or game.get("id") or "")

def payload_games(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        games = payload.get("games")
        return games if isinstance(games, list) else []
    return []

def side_spread(home_spread, preferred, home_team, away_team):
    if home_spread is None or not preferred:
        return None
    try:
        hs = float(home_spread)
    except (TypeError, ValueError):
        return None
    if preferred == home_team:
        return hs
    if preferred == away_team:
        return -hs
    return None

def matchup_key(home, away):
    return f"{canonical(away)}__at__{canonical(home)}"

def find_odds_game(odds_games, game):
    home = game.get("home", {}).get("team") or game.get("home_team")
    away = game.get("away", {}).get("team") or game.get("away_team")
    if not home or not away:
        return None

    candidates = [
        row for row in odds_games
        if row.get("home_team") == home and row.get("away_team") == away
    ]
    if not candidates:
        return None

    start = game_start(game)
    if start:
        candidates.sort(
            key=lambda row: abs(
                ((parse_dt(row.get("commence_time")) or start) - start).total_seconds()
            )
        )
    return candidates[0]

def history_row_id(game, odds_row):
    gid = game_id(game)
    if gid:
        return gid
    if odds_row and odds_row.get("id"):
        return str(odds_row["id"])
    home = game.get("home", {}).get("team") or game.get("home_team")
    away = game.get("away", {}).get("team") or game.get("away_team")
    return matchup_key(home, away)

def update_history(projections, odds_games):
    existing = load_json(HISTORY_PATH, {"meta": {}, "games": {}})
    rows = existing.get("games")
    if not isinstance(rows, dict):
        rows = {}

    stamp = iso_now()
    now = now_utc()

    for game in projections:
        odds_row = find_odds_game(odds_games, game)
        if not odds_row:
            continue

        try:
            observed = float(odds_row.get("spread_home"))
        except (TypeError, ValueError):
            continue

        home = game.get("home", {}).get("team") or game.get("home_team")
        away = game.get("away", {}).get("team") or game.get("away_team")
        rid = history_row_id(game, odds_row)
        start = game_start(game)
        row = rows.get(rid)

        # Never invent an "opening" or "closing" line from the first observation
        # after a game has already kicked. If THI did not capture the game
        # pre-kick, leave it without a history row.
        if row is None and start and now >= start:
            continue

        if row is None:
            row = {
                "game_id": game_id(game) or None,
                "odds_event_id": odds_row.get("id"),
                "home_team": home,
                "away_team": away,
                "start_date": game.get("start_date") or odds_row.get("commence_time"),
                "first_captured_home_spread": observed,
                "first_captured_at": stamp,
                # Backward-compatible aliases retained for existing frontend/data.
                "open_home_spread": observed,
                "open_captured_at": stamp,
                "current_home_spread": observed,
                "current_captured_at": stamp,
                "close_home_spread": None,
                "close_captured_at": None,
                "snapshots": [],
            }

        row["game_id"] = game_id(game) or row.get("game_id")
        row["odds_event_id"] = odds_row.get("id") or row.get("odds_event_id")
        row["home_team"] = home
        row["away_team"] = away
        row["start_date"] = game.get("start_date") or row.get("start_date")

        # Migrate old rows to the clearer FIRST CAPTURED terminology without
        # changing the originally stored number.
        if row.get("first_captured_home_spread") is None:
            row["first_captured_home_spread"] = row.get("open_home_spread")
        if row.get("first_captured_at") is None:
            row["first_captured_at"] = row.get("open_captured_at")

        snapshots = row.get("snapshots")
        if not isinstance(snapshots, list):
            snapshots = []

        if start is None or now < start:
            # Pregame only: update CURRENT and append market changes.
            row["current_home_spread"] = observed
            row["current_captured_at"] = stamp

            if not snapshots or snapshots[-1].get("home_spread") != observed:
                snapshots.append({
                    "captured_at": stamp,
                    "home_spread": observed,
                })
        else:
            # At/after kickoff: do NOT allow a live/in-play quote to become
            # CURRENT or CLOSE. Freeze the latest snapshot THI captured before
            # kickoff as the local closing line.
            if row.get("close_home_spread") is None:
                prekick = []
                for snap in snapshots:
                    snap_time = parse_dt(snap.get("captured_at"))
                    try:
                        snap_spread = float(snap.get("home_spread"))
                    except (TypeError, ValueError):
                        continue
                    if snap_time and snap_time <= start:
                        prekick.append((snap_time, snap_spread))

                if prekick:
                    prekick.sort(key=lambda item: item[0])
                    close_time, close_spread = prekick[-1]
                    row["close_home_spread"] = close_spread
                    row["close_captured_at"] = close_time.isoformat()
                    row["current_home_spread"] = close_spread
                    row["current_captured_at"] = close_time.isoformat()

        row["snapshots"] = snapshots[-96:]
        rows[rid] = row

    payload = {
        "meta": {
            "generated_at": stamp,
            "source": "THI consensus market snapshots",
            "model_a_touched": False,
            "first_line_definition": "FIRST CAPTURED = first consensus spread observed by THI, not a claimed sportsbook opener.",
            "close_definition": "CLOSE = latest THI-captured pre-kick consensus spread. Post-kick/in-play quotes are never used.",
            "note": "Historical rows created before this schema retain their original first-captured value through backward-compatible open_* fields."
        },
        "games": rows,
    }
    save_json(HISTORY_PATH, payload)
    return payload

def api_get(url, params):
    try:
        response = requests.get(url, params=params, timeout=35)
    except requests.RequestException as exc:
        print(f"⚠ Odds API request failed: {exc}")
        return None

    remaining = response.headers.get("x-requests-remaining")
    used = response.headers.get("x-requests-used")
    last = response.headers.get("x-requests-last")
    if remaining is not None:
        print(f"   Odds API remaining={remaining} used={used} last_cost={last}")

    if not response.ok:
        print(f"⚠ Odds API HTTP {response.status_code}: {response.text[:250]}")
        return None

    try:
        return response.json()
    except ValueError:
        return None

def fetch_featured_spreads(api_key):
    return api_get(
        f"{ODDS_BASE}/sports/{SPORT_KEY}/odds",
        {
            "apiKey": api_key,
            "regions": "us",
            "markets": "spreads",
            "oddsFormat": "american",
            "dateFormat": "iso",
        },
    ) or []

def best_main_price(raw_event, preferred, preferred_point):
    best = None
    for book in raw_event.get("bookmakers", []) or []:
        for market in book.get("markets", []) or []:
            if market.get("key") != "spreads":
                continue
            for outcome in market.get("outcomes", []) or []:
                if not team_matches(outcome.get("name"), preferred):
                    continue
                try:
                    point = float(outcome.get("point"))
                    price = int(outcome.get("price"))
                except (TypeError, ValueError):
                    continue
                if abs(point - preferred_point) > 0.001:
                    continue
                if best is None or price > best["price"]:
                    key = str(book.get("key") or "")
                    best = {
                        "point": point,
                        "price": price,
                        "bookmaker": book.get("title") or key or "Unknown",
                        "bookmaker_key": key,
                        "book_abbr": BOOK_ABBR.get(key, (book.get("title") or key or "BOOK")[:4].upper()),
                    }
    return best

def extract_alt_ladder(event_payload, preferred):
    by_point = {}
    for book in event_payload.get("bookmakers", []) or []:
        key = str(book.get("key") or "")
        title = book.get("title") or key or "Unknown"
        abbr = BOOK_ABBR.get(key, title[:4].upper())
        for market in book.get("markets", []) or []:
            if market.get("key") != "alternate_spreads":
                continue
            for outcome in market.get("outcomes", []) or []:
                if not team_matches(outcome.get("name"), preferred):
                    continue
                try:
                    point = float(outcome.get("point"))
                    price = int(outcome.get("price"))
                except (TypeError, ValueError):
                    continue

                row = {
                    "point": point,
                    "price": price,
                    "bookmaker": title,
                    "bookmaker_key": key,
                    "book_abbr": abbr,
                }
                current = by_point.get(point)
                if current is None or price > current["price"]:
                    by_point[point] = row

    return [by_point[p] for p in sorted(by_point)]

def find_raw_event(raw_events, odds_event_id):
    for row in raw_events:
        if str(row.get("id")) == str(odds_event_id):
            return row
    return None

def build_alt_lines(projections, odds_games, history):
    api_key = clean_key(os.environ.get("ODDS_API_KEY"))
    if not api_key:
        print("❌ ODDS_API_KEY missing; cannot fetch alternate spreads.")
        return

    existing = load_json(ALTS_PATH, {"meta": {}, "games": {}})
    rows = existing.get("games")
    if not isinstance(rows, dict):
        rows = {}

    raw_featured = fetch_featured_spreads(api_key)
    now = now_utc()
    horizon = now + timedelta(hours=ALT_LOOKAHEAD_HOURS)

    eligible = []
    for game in projections:
        if is_fcs_fallback(game):
            continue

        start = game_start(game)
        if not start:
            continue
        if start < now - timedelta(hours=1) or start > horizon:
            continue

        odds_row = find_odds_game(odds_games, game)
        if not odds_row or not odds_row.get("id"):
            continue
        if odds_row.get("spread_home") is None:
            continue

        preferred = preferred_side(game, odds_row)
        if not preferred:
            # Exact THI/market alignment has no honest preferred-side ladder.
            continue

        eligible.append((start, game, odds_row))

    eligible.sort(key=lambda item: item[0])
    eligible = eligible[:ALT_MAX_GAMES]

    print(
        f"🔨 Alternate-spread refresh: {len(eligible)} eligible games "
        f"(lookahead={ALT_LOOKAHEAD_HOURS}h, max={ALT_MAX_GAMES})."
    )
    print("   One event-level alternate_spreads request is made per eligible game.")

    fetched = 0

    for _, game, odds_row in eligible:
        preferred = preferred_side(game, odds_row)
        home = game.get("home", {}).get("team") or game.get("home_team")
        away = game.get("away", {}).get("team") or game.get("away_team")
        event_id = odds_row.get("id")
        rid = history_row_id(game, odds_row)

        market_home = odds_row.get("spread_home")
        try:
            market_home = float(market_home)
        except (TypeError, ValueError):
            market_home = None

        model_home = projection_home_spread(game)
        market_side = side_spread(market_home, preferred, home, away)
        thi_side = side_spread(model_home, preferred, home, away)

        payload = api_get(
            f"{ODDS_BASE}/sports/{SPORT_KEY}/events/{event_id}/odds",
            {
                "apiKey": api_key,
                "regions": "us",
                "markets": "alternate_spreads",
                "oddsFormat": "american",
                "dateFormat": "iso",
            },
        )

        if not payload:
            continue

        ladder = extract_alt_ladder(payload, preferred)
        raw_event = find_raw_event(raw_featured, event_id)
        main = (
            best_main_price(raw_event, preferred, market_side)
            if raw_event and market_side is not None
            else None
        )

        merged = {row["point"]: dict(row) for row in ladder}
        if main:
            merged[main["point"]] = {**main, "is_main": True}

        output = []
        for point in sorted(merged):
            row = merged[point]
            row["is_main"] = bool(
                row.get("is_main")
                or (market_side is not None and abs(point - market_side) < 0.001)
            )
            if thi_side is not None:
                distance = round(point - thi_side, 1)
                row["distance_from_thi"] = distance
                row["distance_label"] = (
                    f"{abs(distance):.1f} pts inside THI"
                    if distance >= 0
                    else f"{abs(distance):.1f} pts beyond THI"
                )
            output.append(row)

        # Keep a useful band around the market/THI numbers instead of dumping
        # every extreme alternate available at a book.
        if market_side is not None and thi_side is not None:
            low = min(market_side, thi_side) - 5.0
            high = max(market_side, thi_side) + 5.0
            compact = [row for row in output if low <= row["point"] <= high]
            if len(compact) >= 3:
                output = compact

        rows[rid] = {
            "game_id": game_id(game) or None,
            "odds_event_id": event_id,
            "home_team": home,
            "away_team": away,
            "start_date": game.get("start_date") or odds_row.get("commence_time"),
            "signal": signal_name(game),
            "preferred_side": preferred,
            "thi_spread_for_preferred_side": thi_side,
            "main_market_spread_for_preferred_side": market_side,
            "fetched_at": iso_now(),
            "lines": output,
        }
        fetched += 1
        time.sleep(0.12)

    save_json(
        ALTS_PATH,
        {
            "meta": {
                "generated_at": iso_now(),
                "source": "The Odds API",
                "market": "alternate_spreads",
                "preferred_side_only": True,
                "model_a_touched": False,
                "lookahead_hours": ALT_LOOKAHEAD_HOURS,
                "max_games_per_run": ALT_MAX_GAMES,
                "eligibility": ALT_MODE,
                "games_refreshed": fetched,
                "note": "Best observed American price per alternate point for THI preferred side. Event-level requests consume additional Odds API quota."
            },
            "games": rows,
        },
    )

def main():
    projections_payload = load_json(PROJECTIONS_PATH, {})
    odds_payload = load_json(ODDS_PATH, {})

    projections = payload_games(projections_payload)
    odds_games = payload_games(odds_payload)

    if not projections:
        print(f"❌ No projections found in {PROJECTIONS_PATH}")
        sys.exit(1)
    if not odds_games:
        print(f"❌ No odds found in {ODDS_PATH}")
        sys.exit(1)

    history = update_history(projections, odds_games)
    print(f"✅ Updated {HISTORY_PATH.relative_to(ROOT)}")

    if FETCH_ALT_LINES:
        build_alt_lines(projections, odds_games, history)
        print(f"✅ Updated {ALTS_PATH.relative_to(ROOT)}")
    else:
        print("ℹ Alternate-spread API fetch skipped (FETCH_ALT_LINES != 1).")

    print("✅ Model A untouched.")

if __name__ == "__main__":
    main()
