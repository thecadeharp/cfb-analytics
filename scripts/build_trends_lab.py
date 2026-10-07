#!/usr/bin/env python3
"""Build THI's reproducible CFB/CBB Variance Lab and evidence registry."""
from __future__ import annotations
import argparse,csv,gzip,json,math
from datetime import datetime,timezone
from pathlib import Path
from typing import Any,Callable
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1];VERSION="thi-variance-systems-lab-v2.0";ACADEMIES={"Army","Navy","Air Force"};EASTERN=ZoneInfo("America/New_York")
def num(v:Any)->float|None:
 try:v=float(v);return v if math.isfinite(v) else None
 except(TypeError,ValueError):return None
def iso(v):
 try:return datetime.fromisoformat(str(v).replace("Z","+00:00"))
 except(TypeError,ValueError):return None
def evidence_state(n,w,roi):
 if not n:return "source_pending"
 significant=(w/n-.5)/math.sqrt(.25/n)>=1.96
 if n>=200 and (roi or 0)>0 and significant:return "verified"
 if n>=75 and (roi or 0)<=0:return "failed_hypothesis"
 return "developing"
def system(rows,name,rule,select:Callable[[dict[str,Any]],bool],market,side="home",source_note="THI historical warehouse",family="situational"):
 w=l=p=0;seasons=set()
 for r in rows:
  if not select(r):continue
  margin,total,spread,market_total=map(num,(r.get("margin"),r.get("total"),r.get("spread"),r.get("market_total")))
  if market=="ats":
   if margin is None or spread is None:continue
   result=margin+spread;result=-result if side=="away" else result
  else:
   if total is None or market_total is None:continue
   result=market_total-total if market=="under" else total-market_total
  if abs(result)<.001:p+=1
  elif result>0:w+=1
  else:l+=1
  seasons.add(int(r["season"]))
 n=w+l;rate=round(100*w/n,1)if n else None;roi=round(100*(w-l*1.1)/(1.1*n),1)if n else None
 return {"id":name.lower().replace("&","and").replace(" ","-").replace("/","-"),"name":name,"description":rule,"family":family,"market":"ATS"if market=="ats"else market.title(),"wins":w,"losses":l,"pushes":p,"decisions":n,"hit_rate":rate,"roi_pct_at_minus_110":roi,"seasons":sorted(seasons),"state":evidence_state(n,w,roi),"source_note":source_note}
def context_index(path):
 if not path.exists():return {}
 return {f"{x.get('sport')}:{x['game_id']}":x for x in json.loads(path.read_text()).get("games",[])}
def cfb_rows(path,ctx):
 out=[]
 with path.open(newline="")as h:
  for r in csv.DictReader(h):
   if str(r.get("completed")).lower()!="true":continue
   joined=ctx.get(f"cfb:{r.get('game_id')}",{})
   out.append({"game_id":str(r.get("game_id")),"season":int(r["season"]),"week":int(float(r.get("week")or 0)),"home_team":r.get("home_team"),"away_team":r.get("away_team"),"margin":num(r.get("actual_home_margin")),"total":num(r.get("actual_total")),"spread":num(r.get("market_home_spread")),"market_total":num(r.get("market_total")),**joined})
 return out
def cbb_rows(history,ctx):
 out=[]
 for p in sorted(history.glob("season_*.json.gz")):
  payload=json.load(gzip.open(p,"rt"));season=int(payload["meta"]["season"])
  for g in payload.get("games",[]):
   m=g.get("market")or{};o=g.get("outcome")or{};started=iso(g.get("start_date"));et=started.astimezone(EASTERN)if started else None;joined=ctx.get(f"cbb:{g.get('game_id')}",{})
   out.append({"game_id":str(g.get("game_id")),"season":season,"start_date":g.get("start_date"),"month":et.month if et else None,"eastern_hour":et.hour+et.minute/60 if et else None,"home_team":g.get("home_team"),"away_team":g.get("away_team"),"margin":num(o.get("home_margin")),"total":num(o.get("total_points")),"spread":num(m.get("home_spread_close")),"market_total":num(m.get("total_close")),"open_spread":num(m.get("home_spread_open")),"neutral":bool(g.get("neutral_site")),"conference":bool(g.get("conference_game")),**joined})
 return out
