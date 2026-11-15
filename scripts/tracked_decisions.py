"""Shared helpers for immutable, prospective CFB tracking decisions.

The live market comparison may change as prices move.  Accountability may not:
the first eligible pregame snapshot with a real side and executable spread is
the ticket that remains attached to the game through settlement.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable


def game_key(row: dict[str, Any]) -> str:
    value = row.get("game_key") or row.get("game_id") or row.get("result_game_id")
    return "" if value in (None, "") else str(value)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_pregame(row: dict[str, Any]) -> bool:
    captured = _timestamp(row.get("captured_at_utc"))
    kickoff = _timestamp(row.get("start_date"))
    return not (captured and kickoff) or captured <= kickoff


def is_tracked_side(row: dict[str, Any]) -> bool:
    if row.get("tracking_eligible", True) is False or not is_pregame(row):
        return False
    side = str(row.get("preferred_side") or "")
    if side not in {str(row.get("home_team") or ""), str(row.get("away_team") or "")}:
        return False
    return _number(row.get("snapshot_home_spread")) is not None


def first_rows(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return the earliest row for every game, regardless of side availability."""
    selected: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: (
        str(item.get("captured_at_utc") or ""),
        str(item.get("snapshot_id") or ""),
    )):
        key = game_key(row)
        if key:
            selected.setdefault(key, row)
    return selected


def first_tracked_rows(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return each game's immutable first executable side decision."""
    return first_rows(row for row in rows if is_tracked_side(row))


def frozen_rows(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Prefer the first tracked side, falling back to the earliest forecast row."""
    materialized = list(rows)
    earliest = first_rows(materialized)
    earliest.update(first_tracked_rows(materialized))
    return earliest
