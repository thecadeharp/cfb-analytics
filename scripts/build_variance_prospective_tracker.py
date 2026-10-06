#!/usr/bin/env python3
"""Append future qualifiers to an immutable prospective systems ledger."""
import json
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/"data/variance/prospective_tracker.json";ET=ZoneInfo("America/New_York")
def load(p,d):
 try:return json.loads(p.read_text())
 except FileNotFoundError:return d
def main():
 now=datetime.now(timezone.utc);old=load(OUT,{"frozen":[]});by_id={x["freeze_id"]:x for x in old.get("frozen",[])}
 for sport,path in(("cfb",ROOT/"data/projections.json"),("cbb",ROOT/"data/cbb/projection_board.json")):
  for g in load(path,{"games":[]}).get("games",[]):
   try:start=datetime.fromisoformat(str(g.get("start_date")).replace("Z","+00:00"))
   except Exception:continue
   if start<=now or str(g.get("status","")).lower()not in{"scheduled","upcoming"}:continue
   et=start.astimezone(ET);market=g.get("market")or{};spread=market.get("home_spread");total=market.get("total");systems=[]
   if et.hour+et.minute/60>=19:
    if isinstance(total,(int,float)):systems.append("primetime-unders")
    if isinstance(spread,(int,float))and spread>0:systems.append("primetime-home-dogs")
   if sport=="cbb"and et.month==11 and not g.get("neutral_site")and not g.get("conference_game")and isinstance(spread,(int,float)):systems.append("november-nonconference-home-dogs"if spread>0 else"november-nonconference-home-favorites")
   home=(g.get("home")or{}).get("team");away=(g.get("away")or{}).get("team");gid=str(g.get("game_id"))
   for sid in systems:
    fid=f"{sport}:{gid}:{sid}";by_id.setdefault(fid,{"freeze_id":fid,"sport":sport,"game_id":gid,"system_id":sid,"start_date":g.get("start_date"),"away_team":away,"home_team":home,"spread_at_freeze":spread,"total_at_freeze":total,"frozen_at_utc":now.isoformat().replace("+00:00","Z"),"result":"pending"})
 payload={"meta":{"version":"thi-variance-prospective-v1.0","generated_at_utc":now.isoformat().replace("+00:00","Z"),"policy":"First eligible pregame capture is immutable; later snapshots never replace the frozen line."},"frozen":sorted(by_id.values(),key=lambda x:(x["start_date"],x["freeze_id"]))};OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,indent=2)+"\n");print(len(payload["frozen"]))
if __name__=="__main__":main()
