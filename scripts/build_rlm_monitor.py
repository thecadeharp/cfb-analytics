#!/usr/bin/env python3
"""Build deterministic market-movement, RLM and CFB steam-reversal alerts."""
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
def sharp_line_moves(state):
 moves=[]
 for row in (state or {}).get("events",{}).values():
  opening=number(row.get("opening_home_spread"));current=number(row.get("current_home_spread"))
  if opening is None or current is None:continue
  delta=round(current-opening,2)
  if abs(delta)<.5:continue
  toward="home" if delta<0 else "away";team=row.get(f"{toward}_team");sport=str(row.get("sport")or"").lower()
  key=crossed_key(opening,current) if sport=="cfb" else None
  severity="key_number" if key else("major" if abs(delta)>=2 else"move")
  moves.append({**row,"line_delta":delta,"movement_toward":toward,"movement_toward_team":team,"key_number_crossed":key,"severity":severity,"definition":"Observed Pinnacle spread movement from THI's first captured number. Public betting splits are unavailable, so this is not an RLM or sharp-money claim."})
 return sorted(moves,key=lambda row:(str(row.get("start_date")),str(row.get("event_id"))))

def canonical_team(value):
 text="".join(ch for ch in str(value or "").lower() if ch.isalnum())
 aliases={"umass":"massachusetts","umassminutemen":"massachusetts","cal":"california","calgoldenbears":"california","lsu":"louisianastate","lsutigers":"louisianastate"}
 return aliases.get(text,text)
def same_team(left,right):
 a,b=canonical_team(left),canonical_team(right)
 return a==b or (min(len(a),len(b))>=4 and (a.startswith(b) or b.startswith(a)))
def active_availability_flags(row,availability,now=None):
 now=now or datetime.now(timezone.utc);flags=[]
 for team,notes in (availability or {}).get("teams",{}).items():
  side=next((side for side in("away","home") if same_team(team,row.get(f"{side}_team"))),None)
  if not side:continue
  for note in notes or []:
   if not(note.get("market_context_relevant")or note.get("withhold_public_signal")):continue
   try:
    verified=datetime.fromisoformat(str(note.get("verified_at_utc")).replace("Z","+00:00"));expires=datetime.fromisoformat(str(note.get("valid_until_utc")).replace("Z","+00:00"))
    if not(verified<=now<expires):continue
   except(TypeError,ValueError):continue
   flags.append({"team":team,"side":side,"player":note.get("player"),"position":note.get("position"),"status":note.get("status"),"text":note.get("text"),"source_label":note.get("source_label"),"source_url":note.get("source_url"),"withhold_public_signal":note.get("withhold_public_signal")is True})
 return flags
def steam_reversal_alerts(moves,threshold=3.0,availability=None,now=None):
 alerts=[]
 for row in moves:
  if str(row.get("sport")or"").lower()!="cfb":continue
  delta=number(row.get("line_delta"));current=number(row.get("current_home_spread"))
  if delta is None or current is None or abs(delta)<threshold:continue
  steam_side="home" if delta<0 else "away";fade_side="away" if steam_side=="home" else "home"
  fade_line=-current if fade_side=="away" else current
  flags=active_availability_flags(row,availability,now);held=any(flag["withhold_public_signal"] for flag in flags)
  status="material_availability_overlap" if flags else"unclassified"
  action="context_hold" if held else("context_review" if flags else"monitor_only")
  note="Sourced player availability overlaps this move. THI does not claim it caused the move; the public fade label is held pending context review." if held else("Sourced player availability overlaps this move. THI does not claim it caused the move." if flags else"Price movement alone does not establish sharp money, injury, weather or public causation.")
  alerts.append({**row,"system_id":"steam-reversal","trigger_threshold_points":threshold,"steam_side":steam_side,"steam_team":row.get(f"{steam_side}_team"),"fade_side":fade_side,"fade_team":row.get(f"{fade_side}_team"),"fade_spread":round(fade_line,2),"movement_points":round(abs(delta),2),"context_status":status,"action_status":action,"context_flags":flags,"context_note":note})
 return sorted(alerts,key=lambda row:(str(row.get("start_date")),str(row.get("event_id"))))
def main():
 p=argparse.ArgumentParser();p.add_argument("--snapshots",type=Path,default=ROOT/"data/market/rlm_snapshots.jsonl");p.add_argument("--sharp-state",type=Path,default=ROOT/"data/market/sharp_line_state.json");p.add_argument("--availability",type=Path,default=ROOT/"data/roster_notes.json");p.add_argument("--output",type=Path,default=ROOT/"data/market/rlm_monitor.json");a=p.parse_args();raw=[]
 if a.snapshots.exists():
  for line in a.snapshots.read_text().splitlines():
   if line.strip():raw.append(json.loads(line))
 selected=select_authoritative_rows(raw);alerts=sorted((alert for row in selected if(alert:=analyze(row))),key=lambda x:str(x.get("start_date")));sharp_state=json.loads(a.sharp_state.read_text())if a.sharp_state.exists()else{};moves=sharp_line_moves(sharp_state);tracked=len((sharp_state or{}).get("events",{}))
 availability=json.loads(a.availability.read_text())if a.availability.exists()else{}
 steam_alerts=steam_reversal_alerts(moves,availability=availability)
 payload={"meta":{"version":"thi-rlm-monitor-v1.4","generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"status":"line_monitoring"if tracked else"source_pending","rlm_status":"monitoring"if selected else"public_splits_pending","sharp_line_status":"monitoring"if tracked else"api_key_pending","alert_count":len(alerts),"sharp_move_count":len(moves),"steam_reversal_alert_count":len(steam_alerts),"steam_context_hold_count":sum(row.get("action_status")=="context_hold" for row in steam_alerts),"sharp_tracked_event_count":tracked,"qualified_event_count":len(selected),"sharp_book_policy":{"primary":"Pinnacle","fallback":"BetOnline","rejected_as_sharp_reference":["DraftKings","FanDuel","Caesars","BetMGM"]},"free_source":{"provider":"The Odds API","monthly_credits":500,"polls_per_day":6,"historical_odds":False},"minimum_ticket_pct":65,"minimum_move_points":.5,"steam_reversal_threshold_points":3.0,"requirements":["Ticket percentage and side from a licensed splits source before any RLM label","Opening and current spread from the same named sharp book","Pinnacle is required when present; BetOnline is used only when Pinnacle is absent","No sharp-money claim from line movement alone","Steam triggers remain research observations, but the public fade label is held when material sourced availability overlaps the move","No alert when required inputs are absent"]},"sharp_line_moves":moves,"steam_reversal_alerts":steam_alerts,"alerts":alerts}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(payload,indent=2)+"\n");print(len(alerts))
if __name__=="__main__":main()
