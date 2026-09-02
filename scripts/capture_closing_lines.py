"""
CFB ANALYTICS
capture_closing_lines.py

Near-kickoff market capture for prospective CLV evaluation.

Runs after build_projections.py refreshes the current market using cached
schedule mode. This script does not call CFBD or any API itself.

It captures one near-kickoff market line per game:
- up to 90 minutes before scheduled kickoff
- up to 10 minutes after scheduled kickoff

Output:
    data/snapshots/closing_lines.jsonl
    data/snapshots/latest_closing_capture.json
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTIONS_PATH = ROOT / "data" / "projections.json"
CLOSING_LEDGER_PATH = ROOT / "data" / "snapshots" / "closing_lines.jsonl"
LATEST_CLOSING_PATH = ROOT / "data" / "snapshots" / "latest_closing_capture.json"

PRE_KICKOFF_WINDOW_MINUTES = 90
POST_KICKOFF_GRACE_MINUTES = 10
MODEL_VERSION = "production-model-a-2026-week1-freeze-v1"


def utc_now():
    return datetime.now(timezone.utc)


def parse_datetime(value):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def game_key(game):
    gid = game.get("game_id")
    if gid is not None:
        return str(gid)
    away = ((game.get("away") or {}).get("team") or "").strip()
    home = ((game.get("home") or {}).get("team") or "").strip()
    start = str(game.get("start_date") or "")
    return f"{away}@{home}|{start}"


def closing_id(game):
    raw = "|".join([MODEL_VERSION, game_key(game), "closing-line"])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def load_existing_game_keys():
    if not CLOSING_LEDGER_PATH.exists():
        return set()
    keys = set()
    with CLOSING_LEDGER_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            key = row.get("game_key")
            if key:
                keys.add(str(key))
    return keys


def main():
    if not PROJECTIONS_PATH.exists():
        raise SystemExit("data/projections.json does not exist.")

    payload = load_json(PROJECTIONS_PATH)
    if isinstance(payload, list):
        games = payload
        meta = {}
    elif isinstance(payload, dict):
        games = payload.get("projections") or payload.get("games") or []
        meta = payload.get("meta") or {}
    else:
        raise SystemExit("Unsupported projections.json structure.")

    if not games:
        raise SystemExit("No projections found.")

    now = utc_now()
    existing_keys = load_existing_game_keys()
    rows = []

    earliest = now - timedelta(minutes=POST_KICKOFF_GRACE_MINUTES)
    latest = now + timedelta(minutes=PRE_KICKOFF_WINDOW_MINUTES)

    for game in games:
        if str(game.get("status") or "").lower() == "completed":
            continue

        kickoff = parse_datetime(game.get("start_date"))
        if kickoff is None or kickoff < earliest or kickoff > latest:
            continue

        key = game_key(game)
        if key in existing_keys:
            continue

        market = game.get("market") or {}
        projection = game.get("projection") or {}
        comparison = game.get("comparison") or {}

        market_home_spread = market.get("home_spread")
        if market_home_spread is None:
            continue

        minutes_to_kick = round((kickoff - now).total_seconds() / 60.0, 1)

        row = {
            "closing_id": closing_id(game),
            "game_key": key,
            "captured_at_utc": now.isoformat(),
            "scheduled_kickoff_utc": kickoff.isoformat(),
            "minutes_to_kickoff": minutes_to_kick,
            "capture_type": "near_kickoff_closing_proxy",
            "model_version": MODEL_VERSION,
            "projection_source_generated": meta.get("generated"),
            "game_id": game.get("game_id"),
            "week": game.get("week"),
            "home_team": (game.get("home") or {}).get("team"),
            "away_team": (game.get("away") or {}).get("team"),
            "neutral_site": bool(game.get("neutral_site", False)),
            "model_reference": {
                "home_spread": projection.get("home_spread"),
                "total": projection.get("total"),
            },
            "closing_market": {
                "home_spread": market_home_spread,
                "total": market.get("total"),
                "bookmaker": market.get("bookmaker"),
            },
            "signal_at_close": {
                "disagreement": comparison.get("disagreement"),
                "preferred_side": comparison.get("preferred_side"),
                "signal": comparison.get("signal") or comparison.get("status"),
                "bet_status": comparison.get("bet_status"),
                "status_system": comparison.get("status_system"),
            },
        }

        rows.append(row)
        existing_keys.add(key)

    CLOSING_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)

    if rows:
        with CLOSING_LEDGER_PATH.open("a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, separators=(",", ":")) + "\n")

    latest_payload = {
        "captured_at_utc": now.isoformat(),
        "window": {
            "pre_kickoff_minutes": PRE_KICKOFF_WINDOW_MINUTES,
            "post_kickoff_grace_minutes": POST_KICKOFF_GRACE_MINUTES,
        },
        "closing_lines_added": len(rows),
        "ledger_path": str(CLOSING_LEDGER_PATH.relative_to(ROOT)),
        "captures": rows,
    }

    LATEST_CLOSING_PATH.write_text(
        json.dumps(latest_payload, indent=2),
        encoding="utf-8",
    )

    print("=" * 72)
    print("NEAR-KICKOFF CLOSING LINE CAPTURE COMPLETE")
    print("=" * 72)
    print("Captured:", now.isoformat())
    print("Closing lines added:", len(rows))
    print("Ledger:", CLOSING_LEDGER_PATH.relative_to(ROOT))
    print("Latest:", LATEST_CLOSING_PATH.relative_to(ROOT))


if __name__ == "__main__":
    main()
