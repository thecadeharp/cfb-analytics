#!/usr/bin/env python3
"""Audit CFB player ratings, roster identities and leaderboard contracts."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.build_player_intelligence import POSITION_GROUPS, RATING_MINIMUMS, usage_volume
except ModuleNotFoundError:
    from build_player_intelligence import POSITION_GROUPS, RATING_MINIMUMS, usage_volume


ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cfb-player-audit-v1.0"


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def roster_index(roster: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    indexed: dict[str, dict[str, Any]] = {}
    memberships: defaultdict[str, list[str]] = defaultdict(list)
    for team, payload in (roster.get("teams") or {}).items():
        for player in payload.get("players") or []:
            athlete_id = str(player.get("athlete_id") or "")
            if not athlete_id:
                continue
            memberships[athlete_id].append(team)
            indexed[athlete_id] = {**player, "team": team}
    return indexed, dict(memberships)


def audit(payload: dict[str, Any], roster: dict[str, Any]) -> dict[str, Any]:
    players = payload.get("players") or {}
    teams = payload.get("teams") or {}
    leaderboards = payload.get("leaderboards") or {}
    roster_players, memberships = roster_index(roster)
    duplicate_roster_memberships = {
        athlete_id: team_names for athlete_id, team_names in memberships.items() if len(team_names) != 1
    }
    identity_mismatches = []
    position_mismatches = []
    volume_mismatches = []
    rating_contract_mismatches = []
    invalid_ratings = []
    component_mismatches = []

    for athlete_id, player in players.items():
        roster_player = roster_players.get(str(athlete_id))
        if roster_player is None or roster_player.get("team") != player.get("team"):
            identity_mismatches.append({
                "athlete_id": athlete_id,
                "name": player.get("name"),
                "published_team": player.get("team"),
                "roster_team": (roster_player or {}).get("team"),
            })
        roster_position = str((roster_player or {}).get("position") or player.get("position") or "").upper()
        expected_group = POSITION_GROUPS.get(roster_position)
        if expected_group and player.get("position_group") != expected_group:
            position_mismatches.append({
                "athlete_id": athlete_id,
                "name": player.get("name"),
                "position": roster_position,
                "expected_group": expected_group,
                "published_group": player.get("position_group"),
            })
        expected_volume = usage_volume(player.get("position_group"), player.get("traditional") or {})
        if abs(float(player.get("primary_volume") or 0) - expected_volume) > 1e-9:
            volume_mismatches.append({
                "athlete_id": athlete_id,
                "name": player.get("name"),
                "group": player.get("position_group"),
                "expected_volume": expected_volume,
                "published_volume": player.get("primary_volume"),
            })
        minimum = RATING_MINIMUMS.get(player.get("position_group"))
        eligible = minimum is not None and expected_volume >= minimum
        rated = finite(player.get("rating"))
        if eligible != rated:
            rating_contract_mismatches.append({
                "athlete_id": athlete_id,
                "name": player.get("name"),
                "group": player.get("position_group"),
                "volume": expected_volume,
                "minimum": minimum,
                "rating": player.get("rating"),
            })
        if rated and not 1 <= float(player["rating"]) <= 99:
            invalid_ratings.append({"athlete_id": athlete_id, "name": player.get("name"), "rating": player.get("rating")})
        components = player.get("rating_components")
        if rated:
            required = ["workload_percentile", "raw_composite", "reliability_percent", "final_rating", "formula"]
            missing = [key for key in required if not isinstance(components, dict) or components.get(key) is None]
            numeric_keys = ["workload_percentile", "raw_composite", "reliability_percent", "final_rating"]
            invalid = [
                key for key in numeric_keys
                if not isinstance(components, dict) or not finite(components.get(key))
                or not 0 <= float(components[key]) <= 100
            ]
            if player.get("position_group") != "DEF":
                for key in ("efficiency_percentile", "total_production_percentile", "success_percentile"):
                    if not isinstance(components, dict) or not finite(components.get(key)) or not 0 <= float(components[key]) <= 100:
                        invalid.append(key)
            final_mismatch = (
                isinstance(components, dict)
                and finite(components.get("final_rating"))
                and abs(float(components["final_rating"]) - float(player["rating"])) > 1e-9
            )
            if missing or invalid or final_mismatch:
                component_mismatches.append({
                    "athlete_id": athlete_id, "name": player.get("name"),
                    "missing": missing, "invalid": sorted(set(invalid)),
                    "rating": player.get("rating"), "components": components,
                })
        elif components is not None:
            component_mismatches.append({
                "athlete_id": athlete_id, "name": player.get("name"),
                "reason": "unrated_player_has_components", "components": components,
            })

    team_memberships: defaultdict[str, list[str]] = defaultdict(list)
    team_payload_mismatches = []
    for team, athlete_ids in teams.items():
        for athlete_id in athlete_ids:
            team_memberships[str(athlete_id)].append(team)
            player = players.get(str(athlete_id))
            if player is None or player.get("team") != team:
                team_payload_mismatches.append({
                    "athlete_id": athlete_id,
                    "listed_team": team,
                    "player_team": (player or {}).get("team"),
                })
    duplicate_team_payload_memberships = {
        athlete_id: team_names for athlete_id, team_names in team_memberships.items() if len(team_names) != 1
    }

    leaderboard_mismatches = []
    for group in RATING_MINIMUMS:
        expected = [
            row["athlete_id"]
            for row in sorted(
                [row for row in players.values() if row.get("position_group") == group and finite(row.get("rating"))],
                key=lambda row: (-float(row["rating"]), str(row.get("name") or "")),
            )
        ]
        published = [str(value) for value in leaderboards.get(group) or []]
        if published != expected:
            leaderboard_mismatches.append({"group": group, "expected_count": len(expected), "published_count": len(published)})
        for rank, athlete_id in enumerate(expected, 1):
            if players[athlete_id].get("national_position_rank") != rank:
                leaderboard_mismatches.append({
                    "group": group,
                    "athlete_id": athlete_id,
                    "expected_rank": rank,
                    "published_rank": players[athlete_id].get("national_position_rank"),
                })

    checks = {
        "current_roster_identity": not identity_mismatches,
        "unique_roster_membership": not duplicate_roster_memberships,
        "position_cohort_consistency": not position_mismatches,
        "position_specific_volume": not volume_mismatches,
        "rating_eligibility_contract": not rating_contract_mismatches,
        "finite_bounded_ratings": not invalid_ratings,
        "rating_decomposition_integrity": not component_mismatches,
        "team_payload_integrity": not team_payload_mismatches and not duplicate_team_payload_memberships,
        "leaderboard_integrity": not leaderboard_mismatches,
        "national_coverage": len(teams) >= 130 and len(players) >= 3000,
        "model_a_isolation_declared": payload.get("meta", {}).get("model_usage") == "display_only_not_used_by_model_a",
    }
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "passed" if all(checks.values()) else "failed",
            "season": payload.get("meta", {}).get("season"),
            "through_week": payload.get("meta", {}).get("through_week"),
            "rating_version": payload.get("meta", {}).get("rating_version"),
        },
        "checks": checks,
        "coverage": {
            "published_players": len(players),
            "published_teams": len(teams),
            "rated_players": sum(finite(row.get("rating")) for row in players.values()),
            "position_groups": dict(sorted(Counter(row.get("position_group") for row in players.values()).items())),
            "finding_counts": {
                "identity_mismatches": len(identity_mismatches),
                "duplicate_roster_memberships": len(duplicate_roster_memberships),
                "position_mismatches": len(position_mismatches),
                "volume_mismatches": len(volume_mismatches),
                "rating_contract_mismatches": len(rating_contract_mismatches),
                "invalid_ratings": len(invalid_ratings),
                "component_mismatches": len(component_mismatches),
                "team_payload_mismatches": len(team_payload_mismatches),
                "duplicate_team_payload_memberships": len(duplicate_team_payload_memberships),
                "leaderboard_mismatches": len(leaderboard_mismatches),
            },
        },
        "findings": {
            "identity_mismatches": identity_mismatches[:100],
            "duplicate_roster_memberships": duplicate_roster_memberships,
            "position_mismatches": position_mismatches[:100],
            "volume_mismatches": volume_mismatches[:100],
            "rating_contract_mismatches": rating_contract_mismatches[:100],
            "invalid_ratings": invalid_ratings[:100],
            "component_mismatches": component_mismatches[:100],
            "team_payload_mismatches": team_payload_mismatches[:100],
            "duplicate_team_payload_memberships": duplicate_team_payload_memberships,
            "leaderboard_mismatches": leaderboard_mismatches[:100],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players", type=Path, default=ROOT / "data" / "player_intelligence.json")
    parser.add_argument("--rosters", type=Path, default=ROOT / "data" / "roster_assets.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "player_intelligence_audit.json")
    args = parser.parse_args()
    report = audit(json.loads(args.players.read_text()), json.loads(args.rosters.read_text()))
    args.output.write_text(json.dumps(report, separators=(",", ":"), allow_nan=False) + "\n")
    print(VERSION, report["meta"]["status"], report["checks"])
    if report["meta"]["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
