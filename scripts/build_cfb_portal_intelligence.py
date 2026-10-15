#!/usr/bin/env python3
"""Build verified, display-only CFB portal and JUCO intelligence."""
from __future__ import annotations

import json
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "portal_2026.json"
PORTAL_API = "https://api.collegefootballdata.com/player/portal"
RECRUITING_API = "https://api.collegefootballdata.com/recruiting/players"
SEASON = int(os.environ.get("SEASON_YEAR", "2026"))
OFFENSE = {"QB", "RB", "FB", "WR", "TE", "OT", "OG", "C", "OL", "IOL"}
DEFENSE = {"DL", "DE", "DT", "EDGE", "LB", "ILB", "OLB", "CB", "DB", "S", "ATH"}


def finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def school(value):
    if isinstance(value, dict):
        return str(value.get("school") or value.get("name") or value.get("team") or "").strip()
    return str(value or "").strip()


def side(position):
    position = str(position or "").upper().strip()
    if position in OFFENSE:
        return "offense"
    if position in DEFENSE:
        return "defense"
    return "specialists"


def rating_score(value):
    """Return one consistent 0–100 display scale for CFBD ratings."""
    rating = finite(value)
    if rating is None:
        return None
    score = rating * 100 if abs(rating) <= 1.5 else rating
    return round(score, 1)


def summarize_unit(players):
    scores = [player["rating_score"] for player in players if player["rating_score"] is not None]
    ordered = sorted(scores, reverse=True)
    return {
        "count": len(players),
        "rated_count": len(scores),
        "avg_rating": round(sum(scores) / len(scores), 1) if scores else None,
        "top3_avg": round(sum(ordered[:3]) / min(3, len(ordered)), 1) if ordered else None,
        "quality_points": round(sum(max(score - 80, 0) for score in scores), 1),
    }


