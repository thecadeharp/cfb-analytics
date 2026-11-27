#!/usr/bin/env python3
"""Validate the source-linked, display-only CFB postseason availability file."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "postseason_availability.json"
ALLOWED_CATEGORIES = {
    "injury_out",
    "opt_out",
    "portal_departure",
    "suspension",
    "questionable",
    "available",
}
ALLOWED_CERTAINTY = {"confirmed", "developing", "unstable"}


def parse_timestamp(value):
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate(payload):
    errors = []
    meta = payload.get("meta") or {}
    if meta.get("model_usage") != "traditional_bowl_display_and_research_scenario_only":
        errors.append("meta.model_usage must preserve the display/research-only contract")

    for game_id, game in (payload.get("games") or {}).items():
        if not str(game_id).strip():
            errors.append("postseason availability contains an empty game id")
        teams = game.get("teams") or {}
        if len(teams) != 2:
            errors.append(f"{game_id}: exactly two teams are required")
        for team_name, team in teams.items():
            certainty = str(team.get("certainty") or "developing").lower()
            if certainty not in ALLOWED_CERTAINTY:
                errors.append(f"{game_id}/{team_name}: invalid certainty {certainty}")
            for source in team.get("sources") or []:
                if not str(source.get("url") or "").startswith("https://"):
                    errors.append(f"{game_id}/{team_name}: source URL must use https")
            for player in team.get("players") or []:
                label = f"{game_id}/{team_name}/{player.get('player') or 'unknown player'}"
                if str(player.get("category") or "").lower() not in ALLOWED_CATEGORIES:
                    errors.append(f"{label}: invalid player category")
                if not str(player.get("source_url") or "").startswith("https://"):
                    errors.append(f"{label}: source_url must use https")
                try:
                    parse_timestamp(player.get("verified_at_utc"))
                except (TypeError, ValueError):
                    errors.append(f"{label}: verified_at_utc must be an ISO timestamp")
                if "availability_adjustment_points" in player:
                    errors.append(f"{label}: manual point adjustments are prohibited")
            for note in team.get("staff_notes") or []:
                if not str(note.get("source_url") or "").startswith("https://"):
                    errors.append(f"{game_id}/{team_name}: staff note source must use https")
                if any(key in note for key in ("points", "adjustment", "availability_adjustment_points")):
                    errors.append(f"{game_id}/{team_name}: staff context must remain unpriced")
    return errors


def main():
    payload = json.loads(PATH.read_text(encoding="utf-8"))
    errors = validate(payload)
    if errors:
        raise SystemExit("\n".join(f"- {error}" for error in errors))
    print(f"Validated postseason availability registry: {len(payload.get('games') or {})} games")


if __name__ == "__main__":
    main()
