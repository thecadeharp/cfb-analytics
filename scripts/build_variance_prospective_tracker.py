#!/usr/bin/env python3
"""Freeze and settle prospective CFB/CBB Variance Lab qualifiers.

The first eligible pregame line is immutable. Results are graded against that
line after an explicit final score is available; later markets cannot rewrite
the decision or turn a non-qualifier into a qualifier retroactively.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/variance/prospective_tracker.json"
ET = ZoneInfo("America/New_York")
VERSION = "thi-variance-prospective-v1.1"
ACADEMIES = {"Army", "Navy", "Air Force"}
P4 = {"ACC", "Atlantic Coast", "Big Ten", "Big 12", "SEC", "Southeastern"}
G5 = {"AAC", "American", "CUSA", "Conference USA", "MAC", "Mid-American", "Mountain West", "Pac-12", "Sun Belt"}


def load(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
        return payload if isinstance(payload, dict) else default
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def number(value: Any) -> float | None:
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def instant(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def team_name(game: dict[str, Any], side: str) -> str:
    team = game.get(side) or {}
    return str(team.get("team") or game.get(f"{side}_team") or "").strip()


def conference(game: dict[str, Any], side: str) -> str:
    team = game.get(side) or {}
    return str(team.get("conference") or game.get(f"{side}_conference") or "").strip()


def canonical(value: Any) -> str:
    text = str(value or "").lower().replace("&", "and")
    text = re.sub(r"\buniversity\b", "", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    aliases = {
        "miamifla": "miami", "miamiflorida": "miami", "olemiss": "mississippi",
        "southernmiss": "southernmississippi", "utsa": "texassanantonio",
        "utep": "texaselpaso", "ucf": "centralflorida", "byu": "brighamyoung",
        "lsu": "louisianastate", "smu": "southernmethodist", "tcu": "texaschristian",
    }
    return aliases.get(text, text)


def matchup_key(away: Any, home: Any) -> str:
    return f"{canonical(away)}@{canonical(home)}"


def market_values(game: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    market = game.get("market") or {}
    spread = number(market.get("home_spread"))
    if spread is None: spread = number(market.get("consensus_home_spread"))
    total = number(market.get("total"))
    if total is None: total = number(market.get("consensus_total"))
    return spread, total, number(market.get("opening_home_spread"))


def qualifying_systems(sport: str, game: dict[str, Any], start: datetime, spread: float | None, total: float | None, opening: float | None) -> list[str]:
    et = start.astimezone(ET)
    home, away = team_name(game, "home"), team_name(game, "away")
    systems: list[str] = []
    if et.hour + et.minute / 60 >= 19:
        if total is not None: systems.append("primetime-unders")
        if spread is not None and spread > 0: systems.append("primetime-home-dogs")
    if sport == "cfb":
        week = int(number(game.get("week")) or 0)
        if total is not None and week <= 1: systems.append("opening-week-unders")
        if total is not None and total >= 60: systems.append("high-total-unders")
        if total is not None and home in ACADEMIES and away in ACADEMIES: systems.append("service-academy-matchups")
        if spread is not None and spread <= -45: systems.append("massive-home-favorites")
        if spread is not None and spread > 0: systems.append("home-dogs-vs.-road-favorites")
        home_conference, away_conference = conference(game, "home"), conference(game, "away")
        if spread is not None and spread > 0 and home_conference in G5 and away_conference in P4: systems.append("p4-at-g5-home-dogs")
        if spread is not None and spread <= -35 and home_conference in P4 and str(game.get("opponent_type") or "").upper() == "FCS": systems.append("p4-vs-fcs-massive-favorites")
    else:
        if spread is not None and spread <= -10: systems.append("double-digit-road-underdogs")
        if total is not None and total < 130: systems.append("sub-130-totals")
        if game.get("conference_game") and total is not None: systems.append("conference-unders")
        if opening is not None and spread is not None and spread - opening <= -1.5: systems.append("home-side-closing-support")
        if et.month == 11 and not game.get("neutral_site") and not game.get("conference_game") and spread is not None:
            systems.append("november-nonconference-home-dogs" if spread > 0 else "november-nonconference-home-favorites")
    return list(dict.fromkeys(systems))


def final_scores(sport: str, cfb_results: dict[str, Any], cbb_board: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = (cfb_results.get("games") or []) if sport == "cfb" else (cbb_board.get("games") or [])
    by_id: dict[str, dict[str, Any]] = {}
    by_matchup: dict[str, dict[str, Any]] = {}
    for game in rows:
        status = str(game.get("status") or game.get("game_state") or "").lower()
        if status not in {"final", "completed", "complete", "post"}: continue
        home, away = team_name(game, "home"), team_name(game, "away")
        home_points = number((game.get("home") or {}).get("score"))
        away_points = number((game.get("away") or {}).get("score"))
        if home_points is None: home_points = number(game.get("home_points"))
        if away_points is None: away_points = number(game.get("away_points"))
        if home_points is None or away_points is None: continue
        result = {"home_points": home_points, "away_points": away_points, "source": game.get("source") or ("CBB projection board" if sport == "cbb" else "CFB results")}
        by_id[str(game.get("game_id"))] = result
        key = matchup_key(away, home)
        if key != "@": by_matchup[key] = result
    return by_id, by_matchup


def grade(row: dict[str, Any], result: dict[str, Any]) -> str | None:
    actual_total = result["home_points"] + result["away_points"]
    actual_margin = result["home_points"] - result["away_points"]
    totals_systems = {"primetime-unders", "opening-week-unders", "high-total-unders", "service-academy-matchups", "sub-130-totals", "conference-unders"}
    if row["system_id"] in totals_systems:
        line = number(row.get("total_at_freeze")); value = line - actual_total if line is not None else None
    else:
        line = number(row.get("spread_at_freeze")); value = actual_margin + line if line is not None else None
    if value is None: return None
    if abs(value) < 1e-9: return "P"
    return "W" if value > 0 else "L"


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for sport in ("cfb", "cbb"):
        sport_rows = [row for row in rows if row.get("sport") == sport]
        systems: dict[str, Any] = {}
        for system_id in sorted({row["system_id"] for row in sport_rows}):
            selected = [row for row in sport_rows if row["system_id"] == system_id]; counts = Counter(row.get("result") for row in selected); decisions = counts["W"] + counts["L"]
            systems[system_id] = {"qualifiers": len(selected), "pending": counts["pending"], "wins": counts["W"], "losses": counts["L"], "pushes": counts["P"], "decisions": decisions, "hit_rate": round(100 * counts["W"] / decisions, 1) if decisions else None, "roi_pct_at_minus_110": round(100 * (counts["W"] - 1.1 * counts["L"]) / (1.1 * decisions), 1) if decisions else None}
        output[sport] = {"qualifiers": len(sport_rows), "pending": sum(row.get("result") == "pending" for row in sport_rows), "systems": systems}
    return output


def build(old: dict[str, Any], cfb_board: dict[str, Any], cbb_board: dict[str, Any], cfb_results: dict[str, Any], now: datetime) -> dict[str, Any]:
    by_freeze = {row["freeze_id"]: dict(row) for row in old.get("frozen") or []}
    for sport, board in (("cfb", cfb_board), ("cbb", cbb_board)):
        for game in board.get("games") or []:
            start = instant(game.get("start_date"))
            if start is None or start <= now or str(game.get("status") or "").lower() not in {"scheduled", "upcoming"}: continue
            spread, total, opening = market_values(game); game_id = str(game.get("game_id"))
            for system_id in qualifying_systems(sport, game, start, spread, total, opening):
                freeze_id = f"{sport}:{game_id}:{system_id}"
                by_freeze.setdefault(freeze_id, {"freeze_id": freeze_id, "sport": sport, "game_id": game_id, "system_id": system_id, "start_date": game.get("start_date"), "away_team": team_name(game, "away"), "home_team": team_name(game, "home"), "neutral_site": bool(game.get("neutral_site")), "spread_at_freeze": spread, "total_at_freeze": total, "opening_spread_at_freeze": opening, "frozen_at_utc": now.isoformat().replace("+00:00", "Z"), "result": "pending"})

    for sport in ("cfb", "cbb"):
        by_id, by_matchup = final_scores(sport, cfb_results, cbb_board)
        for row in by_freeze.values():
            if row.get("sport") != sport or row.get("result") != "pending": continue
            result = by_id.get(str(row.get("game_id"))) or by_matchup.get(matchup_key(row.get("away_team"), row.get("home_team")))
            if not result: continue
            verdict = grade(row, result)
            if not verdict: continue
            row.update({"result": verdict, "settled_at_utc": now.isoformat().replace("+00:00", "Z"), "home_points": result["home_points"], "away_points": result["away_points"], "actual_home_margin": result["home_points"] - result["away_points"], "actual_total": result["home_points"] + result["away_points"], "settlement_source": result["source"]})

    rows = sorted(by_freeze.values(), key=lambda row: (str(row.get("start_date")), row["freeze_id"]))
    return {"meta": {"version": VERSION, "generated_at_utc": now.isoformat().replace("+00:00", "Z"), "policy": "First eligible pregame capture is immutable. Every final is graded against its frozen line; later market moves cannot rewrite qualification or settlement."}, "summary": summary(rows), "frozen": rows}


def main() -> None:
    now = datetime.now(timezone.utc)
    payload = build(load(OUT, {"frozen": []}), load(ROOT / "data/projections.json", {"games": []}), load(ROOT / "data/cbb/projection_board.json", {"games": []}), load(ROOT / "data/results.json", {"games": []}), now)
    OUT.parent.mkdir(parents=True, exist_ok=True); OUT.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    settled = sum(row.get("result") in {"W", "L", "P"} for row in payload["frozen"])
    print(f"{VERSION}: {len(payload['frozen'])} qualifiers, {settled} settled")


if __name__ == "__main__": main()
