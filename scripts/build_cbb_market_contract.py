#!/usr/bin/env python3
"""Build the stable display/evaluation contract for CBB market data."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-market-contract-v1.0"


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def history_rows(history: dict[str, Any], game_id: str) -> list[dict[str, Any]]:
    stored = (history.get("games") or {}).get(game_id) or []
    if isinstance(stored, dict):
        stored = stored.get("snapshots") or []
    return [row for row in stored if isinstance(row, dict)][-200:]


def normalized_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "captured_at_utc": row.get("captured_at_utc") or row.get("captured_at"),
        "home_spread": finite(row.get("consensus_home_spread") if row.get("consensus_home_spread") is not None else row.get("home_spread")),
        "total": finite(row.get("consensus_total") if row.get("consensus_total") is not None else row.get("total")),
        "book_count": int(row.get("book_count") or 0),
    }


def movement_direction(opening: float | None, current: float | None, home: str, away: str) -> str:
    if opening is None or current is None or abs(current - opening) < 0.01:
        return "unchanged" if opening is not None and current is not None else "unavailable"
    return f"toward_{home}" if current < opening else f"toward_{away}"


def build_contract(board: dict[str, Any], history: dict[str, Any] | None = None) -> dict[str, Any]:
    history = history or {"games": {}}
    games: dict[str, Any] = {}
    market_count = 0
    for game in board.get("games") or []:
        if not isinstance(game, dict) or not game.get("projection"):
            continue
        game_id = str(game.get("game_id"))
        projection = game["projection"]
        market = game.get("market") or {}
        snapshots = [normalized_snapshot(row) for row in history_rows(history, game_id)]
        opening_spread = finite(market.get("opening_home_spread"))
        opening_total = finite(market.get("opening_total"))
        if snapshots:
            opening_spread = snapshots[0]["home_spread"] if snapshots[0]["home_spread"] is not None else opening_spread
            opening_total = snapshots[0]["total"] if snapshots[0]["total"] is not None else opening_total
        current_spread = finite(market.get("consensus_home_spread"))
        current_total = finite(market.get("consensus_total"))
        if snapshots:
            current_spread = snapshots[-1]["home_spread"] if snapshots[-1]["home_spread"] is not None else current_spread
            current_total = snapshots[-1]["total"] if snapshots[-1]["total"] is not None else current_total
        if market or snapshots:
            market_count += 1
        home = str((game.get("home") or {}).get("team") or "home")
        away = str((game.get("away") or {}).get("team") or "away")
        games[game_id] = {
            "game_id": game_id,
            "start_date": game.get("start_date"),
            "status": game.get("status"),
            "neutral_site": bool(game.get("neutral_site")),
            "away_team": away,
            "home_team": home,
            "model": {
                "thi_home_spread": -finite(projection.get("home_margin")) if finite(projection.get("home_margin")) is not None else None,
                "thi_total": finite(projection.get("total")),
                "away_points": finite(projection.get("away_points")),
                "home_points": finite(projection.get("home_points")),
                "projected_possessions": finite(projection.get("projected_possessions")),
                "home_win_probability": finite(projection.get("home_win_probability")),
            },
            "market": {
                "opening": {
                    "home_spread": opening_spread,
                    "total": opening_total,
                    "captured_at_utc": (snapshots[0]["captured_at_utc"] if snapshots else market.get("first_seen_at_utc")),
                    "label": "THI first captured",
                },
                "current": {
                    "home_spread": current_spread,
                    "total": current_total,
                    "captured_at_utc": (snapshots[-1]["captured_at_utc"] if snapshots else market.get("last_seen_at_utc")),
                },
                "movement": {
                    "home_spread_points": round(current_spread - opening_spread, 2) if current_spread is not None and opening_spread is not None else None,
                    "total_points": round(current_total - opening_total, 2) if current_total is not None and opening_total is not None else None,
                    "spread_direction": movement_direction(opening_spread, current_spread, home, away),
                    "toward_thi": (
                        abs(current_spread - -float(projection["home_margin"])) < abs(opening_spread - -float(projection["home_margin"]))
                        if current_spread is not None and opening_spread is not None and finite(projection.get("home_margin")) is not None else None
                    ),
                },
                "book_count": int(market.get("book_count") or 0),
                "book_lines": market.get("book_lines") if isinstance(market.get("book_lines"), list) else [],
                "reference_moneyline": market.get("reference_moneyline") if isinstance(market.get("reference_moneyline"), dict) else {},
                "spread_price_status": market.get("spread_price_status") or "unavailable",
            },
            "history": snapshots,
        }
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "projection_board_version": (board.get("meta") or {}).get("version"),
            "game_count": len(games),
            "games_with_market": market_count,
            "opening_label_policy": "Opening is THI's first captured observation unless the source explicitly supplies an opener.",
            "model_isolation": "Market fields are display and evaluation context only; they are never model features.",
        },
        "games": games,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", type=Path, default=ROOT / "data/cbb/projection_board.json")
    parser.add_argument("--history", type=Path, default=ROOT / "data/cbb/market_snapshots.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/cbb/market_contract.json")
    args = parser.parse_args()
    board = json.loads(args.board.read_text())
    history = json.loads(args.history.read_text()) if args.history.exists() else None
    payload = build_contract(board, history)
    atomic_write(args.output, payload)
    print(f"{VERSION}: {payload['meta']['game_count']} games; {payload['meta']['games_with_market']} with market observations")


if __name__ == "__main__":
    main()
