#!/usr/bin/env python3
"""Aggregate private operational readiness without adding public-page clutter."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: str) -> dict:
    target = ROOT / path
    return json.loads(target.read_text()) if target.exists() else {}


def build() -> dict:
    projections = load("data/projections.json")
    settled = load("data/reports/settled_results.json")
    cbb = load("data/cbb/platform_health.json")
    rlm = load("data/market/rlm_monitor.json")
    providers = load("data/market/provider_capabilities.json")
    audit = load("data/research/cfbd_training_pack_audit.json")
    cfb_games = projections.get("games", [])
    now = datetime.now(timezone.utc)
    upcoming = []
    for game in cfb_games:
        try: kickoff = datetime.fromisoformat(str(game.get("start_date") or "").replace("Z", "+00:00"))
        except ValueError: continue
        if str(game.get("status", "")).lower() != "final" and kickoff >= now:
            upcoming.append(game)
    active_week = min((int(game.get("week") or 0) for game in upcoming), default=None)
    active = [game for game in upcoming if active_week is not None and int(game.get("week") or 0) == active_week]
    lined = [g for g in active if (g.get("market") or {}).get("home_spread") is not None]
    unlined = [
        {
            "game_id": game.get("game_id"),
            "start_date": game.get("start_date"),
            "away_team": (game.get("away") or {}).get("team") or game.get("away_team"),
            "home_team": (game.get("home") or {}).get("team") or game.get("home_team"),
        }
        for game in active if (game.get("market") or {}).get("home_spread") is None
    ]
    counts = settled.get("counts", {})
    blockers = []
    if active and len(lined) < len(active): blockers.append(f"CFB Week {active_week}: {len(active)-len(lined)} games do not have a spread.")
    cbb_cov = cbb.get("coverage", {})
    if cbb_cov.get("games_with_market", 0) == 0: blockers.append("CBB books have not posted board lines yet.")
    if cbb_cov.get("sides_with_verified_mileage", 0) == 0: blockers.append("CBB verified venue coordinates are not loaded; mileage remains inactive.")
    if cbb_cov.get("verified_availability_reports", 0) == 0: blockers.append("CBB verified player availability reports are not loaded.")
    if (rlm.get("meta") or {}).get("rlm_status") != "active": blockers.append("True RLM remains inactive until a licensed public-splits feed is configured.")
    return {
        "meta": {"version": "thi-operations-readiness-v1.0", "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "audience": "internal", "public_navigation": False},
        "cfb": {"active_week": active_week, "scheduled_games": len(active), "games_with_spread": len(lined), "games_awaiting_spread": unlined, "frozen_snapshot_games": counts.get("unique_snapshot_games"), "settled_initial_snapshots": counts.get("initial_snapshots_settled"), "unmatched_initial_snapshots": counts.get("initial_snapshots_unmatched"), "cfbd_training_pack": {"status": (audit.get("meta") or {}).get("status"), "week": (audit.get("scope") or {}).get("weeks"), "rows": (audit.get("scope") or {}).get("rows")}},
        "cbb": {"platform_status": (cbb.get("meta") or {}).get("status"), **cbb_cov},
        "market_monitor": {"status": (rlm.get("meta") or {}).get("status"), "rlm_status": (rlm.get("meta") or {}).get("rlm_status"), "sharp_tracked_events": (rlm.get("meta") or {}).get("sharp_tracked_event_count"), "sharp_moves": (rlm.get("meta") or {}).get("sharp_move_count"), "true_rlm_alerts": (rlm.get("meta") or {}).get("alert_count"), "provider_readiness": providers.get("providers", {})},
        "open_items": blockers,
    }


if __name__ == "__main__":
    output = ROOT / "data/reports/operations_readiness.json"
    payload = build()
    if output.exists():
        previous=json.loads(output.read_text()); old=dict(previous); new=dict(payload); old.pop("meta",None);new.pop("meta",None)
        if old==new: print(previous["meta"]["version"],len(previous["open_items"]),"open items");raise SystemExit
    output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(payload["meta"]["version"], len(payload["open_items"]), "open items")