def cfb_systems(r):
 cards=[system(r,"Massive home favorites","Home favorites laying 45 points or more",lambda x:num(x.get("spread"))is not None and x["spread"]<=-45,"ats"),system(r,"Home dogs vs. road favorites","Home underdogs catching points against any road favorite",lambda x:num(x.get("spread"))is not None and x["spread"]>0,"ats"),system(r,"Service academy matchups","Under when two of Army, Navy and Air Force face each other",lambda x:x.get("home_team")in ACADEMIES and x.get("away_team")in ACADEMIES,"under"),system(r,"Opening-week unders","Under in Weeks 0–1",lambda x:(x.get("week")or 0)<=1,"under"),system(r,"High-total unders","Under when the closing total is 60 or higher",lambda x:(num(x.get("market_total"))or-999)>=60,"under")]
 if any(x.get("eastern_hour")is not None for x in r):cards += [system(r,"Primetime unders","Under in games kicking at 7:00 p.m. ET or later",lambda x:(num(x.get("eastern_hour"))or-1)>=19,"under",family="time"),system(r,"Primetime home dogs","Home underdog ATS in games kicking at 7:00 p.m. ET or later",lambda x:(num(x.get("eastern_hour"))or-1)>=19 and(num(x.get("spread"))or 0)>0,"ats",family="time")]
 if any(x.get("home_classification")for x in r):cards += [system(r,"P4 at G5 home dogs","G5 campus home underdogs hosting P4 opponents",lambda x:x.get("home_classification")=="g5"and x.get("away_classification")=="p4"and(num(x.get("spread"))or 0)>0,"ats",family="classification"),system(r,"P4 vs FCS massive favorites","P4 home favorites of 35+ against FCS opponents",lambda x:x.get("home_classification")=="p4"and x.get("away_classification")=="fcs"and(num(x.get("spread"))or 0)<=-35,"ats",family="classification")]
 if any(x.get("home_rank")or x.get("away_rank")for x in r):cards.append(system(r,"Unranked home dogs vs ranked visitors","Unranked home underdog ATS against a ranked road team using the pregame poll",lambda x:not x.get("home_rank")and x.get("away_rank")and(num(x.get("spread"))or 0)>0,"ats",family="ranking"))
 if any(x.get("wind_mph")is not None for x in r):cards += [system(r,"High-wind unders","Under with sustained kickoff wind of at least 15 mph",lambda x:not x.get("indoor")and(num(x.get("wind_mph"))or-1)>=15,"under",family="weather"),system(r,"Extreme-heat overs","Over with kickoff temperature above 90°F",lambda x:not x.get("indoor")and(num(x.get("temperature_f"))or-999)>90,"over",family="weather"),system(r,"Measurable-precipitation unders","Under with measurable rain or snow at kickoff",lambda x:not x.get("indoor")and(num(x.get("precipitation"))or 0)>0,"under",family="weather")]
 return cards
