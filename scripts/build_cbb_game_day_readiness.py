#!/usr/bin/env python3
"""Audit the CBB projection, market-freeze and final-grading lifecycle."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-game-day-readiness-v1.0"


def parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def complete_score(game: dict[str, Any]) -> bool:
    return all((game.get(side) or {}).get("score") is not None for side in ("away", "home"))


def build(board: dict[str, Any], tracking: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    games = board.get("games") or []
    ids = [str(game.get("game_id")) for game in games]
    scheduled = [game for game in games if str(game.get("status") or "").lower() == "scheduled"]
    finals = [game for game in games if str(game.get("status") or "").lower() in {"final", "completed", "complete"}]
    generated = parse_time((board.get("meta") or {}).get("generated_at_utc"))
    age_hours = (now - generated).total_seconds() / 3600 if generated else None
    checks = {
        "projection_board_contract_valid": (board.get("meta") or {}).get("version") == "thi-cbb-projection-board-v0.5",
        "unique_game_ids": len(ids) == len(set(ids)),
        "all_scheduled_games_have_frozen_projection": all(bool(game.get("projection")) for game in scheduled),
        "all_final_games_retain_projection": all(bool(game.get("projection")) for game in finals),
        "all_final_games_have_scores": all(complete_score(game) for game in finals),
        "all_final_games_have_closing_market_when_opening_market_exists": all(
            not game.get("market") or bool(game.get("closing_market")) for game in finals
        ),
        "tracking_matches_projection_board": (tracking.get("meta") or {}).get("projection_board_version") == (board.get("meta") or {}).get("version"),
        "refresh_is_current_within_36_hours": age_hours is not None and -1 <= age_hours <= 36,
    }
    upcoming_market = [game for game in scheduled if game.get("market")]
    frozen_final = [game for game in finals if game.get("projection")]
    closing_final = [game for game in finals if game.get("closing_market")]
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": now.isoformat().replace("+00:00", "Z"),
            "season": (board.get("meta") or {}).get("season"),
            "status": "ready" if all(checks.values()) else "attention_required",
            "published_model_unchanged": True,
        },
        "checks": checks,
        "coverage": {
            "games": len(games),
            "scheduled": len(scheduled),
            "final": len(finals),
            "live": sum(str(game.get("status") or "").lower() in {"live", "in_progress", "inprogress"} for game in games),
            "upcoming_with_market": len(upcoming_market),
            "finals_with_frozen_projection": len(frozen_final),
            "finals_with_closing_market": len(closing_final),
            "graded_spread_decisions": len(tracking.get("spread_decisions") or []),
            "graded_total_decisions": len(tracking.get("total_decisions") or []),
            "board_age_hours": round(age_hours, 2) if age_hours is not None else None,
        },
        "automation": {
            "opening_snapshot": "The first published projection and market remain frozen when the game leaves scheduled status.",
            "closing_snapshot": "The final provider market is stored separately as closing_market and never rewrites the frozen decision line.",
            "final_grading": "Final scores grade the frozen decision line; closing market is used only for CLV and beat-close measurement.",
            "rating_update": "The next coordinated refresh updates current team states only after completed games are ingested.",
        },
        "exceptions": [key for key, passed in checks.items() if not passed],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projection-board", type=Path, default=ROOT / "data" / "cbb" / "projection_board.json")
    parser.add_argument("--tracking", type=Path, default=ROOT / "data" / "cbb" / "model_tracking.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "cbb" / "game_day_readiness.json")
    args = parser.parse_args()
    payload = build(json.loads(args.projection_board.read_text()), json.loads(args.tracking.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(f"{VERSION}: {payload['meta']['status']} ({sum(payload['checks'].values())}/{len(payload['checks'])} checks)")


if __name__ == "__main__":
    main()
