"""
CFB ANALYTICS
snapshot_projections.py

Append-only prospective projection + market snapshot ledger.

This script runs AFTER build_projections.py. It reads the current production
projections and writes immutable timestamped snapshots to:

    data/snapshots/projection_market_snapshots.jsonl

Each run creates one snapshot per currently scheduled game that has a market
spread. Existing snapshot_ids are never overwritten.

This is the foundation for prospective CLV tracking. A future closing-line
settlement step can compare the market line captured here with a closing line.

IMPORTANT:
- The ledger records what the model/market said AT THAT TIME.
- It does not change projection math.
- It does not use closing lines as predictive features.
- It does not call an API itself.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECTIONS_PATH = ROOT / "data" / "projections.json"
CONDITIONS_PATH = ROOT / "data" / "game_conditions.json"
LEDGER_PATH = ROOT / "data" / "snapshots" / "projection_market_snapshots.jsonl"
LATEST_PATH = ROOT / "data" / "snapshots" / "latest_snapshot.json"

MODEL_VERSION = "production-model-a-2026-week1-freeze-v1"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def kickoff_has_passed(game, captured_at):
    raw = game.get("start_date")
    if not raw:
        return False
    try:
        kickoff = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=timezone.utc)
        captured = datetime.fromisoformat(captured_at)
        return kickoff <= captured
    except ValueError:
        return False


def load_existing_ids():
    if not LEDGER_PATH.exists():
        return set()

    ids = set()
    with LEDGER_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                raise RuntimeError(
                    f"Invalid JSONL row in {LEDGER_PATH.relative_to(ROOT)}"
                )
            sid = row.get("snapshot_id")
            if sid:
                ids.add(str(sid))
    return ids


def game_key(game):
    gid = game.get("game_id")
    if gid is not None:
        return str(gid)

    away = ((game.get("away") or {}).get("team") or "").strip()
    home = ((game.get("home") or {}).get("team") or "").strip()
    start = str(game.get("start_date") or "")
    return f"{away}@{home}|{start}"


def snapshot_id(game, captured_at):
    raw = "|".join([
        MODEL_VERSION,
        game_key(game),
        captured_at,
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def main():
    if not PROJECTIONS_PATH.exists():
        raise SystemExit("data/projections.json does not exist.")

    payload = load_json(PROJECTIONS_PATH)

    if isinstance(payload, list):
        games = payload
        projections_meta = {}
    elif isinstance(payload, dict):
        games = payload.get("projections") or payload.get("games") or []
        projections_meta = payload.get("meta") or {}
    else:
        raise SystemExit("Unsupported projections.json structure.")

    if not games:
        raise SystemExit("No projections found in data/projections.json.")

    captured_at = utc_now()
    existing_ids = load_existing_ids()
    conditions_payload = load_json(CONDITIONS_PATH) if CONDITIONS_PATH.exists() else {}
    conditions_by_game = conditions_payload.get("games") or {}

    rows = []

    for game in games:
        if game.get("status") == "completed":
            continue
        if kickoff_has_passed(game, captured_at):
            continue

        projection = game.get("projection") or {}
        market = game.get("market") or {}
        comparison = game.get("comparison") or {}
        conditions = conditions_by_game.get(str(game.get("game_id"))) or {}
        adjusted = conditions.get("adjusted") or {}
        adjustments = conditions.get("adjustments") or {}
        spread_logic = conditions.get("spread_logic") or {}

        model_spread = projection.get("home_spread")
        market_spread = market.get("home_spread")
        public_spread = number(adjusted.get("home_spread"))
        if public_spread is None:
            public_spread = number(model_spread)
        public_total = number(adjusted.get("total"))
        if public_total is None:
            public_total = number(projection.get("total"))

        # CLV requires a real market reference at prediction time.
        if model_spread is None or market_spread is None:
            continue

        home = (game.get("home") or {}).get("team")
        away = (game.get("away") or {}).get("team")

        sid = snapshot_id(game, captured_at)
        if sid in existing_ids:
            continue

        row = {
            "snapshot_id": sid,
            "captured_at_utc": captured_at,
            "model_version": MODEL_VERSION,
            "projection_source_generated": projections_meta.get("generated"),
            "game_id": game.get("game_id"),
            "week": game.get("week"),
            "start_date": game.get("start_date"),
            "home_team": home,
            "away_team": away,
            "neutral_site": bool(game.get("neutral_site", False)),
            "model": {
                "home_spread": model_spread,
                "total": projection.get("total"),
                "home_win_probability": (
                    (projection.get("win_probability") or {}).get("home")
                ),
            },
            "public_projection": {
                "home_spread": public_spread,
                "total": public_total,
                "weather_applied": bool(conditions),
            },
            "weather_at_snapshot": {
                "conditions_line": conditions.get("conditions_line"),
                "impact": conditions.get("impact"),
                "total_adjustment": adjustments.get("total_points"),
                "spread_adjustment": adjustments.get("home_spread_points"),
                "spread_status": spread_logic.get("status"),
            } if conditions else None,
            "market_at_snapshot": {
                "home_spread": market_spread,
                "total": market.get("total"),
                "bookmaker": market.get("bookmaker"),
            },
            "comparison_at_snapshot": {
                "disagreement": comparison.get("disagreement"),
                "preferred_side": comparison.get("preferred_side"),
                # Preserve the historical UI label, but explicitly identify it
                # as disagreement status rather than validated betting advice.
                "market_disagreement_status": comparison.get("status"),
                "status_system": comparison.get("status_system"),
            },
            "clv": {
                "closing_home_spread": None,
                "clv_points_preferred_side": None,
                "beat_close": None,
                "settled": False,
            },
            "result": {
                "home_points": None,
                "away_points": None,
                "actual_home_margin": None,
                "ats_result_at_snapshot": None,
                "settled": False,
            },
        }

        rows.append(row)
        existing_ids.add(sid)

    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)

    if rows:
        with LEDGER_PATH.open("a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, separators=(",", ":")) + "\n")

    latest = {
        "captured_at_utc": captured_at,
        "model_version": MODEL_VERSION,
        "snapshots_added": len(rows),
        "ledger_path": str(LEDGER_PATH.relative_to(ROOT)),
        "note": (
            "Prospective timestamped model/market snapshot. "
            "Closing lines are evaluation targets only."
        ),
        "snapshots": rows,
    }

    LATEST_PATH.write_text(
        json.dumps(latest, indent=2),
        encoding="utf-8",
    )

    print("=" * 72)
    print("PROJECTION / MARKET SNAPSHOT COMPLETE")
    print("=" * 72)
    print("Model version:", MODEL_VERSION)
    print("Captured:", captured_at)
    print("Snapshots added:", len(rows))
    print("Ledger:", LEDGER_PATH.relative_to(ROOT))
    print("Latest:", LATEST_PATH.relative_to(ROOT))


if __name__ == "__main__":
    main()
