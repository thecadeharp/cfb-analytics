#!/usr/bin/env python3
"""Build THI's reproducible CFB/CBB situational systems laboratory."""
from __future__ import annotations
import argparse,csv,gzip,json
from datetime import datetime,timezone
from pathlib import Path
from typing import Any,Callable
ROOT=Path(__file__).resolve().parents[1];VERSION="thi-variance-systems-lab-v1.1";ACADEMIES={"Army","Navy","Air Force"}
def num(v:Any)->float|None:
 try:x=float(v);return x if x==x else None
 except(TypeError,ValueError):return None
def system(rows:list[dict[str,Any]],name:str,rule:str,select:Callable[[dict[str,Any]],bool],market:str,side:str="home",source_note:str="THI historical warehouse")->dict[str,Any]:
 wins=losses=pushes=0;seasons=set()
 for r in rows:
  if not select(r):continue
  margin,total,spread,market_total=map(num,(r.get("margin"),r.get("total"),r.get("spread"),r.get("market_total")))
  if market=="ats":
   if margin is None or spread is None:continue
   result=margin+spread
   if side=="away":result=-result
  else:
   if total is None or market_total is None:continue
   result=(market_total-total) if market=="under" else(total-market_total)
  if abs(result)<.001:pushes+=1
  elif result>0:wins+=1
  else:losses+=1
  seasons.add(int(r["season"]))
 decisions=wins+losses;rate=round(100*wins/decisions,1) if decisions else None;roi=round(100*(wins-losses*1.1)/(1.1*decisions),1) if decisions else None
 return {"name":name,"description":rule,"market":"ATS" if market=="ats" else market.title(),"wins":wins,"losses":losses,"pushes":pushes,"decisions":decisions,"hit_rate":rate,"roi_pct_at_minus_110":roi,"seasons":sorted(seasons),"state":"qualified" if decisions>=200 else("developing" if decisions>=75 else"limited_sample"),"source_note":source_note}
def cfb_rows(path:Path)->list[dict[str,Any]]:
 out=[]
 with path.open(newline="") as h:
  for r in csv.DictReader(h):
   if str(r.get("completed")).lower()!="true":continue
   out.append({"season":int(r["season"]),"week":int(float(r.get("week")or 0)),"home_team":r.get("home_team"),"away_team":r.get("away_team"),"margin":num(r.get("actual_home_margin")),"total":num(r.get("actual_total")),"spread":num(r.get("market_home_spread")),"market_total":num(r.get("market_total"))})
 return out
def cbb_rows(history:Path)->list[dict[str,Any]]:
 out=[]
 for p in sorted(history.glob("season_*.json.gz")):
  payload=json.load(gzip.open(p,"rt"));season=int(payload["meta"]["season"])
  for g in payload.get("games",[]):
   m=g.get("market")or{};o=g.get("outcome")or{};start=str(g.get("start_date")or"")
   out.append({"season":season,"month":int(start[5:7]) if len(start)>=7 else None,"home_team":g.get("home_team"),"away_team":g.get("away_team"),"margin":num(o.get("home_margin")),"total":num(o.get("total_points")),"spread":num(m.get("home_spread_close")),"market_total":num(m.get("total_close")),"open_spread":num(m.get("home_spread_open")),"neutral":bool(g.get("neutral_site")),"conference":bool(g.get("conference_game"))})
 return out
def cfb_systems(r):return[
 system(r,"Massive home favorites","Home favorites laying 45 points or more",lambda x:num(x.get("spread"))is not None and x["spread"]<=-45,"ats",source_note="Opponent classification is not yet joined."),
 system(r,"Home dogs vs. road favorites","Home underdogs catching points against any road favorite",lambda x:num(x.get("spread"))is not None and x["spread"]>0,"ats"),
 system(r,"Service academy matchups","Under when two of Army, Navy and Air Force face each other",lambda x:x.get("home_team")in ACADEMIES and x.get("away_team")in ACADEMIES,"under"),
 system(r,"Opening-week unders","Under in Weeks 0–1",lambda x:(x.get("week")or 0)<=1,"under"),
 system(r,"High-total unders","Under when the closing total is 60 or higher",lambda x:(num(x.get("market_total")) or -999)>=60,"under")]
def cbb_systems(r):return[
 system(r,"Double-digit road underdogs","Away underdogs catching 10 points or more",lambda x:num(x.get("spread"))is not None and x["spread"]<=-10,"ats","away",source_note="All qualifiers; no public-ticket condition is available."),
 system(r,"Sub-130 totals","Under when the closing total is below 130",lambda x:(num(x.get("market_total")) or 999)<130,"under",source_note="Blind-Under test; the cited VSiN rule used the majority bettor's chosen side."),
 system(r,"November nonconference home favorites","Home favorites in November nonconference campus games",lambda x:x.get("month")==11 and not x.get("conference")and not x.get("neutral")and(num(x.get("spread"))or 0)<0,"ats"),
 system(r,"November nonconference home dogs","Home underdogs in November nonconference campus games",lambda x:x.get("month")==11 and not x.get("conference")and not x.get("neutral")and(num(x.get("spread"))or 0)>0,"ats"),
 system(r,"Home-side closing support","Home side ATS when the spread moves 1.5+ points toward home",lambda x:num(x.get("open_spread"))is not None and num(x.get("spread"))is not None and x["spread"]-x["open_spread"]<=-1.5,"ats",source_note="Line movement only; not reverse line movement without public percentages."),
 system(r,"Conference unders","Under in conference games",lambda x:x.get("conference")is True,"under")]
def build(cfb,cbb):return {"meta":{"version":VERSION,"generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"policy":"Every system is recomputed from THI's settled games and closing lines. Samples and estimated -110 ROI publish even when a popular hypothesis fails."},"sports":{"cfb":{"settled_games":len(cfb),"cards":cfb_systems(cfb)},"cbb":{"settled_games":len(cbb),"cards":cbb_systems(cbb)}},"source_backlog":[{"name":"Primetime systems","status":"requires_historical_start_times","path":"Join verified kickoff/tip times and define the window before testing."},{"name":"Ranked vs. unranked","status":"requires_point_in_time_polls","path":"Join the poll released before each game, never final-season ranks."},{"name":"P4 vs. G5/FCS","status":"requires_historical_conference_membership","path":"Join season-specific conference and division membership."},{"name":"Wind and heat","status":"requires_historical_game_weather","path":"Join stadium coordinates and weather at kickoff."},{"name":"Public handle and tickets","status":"requires_licensed_splits_feed","path":"A closing line alone cannot identify reverse line movement or public fades."}]}
def main():
 p=argparse.ArgumentParser();p.add_argument("--output",type=Path,default=ROOT/"data/trends_lab.json");a=p.parse_args();x=build(cfb_rows(ROOT/"data/training/historical_games.csv"),cbb_rows(ROOT/"data/cbb/history"));a.output.write_text(json.dumps(x,indent=2,allow_nan=False)+"\n");print(VERSION)
if __name__=="__main__":main()
