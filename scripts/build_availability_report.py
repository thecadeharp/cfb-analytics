#!/usr/bin/env python3
"""Build a fresh display-only player availability snapshot from ESPN listings."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_PATH = ROOT / "data" / "external_ratings.json"
OUTPUT_PATH = ROOT / "data" / "roster_notes.json"
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/injuries"
MAX_AGE = timedelta(days=7)


def utc_now():
    return datetime.now(timezone.utc)


def parse_utc(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def https_link(links):
    for link in links or []:
        href = str(link.get("href") or "")
        rel = set(link.get("rel") or [])
        if href.startswith("https://") and ("playercard" in rel or "athlete" in rel):
            return href
    return None


def team_map():
    payload = json.loads(EXTERNAL_PATH.read_text(encoding="utf-8"))
    return {
        str(row.get("team_id")): team
        for team, row in (payload.get("teams") or {}).items()
        if row.get("team_id") is not None
    }


def main():
    now = utc_now()
    existing = json.loads(OUTPUT_PATH.read_text(encoding="utf-8")) if OUTPUT_PATH.exists() else {}
    response = requests.get(
        ESPN_URL,
        headers={"User-Agent": "THI-Availability-Report/1.0"},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    id_to_team = team_map()
    teams = {}
    retained_manual = 0
    for team_name, notes in (existing.get("teams") or {}).items():
        current = []
        for note in notes or []:
            expires = parse_utc(note.get("valid_until_utc"))
            if str(note.get("source_label") or "").upper() == "ESPN" or expires is None or expires <= now:
                continue
            current.append(note)
        if current:
            teams[team_name] = current
            retained_manual += len(current)

    espn_note_count = 0

    for group in payload.get("injuries") or []:
        team_name = id_to_team.get(str(group.get("id") or ""))
        if not team_name:
            continue
        notes = []
        for item in group.get("injuries") or []:
            updated = parse_utc(item.get("date"))
            if updated is None or updated > now + timedelta(minutes=10) or now - updated > MAX_AGE:
                continue
            athlete = item.get("athlete") or {}
            player = str(athlete.get("displayName") or "").strip()
            status = str(item.get("status") or item.get("type", {}).get("description") or "Update").strip()
            source_url = https_link(athlete.get("links"))
            if not player or not source_url:
                continue
            position = str((athlete.get("position") or {}).get("abbreviation") or "").strip()
            valid_until = min(updated + MAX_AGE, now + MAX_AGE)
            notes.append({
                "player": player,
                "position": position or None,
                "status": status,
                "text": f"{player} is listed {status.lower()} in ESPN's college football availability feed.",
                "source_label": "ESPN",
                "source_url": source_url,
                "verified_at_utc": updated.isoformat().replace("+00:00", "Z"),
                "valid_until_utc": valid_until.isoformat().replace("+00:00", "Z"),
            })
        if notes:
            notes.sort(key=lambda row: (row["status"], row["position"] or "", row["player"]))
            teams.setdefault(team_name, []).extend(notes)
            espn_note_count += len(notes)

    output = {
        "meta": {
            "season": int(os.environ.get("SEASON_YEAR", "2026")),
            "schema_version": "1.1",
            "generated_at_utc": now.isoformat().replace("+00:00", "Z"),
            "purpose": "Fresh, source-linked player availability context. Display only; never used by Model A.",
            "notes_policy": "Only ESPN records updated within seven days are retained. Empty or expired notes imply unknown status, not full availability.",
            "model_usage": "display_only_not_used_by_model_a",
            "team_count_with_current_notes": len(teams),
            "current_note_count": sum(len(notes) for notes in teams.values()),
            "espn_current_note_count": espn_note_count,
            "retained_manual_note_count": retained_manual,
        },
        "conference_sources": existing.get("conference_sources") or {},
        "teams": teams,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=OUTPUT_PATH.parent, delete=False, encoding="utf-8") as handle:
        json.dump(output, handle, indent=2, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(OUTPUT_PATH)
    print(f"Availability snapshot: {output['meta']['current_note_count']} current notes across {len(teams)} teams")


if __name__ == "__main__":
    main()
