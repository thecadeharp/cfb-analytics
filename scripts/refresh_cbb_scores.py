#!/usr/bin/env python3
"""Refresh CBB game states and scores without rebuilding pregame projections."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from scripts.verify_cbb_api_foundation import clean_key, fetch_json
except ModuleNotFoundError:
    from verify_cbb_api_foundation import clean_key, fetch_json


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_LOOKBACK = timedelta(hours=8)
ACTIVE_LOOKAHEAD = timedelta(minutes=45)
FINAL_STATES = {"final", "completed", "complete", "post", "postgame"}
LIVE_STATES = {
    "live", "inprogress", "in_progress", "in progress", "halftime", "half time",
    "overtime", "ot", "1st half", "2nd half", "first half", "second half",
}
ESPN_SUMMARY_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/"
    "mens-college-basketball/summary?event={event_id}"
)


def parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def canonical_status(value: Any) -> str:
    raw = str(value or "").strip().lower()
    compact = raw.replace("-", " ").replace("_", " ")
    if raw in FINAL_STATES or any(token in compact for token in ("final", "complete", "postgame")):
        return "final"
    if raw in LIVE_STATES or any(token in compact for token in ("progress", "halftime", "overtime")):
        return "live"
    return "scheduled"


def status_rank(value: Any) -> int:
    return {"scheduled": 0, "live": 1, "final": 2}[canonical_status(value)]


def number(value: Any) -> int | float | None:
    try:
        parsed = float(value)
        if not math.isfinite(parsed):
            return None
        return int(parsed) if parsed.is_integer() else parsed
    except (TypeError, ValueError):
        return None


def nested(row: dict[str, Any], *path: str) -> Any:
    value: Any = row
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def first_value(row: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> Any:
    for path in paths:
        value = nested(row, *path)
        if value is not None:
            return value
    return None


def score(row: dict[str, Any], side: str) -> int | float | None:
    title = side.capitalize()
    return number(first_value(row, (
        (f"{side}Points",), (f"{side}Score",),
        (f"{side}Team", "points"), (f"{side}Team", "score"),
        (side, "points"), (side, "score"),
        (f"{title}Points",), (f"{title}Score",),
    )))


def provider_game_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or row.get("gameId") or row.get("game_id") or "")


def provider_rows_by_id(*collections: Any) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for collection in collections:
        rows = collection.get("games") if isinstance(collection, dict) else collection
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            game_id = provider_game_id(row)
            if not game_id:
                continue
            current = merged.get(game_id)
            if current is None or status_rank(row.get("status")) >= status_rank(current.get("status")):
                merged[game_id] = row
    return merged


def fetch_espn_summary(event_id: str) -> dict[str, Any] | None:
    request = Request(
        ESPN_SUMMARY_URL.format(event_id=event_id),
        headers={"User-Agent": "THI-CBB-Score-Reconciliation/1.0"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
        return payload if isinstance(payload, dict) else None
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None


def espn_provider_row(payload: dict[str, Any], event_id: str) -> dict[str, Any] | None:
    header = payload.get("header") or {}
    competitions = header.get("competitions") or []
    competition = competitions[0] if competitions else {}
    competitors = competition.get("competitors") or []
    home = next((row for row in competitors if row.get("homeAway") == "home"), None)
    away = next((row for row in competitors if row.get("homeAway") == "away"), None)
    if home is None or away is None:
        return None
    status = competition.get("status") or {}
    status_type = status.get("type") or {}
    state = str(status_type.get("state") or "pre").lower()
    normalized = "final" if status_type.get("completed") or state == "post" else "live" if state == "in" else "scheduled"
    return {
        "id": event_id,
        "status": normalized,
        "homePoints": home.get("score"),
        "awayPoints": away.get("score"),
        "period": status.get("period"),
        "clock": status.get("displayClock"),
        "statusDetail": status_type.get("shortDetail") or status_type.get("detail"),
        "source": "ESPN verified fallback",
    }


def candidate_window(board: dict[str, Any], now: datetime) -> tuple[datetime, datetime] | None:
    candidates: list[datetime] = []
    for game in board.get("games") or []:
        status = canonical_status(game.get("status"))
        start = parse_time(game.get("start_date"))
        if status == "final" or start is None:
            continue
        if status == "live" or now - ACTIVE_LOOKBACK <= start <= now + ACTIVE_LOOKAHEAD:
            candidates.append(start)
    if not candidates:
        return None
    return min(candidates) - timedelta(hours=2), max(candidates) + timedelta(hours=10)


def live_context(row: dict[str, Any]) -> dict[str, Any] | None:
    period = first_value(row, (("period",), ("currentPeriod",), ("gameState", "period")))
    clock = first_value(row, (("clock",), ("displayClock",), ("gameState", "clock")))
    detail = first_value(row, (("statusDetail",), ("statusText",), ("gameState", "detail")))
    context = {"period": period, "clock": clock, "detail": detail}
    return context if any(value not in (None, "") for value in context.values()) else None


def apply_scores(
    game_board: dict[str, Any],
    projection_board: dict[str, Any],
    provider_rows: dict[str, dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    newly_final_ids: list[str] = []
    game_board_by_id = {str(game.get("game_id")): game for game in game_board.get("games") or []}
    projection_by_id = {str(game.get("game_id")): game for game in projection_board.get("games") or []}

    for game_id, row in provider_rows.items():
        target_status = canonical_status(row.get("status"))
        home_score, away_score = score(row, "home"), score(row, "away")
        for target in (game_board_by_id.get(game_id), projection_by_id.get(game_id)):
            if not target:
                continue
            old_status = canonical_status(target.get("status"))
            next_status = target_status if status_rank(target_status) >= status_rank(old_status) else old_status
            changed = next_status != old_status
            if next_status == "final" and old_status != "final" and target is projection_by_id.get(game_id) and not target.get("closing_market"):
                target["closing_market"] = copy.deepcopy(target.get("market") or {})
                changed = True
            if next_status in {"live", "final"}:
                if home_score is not None and target.get("home", {}).get("score") != home_score:
                    target.setdefault("home", {})["score"] = home_score
                    changed = True
                if away_score is not None and target.get("away", {}).get("score") != away_score:
                    target.setdefault("away", {})["score"] = away_score
                    changed = True
            context = live_context(row) if next_status == "live" else None
            if context != target.get("live"):
                if context:
                    target["live"] = context
                else:
                    target.pop("live", None)
                changed = True
            if changed:
                target["status"] = next_status
    # Determine material changes against the snapshots retained by the caller.
    before = projection_board.pop("_score_pulse_before", {})
    before_games = before.get("games", {}) if isinstance(before, dict) else {}
    material_ids = []
    for game_id, game in projection_by_id.items():
        prior = before_games.get(game_id)
        current = {
            "status": canonical_status(game.get("status")),
            "home": (game.get("home") or {}).get("score"),
            "away": (game.get("away") or {}).get("score"),
            "live": game.get("live"),
        }
        if prior != current:
            material_ids.append(game_id)
            if prior and prior.get("status") != "final" and current["status"] == "final":
                newly_final_ids.append(game_id)

    if material_ids:
        for payload in (game_board, projection_board):
            payload.setdefault("meta", {})["generated_at_utc"] = generated_at
            payload["meta"]["score_pulse_generated_at_utc"] = generated_at
        games = projection_board.get("games") or []
        projection_board["meta"]["status_counts"] = {
            "upcoming": sum(canonical_status(game.get("status")) == "scheduled" for game in games),
            "live": sum(canonical_status(game.get("status")) == "live" for game in games),
            "final": sum(canonical_status(game.get("status")) == "final" for game in games),
        }
    return {"updated_ids": sorted(set(material_ids)), "newly_final_ids": sorted(set(newly_final_ids))}


def snapshot_projection(board: dict[str, Any]) -> None:
    board["_score_pulse_before"] = {
        "games": {
            str(game.get("game_id")): {
                "status": canonical_status(game.get("status")),
                "home": (game.get("home") or {}).get("score"),
                "away": (game.get("away") or {}).get("score"),
                "live": game.get("live"),
            }
            for game in board.get("games") or []
        }
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def refresh(
    game_board: dict[str, Any],
    projection_board: dict[str, Any],
    fetcher: Callable[[str, dict[str, Any]], Any],
    now: datetime,
    espn_fetcher: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    window = candidate_window(projection_board, now)
    if window is None:
        return {"active_window": False, "updated_ids": [], "newly_final_ids": [], "recent_final": False}
    start, end = window
    params = {
        "startDateRange": start.isoformat().replace("+00:00", "Z"),
        "endDateRange": end.isoformat().replace("+00:00", "Z"),
    }
    games = fetcher("/games", params)
    scoreboard = fetcher("/scoreboard", {})
    if not isinstance(games, list) or not isinstance(scoreboard, (list, dict)):
        raise RuntimeError("CBBD score pulse returned an invalid response")
    provider_rows = provider_rows_by_id(games, scoreboard)
    espn_fetcher = espn_fetcher or fetch_espn_summary
    for game in projection_board.get("games") or []:
        game_id = str(game.get("game_id") or "")
        external = game.get("external_ids") or {}
        espn_id = str(external.get("espn") or "")
        start_time = parse_time(game.get("start_date"))
        if (
            not espn_id
            or game_id in provider_rows
            or start_time is None
            or not (now - ACTIVE_LOOKBACK <= start_time <= now + ACTIVE_LOOKAHEAD)
        ):
            continue
        payload = espn_fetcher(espn_id)
        if payload and (row := espn_provider_row(payload, espn_id)):
            provider_rows[game_id] = row

    snapshot_projection(projection_board)
    result = apply_scores(
        game_board,
        projection_board,
        provider_rows,
        now.isoformat().replace("+00:00", "Z"),
    )
    result["active_window"] = True
    result["recent_final"] = any(
        canonical_status(game.get("status")) == "final"
        and (start_time := parse_time(game.get("start_date"))) is not None
        and now - timedelta(hours=8) <= start_time <= now
        for game in projection_board.get("games") or []
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-board", type=Path, default=ROOT / "data/cbb/game_board.json")
    parser.add_argument("--projection-board", type=Path, default=ROOT / "data/cbb/projection_board.json")
    parser.add_argument("--changed-flag", type=Path)
    parser.add_argument("--recent-final-flag", type=Path)
    parser.add_argument("--newly-final-flag", type=Path)
    args = parser.parse_args()
    key = clean_key(os.environ.get("CBBD_API_KEY"))
    if not key:
        raise SystemExit("CBBD_API_KEY is required")
    game_board = json.loads(args.game_board.read_text())
    projection_board = json.loads(args.projection_board.read_text())
    now = datetime.now(timezone.utc)
    result = refresh(game_board, projection_board, lambda path, params: fetch_json(path, params, key), now)
    if result["updated_ids"]:
        atomic_write(args.game_board, game_board)
        atomic_write(args.projection_board, projection_board)
        if args.changed_flag:
            args.changed_flag.write_text("\n".join(result["updated_ids"]) + "\n", encoding="utf-8")
    if result["recent_final"] and args.recent_final_flag:
        args.recent_final_flag.write_text("1\n", encoding="utf-8")
    if result["newly_final_ids"] and args.newly_final_flag:
        args.newly_final_flag.write_text("\n".join(result["newly_final_ids"]) + "\n", encoding="utf-8")
    print(
        f"CBB score pulse: active_window={result['active_window']} "
        f"updated={len(result['updated_ids'])} newly_final={len(result['newly_final_ids'])}"
    )


if __name__ == "__main__":
    main()
