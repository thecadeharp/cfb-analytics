#!/usr/bin/env python3
"""Build deterministic reverse-line-movement alerts from synchronized snapshots."""
from __future__ import annotations
import argparse,json,math
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SHARP_BOOK_PRIORITY={"pinnacle":1,"betonline":2}
SHARP_BOOK_ALIASES={"pinnacle":"pinnacle","pinny":"pinnacle","betonline":"betonline","betonlineag":"betonline","betonline.ag":"betonline"}
def number(v):
 try:v=float(v);return v if math.isfinite(v)else None
 except(TypeError,ValueError):return None
def crossed_key(opening,current):
 lo,hi=sorted((abs(opening),abs(current)))
 return next((key for key in(3,7,10)if lo<key<=hi),None)
def sharp_book_identity(value):
 key="".join(ch for ch in str(value or "").lower()if ch.isalnum()or ch==".")
 return SHARP_BOOK_ALIASES.get(key)
def analyze(row):
 book=sharp_book_identity(row.get("sharp_book")or row.get("book"))
 if not book:return None
 opening=number(row.get("opening_home_spread"));current=number(row.get("current_home_spread"));tickets=number(row.get("public_ticket_pct"));side=str(row.get("public_side","")).lower()
 if opening is None or current is None or tickets is None or side not in{"home","away"}:return None
 delta=round(current-opening,2);against_public=(side=="home"and delta>=.5)or(side=="away"and delta<=-.5)
 if tickets<65 or not against_public:return None
 key=crossed_key(opening,current);magnitude=abs(delta);severity="max"if key or(tickets>=75 and magnitude>=1.5)else("strong"if tickets>=70 and magnitude>=1 else"watch")
 sharp_side="away"if side=="home"else"home"
 return {**row,"sharp_book":book,"sharp_source_tier":"primary"if book=="pinnacle"else"fallback","line_delta":delta,"sharp_side":sharp_side,"sharp_team":row.get(f"{sharp_side}_team"),"key_number_crossed":key,"severity":severity,"definition":"Public side has at least 65% of tickets while the synchronized sharp-book spread moved at least 0.5 points toward the opponent."}
def select_authoritative_rows(rows):
 latest={}
 for row in rows:
  book=sharp_book_identity(row.get("sharp_book")or row.get("book"))
  if not book:continue
  key=(str(row.get("sport")),str(row.get("event_id")),book)
  if key not in latest or str(row.get("captured_at_utc"))>str(latest[key].get("captured_at_utc")):latest[key]={**row,"sharp_book":book}
 events={}
 for (sport,event_id,book),row in latest.items():
  key=(sport,event_id);current=events.get(key)
  if current is None or SHARP_BOOK_PRIORITY[book]<SHARP_BOOK_PRIORITY[current["sharp_book"]]:events[key]=row
 return list(events.values())
def main():
 p=argparse.ArgumentParser();p.add_argument("--snapshots",type=Path,default=ROOT/"data/market/rlm_snapshots.jsonl");p.add_argument("--output",type=Path,default=ROOT/"data/market/rlm_monitor.json");a=p.parse_args();raw=[]
 if a.snapshots.exists():
  for line in a.snapshots.read_text().splitlines():
   if line.strip():raw.append(json.loads(line))
 selected=select_authoritative_rows(raw);alerts=sorted((alert for row in selected if(alert:=analyze(row))),key=lambda x:str(x.get("start_date")))
 payload={"meta":{"version":"thi-rlm-monitor-v1.1","generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"status":"monitoring"if selected else"source_pending","alert_count":len(alerts),"qualified_event_count":len(selected),"sharp_book_policy":{"primary":"Pinnacle","fallback":"BetOnline","rejected_as_sharp_reference":["DraftKings","FanDuel","Caesars","BetMGM"]},"minimum_ticket_pct":65,"minimum_move_points":.5,"requirements":["Ticket percentage and side from a licensed splits source","Opening and current spread from the same named sharp book","Pinnacle is required when present; BetOnline is used only when Pinnacle is absent","Snapshots captured no more than five minutes apart","No alert when either input is absent"]},"alerts":alerts}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(payload,indent=2)+"\n");print(len(alerts))
if __name__=="__main__":main()
