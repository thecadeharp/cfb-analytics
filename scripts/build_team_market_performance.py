#!/usr/bin/env python3
"""Build descriptive team ATS and average-cover-margin profiles."""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
INPUT = DATA / "reports" / "settled_results.json"
OUTPUT = DATA / "team_market_performance.json"


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def record(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(row["result"] == "W" for row in rows)
    losses = sum(row["result"] == "L" for row in rows)
    pushes = sum(row["result"] == "P" for row in rows)
    decisions = wins + losses
    margins = [float(row["cover_margin"]) for row in rows]
    return {
        "games": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "record": f"{wins}-{losses}" + (f"-{pushes}" if pushes else ""),
        "win_pct_ex_pushes": round(100 * wins / decisions, 1) if decisions else None,
        "average_cover_margin": round(statistics.fmean(margins), 2) if margins else None,
        "median_cover_margin": round(statistics.median(margins), 2) if margins else None,
    }


def main() -> None:
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    rows = [row for row in payload.get("rows", []) if row.get("result_settled")]

    initial_by_game: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("game_key") or row.get("result_game_id") or "")
        if not key:
            continue
        current = initial_by_game.get(key)
        if current is None or str(row.get("captured_at_utc") or "") < str(current.get("captured_at_utc") or ""):
            initial_by_game[key] = row

    team_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    used_games = 0
    for row in initial_by_game.values():
        if not finite(row.get("actual_home_margin")):
            continue
        market_spread = row.get("closing_home_spread")
        line_source = "closing_proxy"
        if not finite(market_spread):
            market_spread = row.get("snapshot_home_spread")
            line_source = "initial_snapshot"
        if not finite(market_spread):
            continue

        used_games += 1
        actual_home_margin = float(row["actual_home_margin"])
        home_spread = float(market_spread)
        home_cover_margin = actual_home_margin + home_spread
        home_result = "W" if home_cover_margin > 0 else "L" if home_cover_margin < 0 else "P"
        away_result = "L" if home_result == "W" else "W" if home_result == "L" else "P"

        home_name = str(row.get("home_team") or "")
        away_name = str(row.get("away_team") or "")
        common = {
            "game_id": str(row.get("game_key") or ""),
            "week": row.get("week"),
            "line_source": line_source,
        }
        team_rows[home_name].append({
            **common,
            "opponent": away_name,
            "location": "home",
            "role": "favorite" if home_spread < 0 else "underdog" if home_spread > 0 else "pickem",
            "team_spread": home_spread,
            "actual_margin": actual_home_margin,
            "cover_margin": round(home_cover_margin, 2),
            "result": home_result,
        })
        team_rows[away_name].append({
            **common,
            "opponent": home_name,
            "location": "away",
            "role": "favorite" if home_spread > 0 else "underdog" if home_spread < 0 else "pickem",
            "team_spread": -home_spread,
            "actual_margin": -actual_home_margin,
            "cover_margin": round(-home_cover_margin, 2),
            "result": away_result,
        })

    teams: dict[str, Any] = {}
    for team, games in team_rows.items():
        overall = record(games)
        teams[team] = {
            "team": team,
            "overall": overall,
            "home": record([game for game in games if game["location"] == "home"]),
            "away": record([game for game in games if game["location"] == "away"]),
            "favorite": record([game for game in games if game["role"] == "favorite"]),
            "underdog": record([game for game in games if game["role"] == "underdog"]),
            "games": sorted(games, key=lambda game: (int(game.get("week") or 0), game["game_id"])),
        }

    eligible = [
        team for team in teams.values()
        if int(team["overall"]["games"] or 0) >= 2
        and finite(team["overall"]["average_cover_margin"])
    ]
    ordered = sorted(
        eligible,
        key=lambda team: float(team["overall"]["average_cover_margin"]),
        reverse=True,
    )
    for index, team in enumerate(ordered, 1):
        team["market_rank"] = index
        team["market_label"] = (
            "OUTPERFORMING MARKET"
            if float(team["overall"]["average_cover_margin"]) >= 3
            else "UNDERPERFORMING MARKET"
            if float(team["overall"]["average_cover_margin"]) <= -3
            else "NEAR MARKET EXPECTATION"
        )

    output = {
        "meta": {
            "season": 2026,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "games": used_games,
            "minimum_ranked_games": 2,
            "model_usage": "descriptive_only_not_used_by_model_a",
            "line_priority": ["near-kickoff closing proxy", "initial prospective snapshot"],
            "definition": "Average Cover Margin is actual team margin minus the market-implied margin. Positive values indicate market outperformance.",
            "warning": "Early-season samples are small. This table describes results and is not a betting recommendation.",
        },
        "most_underrated": [team["team"] for team in ordered[:10]],
        "most_overrated": [team["team"] for team in reversed(ordered[-10:])],
        "teams": teams,
    }
    OUTPUT.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} for {len(teams)} teams across {used_games} games.")


if __name__ == "__main__":
    main()
