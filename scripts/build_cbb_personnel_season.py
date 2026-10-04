#!/usr/bin/env python3
"""Build aggregate CBB recruiting and transfer features for one season."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.verify_cbb_api_foundation import clean_key, fetch_json
except ModuleNotFoundError:
    from verify_cbb_api_foundation import clean_key, fetch_json


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "cbb" / "personnel"
VERSION = "cbb-personnel-features-v1.0"


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def require_list(name: str, payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise RuntimeError(f"{name} returned {type(payload).__name__}; expected list")
    return [row for row in payload if isinstance(row, dict)]


def team_directory(season: int, history_dir: Path, profile_path: Path) -> list[dict[str, Any]]:
    history_path = history_dir / f"season_{season}.json.gz"
    if history_path.exists():
        with gzip.open(history_path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        return [
            {"team_id": row.get("team_id"), "team": row.get("team")}
            for row in payload.get("season_end_teams") or []
        ]
    if profile_path.exists():
        payload = json.loads(profile_path.read_text())
        if int(payload.get("meta", {}).get("season") or 0) == season:
            return [
                {"team_id": row.get("team_id"), "team": row.get("team")}
                for row in payload.get("teams") or []
            ]
    raise RuntimeError(f"no local team directory for season {season}")


def mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 6) if values else None


def build_season(
    season: int,
    teams: list[dict[str, Any]],
    fetcher: Callable[[str, dict[str, Any]], Any],
) -> dict[str, Any]:
    personnel_year = season - 1
    prior_season = season - 1
    recruits = require_list("recruits", fetcher("/recruiting/players", {"year": personnel_year}))
    team_rankings = require_list("team recruiting", fetcher("/recruiting/teams", {"year": personnel_year}))
    portal = require_list("portal", fetcher("/recruiting/portal", {"year": personnel_year}))
    prior_players = require_list("prior player stats", fetcher("/stats/player/season", {"season": prior_season}))

    output: dict[str, dict[str, Any]] = {}
    for team in teams:
        team_id = str(team.get("team_id"))
        output[team_id] = {
            "team_id": team.get("team_id"),
            "team": team.get("team"),
            "recruiting": {
                "class_player_count": 0,
                "rated_player_count": 0,
                "mean_player_rating": None,
                "top_player_rating": None,
                "four_star_count": 0,
                "five_star_count": 0,
                "team_rank": None,
                "team_rating": None,
            },
            "transfers": {
                "incoming_count": 0,
                "rated_incoming_count": 0,
                "mean_incoming_rating": None,
                "top_incoming_rating": None,
                "prior_production_match_count": 0,
                "prior_minutes": 0.0,
                "prior_points": 0.0,
                "prior_usage_mass": 0.0,
            },
        }

    recruit_ratings: dict[str, list[float]] = {}
    for row in recruits:
        destination = row.get("committedTo") or {}
        team_id = str(destination.get("id"))
        if team_id not in output:
            continue
        block = output[team_id]["recruiting"]
        block["class_player_count"] += 1
        rating = finite(row.get("rating"))
        if rating is not None:
            recruit_ratings.setdefault(team_id, []).append(rating)
            block["rated_player_count"] += 1
        stars = int(finite(row.get("stars")) or 0)
        block["four_star_count"] += stars == 4
        block["five_star_count"] += stars >= 5

    for row in team_rankings:
        team_id = str(row.get("teamId"))
        if team_id in output:
            output[team_id]["recruiting"]["team_rank"] = row.get("ranking")
            output[team_id]["recruiting"]["team_rating"] = finite(row.get("rating"))

    prior_by_id_name: dict[tuple[str, str], dict[str, Any]] = {}
    prior_by_team_name: dict[tuple[str, str], dict[str, Any]] = {}
    for row in prior_players:
        name = normalized(row.get("name"))
        if not name:
            continue
        prior_by_id_name[(str(row.get("teamId")), name)] = row
        prior_by_team_name[(normalized(row.get("team")), name)] = row

    transfer_ratings: dict[str, list[float]] = {}
    for row in portal:
        destination = row.get("destination") or {}
        origin = row.get("origin") or {}
        destination_id = str(destination.get("id"))
        if destination_id not in output:
            continue
        block = output[destination_id]["transfers"]
        block["incoming_count"] += 1
        rating = finite(row.get("rating"))
        if rating is not None:
            transfer_ratings.setdefault(destination_id, []).append(rating)
            block["rated_incoming_count"] += 1
        name = normalized(f"{row.get('firstName') or ''} {row.get('lastName') or ''}")
        prior = prior_by_id_name.get((str(origin.get("id")), name))
        if prior is None:
            prior = prior_by_team_name.get((normalized(origin.get("name")), name))
        if prior is not None:
            minutes = finite(prior.get("minutes")) or 0.0
            points = finite(prior.get("points")) or 0.0
            usage = finite(prior.get("usage")) or 0.0
            block["prior_production_match_count"] += 1
            block["prior_minutes"] += minutes
            block["prior_points"] += points
            block["prior_usage_mass"] += minutes * usage

    for team_id, row in output.items():
        recruiting = row["recruiting"]
        ratings = recruit_ratings.get(team_id, [])
        recruiting["mean_player_rating"] = mean(ratings)
        recruiting["top_player_rating"] = round(max(ratings), 6) if ratings else None
        transfers = row["transfers"]
        ratings = transfer_ratings.get(team_id, [])
        transfers["mean_incoming_rating"] = mean(ratings)
        transfers["top_incoming_rating"] = round(max(ratings), 6) if ratings else None
        for key in ("prior_minutes", "prior_points", "prior_usage_mass"):
            transfers[key] = round(transfers[key], 3)

    rows = sorted(output.values(), key=lambda row: str(row.get("team") or ""))
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "season": season,
            "personnel_year": personnel_year,
            "prior_season": prior_season,
            "request_count": 4,
            "team_count": len(rows),
            "raw_api_data_stored": False,
            "returning_production_status": "unavailable_until_current_rosters_are_populated",
            "source_attribution": "Data provided by CollegeBasketballData.com; aggregate features by The Hammer Index.",
        },
        "coverage": {
            "recruit_records": len(recruits),
            "team_recruiting_records": len(team_rankings),
            "portal_records": len(portal),
            "prior_player_records": len(prior_players),
            "teams_with_recruits": sum(row["recruiting"]["class_player_count"] > 0 for row in rows),
            "teams_with_incoming_transfers": sum(row["transfers"]["incoming_count"] > 0 for row in rows),
            "teams_with_matched_transfer_production": sum(row["transfers"]["prior_production_match_count"] > 0 for row in rows),
        },
        "teams": rows,
    }


def atomic_gzip(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n").encode()
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    with temporary.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
        zipped.write(encoded)
    temporary.replace(path)


def rebuild_manifest(output_dir: Path) -> None:
    seasons = []
    for path in sorted(output_dir.glob("season_*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        seasons.append({
            "season": payload["meta"]["season"],
            "file": path.name,
            "team_count": payload["meta"]["team_count"],
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        })
    manifest = {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "season_count": len(seasons),
        },
        "seasons": seasons,
    }
    target = output_dir / "manifest.json"
    target.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--history-dir", type=Path, default=ROOT / "data" / "cbb" / "history")
    parser.add_argument("--team-profiles", type=Path, default=ROOT / "data" / "cbb" / "team_profiles.json")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    api_key = clean_key(os.environ.get("CBBD_API_KEY"))
    if not api_key:
        raise SystemExit("CBBD_API_KEY is required")
    teams = team_directory(args.season, args.history_dir, args.team_profiles)
    payload = build_season(args.season, teams, lambda path, params: fetch_json(path, params, api_key))
    atomic_gzip(args.output_dir / f"season_{args.season}.json.gz", payload)
    rebuild_manifest(args.output_dir)
    print(f"CBB personnel {args.season}: {payload['meta']['team_count']} teams; {payload['coverage']}")


if __name__ == "__main__":
    main()
