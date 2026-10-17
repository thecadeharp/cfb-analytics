#!/usr/bin/env python3
"""Build the current CFB player-availability snapshot from public sources."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import requests
except ModuleNotFoundError:  # Unit tests exercise pure payload normalization.
    requests = None

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_PATH = ROOT / "data" / "external_ratings.json"
OUTPUT_PATH = ROOT / "data" / "roster_notes.json"
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/injuries"
HDI_URL = "https://app.hdintelligence.com/api/get-publish-public"
PAC12_URL = "https://sbcautostorage.blob.core.windows.net/availability-reports/pac12-football/prod/report.json"
MAX_AGE = timedelta(days=7)
MAX_ABS_SCENARIO_POINTS = 10.0
PLAYER_PATTERN = re.compile(r"^(?P<position>[A-Z0-9/.-]+)\s+#(?P<number>\d+)\s+(?P<player>.+)$")
TIME_ZONES = {"ET": "America/New_York", "CT": "America/Chicago", "MT": "America/Denver", "PT": "America/Los_Angeles"}

OFFICIAL_SOURCES = {
    "ACC": {"kind": "hdi", "organization": "ACC", "conference": "ACC", "url": "https://theacc.com/sports/2025/8/28/availability-reporting-football.aspx"},
    "Big Ten": {"kind": "hdi", "organization": "B10", "conference": "B10", "url": "https://bigten.org/fb/availability-reports/"},
    "Big 12": {"kind": "hdi", "organization": "B12", "conference": "B12", "url": "https://big12sports.com/sports/2025/8/14/FBreporting.aspx"},
    "SEC": {"kind": "hdi", "organization": "SEC", "conference": "SEC", "url": "https://www.secsports.com/fbreports"},
    "Pac-12": {"kind": "pac12", "url": "https://pac-12.com/news/2026/9/11/2026-football-reports.aspx"},
}


def utc_now():
    return datetime.now(timezone.utc)


def iso_utc(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
    return {str(row.get("team_id")): team for team, row in (payload.get("teams") or {}).items() if row.get("team_id") is not None}


def valid_until(verified, game_date=None):
    expiry = verified + MAX_AGE
    if game_date:
        # Noon UTC the next day covers late-night West Coast games while still
        # removing the report promptly after the matchup is complete.
        expiry = min(expiry, datetime.combine(game_date + timedelta(days=1), time(12), timezone.utc))
    return expiry


def is_material_status(position, status):
    """Withhold public signals for uncertain or unavailable quarterbacks only."""
    positions = str(position or "").upper().split("/")
    normalized_status = str(status or "").lower()
    return "QB" in positions and any(token in normalized_status for token in ("out", "doubtful", "questionable", "game time decision"))


def parse_player_label(value):
    label = " ".join(str(value or "").split())
    match = PLAYER_PATTERN.match(label)
    if not match:
        return None, None, label
    return match.group("position"), match.group("number"), match.group("player").strip()


def local_report_time(report):
    try:
        day = date.fromisoformat(str(report.get("publishDate")))
        clock = time.fromisoformat(str(report.get("postedTime")))
    except (TypeError, ValueError):
        return None
    zone = ZoneInfo(TIME_ZONES.get(str(report.get("conferenceTimeZone") or "CT"), "America/Chicago"))
    return datetime.combine(day, clock, zone).astimezone(timezone.utc)


def report_game_date(report):
    try:
        return date.fromisoformat(str((report.get("footer") or {}).get("date")))
    except (TypeError, ValueError):
        return None


def official_note(*, conference, source_url, opponent, player, position, number, status, verified, game_date, report_type, report_id):
    hold = is_material_status(position, status)
    return {
        "player": player,
        "position": position or None,
        "jersey_number": number or None,
        "status": status,
        "text": f"{player} is listed {status.lower()} on the official {conference} availability report.",
        "source_type": "official_conference",
        "source_conference": conference,
        "source_label": f"Official {conference} availability report",
        "source_url": source_url,
        "verified_at_utc": iso_utc(verified),
        "valid_until_utc": iso_utc(valid_until(verified, game_date)),
        "opponent": opponent or None,
        "report_type": report_type or None,
        "official_report_id": str(report_id) if report_id is not None else None,
        "withhold_public_signal": hold,
        "market_context_relevant": hold,
    }


def parse_hdi_payload(payload, conference, source, now):
    notes, reports = {}, []
    for report_id, report in (payload or {}).items():
        if not isinstance(report, dict):
            continue
        verified = local_report_time(report)
        if verified is None or verified > now + timedelta(minutes=10) or now - verified > MAX_AGE:
            continue
        game_date = report_game_date(report)
        team_rows = report.get("games") or []
        names = [str(team.get("teamDisplayName") or team.get("teamName") or "").strip() for team in team_rows]
        report_note_count = 0
        for index, team in enumerate(team_rows):
            team_name = names[index]
            if not team_name:
                continue
            opponent = next((name for offset, name in enumerate(names) if offset != index and name), None)
            for row in team.get("rows") or []:
                status = " ".join(str(row.get("status") or "").split())
                exempt = " ".join(str(row.get("exemptStatus") or "").split())
                if not status or status.lower() in {"available", "exempt"} or exempt.lower() == "exempt":
                    continue
                position, number, player = parse_player_label(row.get("name"))
                if not player:
                    continue
                notes.setdefault(team_name, []).append(official_note(
                    conference=conference, source_url=source["url"], opponent=opponent,
                    player=player, position=position, number=number, status=status,
                    verified=verified, game_date=game_date, report_type=report.get("ReportType"), report_id=report_id,
                ))
                report_note_count += 1
        reports.append({
            "report_id": str(report_id), "verified_at_utc": iso_utc(verified),
            "game_date": game_date.isoformat() if game_date else None,
            "report_type": report.get("ReportType"), "teams": names,
            "listed_player_count": report_note_count,
        })
    return notes, reports


def parse_pac12_payload(payload, conference, source, now):
    notes, reports = {}, []
    for game in (payload or {}).get("games") or []:
        verified = parse_utc(game.get("updatedAtUTC"))
        if verified is None or verified > now + timedelta(minutes=10) or now - verified > MAX_AGE:
            continue
        try:
            game_date = date.fromisoformat(str(game.get("dateISO")))
        except (TypeError, ValueError):
            game_date = None
        sides = [game.get("away") or {}, game.get("home") or {}]
        names = [str(side.get("name") or "").strip() for side in sides]
        report_note_count = 0
        for index, side in enumerate(sides):
            team_name = names[index]
            if not team_name:
                continue
            opponent = names[1 - index] if len(names) == 2 else None
            for row in side.get("players") or []:
                status = " ".join(str(row.get("status") or "").split())
                player = " ".join(str(row.get("name") or "").split())
                position = " ".join(str(row.get("position") or "").split())
                if not player or not status or status.lower() in {"available", "exempt"}:
                    continue
                notes.setdefault(team_name, []).append(official_note(
                    conference=conference, source_url=source["url"], opponent=opponent,
                    player=player, position=position, number=None, status=status,
                    verified=verified, game_date=game_date, report_type=game.get("notes"), report_id=game.get("gameId"),
                ))
                report_note_count += 1
        reports.append({
            "report_id": str(game.get("gameId") or ""), "verified_at_utc": iso_utc(verified),
            "game_date": game_date.isoformat() if game_date else None,
            "report_type": game.get("notes"), "teams": names,
            "listed_player_count": report_note_count,
        })
    return notes, reports


def fetch_official_source(session, conference, source, now):
    if source["kind"] == "hdi":
        response = session.post(HDI_URL, json={"sport": "Football", "organization": source["organization"], "conference": source["conference"]}, timeout=60)
        response.raise_for_status()
        return parse_hdi_payload(response.json(), conference, source, now)
    response = session.get(PAC12_URL, timeout=60)
    response.raise_for_status()
    return parse_pac12_payload(response.json(), conference, source, now)


def retain_existing_notes(existing, now):
    manual, official = {}, {}
    retained_manual = 0
    for team_name, notes in (existing.get("teams") or {}).items():
        for original in notes or []:
            note = dict(original)
            expires = parse_utc(note.get("valid_until_utc"))
            if expires is None or expires <= now:
                continue
            source_type = str(note.get("source_type") or "")
            source_label = str(note.get("source_label") or "")
            if source_type == "espn" or source_label.upper() == "ESPN":
                continue
            if source_type == "official_conference":
                conference = str(note.get("source_conference") or "")
                if conference:
                    official.setdefault(conference, {}).setdefault(team_name, []).append(note)
                continue
            adjustment = note.get("availability_adjustment_points")
            if adjustment is not None:
                try:
                    adjustment = float(adjustment)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(adjustment) or abs(adjustment) > MAX_ABS_SCENARIO_POINTS:
                    continue
                note["availability_adjustment_points"] = round(adjustment, 1)
            manual.setdefault(team_name, []).append(note)
            retained_manual += 1
    return manual, official, retained_manual


def collect_espn(session, now):
    response = session.get(ESPN_URL, timeout=60)
    response.raise_for_status()
    payload, id_to_team, teams = response.json(), team_map(), {}
    for group in payload.get("injuries") or []:
        team_name = id_to_team.get(str(group.get("id") or ""))
        if not team_name:
            continue
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
            hold = is_material_status(position, status)
            teams.setdefault(team_name, []).append({
                "player": player, "position": position or None, "status": status,
                "text": f"{player} is listed {status.lower()} in ESPN's college football availability feed.",
                "source_type": "espn", "source_label": "ESPN", "source_url": source_url,
                "verified_at_utc": iso_utc(updated), "valid_until_utc": iso_utc(valid_until(updated)),
                "withhold_public_signal": hold, "market_context_relevant": hold,
            })
    return teams


def merge_notes(target, incoming):
    for team_name, notes in incoming.items():
        target.setdefault(team_name, []).extend(notes)


def deduplicate_and_sort(teams):
    result = {}
    source_priority = {"official_conference": 0, "manual": 1, "espn": 2}
    for team_name, notes in teams.items():
        ordered = sorted(notes, key=lambda note: (
            source_priority.get(str(note.get("source_type") or "manual"), 1),
            str(note.get("player") or "").lower(), str(note.get("status") or "").lower(),
        ))
        seen, kept = set(), []
        for note in ordered:
            key = (str(note.get("player") or "").casefold(), str(note.get("status") or "").casefold())
            if key in seen:
                continue
            seen.add(key)
            kept.append(note)
        if kept:
            result[team_name] = kept
    return result


def main():
    if requests is None:
        raise RuntimeError("requests is required to collect live availability reports")
    now = utc_now()
    existing = json.loads(OUTPUT_PATH.read_text(encoding="utf-8")) if OUTPUT_PATH.exists() else {}
    teams, previous_official, retained_manual = retain_existing_notes(existing, now)
    session = requests.Session()
    session.headers.update({"User-Agent": "THI-Availability-Report/2.0"})
    source_health, official_report_count, official_note_count = {}, 0, 0
    for conference, source in OFFICIAL_SOURCES.items():
        try:
            conference_notes, reports = fetch_official_source(session, conference, source, now)
            merge_notes(teams, conference_notes)
            count = sum(len(rows) for rows in conference_notes.values())
            official_note_count += count
            official_report_count += len(reports)
            source_health[conference] = {
                "status": "ok", "checked_at_utc": iso_utc(now), "report_count": len(reports),
                "listed_player_count": count,
                "latest_report_utc": max((row["verified_at_utc"] for row in reports), default=None),
            }
        except (requests.RequestException, ValueError, TypeError, KeyError) as error:
            fallback = previous_official.get(conference, {})
            merge_notes(teams, fallback)
            fallback_count = sum(len(rows) for rows in fallback.values())
            official_note_count += fallback_count
            source_health[conference] = {
                "status": "stale_fallback" if fallback_count else "error",
                "checked_at_utc": iso_utc(now), "retained_player_count": fallback_count,
                "error": f"{type(error).__name__}: {error}"[:300],
            }
    try:
        espn_teams = collect_espn(session, now)
        merge_notes(teams, espn_teams)
        espn_note_count = sum(len(rows) for rows in espn_teams.values())
        source_health["ESPN"] = {"status": "ok", "checked_at_utc": iso_utc(now), "listed_player_count": espn_note_count}
    except (requests.RequestException, ValueError, TypeError, KeyError) as error:
        espn_note_count = 0
        source_health["ESPN"] = {"status": "error", "checked_at_utc": iso_utc(now), "error": f"{type(error).__name__}: {error}"[:300]}

    teams = deduplicate_and_sort(teams)
    output = {
        "meta": {
            "season": int(os.environ.get("SEASON_YEAR", "2026")), "schema_version": "2.0",
            "generated_at_utc": iso_utc(now),
            "purpose": "Fresh, source-linked player availability context. Official statuses can hold public signals; they never alter Model A automatically.",
            "notes_policy": "Official ACC, Big Ten, Big 12, SEC and Pac-12 reports are ingested when published. A failed source retains its last still-valid official snapshot. Empty status remains unknown, not healthy.",
            "model_usage": "display_and_signal_hold_not_used_by_model_a",
            "adjustment_policy": "No automated source is assigned a point value. Current official or ESPN QB Out, Doubtful, Questionable, or Game Time Decision statuses withhold the public signal pending resolution.",
            "team_count_with_current_notes": len(teams), "current_note_count": sum(len(notes) for notes in teams.values()),
            "official_report_count": official_report_count, "official_current_note_count": official_note_count,
            "espn_current_note_count": espn_note_count, "retained_manual_note_count": retained_manual,
            "source_health": source_health,
        },
        "conference_sources": {conference: {"url": source["url"]} for conference, source in OFFICIAL_SOURCES.items()},
        "teams": teams,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=OUTPUT_PATH.parent, delete=False, encoding="utf-8") as handle:
        json.dump(output, handle, indent=2, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(OUTPUT_PATH)
    print(f"Availability snapshot: {output['meta']['current_note_count']} current notes across {len(teams)} teams; {official_report_count} official reports")


if __name__ == "__main__":
    main()
