#!/usr/bin/env python3
"""Freeze THI's preseason CBB schedule-strength view for later reconstruction."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-preseason-sos-snapshot-v1.0"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(payload: dict) -> str:
    material = {"meta": {key: value for key, value in payload["meta"].items() if key not in {"frozen_at_utc", "canonical_sha256"}}, "teams": payload["teams"]}
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def build_snapshot(intelligence_path: Path, board_path: Path, power_path: Path) -> dict:
    intelligence = json.loads(intelligence_path.read_text(encoding="utf-8"))
    board = json.loads(board_path.read_text(encoding="utf-8"))
    power = json.loads(power_path.read_text(encoding="utf-8"))
    rows = []
    for dossier in intelligence.get("team_dossiers") or []:
        schedule = dossier.get("schedule_strength") or {}
        opponents = [
            {"game_id": game.get("game_id"), "opponent_id": game.get("opponent_id"), "opponent": game.get("opponent"), "site": game.get("site")}
            for game in dossier.get("schedule_window") or []
        ]
        rows.append({
            "team_id": dossier.get("team_id"),
            "team": dossier.get("team"),
            "conference": dossier.get("conference"),
            "confirmed_matchups": int(schedule.get("scheduled_games") or len(opponents)),
            "projected_sos": schedule.get("average_opponent_thi_net"),
            "projected_nonconference_sos": schedule.get("nonconference_average_opponent_thi_net"),
            "opponents": opponents,
        })
    rows.sort(key=lambda row: str(row.get("team") or ""))
    payload = {
        "meta": {
            "version": VERSION,
            "season": int(board.get("meta", {}).get("season") or 2027),
            "status": "immutable_preseason_snapshot",
            "immutable": True,
            "schedule_scope": "Confirmed matchups present in THI's published preseason schedule window at freeze time; incomplete future announcements are excluded.",
            "calculation": "Average Structural Power v2 net rating of confirmed opponents; no game result, market price or future schedule addition is included.",
            "future_labels": {"played": "Played SOS", "remaining": "Remaining SOS"},
            "game_count": len(board.get("games") or []),
            "team_count": len(rows),
            "projection_board_version": board.get("meta", {}).get("version"),
            "power_version": power.get("meta", {}).get("version"),
            "source_sha256": {
                "intelligence_suite": file_sha256(intelligence_path),
                "projection_board": file_sha256(board_path),
                "display_power": file_sha256(power_path),
            },
        },
        "teams": rows,
    }
    payload["meta"]["canonical_sha256"] = canonical_hash(payload)
    return payload


def freeze(intelligence_path: Path, board_path: Path, power_path: Path, output: Path) -> dict:
    snapshot = build_snapshot(intelligence_path, board_path, power_path)
    if output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
        if existing.get("meta", {}).get("canonical_sha256") != snapshot["meta"]["canonical_sha256"]:
            raise RuntimeError(f"immutable SOS snapshot already exists with different content: {output}")
        return existing
    snapshot["meta"]["frozen_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--intelligence", type=Path, default=ROOT / "data/cbb/intelligence_suite.json")
    parser.add_argument("--board", type=Path, default=ROOT / "data/cbb/projection_board.json")
    parser.add_argument("--power", type=Path, default=ROOT / "data/cbb/model/display_power_ratings.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/cbb/frozen/preseason_sos_2027.json")
    args = parser.parse_args()
    payload = freeze(args.intelligence, args.board, args.power, args.output)
    print(f"Frozen CBB preseason SOS: {payload['meta']['team_count']} teams · {payload['meta']['canonical_sha256'][:16]}")


if __name__ == "__main__":
    main()
