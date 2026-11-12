#!/usr/bin/env python3
"""Build THI's analysis-only CFB live game center from CFBD live plays."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = "https://api.collegefootballdata.com/live/plays"
VERSION = "thi-cfb-live-center-v1.0"


def clean_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def fetch_live(game_id: Any, api_key: str) -> dict[str, Any]:
    request = Request(
        f"{API_ROOT}?{urlencode({'gameId': game_id})}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    with urlopen(request, timeout=20) as response:  # nosec B310 - fixed HTTPS host
        return json.loads(response.read().decode("utf-8"))


def projection_for(live: dict[str, Any], projections: list[dict[str, Any]]) -> dict[str, Any] | None:
    away = clean_name(live.get("away_team"))
    home = clean_name(live.get("home_team"))
    for game in projections:
        if clean_name(game.get("away", {}).get("team")) == away and clean_name(game.get("home", {}).get("team")) == home:
            return game
    return None


def clock_seconds(clock: Any) -> int:
    match = re.search(r"(\d+):(\d+)", str(clock or ""))
    return int(match.group(1)) * 60 + int(match.group(2)) if match else 0


def elapsed_fraction(period: Any, clock: Any) -> float:
    quarter = max(1, int(period or 1))
    if quarter > 4:
        return 1.0
    elapsed = (quarter - 1) * 900 + (900 - min(900, clock_seconds(clock)))
    return max(0.03, min(1.0, elapsed / 3600))


def all_plays(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [play for drive in payload.get("drives") or [] for play in drive.get("plays") or []]


def score_flow(payload: dict[str, Any]) -> dict[str, Any]:
    plays = all_plays(payload)
    team_points = {str(team.get("homeAway") or "").lower(): int(team.get("points") or 0) for team in payload.get("teams") or []}
    home_points = max([int(play.get("homeScore") or 0) for play in plays] + [team_points.get("home", 0)])
    away_points = max([int(play.get("awayScore") or 0) for play in plays] + [team_points.get("away", 0)])
    home_lead = away_lead = 0
    checkpoints: dict[str, dict[str, int]] = {}
    for play in plays:
        home = int(play.get("homeScore") or 0)
        away = int(play.get("awayScore") or 0)
        home_lead = max(home_lead, home - away)
        away_lead = max(away_lead, away - home)
        period = int(play.get("period") or 0)
        if period in (1, 2, 3, 4):
            checkpoints[f"q{period}"] = {"home": home, "away": away}
    competitive = [play for play in plays if not play.get("garbageTime")]
    recent = competitive[-10:]
    explosive = sum(
        1 for play in competitive
        if (str(play.get("rushPass") or "").lower() == "rush" and float(play.get("yardsGained") or 0) >= 10)
        or (str(play.get("rushPass") or "").lower() == "pass" and float(play.get("yardsGained") or 0) >= 20)
    )
    return {
        "current_score": {"home": home_points, "away": away_points},
        "largest_lead": {"home": home_lead, "away": away_lead},
        "score_checkpoints": checkpoints,
        "competitive_plays": len(competitive),
        "garbage_time_plays": len(plays) - len(competitive),
        "explosive_plays": explosive,
        "recent_competitive_plays": [{
            "team": play.get("team"), "period": play.get("period"), "clock": play.get("clock"),
            "down": play.get("down"), "distance": play.get("distance"),
            "yards_gained": play.get("yardsGained"), "epa": play.get("epa"),
            "success": bool(play.get("success")), "play_type": play.get("playType"),
        } for play in recent],
    }


def live_estimate(payload: dict[str, Any], projection: dict[str, Any], flow: dict[str, Any]) -> dict[str, Any]:
    fraction = elapsed_fraction(payload.get("period"), payload.get("clock"))
    remaining = 1.0 - fraction
    current = flow["current_score"]
    current_total = current["home"] + current["away"]
    current_margin = current["home"] - current["away"]
    pregame_total = float(projection.get("projection", {}).get("total") or 52.0)
    pregame_margin = -float(projection.get("projection", {}).get("home_spread") or 0.0)
    pace_total = current_total / fraction
    estimated_total = 0.68 * (current_total + pregame_total * remaining) + 0.32 * pace_total
    estimated_total = max(float(current_total), min(100.0, estimated_total))
    estimated_margin = current_margin + pregame_margin * remaining
    home_final = (estimated_total + estimated_margin) / 2
    away_final = estimated_total - home_final
    sigma = max(4.0, 16.0 * math.sqrt(max(0.05, remaining)))
    home_wp = 100.0 * 0.5 * (1 + math.erf(estimated_margin / (sigma * math.sqrt(2))))
    return {
        "projected_final": {"away": round(max(0, away_final), 1), "home": round(max(0, home_final), 1)},
        "projected_total": round(estimated_total, 1),
        "home_win_probability": round(max(0.0, min(100.0, home_wp)), 1),
        "game_elapsed_pct": round(fraction * 100, 1),
        "method": "Pregame THI expectation blended with observed score pace; display-only and not a betting signal.",
    }


def compact_team(team: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "teamId", "team", "homeAway", "lineScores", "points", "drives", "scoringOpportunities",
        "pointsPerOpportunity", "averageStartYardLine", "plays", "lineYards", "lineYardsPerRush",
        "secondLevelYards", "secondLevelYardsPerRush", "openFieldYards", "openFieldYardsPerRush",
        "epaPerPlay", "totalEpa", "passingEpa", "epaPerPass", "rushingEpa", "epaPerRush",
        "successRate", "standardDownSuccessRate", "passingDownSuccessRate", "explosiveness", "deserveToWin",
    )
    return {key: team.get(key) for key in keys}


def compact_drive(drive: dict[str, Any]) -> dict[str, Any]:
    return {key: drive.get(key) for key in (
        "id", "offense", "defense", "playCount", "yards", "startPeriod", "startClock",
        "endPeriod", "endClock", "duration", "scoringOpportunity", "result", "pointsGained",
    )}


def build(
    live_scores: dict[str, Any], projections: dict[str, Any], api_key: str | None,
    fetcher: Callable[[Any, str], dict[str, Any]] = fetch_live,
) -> dict[str, Any]:
    games: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for live in live_scores.get("games") or []:
        projection = projection_for(live, projections.get("games") or [])
        if not projection:
            errors.append({"game_id": live.get("game_id"), "error": "projection match unavailable"})
            continue
        cfbd_game_id = projection.get("game_id")
        if not api_key:
            errors.append({"game_id": cfbd_game_id, "error": "CFBD_API_KEY unavailable"})
            continue
        try:
            payload = fetcher(cfbd_game_id, api_key)
            flow = score_flow(payload)
            games.append({
                "game_id": cfbd_game_id,
                "status": payload.get("status") or live.get("status"),
                "period": payload.get("period"), "clock": payload.get("clock"),
                "possession": payload.get("possession"), "down": payload.get("down"),
                "distance": payload.get("distance"), "yards_to_goal": payload.get("yardsToGoal"),
                "away": projection.get("away"), "home": projection.get("home"),
                "teams": [compact_team(team) for team in payload.get("teams") or []],
                "recent_drives": [compact_drive(drive) for drive in (payload.get("drives") or [])[-4:]],
                "game_flow": flow,
                "live_estimate": live_estimate(payload, projection, flow),
                "coverage_state": "tracked" if len(all_plays(payload)) >= 20 else "developing",
            })
        except Exception as error:  # noqa: BLE001 - preserve partial board on provider failure
            errors.append({"game_id": cfbd_game_id, "error": str(error)[:180]})
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "live_game_count": len(live_scores.get("games") or []),
            "tracked_game_count": len(games),
            "policy": "Analysis-only live context. No live odds are collected or displayed. Frozen pregame THI projections remain unchanged.",
        },
        "games": games,
        "fetch_errors": errors,
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", type=Path, default=ROOT / "data/live_scores.json")
    parser.add_argument("--projections", type=Path, default=ROOT / "data/projections.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/cfb_live_center.json")
    args = parser.parse_args()
    payload = build(json.loads(args.live.read_text()), json.loads(args.projections.read_text()), os.getenv("CFBD_API_KEY"))
    atomic_write(args.output, payload)
    print(f"{VERSION}: {payload['meta']['tracked_game_count']} live games enriched")


if __name__ == "__main__":
    main()
