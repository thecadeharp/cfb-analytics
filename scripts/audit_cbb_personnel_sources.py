#!/usr/bin/env python3
"""Measure CBBD preseason personnel coverage without storing raw API rows."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.verify_cbb_api_foundation import clean_key, fetch_json
except ModuleNotFoundError:
    from verify_cbb_api_foundation import clean_key, fetch_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "cbb" / "research" / "personnel_source_audit.json"
AUDIT_VERSION = "cbb-personnel-audit-v1.0"


def finite(value: Any) -> float:
    try:
        number = float(value)
        return number if number == number else 0.0
    except (TypeError, ValueError):
        return 0.0


def normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def require_list(name: str, payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise RuntimeError(f"{name} returned {type(payload).__name__}; expected list")
    return [row for row in payload if isinstance(row, dict)]


def roster_player_rows(roster: dict[str, Any]) -> list[dict[str, Any]]:
    container = roster.get("players")
    if isinstance(container, list):
        return [row for row in container if isinstance(row, dict)]
    if isinstance(container, dict):
        for key in ("rows", "players", "items", "data"):
            nested = container.get(key)
            if isinstance(nested, list):
                return [row for row in nested if isinstance(row, dict)]
        if container and all(isinstance(row, dict) for row in container.values()):
            return list(container.values())
    return []


def build_audit(
    season: int,
    prior_season: int,
    recruiting_year: int,
    fetcher: Callable[[str, dict[str, Any]], Any],
) -> dict[str, Any]:
    rosters = require_list("current rosters", fetcher("/teams/roster", {"season": season}))
    prior_players = require_list("prior player stats", fetcher("/stats/player/season", {"season": prior_season}))
    recruits = require_list("recruits", fetcher("/recruiting/players", {"year": recruiting_year}))
    team_recruiting = require_list("team recruiting", fetcher("/recruiting/teams", {"year": recruiting_year}))
    portal_primary = require_list("portal primary year", fetcher("/recruiting/portal", {"year": recruiting_year}))
    portal_next = require_list("portal next year", fetcher("/recruiting/portal", {"year": recruiting_year + 1}))

    roster_players = []
    roster_by_id: dict[str, tuple[str, str]] = {}
    roster_by_name: set[tuple[str, str]] = set()
    roster_team_ids = {str(row.get("teamId")) for row in rosters if row.get("teamId") is not None}
    player_container_types = Counter(type(row.get("players")).__name__ for row in rosters)
    player_object_keys = sorted({
        key
        for row in rosters[:100]
        if isinstance(row.get("players"), dict)
        for key in row["players"].keys()
    })
    for roster in rosters:
        team_id = str(roster.get("teamId"))
        team_name = str(roster.get("team") or "")
        for player in roster_player_rows(roster):
            roster_players.append(player)
            athlete_id = player.get("id")
            if athlete_id is not None:
                roster_by_id[str(athlete_id)] = (team_id, team_name)
            roster_by_name.add((normalized(team_name), normalized(player.get("name"))))

    prior_by_id = {
        str(row.get("athleteId")): row
        for row in prior_players
        if row.get("athleteId") is not None
    }
    prior_minutes_by_team: dict[str, float] = {}
    for row in prior_players:
        team_id = str(row.get("teamId"))
        prior_minutes_by_team[team_id] = prior_minutes_by_team.get(team_id, 0.0) + finite(row.get("minutes"))

    matched_ids = set(roster_by_id) & set(prior_by_id)
    returning_minutes_by_team: dict[str, float] = {}
    incoming_minutes_by_team: dict[str, float] = {}
    matched_transfer_players = 0
    for athlete_id in matched_ids:
        current_team_id, _ = roster_by_id[athlete_id]
        prior = prior_by_id[athlete_id]
        prior_team_id = str(prior.get("teamId"))
        minutes = finite(prior.get("minutes"))
        if prior_team_id == current_team_id:
            returning_minutes_by_team[current_team_id] = returning_minutes_by_team.get(current_team_id, 0.0) + minutes
        else:
            incoming_minutes_by_team[current_team_id] = incoming_minutes_by_team.get(current_team_id, 0.0) + minutes
            if minutes > 0:
                matched_transfer_players += 1

    returning_pcts = []
    for team_id, denominator in prior_minutes_by_team.items():
        if denominator > 0:
            returning_pcts.append(100 * returning_minutes_by_team.get(team_id, 0.0) / denominator)

    recruit_ids = {str(row.get("athleteId")) for row in recruits if row.get("athleteId") is not None}
    recruit_teams = {
        str((row.get("committedTo") or {}).get("id"))
        for row in recruits
        if isinstance(row.get("committedTo"), dict) and (row.get("committedTo") or {}).get("id") is not None
    }

    def portal_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        destinations = [row.get("destination") for row in rows if isinstance(row.get("destination"), dict)]
        matched_by_name = 0
        for row in rows:
            destination = row.get("destination") or {}
            full_name = f"{row.get('firstName') or ''} {row.get('lastName') or ''}"
            if (normalized(destination.get("name")), normalized(full_name)) in roster_by_name:
                matched_by_name += 1
        return {
            "record_count": len(rows),
            "destination_known_count": len(destinations),
            "rating_known_count": sum(row.get("rating") is not None for row in rows),
            "matched_to_current_roster_by_team_and_name": matched_by_name,
        }

    sorted_returning = sorted(returning_pcts)
    median_returning = sorted_returning[len(sorted_returning) // 2] if sorted_returning else None
    return {
        "meta": {
            "audit_version": AUDIT_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "season": season,
            "prior_season": prior_season,
            "recruiting_year": recruiting_year,
            "request_count": 6,
            "raw_api_data_stored": False,
            "purpose": "coverage audit only; no model activation",
        },
        "rosters": {
            "record_count": len(rosters),
            "unique_team_count": len(roster_team_ids),
            "player_count": len(roster_players),
            "unique_player_id_count": len(roster_by_id),
            "players_per_team": round(len(roster_players) / len(roster_team_ids), 3) if roster_team_ids else None,
            "schema_probe": {
                "top_level_keys": sorted({key for row in rosters[:100] for key in row.keys()}),
                "players_container_types": dict(sorted(player_container_types.items())),
                "players_object_keys": player_object_keys,
            },
        },
        "prior_player_stats": {
            "record_count": len(prior_players),
            "unique_player_id_count": len(prior_by_id),
            "positive_minutes_count": sum(finite(row.get("minutes")) > 0 for row in prior_players),
        },
        "id_join": {
            "matched_current_players": len(matched_ids),
            "match_rate_pct": round(100 * len(matched_ids) / len(roster_by_id), 3) if roster_by_id else None,
            "teams_with_positive_returning_minutes": sum(value > 0 for value in returning_minutes_by_team.values()),
            "teams_with_positive_incoming_transfer_minutes": sum(value > 0 for value in incoming_minutes_by_team.values()),
            "matched_incoming_players_with_prior_minutes": matched_transfer_players,
            "median_returning_minutes_pct": round(median_returning, 3) if median_returning is not None else None,
        },
        "recruiting": {
            "player_count": len(recruits),
            "player_athlete_id_count": len(recruit_ids),
            "players_matched_to_current_roster": len(recruit_ids & set(roster_by_id)),
            "committed_team_count": len(recruit_teams),
            "team_ranking_count": len(team_recruiting),
        },
        "portal": {
            str(recruiting_year): portal_summary(portal_primary),
            str(recruiting_year + 1): portal_summary(portal_next),
        },
        "readiness": {
            "roster_team_coverage_ok": len(roster_team_ids) >= 300,
            "roster_depth_plausible": len(roster_players) >= len(roster_team_ids) * 10 if roster_team_ids else False,
            "returning_minutes_usable": sum(value > 0 for value in returning_minutes_by_team.values()) >= 300,
            "incoming_transfer_minutes_usable": sum(value > 0 for value in incoming_minutes_by_team.values()) >= 100,
            "recruiting_coverage_usable": len(recruit_teams) >= 100,
        },
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2027)
    parser.add_argument("--prior-season", type=int, default=2026)
    parser.add_argument("--recruiting-year", type=int, default=2026)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    api_key = clean_key(os.environ.get("CBBD_API_KEY"))
    if not api_key:
        raise SystemExit("CBBD_API_KEY is required")
    report = build_audit(
        args.season,
        args.prior_season,
        args.recruiting_year,
        lambda path, params: fetch_json(path, params, api_key),
    )
    atomic_write(args.output, report)
    print(json.dumps({"readiness": report["readiness"], "id_join": report["id_join"]}, indent=2))


if __name__ == "__main__":
    main()
