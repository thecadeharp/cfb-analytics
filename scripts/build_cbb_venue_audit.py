#!/usr/bin/env python3
"""Resolve official CBB venue overrides and publish a neutral-floor audit."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-venue-audit-v1.0"


def apply_overrides(board: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    rows = (overrides or {}).get("games") or {}
    output = {**board, "games": []}
    for source in board.get("games") or []:
        game = dict(source)
        override = rows.get(str(game.get("game_id")))
        if override:
            if "neutral_site" in override:
                game["neutral_site"] = bool(override["neutral_site"])
            if override.get("venue"):
                game["venue"] = dict(override["venue"])
            game["venue_verification"] = {
                "state": override.get("verification") or "manual_override",
                "source_url": override.get("source_url"),
            }
        output["games"].append(game)
    return output


def venue_key(venue: dict[str, Any] | None) -> tuple[str, str, str]:
    venue = venue or {}
    return tuple(str(venue.get(key) or "").strip().lower() for key in ("name", "city", "state"))


def build_audit(raw: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    resolved = apply_overrides(raw, overrides)
    override_rows = (overrides or {}).get("games") or {}
    campus_counts: dict[str, Counter] = defaultdict(Counter)
    for game in raw.get("games") or []:
        if game.get("neutral_site"):
            continue
        home_id = str((game.get("home") or {}).get("team_id") or "")
        key = venue_key(game.get("venue"))
        if home_id and key[0]:
            campus_counts[home_id][key] += 1
    campuses = {team_id: counts.most_common(1)[0][0] for team_id, counts in campus_counts.items() if counts}

    raw_by_id = {str(game.get("game_id")): game for game in raw.get("games") or []}
    rows = []
    for game in resolved.get("games") or []:
        if not game.get("neutral_site"):
            continue
        game_id = str(game.get("game_id"))
        source = raw_by_id.get(game_id) or {}
        source_key = venue_key(source.get("venue"))
        participant_campus_match = []
        for side in ("away", "home"):
            team = game.get(side) or {}
            if source_key[0] and campuses.get(str(team.get("team_id"))) == source_key:
                participant_campus_match.append(team.get("team"))
        override = override_rows.get(game_id) or {}
        resolved_venue = game.get("venue") or {}
        missing = not str(resolved_venue.get("name") or "").strip() or not str(resolved_venue.get("city") or "").strip()
        if override:
            state = "official_override_applied"
        elif participant_campus_match:
            state = "provider_neutral_campus_venue_review"
        elif missing:
            state = "provider_neutral_venue_pending"
        else:
            state = "provider_neutral_flag"
        rows.append({
            "game_id": game.get("game_id"),
            "start_date": game.get("start_date"),
            "away_team": (game.get("away") or {}).get("team"),
            "home_team": (game.get("home") or {}).get("team"),
            "neutral_site": True,
            "source_venue": source.get("venue"),
            "resolved_venue": resolved_venue,
            "audit_state": state,
            "participant_campus_match": participant_campus_match,
            "verification": override.get("verification"),
            "source_url": override.get("source_url"),
            "home_court_points_required": 0.0,
        })
    counts = Counter(row["audit_state"] for row in rows)
    unresolved = counts["provider_neutral_campus_venue_review"]
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "healthy" if unresolved == 0 else "attention_required",
            "policy": "Neutral games always receive zero home-court input. Official schedules resolve provider venue conflicts; unresolved conflicts stay visible and never receive campus points.",
        },
        "summary": {
            "neutral_games": len(rows),
            "official_overrides": counts["official_override_applied"],
            "provider_neutral_flags": counts["provider_neutral_flag"],
            "provider_neutral_venue_pending": counts["provider_neutral_venue_pending"],
            "unresolved_reviews": unresolved,
        },
        "games": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=Path, default=ROOT / "data/cbb/game_board.json")
    parser.add_argument("--overrides", type=Path, default=ROOT / "data/cbb/venue_overrides.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/cbb/venue_audit.json")
    args = parser.parse_args()
    raw = json.loads(args.games.read_text())
    overrides = json.loads(args.overrides.read_text()) if args.overrides.exists() else {"games": {}}
    payload = build_audit(raw, overrides)
    args.output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(VERSION, payload["meta"]["status"], payload["summary"])
    for row in payload["games"]:
        if row["audit_state"] == "provider_neutral_campus_venue_review":
            print("UNRESOLVED_NEUTRAL_VENUE", json.dumps({
                "game_id": row["game_id"],
                "start_date": row["start_date"],
                "away_team": row["away_team"],
                "home_team": row["home_team"],
                "source_venue": row["source_venue"],
                "participant_campus_match": row["participant_campus_match"],
            }, sort_keys=True))


if __name__ == "__main__":
    main()
