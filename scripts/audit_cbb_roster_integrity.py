#!/usr/bin/env python3
"""Fail-closed audit for the public CBB roster and player-rating layer."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-roster-audit-v1.0"


def normalized(value: Any) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in str(value or "")).split())


def audit(payload: dict[str, Any], spot_checks: dict[str, Any] | None = None, expected_teams: int = 350) -> dict[str, Any]:
    rosters = [row for row in payload.get("team_rosters") or [] if isinstance(row, dict)]
    players = [player for roster in rosters for player in roster.get("players") or [] if isinstance(player, dict)]
    by_team = {str(row.get("team_id")): row for row in rosters}
    ids: defaultdict[str, list[str]] = defaultdict(list)
    for row in players:
        source_id = row.get("athlete_source_id") or row.get("athlete_id")
        if source_id is not None:
            ids[str(source_id)].append(str(row.get("name") or "Unknown"))
    duplicate_ids = {key: names for key, names in ids.items() if len(names) > 1}
    invalid_positions = [
        {"team": roster.get("team"), "name": player.get("name"), "position": player.get("position")}
        for roster in rosters for player in roster.get("players") or []
        if str(player.get("position") or "").upper() not in {"G", "PG", "SG", "F", "SF", "PF", "C", "G-F", "F-G", "F-C", "C-F"}
    ]
    spot_results = []
    for check in (spot_checks or {}).get("teams") or []:
        roster = by_team.get(str(check.get("team_id")))
        published = {normalized(row.get("name")) for row in (roster or {}).get("players") or []}
        official = {normalized(name) for name in check.get("official_players") or []}
        overlap = sorted(published & official)
        spot_results.append({
            "team": check.get("team"), "source_url": check.get("source_url"),
            "official_player_count": len(official), "published_player_count": len(published),
            "matching_player_count": len(overlap), "missing_official_players": sorted(official - published),
            "unconfirmed_published_players": sorted(published - official), "passed": bool(official) and official <= published,
        })
    checks = {
        "provider_declares_verified_rosters": payload.get("meta", {}).get("roster_verification_status") == "provider_verified",
        "national_team_coverage": len(rosters) >= expected_teams,
        "unique_player_ids": not duplicate_ids,
        "recognized_positions": not invalid_positions,
        "plausible_roster_sizes": all(8 <= len(row.get("players") or []) <= 22 for row in rosters),
        "official_spot_checks": bool(spot_results) and all(row["passed"] for row in spot_results),
    }
    return {
        "meta": {"version": VERSION, "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "status": "passed" if all(checks.values()) else "withheld", "season": payload.get("meta", {}).get("roster_season")},
        "checks": checks,
        "coverage": {"teams": len(rosters), "players": len(players), "expected_minimum_teams": expected_teams, "roster_size_distribution": dict(sorted(Counter(len(row.get("players") or []) for row in rosters).items()))},
        "duplicate_player_ids": duplicate_ids,
        "invalid_positions": invalid_positions[:100],
        "official_spot_checks": spot_results,
        "decision": "Roster and player-rating publication is allowed." if all(checks.values()) else "Roster and player-rating publication is withheld until a current provider roster clears every gate.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players", type=Path, default=ROOT / "data/cbb/player_ratings.json")
    parser.add_argument("--spot-checks", type=Path, default=ROOT / "data/cbb/roster_spot_checks.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/cbb/roster_audit.json")
    args = parser.parse_args()
    payload = json.loads(args.players.read_text())
    spots = json.loads(args.spot_checks.read_text()) if args.spot_checks.exists() else {}
    report = audit(payload, spots)
    args.output.write_text(json.dumps(report, separators=(",", ":"), allow_nan=False) + "\n")
    print(VERSION, report["meta"]["status"], report["checks"])


if __name__ == "__main__":
    main()