def cbb_systems(r):
 cards=[system(r,"Double-digit road underdogs","Away underdogs catching 10 points or more",lambda x:num(x.get("spread"))is not None and x["spread"]<=-10,"ats","away","All qualifiers; no public-ticket condition is available."),system(r,"Sub-130 totals","Under when the closing total is below 130",lambda x:(num(x.get("market_total"))or 999)<130,"under",source_note="Blind-Under test; the cited system used the majority bettor's chosen side."),system(r,"November nonconference home favorites","Home favorites in November nonconference campus games",lambda x:x.get("month")==11 and not x.get("conference")and not x.get("neutral")and(num(x.get("spread"))or 0)<0,"ats"),system(r,"November nonconference home dogs","Home underdogs in November nonconference campus games",lambda x:x.get("month")==11 and not x.get("conference")and not x.get("neutral")and(num(x.get("spread"))or 0)>0,"ats"),system(r,"Home-side closing support","Home side ATS when the spread moves 1.5+ points toward home",lambda x:num(x.get("open_spread"))is not None and num(x.get("spread"))is not None and x["spread"]-x["open_spread"]<=-1.5,"ats",source_note="Line movement only; not RLM without public percentages.",family="market"),system(r,"Conference unders","Under in conference games",lambda x:x.get("conference")is True,"under"),system(r,"Primetime unders","Under in games tipping at 7:00 p.m. ET or later",lambda x:(num(x.get("eastern_hour"))or-1)>=19,"under",family="time"),system(r,"Primetime home dogs","Home underdog ATS in games tipping at 7:00 p.m. ET or later",lambda x:(num(x.get("eastern_hour"))or-1)>=19 and(num(x.get("spread"))or 0)>0,"ats",family="time")]
 if any(x.get("home_rank")or x.get("away_rank")for x in r):cards.append(system(r,"Unranked home dogs vs ranked visitors","Unranked home underdog ATS against a ranked road team using the pregame poll",lambda x:not x.get("home_rank")and x.get("away_rank")and(num(x.get("spread"))or 0)>0,"ats",family="ranking"))
 return cards
def sections(cards):return {s:[x for x in cards if x["state"]==s]for s in("verified","developing","failed_hypothesis","source_pending")}
def build(cfb,cbb,meta=None):
 meta=meta or {}
 a,b=cfb_systems(cfb),cbb_systems(cbb)
 backlog=[{"name":"CFB kickoff-time systems","status":meta.get("cfb_games_status","source_pending"),"path":"CFBD historical start times; 7:00 p.m. ET threshold frozen before testing."},{"name":"Pregame ranking systems","status":meta.get("rankings_status","source_pending"),"path":"Poll published before the game; final-season rankings are prohibited."},{"name":"P4 / G5 / FCS systems","status":meta.get("classifications_status","source_pending"),"path":"Season-specific conference and subdivision labels joined by game ID."},{"name":"Historical weather systems","status":meta.get("weather_status","source_pending"),"path":"Kickoff wind, temperature and precipitation; indoor games excluded."},{"name":"External systems intake · Trendsperts","status":"source_pending","path":"Public rule definitions are leads only. THI independently rebuilds the sample, line convention, price, holdout and prospective record before publication. The current Discover board exposes four CFB cards and no CBB cards."},{"name":"Coach and prior-meeting systems","status":"source_pending","path":"The visible Trendsperts CFB lead uses coach identity, home-favorite status and previous-meeting result. THI needs chronological coach-tenure and prior-matchup joins before an honest backtest; a 13-game outside sample is not promoted."},{"name":"True reverse line movement","status":"source_pending","path":"Requires synchronized ticket percentages and sharp-book price snapshots."}]
 return {"meta":{"version":VERSION,"generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"policy":"Rules are frozen before evaluation. Every settled qualifier publishes, including losing hypotheses. Verified requires 200 decisions, positive -110 ROI and a 95% separation from 50%."},"sports":{"cfb":{"settled_games":len(cfb),"cards":a,"sections":sections(a)},"cbb":{"settled_games":len(cbb),"cards":b,"sections":sections(b)}},"source_backlog":backlog}
def main():
 p=argparse.ArgumentParser();p.add_argument("--output",type=Path,default=ROOT/"data/trends_lab.json");p.add_argument("--context",type=Path,default=ROOT/"data/variance/context.json");a=p.parse_args();ctx=context_index(a.context);meta=json.loads(a.context.read_text()).get("meta",{})if a.context.exists()else{};payload=build(cfb_rows(ROOT/"data/training/historical_games.csv",ctx),cbb_rows(ROOT/"data/cbb/history",ctx),meta);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(payload,indent=2,allow_nan=False)+"\n");print(VERSION)
if __name__=="__main__":main()
