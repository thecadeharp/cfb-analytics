#!/usr/bin/env python3
"""Build a compact CBB live-game intelligence layer from current PBP."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.build_cbb_play_style import aggregate_game
    from scripts.verify_cbb_api_foundation import clean_key, fetch_json
except ModuleNotFoundError:
    from build_cbb_play_style import aggregate_game
    from verify_cbb_api_foundation import clean_key, fetch_json

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-live-center-v1.0"
LIVE_STATUSES = {"live", "inprogress", "in_progress", "halftime"}


def build(board: dict[str, Any], api_key: str | None) -> dict[str, Any]:
    games = []
    errors = []
    live = [game for game in board.get("games") or [] if str(game.get("status") or "").lower() in LIVE_STATUSES]
    for game in live:
        game_id = str(game.get("game_id"))
        if not api_key:
            errors.append({"game_id": game.get("game_id"), "error": "CBBD_API_KEY unavailable"})
            continue
        try:
            style = aggregate_game(game, fetch_json(f"/plays/game/{game_id}", {}, api_key))
            games.append({
                "game_id": game.get("game_id"),
                "status": game.get("status"),
                "start_date": game.get("start_date"),
                "away": game.get("away"),
                "home": game.get("home"),
                "live": game.get("live") or {},
                "teams": style.get("teams") or [],
                "provider_play_count": style.get("provider_play_count"),
                "coverage_state": "tracked" if int(style.get("provider_play_count") or 0) >= 20 else "developing",
            })
        except RuntimeError as error:
            errors.append({"game_id": game.get("game_id"), "error": str(error)[:180]})
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "live_game_count": len(live),
            "tracked_game_count": len(games),
            "policy": "Live score and compact play aggregates only. Live observations never alter the frozen pregame projection.",
        },
        "games": games,
        "fetch_errors": errors,
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", type=Path, default=ROOT / "data/cbb/projection_board.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/cbb/live_game_center.json")
    args = parser.parse_args()
    payload = build(json.loads(args.board.read_text()), clean_key(os.environ.get("CBBD_API_KEY")))
    atomic_write(args.output, payload)
    print(f"{VERSION}: {payload['meta']['tracked_game_count']} live games enriched")


if __name__ == "__main__":
    main()
