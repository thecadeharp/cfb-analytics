#!/usr/bin/env python3
"""Build descriptive CFB/CBB market trends from THI's settled history."""
from __future__ import annotations

import argparse, csv, gzip, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-trends-lab-v1.0"

def num(value: Any) -> float | None:
    try:
        value = float(value)
        return value if value == value else None
    except (TypeError, ValueError): return None

def grade(rows: list[dict[str, Any]], name: str, description: str, select: Callable[[dict[str, Any]], bool], market: str) -> dict[str, Any]:
    wins = losses = pushes = 0
    seasons = set()
    for row in rows:
        if not select(row): continue
        margin, total = num(row.get("margin")), num(row.get("total"))
        line = num(row.get("spread" if market == "ats" else "market_total"))
        if margin is None or total is None or line is None: continue
        result = margin + line if market == "ats" else total - line
        if abs(result) < .001: pushes += 1
        elif (result > 0 and market == "ats") or (result < 0 and market == "under"): wins += 1
        else: losses += 1
        seasons.add(int(row["season"]))
    decisions = wins + losses
    rate = round(100 * wins / decisions, 1) if decisions else None
    return {"name": name, "description": description, "market": "ATS" if market == "ats" else "Under", "wins": wins, "losses": losses, "pushes": pushes, "decisions": decisions, "hit_rate": rate, "seasons": sorted(seasons), "state": "qualified" if decisions >= 200 else "limited_sample"}

def cfb_rows(path: Path) -> list[dict[str, Any]]:
    out=[]
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            spread, market_total = num(row.get("market_home_spread")), num(row.get("market_total"))
            margin, total = num(row.get("actual_home_margin")), num(row.get("actual_total"))
            if str(row.get("completed")).lower() != "true": continue
            out.append({"season": int(row["season"]), "margin": margin, "total": total, "spread": spread, "market_total": market_total, "neutral": False, "conference": None, "home_favorite": spread is not None and spread < 0, "favorite_size": abs(spread) if spread is not None else None})
    return out

def cbb_rows(history: Path) -> list[dict[str, Any]]:
    out=[]
    for path in sorted(history.glob("season_*.json.gz")):
        payload=json.load(gzip.open(path,"rt")); season=int(payload["meta"]["season"])
        for game in payload.get("games",[]):
            market=game.get("market") or {}; outcome=game.get("outcome") or {}
            spread=num(market.get("home_spread_close")); margin=num(outcome.get("home_margin"))
            out.append({"season":season,"margin":margin,"total":num(outcome.get("total_points")),"spread":spread,"market_total":num(market.get("total_close")),"neutral":bool(game.get("neutral_site")),"conference":bool(game.get("conference_game")),"home_favorite":spread is not None and spread < 0,"favorite_size":abs(spread) if spread is not None else None})
    return out

def cards(rows: list[dict[str, Any]], sport: str) -> list[dict[str, Any]]:
    totals=[num(r.get("market_total")) for r in rows if num(r.get("market_total")) is not None]
    totals.sort(); low=totals[len(totals)//4] if totals else 0; high=totals[(len(totals)*3)//4] if totals else 999
    return [
      grade(rows,"Home favorites","Home teams laying points",lambda r:r["home_favorite"],"ats"),
      grade(rows,"Home underdogs","Home teams catching points",lambda r:num(r.get("spread")) is not None and r["spread"]>0,"ats"),
      grade(rows,"Double-digit favorites","Home favorites of 10 or more",lambda r:r["home_favorite"] and (r["favorite_size"] or 0)>=10,"ats"),
      *([grade(rows,"Neutral-floor favorites","Listed home-side favorite at a neutral site",lambda r:r["neutral"] and r["home_favorite"],"ats")] if sport=="cbb" else []),
      grade(rows,"All posted totals","Every settled game with a closing total",lambda r:True,"under"),
      grade(rows,"High-total unders",f"Closing total at or above the historical 75th percentile ({high:.1f})",lambda r:(num(r.get("market_total")) or -999)>=high,"under"),
      grade(rows,"Low-total unders",f"Closing total at or below the historical 25th percentile ({low:.1f})",lambda r:(num(r.get("market_total")) or 999)<=low,"under"),
      *([grade(rows,"Conference-game unders","Games identified as conference matchups",lambda r:r["conference"] is True,"under")] if sport=="cbb" else []),
    ]

def build(cfb: list[dict[str, Any]], cbb: list[dict[str, Any]]) -> dict[str, Any]:
    return {"meta":{"version":VERSION,"generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"policy":"Descriptive historical research only. Every card publishes its sample and is never an automatic betting recommendation."},"sports":{"cfb":{"settled_games":len(cfb),"cards":cards(cfb,"cfb")},"cbb":{"settled_games":len(cbb),"cards":cards(cbb,"cbb")}},"planned_splits":[{"name":"Ranked vs. unranked","status":"awaiting_point_in_time_rankings","reason":"A ranking must be joined as it existed before each game."},{"name":"Primetime","status":"awaiting_verified_start_times","reason":"The current settled training snapshots do not preserve trustworthy kickoff/tip times."}]}

def main() -> None:
    p=argparse.ArgumentParser(); p.add_argument("--output",type=Path,default=ROOT/"data/trends_lab.json"); a=p.parse_args()
    payload=build(cfb_rows(ROOT/"data/training/historical_games.csv"),cbb_rows(ROOT/"data/cbb/history")); a.output.write_text(json.dumps(payload,indent=2,allow_nan=False)+"\n"); print(VERSION)
if __name__=="__main__": main()
