#!/usr/bin/env python3
"""Build display-only ESPN rosters with optional CFBD statistical usage."""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_PATH = ROOT / "data" / "external_ratings.json"
OUTPUT_PATH = ROOT / "data" / "roster_assets.json"
ESPN_ROSTER_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/"
    "college-football/teams/{team_id}/roster"
)
CFBD_BASE = "https://api.collegefootballdata.com"
GROUPS = {"offense": "Offense", "defense": "Defense", "specialTeam": "Special Teams"}
TEAM_ALIASES = {
    "Appalachian State": "App State",
    "Connecticut": "UConn",
    "Louisiana Monroe": "UL Monroe",
    "San José State": "San Jose State",
    "Southern Mississippi": "Southern Miss",
    "UT San Antonio": "UTSA",
}


def utc_now():
    return datetime.now(timezone.utc)


def clean_key(value):
    key = str(value or "").strip().strip("'\"")
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key.replace("\r", "").replace("\n", "").replace("\t", "").strip()


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def athlete_link(links):
    for link in links or []:
        rel = set(link.get("rel") or [])
        href = str(link.get("href") or "")
        if "athlete" in rel and "playercard" in rel and href.startswith("https://"):
            return href
    return None


def fetch_roster(team, team_id, year):
    response = requests.get(
        ESPN_ROSTER_URL.format(team_id=team_id),
        headers={"User-Agent": "THI-Roster-Assets/1.0"},
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    players = []
    seen = set()
    for section in payload.get("athletes") or []:
        group_key = section.get("position")
        if group_key not in GROUPS:
            continue
        for athlete in section.get("items") or []:
            athlete_id = str(athlete.get("id") or "").strip()
            if not athlete_id or athlete_id in seen:
                continue
            seen.add(athlete_id)
            position = athlete.get("position") or {}
            experience = athlete.get("experience") or {}
            status = athlete.get("status") or {}
            headshot = athlete.get("headshot") or {}
            players.append({
                "athlete_id": athlete_id,
                "name": athlete.get("fullName") or athlete.get("displayName"),
                "jersey": athlete.get("jersey"),
                "position": position.get("abbreviation"),
                "position_name": position.get("displayName") or position.get("name"),
                "group": GROUPS[group_key],
                "class": experience.get("abbreviation"),
                "class_name": experience.get("displayValue"),
                "height_inches": number(athlete.get("height")),
                "height": athlete.get("displayHeight"),
                "weight_lbs": number(athlete.get("weight")),
                "weight": athlete.get("displayWeight"),
                "status": status.get("type") or status.get("name"),
                "headshot": headshot.get("href"),
                "profile_url": athlete_link(athlete.get("links")),
            })
    players.sort(key=lambda row: (row["group"], row.get("position") or "", row.get("name") or ""))
    season = payload.get("season") or {}
    return team, {
        "espn_team_id": int(team_id),
        "source_season": season.get("year"),
        "players": players,
    }


def cfbd_get(path, key, params=None):
    response = requests.get(
        f"{CFBD_BASE}{path}",
        params=params or {},
        headers={"Authorization": f"Bearer {key}", "User-Agent": "THI-Roster-Assets/1.0"},
        timeout=90,
    )
    response.raise_for_status()
    return response.json()


def latest_completed_week(year, key):
    now = utc_now()
    weeks = cfbd_get("/calendar", key, {"year": year})
    completed = []
    for row in weeks:
        if row.get("seasonType") != "regular":
            continue
        try:
            end = datetime.fromisoformat(str(row.get("endDate")).replace("Z", "+00:00"))
            week = int(row.get("week"))
        except (TypeError, ValueError):
            continue
        if end <= now:
            completed.append(week)
    return max(completed, default=0)


def split_fraction(value):
    raw = str(value or "").strip()
    if "/" not in raw:
        return None
    left, right = raw.split("/", 1)
    return number(left), number(right)


def add_player_stats(accumulator, payload):
    for game in payload or []:
        for team in game.get("teams") or []:
            raw_team_name = str(team.get("team") or "")
            team_name = TEAM_ALIASES.get(raw_team_name, raw_team_name)
            for category in team.get("categories") or []:
                category_name = str(category.get("name") or "").lower()
                for stat_type in category.get("types") or []:
                    stat_name = str(stat_type.get("name") or "").upper().replace(" ", "")
                    for athlete in stat_type.get("athletes") or []:
                        athlete_id = str(athlete.get("id") or "").strip()
                        if not athlete_id:
                            continue
                        stat = athlete.get("stat")
                        row = accumulator[(team_name, athlete_id)]
                        if category_name == "passing" and stat_name in {"C/ATT", "COMP/ATT"}:
                            fraction = split_fraction(stat)
                            if fraction and fraction[1] is not None:
                                row["pass_attempts"] += fraction[1]
                        elif category_name == "passing" and stat_name in {"YDS", "YARDS"}:
                            row["pass_yards"] += number(stat) or 0
                        elif category_name == "rushing" and stat_name in {"CAR", "ATT"}:
                            row["rush_attempts"] += number(stat) or 0
                        elif category_name == "rushing" and stat_name in {"YDS", "YARDS"}:
                            row["rush_yards"] += number(stat) or 0
                        elif category_name == "receiving" and stat_name in {"REC", "RECEPTIONS"}:
                            row["receptions"] += number(stat) or 0
                        elif category_name == "receiving" and stat_name in {"YDS", "YARDS"}:
                            row["receiving_yards"] += number(stat) or 0


def attach_usage(teams, stats):
    team_totals = defaultdict(lambda: defaultdict(float))
    for (team, _), row in stats.items():
        for field in ("pass_attempts", "rush_attempts", "receptions"):
            team_totals[team][field] += row[field]

    attached = 0
    for team, roster in teams.items():
        for player in roster["players"]:
            row = stats.get((team, player["athlete_id"]))
            if not row:
                continue
            usage = {}
            for field in ("pass_attempts", "pass_yards", "rush_attempts", "rush_yards", "receptions", "receiving_yards"):
                value = row[field]
                if value:
                    usage[field] = int(value) if float(value).is_integer() else round(value, 1)
            shares = {
                "pass_attempt_share_pct": ("pass_attempts", row["pass_attempts"]),
                "rush_attempt_share_pct": ("rush_attempts", row["rush_attempts"]),
                "reception_share_pct": ("receptions", row["receptions"]),
            }
            for output_field, (total_field, value) in shares.items():
                total = team_totals[team][total_field]
                if total > 0 and value > 0:
                    usage[output_field] = round(100 * value / total, 1)
            if usage:
                player["usage"] = usage
                attached += 1
    return attached


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=int(os.environ.get("SEASON_YEAR", "2026")))
    parser.add_argument("--through-week", type=int, default=int(os.environ.get("THROUGH_WEEK", "0")))
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args()


