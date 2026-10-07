#!/usr/bin/env python3
"""Grade frozen THI CBB projections without rewriting the original forecast."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-model-tracking-v0.1"
REQUIRED_BOARD_VERSION = "thi-cbb-projection-board-v0.5"


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def is_final(game: dict[str, Any]) -> bool:
    return str(game.get("status") or "").lower().replace("_", "") in {"final", "completed", "complete"}


def result_label(value: float) -> str:
    if value > 0.01:
        return "win"
    if value < -0.01:
        return "loss"
    return "push"


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(row["result"] == "win" for row in rows)
    losses = sum(row["result"] == "loss" for row in rows)
    pushes = sum(row["result"] == "push" for row in rows)
    decisions = wins + losses
    clv = [row["clv"] for row in rows if row.get("clv") is not None]
    return {
        "games": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate": round(100 * wins / decisions, 2) if decisions else None,
        "average_clv": round(sum(clv) / len(clv), 3) if clv else None,
        "beat_close_pct": round(100 * sum(value > 0 for value in clv) / len(clv), 2) if clv else None,
        "closing_line_games": len(clv),
    }


def build_tracking(board: dict[str, Any]) -> dict[str, Any]:
    board_version = board.get("meta", {}).get("version")
    if board_version != REQUIRED_BOARD_VERSION:
        raise RuntimeError(f"tracking requires {REQUIRED_BOARD_VERSION}")
    final_games = [game for game in board.get("games") or [] if is_final(game) and game.get("projection")]
    spread_rows: list[dict[str, Any]] = []
    total_rows: list[dict[str, Any]] = []
    margin_errors: list[float] = []
    total_errors: list[float] = []
    winner_results: list[bool] = []

    for game in final_games:
        home_score = finite((game.get("home") or {}).get("score"))
        away_score = finite((game.get("away") or {}).get("score"))
        if home_score is None or away_score is None:
            continue
        projection = game.get("projection") or {}
        projected_margin = finite(projection.get("home_margin"))
        projected_total = finite(projection.get("total"))
        actual_margin = home_score - away_score
        actual_total = home_score + away_score
        if projected_margin is not None:
            margin_errors.append(abs(actual_margin - projected_margin))
            winner_results.append((actual_margin >= 0) == (projected_margin >= 0))
        if projected_total is not None:
            total_errors.append(abs(actual_total - projected_total))

        snapshot = game.get("market") or {}
        closing = game.get("closing_market") or {}
        snapshot_spread = finite(snapshot.get("consensus_home_spread"))
        closing_spread = finite(closing.get("consensus_home_spread"))
        edge = finite(projection.get("spread_edge"))
        if projection.get("spread_signal_eligible") and snapshot_spread is not None and edge is not None:
            pick_home = edge >= 0
            pick_team = (game.get("home") if pick_home else game.get("away")) or {}
            pick_line = snapshot_spread if pick_home else -snapshot_spread
            closing_pick_line = (closing_spread if pick_home else -closing_spread) if closing_spread is not None else None
            grade = (actual_margin if pick_home else -actual_margin) + pick_line
            clv = pick_line - closing_pick_line if closing_pick_line is not None else None
            spread_rows.append({
                "game_id": game.get("game_id"),
                "start_date": game.get("start_date"),
                "away_team": (game.get("away") or {}).get("team"),
                "home_team": (game.get("home") or {}).get("team"),
                "neutral_site": bool(game.get("neutral_site")),
                "pick_team": pick_team.get("team"),
                "pick_team_id": pick_team.get("team_id"),
                "pregame_line": round(pick_line, 2),
                "closing_line": round(closing_pick_line, 2) if closing_pick_line is not None else None,
                "clv": round(clv, 2) if clv is not None else None,
                "result": result_label(grade),
                "result_margin": round(grade, 2),
                "signal_tier": projection.get("spread_signal_tier"),
                "confidence": projection.get("signal_confidence"),
                "model_edge": round(abs(edge), 2),
                "final_score": f"{int(away_score)}-{int(home_score)}",
            })

        snapshot_total = finite(snapshot.get("consensus_total"))
        total_edge = finite(projection.get("total_edge"))
        if projection.get("totals_signal_eligible") and snapshot_total is not None and total_edge is not None:
            over = total_edge >= 0
            grade = actual_total - snapshot_total
            grade = grade if over else -grade
            total_rows.append({
                "game_id": game.get("game_id"),
                "start_date": game.get("start_date"),
                "away_team": (game.get("away") or {}).get("team"),
                "home_team": (game.get("home") or {}).get("team"),
                "neutral_site": bool(game.get("neutral_site")),
                "pick": "over" if over else "under",
                "pregame_total": round(snapshot_total, 2),
                "result": result_label(grade),
                "result_margin": round(grade, 2),
                "model_edge": round(abs(total_edge), 2),
                "final_total": round(actual_total, 2),
            })

    by_tier: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in spread_rows:
        by_tier[str(row.get("signal_tier") or "unknown")].append(row)
        by_month[str(row.get("start_date") or "")[:7] or "unknown"].append(row)
    spread_rows.sort(key=lambda row: str(row.get("start_date") or ""), reverse=True)

    return {
        "meta": {
            "version": VERSION,
            "projection_board_version": board_version,
            "model_version": board.get("meta", {}).get("model_version"),
            "season": board.get("meta", {}).get("season"),
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "grading_policy": "Signals are selected against the frozen pregame market and graded at that frozen line. Closing lines are used only for CLV and beat-close evaluation.",
            "totals_policy": "Official totals tracking remains empty until totals_signal_eligible is activated by the independent totals promotion gate.",
        },
        "summary": {
            "final_games_with_frozen_projection": len(final_games),
            "projection_accuracy": {
                "margin_mae": round(sum(margin_errors) / len(margin_errors), 3) if margin_errors else None,
                "total_mae": round(sum(total_errors) / len(total_errors), 3) if total_errors else None,
                "winner_accuracy": round(100 * sum(winner_results) / len(winner_results), 2) if winner_results else None,
                "games": len(margin_errors),
            },
            "spread": summarize(spread_rows),
            "totals": summarize(total_rows),
        },
        "spread_by_signal": {key: summarize(rows) for key, rows in sorted(by_tier.items())},
        "spread_by_month": {key: summarize(rows) for key, rows in sorted(by_month.items())},
        "spread_decisions": spread_rows,
        "total_decisions": total_rows,
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
    parser.add_argument("--projection-board", type=Path, default=ROOT / "data" / "cbb" / "projection_board.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "cbb" / "model_tracking.json")
    args = parser.parse_args()
    payload = build_tracking(json.loads(args.projection_board.read_text()))
    atomic_write(args.output, payload)
    spread = payload["summary"]["spread"]
    print(f"{VERSION}: {spread['wins']}-{spread['losses']}-{spread['pushes']} across {spread['games']} spread signals")


if __name__ == "__main__":
    main()
