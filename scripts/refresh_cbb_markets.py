#!/usr/bin/env python3
"""Refresh only near-term CBB markets and preserve an auditable snapshot history."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.build_cbb_data_foundation import market_summary
    from scripts.verify_cbb_api_foundation import clean_key, fetch_json
except ModuleNotFoundError:
    from build_cbb_data_foundation import market_summary
    from verify_cbb_api_foundation import clean_key, fetch_json

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-market-capture-v1.0"


def parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def active_window(board: dict[str, Any], now: datetime, hours: int) -> list[dict[str, Any]]:
    end = now + timedelta(hours=hours)
    return [
        game for game in board.get("games") or []
        if str(game.get("status") or "").lower() == "scheduled"
        and (start := parse_time(game.get("start_date"))) is not None
        and now - timedelta(hours=2) <= start <= end
    ]


def merge_market(previous: dict[str, Any] | None, current: dict[str, Any], captured_at: str) -> dict[str, Any]:
    previous = previous or {}
    opening_spread = previous.get("opening_home_spread")
    if opening_spread is None:
        opening_spread = current.get("opening_home_spread") if current.get("opening_home_spread") is not None else current.get("consensus_home_spread")
    opening_total = previous.get("opening_total")
    if opening_total is None:
        opening_total = current.get("opening_total") if current.get("opening_total") is not None else current.get("consensus_total")
    spread = current.get("consensus_home_spread")
    total = current.get("consensus_total")
    return {
        **current,
        "opening_home_spread": opening_spread,
        "opening_total": opening_total,
        "spread_move": round(float(spread) - float(opening_spread), 2) if spread is not None and opening_spread is not None else None,
        "total_move": round(float(total) - float(opening_total), 2) if total is not None and opening_total is not None else None,
        "first_seen_at_utc": previous.get("first_seen_at_utc") or captured_at,
        "last_seen_at_utc": captured_at,
        "source": "CollegeBasketballData.com transformed consensus",
    }


def refresh(
    board: dict[str, Any],
    history: dict[str, Any] | None,
    line_payload: list[dict[str, Any]],
    now: datetime,
    active_ids: set[str],
) -> tuple[dict[str, Any], dict[str, Any], int]:
    captured_at = now.isoformat().replace("+00:00", "Z")
    by_game = {str(row.get("gameId")): row for row in line_payload if isinstance(row, dict)}
    history = history or {"meta": {}, "games": {}}
    history_games = history.setdefault("games", {})
    changed = 0
    for game in board.get("games") or []:
        game_id = str(game.get("game_id"))
        if game_id not in active_ids:
            continue
        raw = by_game.get(game_id) or {}
        rows = [row for row in raw.get("lines") or [] if isinstance(row, dict)]
        current = market_summary(rows)
        if not current:
            continue
        snapshots = history_games.setdefault(game_id, [])
        previous = dict(game.get("market") or {})
        if snapshots:
            first = snapshots[0]
            previous["opening_home_spread"] = first.get("opening_home_spread")
            previous["opening_total"] = first.get("opening_total")
            previous["first_seen_at_utc"] = first.get("captured_at_utc")
        merged = merge_market(previous, current, captured_at)
        before = game.get("market") or {}
        material = tuple(merged.get(key) for key in ("consensus_home_spread", "consensus_total", "book_count"))
        prior_material = tuple(before.get(key) for key in ("consensus_home_spread", "consensus_total", "book_count"))
        game["market"] = merged
        if material != prior_material or not snapshots:
            snapshots.append({
                "captured_at_utc": captured_at,
                "away_team": (game.get("away") or {}).get("team"),
                "home_team": (game.get("home") or {}).get("team"),
                "start_date": game.get("start_date"),
                "neutral_site": bool(game.get("neutral_site")),
                **{key: merged.get(key) for key in ("book_count", "consensus_home_spread", "consensus_total", "opening_home_spread", "opening_total", "spread_move", "total_move")},
            })
            history_games[game_id] = snapshots[-200:]
            changed += 1
    board.setdefault("meta", {})["market_refreshed_at_utc"] = captured_at
    board["meta"]["market_capture_version"] = VERSION
    board["meta"]["games_with_market"] = sum(bool(game.get("market")) for game in board.get("games") or [])
    history["meta"] = {
        "version": VERSION,
        "generated_at_utc": captured_at,
        "tracked_games": len(history_games),
        "snapshot_count": sum(len(rows) for rows in history_games.values()),
        "policy": "Only changed transformed consensus observations are retained; the first observed opening value is immutable.",
    }
    return board, history, changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", type=Path, default=ROOT / "data/cbb/game_board.json")
    parser.add_argument("--history", type=Path, default=ROOT / "data/cbb/market_snapshots.json")
    parser.add_argument("--hours", type=int, default=72)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    board = json.loads(args.board.read_text())
    now = datetime.now(timezone.utc)
    active = active_window(board, now, args.hours)
    if not active and not args.force:
        print(f"{VERSION}: no scheduled games inside {args.hours} hours; provider request skipped")
        return
    starts = [parse_time(game.get("start_date")) for game in active]
    starts = [value for value in starts if value is not None]
    start = min(starts) - timedelta(hours=3) if starts else now - timedelta(hours=3)
    end = max(starts) + timedelta(hours=3) if starts else now + timedelta(hours=args.hours)
    key = clean_key(os.environ.get("CBBD_API_KEY"))
    if not key:
        raise SystemExit("CBBD_API_KEY is required")
    lines = fetch_json("/lines", {"startDateRange": start.isoformat().replace("+00:00", "Z"), "endDateRange": end.isoformat().replace("+00:00", "Z")}, key)
    if not isinstance(lines, list):
        raise RuntimeError("CBBD lines response is not a list")
    history = json.loads(args.history.read_text()) if args.history.exists() else None
    board, history, changed = refresh(board, history, lines, now, {str(game.get("game_id")) for game in active})
    atomic_write(args.board, board)
    atomic_write(args.history, history)
    print(f"{VERSION}: {len(active)} near-term games checked, {changed} changed market snapshots")


if __name__ == "__main__":
    main()
