#!/usr/bin/env python3
"""Build deterministic reverse-line-movement alerts from synchronized snapshots."""
from __future__ import annotations
import argparse,json,math
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def number(v):
 try:v=float(v);return v if math.isfinite(v)else None
 except(TypeError,ValueError):return None
def crossed_key(opening,current):
 lo,hi=sorted((abs(opening),abs(current)))
 return next((key for key in(3,7,10)if lo<key<=hi),None)
def analyze(row):
 opening=number(row.get("opening_home_spread"));current=number(row.get("current_home_spread"));tickets=number(row.get("public_ticket_pct"));side=str(row.get("public_side","")).lower()
 if opening is None or current is None or tickets is None or side not in{"home","away"}:return None
 delta=round(current-opening,2);against_public=(side=="home"and delta>=.5)or(side=="away"and delta<=-.5)
 if tickets<65 or not against_public:return None
 key=crossed_key(opening,current);magnitude=abs(delta);severity="max"if key or(tickets>=75 and magnitude>=1.5)else("strong"if tickets>=70 and magnitude>=1 else"watch")
 sharp_side="away"if side=="home"else"home"
 return {**row,"line_delta":delta,"sharp_side":sharp_side,"sharp_team":row.get(f"{sharp_side}_team"),"key_number_crossed":key,"severity":severity,"definition":"Public side has at least 65% of tickets while the synchronized sharp-book spread moved at least 0.5 points toward the opponent."}
def main():
 p=argparse.ArgumentParser();p.add_argument("--snapshots",type=Path,default=ROOT/"data/market/rlm_snapshots.jsonl");p.add_argument("--output",type=Path,default=ROOT/"data/market/rlm_monitor.json");a=p.parse_args();rows=[]
 if a.snapshots.exists():
  for line in a.snapshots.read_text().splitlines():
   if line.strip():
    alert=analyze(json.loads(line));rows.append(alert)if alert else None
 latest={}
 for row in rows:
  key=f"{row.get('sport')}:{row.get('event_id')}";
  if key not in latest or str(row.get("captured_at_utc"))>str(latest[key].get("captured_at_utc")):latest[key]=row
 alerts=sorted(latest.values(),key=lambda x:str(x.get("start_date")))
 payload={"meta":{"version":"thi-rlm-monitor-v1.0","generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"status":"active"if rows else"source_pending","alert_count":len(alerts),"minimum_ticket_pct":65,"minimum_move_points":.5,"requirements":["Ticket percentage and side from a licensed splits source","Opening and current spread from the same named sharp book","Snapshots captured no more than five minutes apart","No alert when either input is absent"]},"alerts":alerts}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(payload,indent=2)+"\n");print(len(alerts))
if __name__=="__main__":main()
