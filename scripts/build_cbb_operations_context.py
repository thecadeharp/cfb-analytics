#!/usr/bin/env python3
"""Build auditable CBB travel/rest/availability context without model adjustments."""
from __future__ import annotations
import argparse,json,math
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]; VERSION="thi-cbb-operations-context-v1.0"

def instant(v):
    try:return datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except:return None
def miles(a,b):
    if not a or not b:return None
    lat1,lon1,lat2,lon2=map(math.radians,[a["latitude"],a["longitude"],b["latitude"],b["longitude"]]); dlat=lat2-lat1; dlon=lon2-lon1
    h=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return round(3958.8*2*math.asin(math.sqrt(h)))
def build(board:dict[str,Any], geocodes:dict[str,Any], availability:dict[str,Any])->dict[str,Any]:
    games=board.get("games",[]); venue_counts=defaultdict(Counter)
    geocodes=geocodes.get("venues",geocodes)
    for g in games:
      if not g.get("neutral_site") and (g.get("venue") or {}).get("name"): venue_counts[str((g.get("home") or {}).get("team_id"))][(g["venue"]["name"],g["venue"].get("city"),g["venue"].get("state"))]+=1
    campuses={t:c.most_common(1)[0][0] for t,c in venue_counts.items() if c}
    reports={str(r.get("game_id")):r for r in availability.get("reports",[]) if r.get("verified_source_url") and r.get("verified_at_utc")}
    rows=[]; measured=0; no_trip=0
    for g in games:
      venue=g.get("venue") or {}; vkey="|".join(str(venue.get(k) or "") for k in ("name","city","state")); site=geocodes.get(vkey)
      teams={}
      for side in ("away","home"):
        team=g.get(side) or {}; campus_tuple=campuses.get(str(team.get("team_id"))); ckey="|".join(str(x or "") for x in campus_tuple) if campus_tuple else ""; distance=0 if side=="home" and not g.get("neutral_site") else miles(geocodes.get(ckey),site)
        if distance is not None and not (side=="home" and not g.get("neutral_site")): measured+=1
        if side=="home" and not g.get("neutral_site"): no_trip+=1
        state="no_trip_home_site" if side=="home" and not g.get("neutral_site") else ("verified_venue_coordinates" if distance is not None else "awaiting_verified_coordinates")
        teams[side]={"team_id":team.get("team_id"),"team":team.get("team"),"campus_venue":campus_tuple[0] if campus_tuple else None,"travel_miles":distance,"measurement_state":state}
      rows.append({"game_id":g.get("game_id"),"start_date":g.get("start_date"),"venue":venue,"teams":teams,"availability":reports.get(str(g.get("game_id")),{"status":"no_verified_report","model_adjustment":None})})
    return {"meta":{"version":VERSION,"generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"model_usage":"display_only_research_layer","policy":"Mileage publishes only from verified coordinates. Availability requires a timestamped source URL and never creates an automatic model adjustment."},"coverage":{"games":len(rows),"team_game_sides":len(rows)*2,"sides_not_requiring_travel":no_trip,"sides_with_verified_mileage":measured,"verified_availability_reports":len(reports)},"games":rows}
def main():
 p=argparse.ArgumentParser();p.add_argument("--board",type=Path,default=ROOT/"data/cbb/projection_board.json");p.add_argument("--geocodes",type=Path,default=ROOT/"data/cbb/verified_venue_geocodes.json");p.add_argument("--availability",type=Path,default=ROOT/"data/cbb/verified_availability.json");p.add_argument("--output",type=Path,default=ROOT/"data/cbb/operations_context.json");a=p.parse_args()
 load=lambda x:json.loads(x.read_text()) if x.exists() else {}
 payload=build(load(a.board),load(a.geocodes),load(a.availability));a.output.write_text(json.dumps(payload,indent=2,allow_nan=False)+"\n");print(VERSION,payload["coverage"])
if __name__=="__main__":main()
