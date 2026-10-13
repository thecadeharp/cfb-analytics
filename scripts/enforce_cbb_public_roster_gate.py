#!/usr/bin/env python3
"""Remove unverified CBB player records from the public static payload."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def enforce(players: dict, audit: dict) -> tuple[dict, bool]:
    passed = audit.get("meta", {}).get("status") == "passed" and all((audit.get("checks") or {}).values())
    if passed:
        return players, False
    meta = dict(players.get("meta") or {})
    source_player_count = len(players.get("players") or [])
    source_team_count = len(players.get("team_rosters") or [])
    meta.update({
        "roster_verification_status": "withheld_by_thi_audit",
        "public_payload_status": "withheld",
        "public_payload_generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "player_count": 0,
        "team_count": 0,
        "source_player_count_before_gate": source_player_count,
        "source_team_count_before_gate": source_team_count,
        "withheld_reason": "Current rosters have not cleared THI's independent verification audit.",
    })
    coverage = dict(players.get("coverage") or {})
    coverage["published_players"] = 0
    coverage["published_team_rosters"] = 0
    return {"meta": meta, "coverage": coverage, "players": [], "team_rosters": []}, True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players", type=Path, default=ROOT / "data/cbb/player_ratings.json")
    parser.add_argument("--audit", type=Path, default=ROOT / "data/cbb/roster_audit.json")
    args = parser.parse_args()
    players = json.loads(args.players.read_text())
    audit = json.loads(args.audit.read_text())
    public_payload, changed = enforce(players, audit)
    if changed:
        args.players.write_text(json.dumps(public_payload, indent=2, allow_nan=False) + "\n")
    print("CBB public roster gate:", "withheld" if changed else "passed")


if __name__ == "__main__":
    main()
