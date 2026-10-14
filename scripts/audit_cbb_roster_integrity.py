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
VERSION = "thi-cbb-roster-audit-v1.1"
POSITION_ALIASES = {
    "guard": "G", "point guard": "PG", "shooting guard": "SG",
    "forward": "F", "small forward": "SF", "power forward": "PF",
    "center": "C", "guard forward": "G-F", "forward guard": "F-G",
    "forward center": "F-C", "center forward": "C-F",
}


def normalized(value: Any) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in str(value or "")).split())


def normalized_position(value: Any) -> str:
    text = normalized(value)
    return POSITION_ALIASES.get(text, str(value or "").upper().replace("/", "-").replace(" ", ""))


def official_name(row: Any) -> str:
    return str(row.get("name") if isinstance(row, dict) else row or "")


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
        if normalized_position(player.get("position")) not in {"G", "PG", "SG", "F", "SF", "PF", "C", "G-F", "F-G", "F-C", "C-F"}
    ]
    checks_by_team_id = {
        str(check.get("team_id")): check
        for check in (spot_checks or {}).get("teams") or []
        if check.get("team_id") is not None
    }
    spot_results = []
    for check in (spot_checks or {}).get("teams") or []:
        roster = by_team.get(str(check.get("team_id")))
        published = {normalized(row.get("name")) for row in (roster or {}).get("players") or []}
        official = {normalized(official_name(row)) for row in check.get("official_players") or []}
        official.discard("")
        overlap = sorted(published & official)
        complete = check.get("official_roster_complete") is True
        missing = sorted(official - published)
        unconfirmed = sorted(published - official)
        passed = bool(official) and not missing and (not complete or not unconfirmed)
        spot_results.append({
            "team": check.get("team"), "source_url": check.get("source_url"),
            "checked_at": check.get("checked_at"), "official_roster_complete": complete,
            "official_player_count": len(official), "published_player_count": len(published),
            "matching_player_count": len(overlap), "missing_official_players": missing,
            "unconfirmed_published_players": unconfirmed, "passed": passed,
        })
    spot_by_team_id = {
        str(check.get("team_id")): result
        for check, result in zip((spot_checks or {}).get("teams") or [], spot_results)
    }
    team_audit = []
    for roster in sorted(rosters, key=lambda row: str(row.get("team") or "")):
        team_id = str(roster.get("team_id"))
        roster_players = [row for row in roster.get("players") or [] if isinstance(row, dict)]
        invalid_count = sum(
            normalized_position(row.get("position"))
            not in {"G", "PG", "SG", "F", "SF", "PF", "C", "G-F", "F-G", "F-C", "C-F"}
            for row in roster_players
        )
        official_check = checks_by_team_id.get(team_id)
        official_result = spot_by_team_id.get(team_id)
        plausible_size = 8 <= len(roster_players) <= 22
        if official_result:
            verification_state = "official_match" if official_result["passed"] else "official_mismatch"
        elif not plausible_size or invalid_count:
            verification_state = "structural_review"
        else:
            verification_state = "official_source_pending"
        team_audit.append({
            "team_id": roster.get("team_id"),
            "team": roster.get("team"),
            "provider_player_count": len(roster_players),
            "invalid_position_count": invalid_count,
            "plausible_roster_size": plausible_size,
            "verification_state": verification_state,
            "official_source_url": (official_check or {}).get("source_url"),
            "official_checked_at": (official_check or {}).get("checked_at"),
            "official_player_count": (official_result or {}).get("official_player_count"),
            "matching_player_count": (official_result or {}).get("matching_player_count"),
            "missing_official_players": (official_result or {}).get("missing_official_players", []),
            "unconfirmed_provider_players": (official_result or {}).get("unconfirmed_published_players", []),
        })
    state_counts = Counter(row["verification_state"] for row in team_audit)
    checks = {
        "provider_declares_verified_rosters": payload.get("meta", {}).get("roster_verification_status") == "provider_verified",
        "national_team_coverage": len(rosters) >= expected_teams,
        "unique_player_ids": not duplicate_ids,
        "recognized_positions": not invalid_positions,
        "plausible_roster_sizes": all(8 <= len(row.get("players") or []) <= 22 for row in rosters),
        "official_spot_checks": bool(spot_results) and all(row["passed"] for row in spot_results),
        "official_source_coverage": len(spot_results) >= len(rosters) and all(
            row.get("official_roster_complete") for row in spot_results
        ),
    }
    return {
        "meta": {"version": VERSION, "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "status": "passed" if all(checks.values()) else "withheld", "season": payload.get("meta", {}).get("roster_season")},
        "checks": checks,
        "coverage": {
            "teams": len(rosters), "players": len(players), "expected_minimum_teams": expected_teams,
            "roster_size_distribution": dict(sorted(Counter(len(row.get("players") or []) for row in rosters).items())),
            "official_sources_checked": len(spot_results),
            "official_sources_required": len(rosters),
            "verification_state_counts": dict(sorted(state_counts.items())),
        },
        "duplicate_player_ids": duplicate_ids,
        "invalid_positions": invalid_positions[:100],
        "official_spot_checks": spot_results,
        "team_audit": team_audit,
        "decision": "Roster and player-rating publication is allowed." if all(checks.values()) else "Roster and player-rating publication is withheld until every team has a complete official-source match and the structural gates pass.",
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