def build_payload(base, raw_portal, raw_juco=None):
    players = []
    aggregates = defaultdict(lambda: {"offense": [], "defense": [], "specialists": []})
    for row in raw_portal:
        destination = school(row.get("destination"))
        origin = school(row.get("origin"))
        if not destination:
            continue
        position = str(row.get("position") or "").upper().strip() or "—"
        raw_rating = finite(row.get("rating"))
        group = side(position)
        origin_type = " ".join(
            str(row.get(key) or "")
            for key in ("originClassification", "origin_classification", "classification")
        )
        explicit_juco = any(
            token in origin_type.casefold()
            for token in ("juco", "junior college", "community college", "njcaa")
        )
        player = {
            "name": " ".join(part for part in (row.get("firstName"), row.get("lastName")) if part).strip()
            or str(row.get("name") or "Unknown"),
            "position": position,
            "side": group,
            "origin": origin or "Unknown",
            "destination": destination,
            "rating": round(raw_rating, 4) if raw_rating is not None else None,
            "rating_score": rating_score(raw_rating),
            "stars": row.get("stars"),
            "juco": explicit_juco,
            "transfer_date": row.get("transferDate") or row.get("transfer_date"),
        }
        players.append(player)
        aggregates[destination][group].append(player)

    impact = []
    for team, groups in aggregates.items():
        item = {"team": team}
        for group in ("offense", "defense", "specialists"):
            item[group] = summarize_unit(groups[group])
        item["combined_quality_points"] = round(
            item["offense"]["quality_points"] + item["defense"]["quality_points"], 1
        )
        impact.append(item)
    impact.sort(key=lambda row: (-row["combined_quality_points"], row["team"]))

    juco = []
    for row in raw_juco or []:
        destination = school(row.get("committedTo") or row.get("committed_to"))
        if not destination:
            continue
        raw_rating = finite(row.get("rating"))
        juco.append({
            "id": row.get("id"),
            "athlete_id": row.get("athleteId") or row.get("athlete_id"),
            "name": str(row.get("name") or "Unknown").strip(),
            "position": str(row.get("position") or "—").upper().strip(),
            "origin": school(row.get("school")) or "Unknown JUCO",
            "destination": destination,
            "rank": row.get("ranking"),
            "stars": row.get("stars"),
            "rating": round(raw_rating, 4) if raw_rating is not None else None,
            "rating_score": rating_score(raw_rating),
            "recruit_type": "JUCO",
        })
    juco.sort(key=lambda row: (row["rank"] is None, row["rank"] or 99999, -(row["rating_score"] or 0), row["name"]))

    teams = list(base.get("teams") or [])
    conference_groups = defaultdict(list)
    for team in teams:
        conference_groups[str(team.get("conference") or "Independent")].append(team)
    conference_summary = []
    for conference, members in conference_groups.items():
        ordered = sorted(members, key=lambda row: (-(finite(row.get("portal_index")) or 0), row.get("team") or ""))
        indexes = [finite(row.get("portal_index")) for row in members]
        incoming = [finite(row.get("in_avg_rating")) for row in members]
        valid_indexes = [value for value in indexes if value is not None]
        valid_incoming = [value for value in incoming if value is not None]
        conference_summary.append({
            "conference": conference,
            "team_count": len(members),
            "in_count": sum(int(row.get("in_count") or 0) for row in members),
            "out_count": sum(int(row.get("out_count") or 0) for row in members),
            "avg_portal_index": round(sum(valid_indexes) / len(valid_indexes), 1) if valid_indexes else None,
            "avg_in_rating": round(sum(valid_incoming) / len(valid_incoming), 1) if valid_incoming else None,
            "leader": ordered[0].get("team") if ordered else None,
        })
    conference_summary.sort(key=lambda row: (-(row["avg_portal_index"] or 0), row["conference"]))

    result = dict(base)
    result["schema_version"] = "2.0"
    result["players"] = sorted(
        players,
        key=lambda row: (row["destination"], row["side"], -(row["rating_score"] or 0), row["name"]),
    )
    result["juco"] = juco
    result["conference_summary"] = conference_summary
    result["position_impact"] = impact
    result["player_source"] = {
        "name": "CollegeFootballData transfer portal and recruiting",
        "url": "https://collegefootballdata.com/",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_usage": "display_only_not_used_by_model_a",
        "rating_scale": "CFBD ratings normalized to 0–100 for display",
    }
    result["data_health"] = {
        "portal_players": len(players),
        "rated_portal_players": sum(player["rating_score"] is not None for player in players),
        "destinations": len(aggregates),
        "juco_recruits": len(juco),
        "ranked_teams": len(teams),
    }
    return result


def fetch_json(session, url, params, key):
    response = session.get(
        url,
        params=params,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        timeout=(10, 90),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError(f"{url} returned an invalid payload")
    return payload


def main():
    import requests

    key = os.environ.get("CFBD_API_KEY", "").strip()
    if not key:
        raise SystemExit("CFBD_API_KEY is required")
    session = requests.Session()
    raw_portal = fetch_json(session, PORTAL_API, {"year": SEASON}, key)
    raw_juco = fetch_json(session, RECRUITING_API, {"year": SEASON, "classification": "JUCO"}, key)
    if len(raw_portal) < 100:
        raise RuntimeError(f"Portal response is unexpectedly sparse: {len(raw_portal)}")
    if not raw_juco:
        raise RuntimeError("JUCO recruiting response is empty; refusing to publish an unfinished tab")
    base = json.loads(OUTPUT.read_text(encoding="utf-8"))
    payload = build_payload(base, raw_portal, raw_juco)
    with tempfile.NamedTemporaryFile("w", dir=OUTPUT.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(OUTPUT)
    print(
        f"CFB portal intelligence: {len(payload['players'])} portal players; "
        f"{len(payload['juco'])} verified JUCO recruits; "
        f"{len(payload['position_impact'])} destinations"
    )


if __name__ == "__main__":
    main()