def main():
    args = parse_args()
    external = json.loads(EXTERNAL_PATH.read_text(encoding="utf-8"))
    references = {
        team: row.get("team_id")
        for team, row in (external.get("teams") or {}).items()
        if row.get("team_id") is not None
    }
    if len(references) < 130:
        raise RuntimeError(f"Only {len(references)} ESPN team IDs were available")

    teams = {}
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 12))) as pool:
        futures = {
            pool.submit(fetch_roster, team, team_id, args.year): team
            for team, team_id in references.items()
        }
        for future in as_completed(futures):
            team = futures[future]
            try:
                name, roster = future.result()
                teams[name] = roster
            except Exception as exc:  # keep the build useful if one endpoint is temporarily down
                errors.append({"team": team, "error": str(exc)[:180]})

    if len(teams) < 125:
        raise RuntimeError(f"ESPN roster safety check failed: only {len(teams)} teams loaded")

    cfbd_key = clean_key(os.environ.get("CFBD_API_KEY"))
    through_week = args.through_week
    stats = defaultdict(lambda: defaultdict(float))
    if cfbd_key:
        if through_week <= 0:
            through_week = latest_completed_week(args.year, cfbd_key)
        for week in range(1, through_week + 1):
            payload = cfbd_get(
                "/games/players",
                cfbd_key,
                {"year": args.year, "week": week, "seasonType": "regular", "classification": "fbs"},
            )
            add_player_stats(stats, payload)
    usage_players = attach_usage(teams, stats)

    total_players = sum(len(row["players"]) for row in teams.values())
    output = {
        "meta": {
            "year": args.year,
            "through_week": through_week if cfbd_key else None,
            "generated_at": utc_now().isoformat(),
            "sources": [
                "ESPN public college-football team roster endpoint",
                *( ["CollegeFootballData game player statistics"] if cfbd_key else [] ),
            ],
            "team_count": len(teams),
            "player_count": total_players,
            "players_with_statistical_usage": usage_players,
            "official_depth_chart": False,
            "model_usage": "display_only_not_used_by_model_a",
            "usage_note": "Shares describe recorded box-score workload, not snap percentage or official depth order.",
            "errors": errors,
        },
        "teams": dict(sorted(teams.items())),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=OUTPUT_PATH.parent, delete=False) as file:
        json.dump(output, file, indent=2, ensure_ascii=False, allow_nan=False)
        file.write("\n")
        temp_path = Path(file.name)
    temp_path.replace(OUTPUT_PATH)
    print(f"Roster assets written for {len(teams)} teams and {total_players} players")
    print(f"Statistical usage attached to {usage_players} players through Week {through_week}")
    print("Model A files were not changed")


if __name__ == "__main__":
    main()
