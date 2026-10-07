#!/usr/bin/env python3
"""Add verified player/position context to the CFB portal product."""
from __future__ import annotations

import json, math, os, tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "portal_2026.json"
API = "https://api.collegefootballdata.com/recruiting/portal"
OFFENSE = {"QB","RB","FB","WR","TE","OT","OG","C","OL","IOL"}
DEFENSE = {"DL","DE","DT","EDGE","LB","ILB","OLB","CB","DB","S","ATH"}

def finite(value):
    try:
        number=float(value); return number if math.isfinite(number) else None
    except (TypeError,ValueError): return None

def school(value):
    if isinstance(value,dict):
        return str(value.get("school") or value.get("name") or value.get("team") or "").strip()
    return str(value or "").strip()

def side(position):
    position=str(position or "").upper().strip()
    if position in OFFENSE:return "offense"
    if position in DEFENSE:return "defense"
    return "specialists"

def build_payload(base, raw):
    players=[]; aggregates=defaultdict(lambda:{"offense":[],"defense":[],"specialists":[]})
    for row in raw:
        destination=school(row.get("destination")); origin=school(row.get("origin"))
        if not destination: continue
        position=str(row.get("position") or "").upper().strip() or "—"
        rating=finite(row.get("rating")); group=side(position)
        origin_type=" ".join(str(row.get(key) or "") for key in ("originClassification","origin_classification","classification"))
        juco=any(token in f"{origin} {origin_type}".casefold() for token in ("juco","junior college","community college","njcaa"))
        player={
            "name":" ".join(part for part in (row.get("firstName"),row.get("lastName")) if part).strip() or str(row.get("name") or "Unknown"),
            "position":position,"side":group,"origin":origin or "Unknown","destination":destination,
            "rating":round(rating,4) if rating is not None else None,"stars":row.get("stars"),"juco":juco,
            "transfer_date":row.get("transferDate") or row.get("transfer_date")
        }
        players.append(player); aggregates[destination][group].append(player)
    impact=[]
    for team,groups in aggregates.items():
        item={"team":team}
        for group in ("offense","defense","specialists"):
            ratings=[p["rating"] for p in groups[group] if p["rating"] is not None]
            item[group]={"count":len(groups[group]),"avg_rating":round(sum(ratings)/len(ratings),3) if ratings else None}
        impact.append(item)
    impact.sort(key=lambda row:(-(row["offense"]["count"]+row["defense"]["count"]),row["team"]))
    result=dict(base); result["players"]=sorted(players,key=lambda row:(row["destination"],row["side"],-(row["rating"] or 0),row["name"]))
    result["position_impact"]=impact
    result["player_source"]={"name":"CollegeFootballData transfer portal","url":"https://collegefootballdata.com/","generated_at":datetime.now(timezone.utc).isoformat(),"model_usage":"display_only_not_used_by_model_a"}
    return result

def main():
    import requests
    key=os.environ.get("CFBD_API_KEY","").strip()
    if not key: raise SystemExit("CFBD_API_KEY is required")
    response=requests.get(API,params={"year":2026},headers={"Authorization":f"Bearer {key}","Accept":"application/json"},timeout=(10,90));response.raise_for_status()
    raw=response.json()
    if not isinstance(raw,list) or len(raw)<100: raise RuntimeError(f"Portal response is unexpectedly sparse: {len(raw) if isinstance(raw,list) else 'invalid'}")
    base=json.loads(OUTPUT.read_text())
    payload=build_payload(base,raw)
    with tempfile.NamedTemporaryFile("w",dir=OUTPUT.parent,delete=False,encoding="utf-8") as handle:
        json.dump(payload,handle,indent=2,allow_nan=False);handle.write("\n");temporary=Path(handle.name)
    temporary.replace(OUTPUT)
    print(f"CFB portal intelligence: {len(payload['players'])} verified player rows")

if __name__=="__main__": main()
