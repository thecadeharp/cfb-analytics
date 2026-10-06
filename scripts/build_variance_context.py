#!/usr/bin/env python3
"""Cache point-in-time CFB context used by Variance Lab; never guess missing fields."""
from __future__ import annotations
import argparse,gzip,json,os,sys,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1];CFB_BASE="https://api.collegefootballdata.com";CBB_BASE="https://api.collegebasketballdata.com";P4={"ACC","Big 12","Big Ten","SEC","Pac-12"}
def fetch(path,params,key,base=CFB_BASE):
 req=Request(f"{base}{path}?{urlencode(params)}",headers={"Authorization":f"Bearer {key}","User-Agent":"THI-Variance-Lab/2.0"})
 for i,wait in enumerate((0,2,5)):
  if wait:time.sleep(wait)
  try:
   with urlopen(req,timeout=45)as response:return json.load(response)
  except Exception:
   if i==2:raise
def poll_map(rows):
 out={}
 for week in rows:
  w=int(week.get("week")or 0);ap=next((p for p in week.get("polls",[])if str(p.get("poll","")).lower()in{"ap top 25","ap poll"}),None)
  for rank in(ap or{}).get("ranks",[]):out[(w,rank.get("school"))]=int(rank.get("rank"))
 return out
def group(conf,raw):
 raw=str(raw or"").lower()
 if raw=="fcs":return"fcs"
 if conf in P4:return"p4"
 if raw=="fbs":return"g5"
 return raw or None
def utc_datetime(value):
 date=datetime.fromisoformat(str(value).replace("Z","+00:00"))
 return date.replace(tzinfo=timezone.utc)if date.tzinfo is None else date.astimezone(timezone.utc)
def cbb_ranked_games(key,start_season,end_season):
 output=[];successful=[];failed=[]
 for path in sorted((ROOT/"data/cbb/history").glob("season_*.json.gz")):
  payload=json.load(gzip.open(path,"rt"));season=int(payload["meta"]["season"])
  if season<start_season or season>end_season:continue
  try:rows=fetch("/rankings",{"season":season,"pollType":"ap"},key,CBB_BASE);successful.append(season)
  except Exception as exc:
   failed.append({"season":season,"error":f"{type(exc).__name__}: {exc}"});print(f"CBB rankings unavailable for {season}: {exc}",file=sys.stderr);continue
  by_team={}
  for row in rows:
   poll_type=str(row.get("pollType")or row.get("poll_type")or"").lower()
   if poll_type and "ap"not in poll_type:continue
   try:date=utc_datetime(row.get("pollDate")or row.get("poll_date"));ranking=int(row.get("ranking")or row.get("rank"));team=row.get("team")
   except (TypeError,ValueError):continue
   if team:by_team.setdefault(team,[]).append((date,ranking))
  for values in by_team.values():values.sort()
  for game in payload.get("games",[]):
   try:start=utc_datetime(game.get("start_date"))
   except (TypeError,ValueError):continue
   def rank(team):
    eligible=[value for date,value in by_team.get(team,[])if date<=start]
    return eligible[-1]if eligible else None
   output.append({"game_id":str(game.get("game_id")),"sport":"cbb","season":season,"home_rank":rank(game.get("home_team")),"away_rank":rank(game.get("away_team"))})
 return output,successful,failed
def main():
 p=argparse.ArgumentParser();p.add_argument("--start-season",type=int,default=2019);p.add_argument("--end-season",type=int,default=2026);p.add_argument("--output",type=Path,default=ROOT/"data/variance/context.json");a=p.parse_args();key=os.environ.get("CFBD_API_KEY","").strip();cbb_key=os.environ.get("CBBD_API_KEY","").strip()
 if not key or not cbb_key:raise SystemExit("CFBD_API_KEY and CBBD_API_KEY are required")
 games=[];weather_ok=rankings_ok=True
 for season in range(a.start_season,a.end_season+1):
  season_games=fetch("/games",{"year":season},key)
  try:ranks=poll_map(fetch("/rankings",{"year":season},key))
  except Exception:ranks={};rankings_ok=False
  try:weather={str(x.get("id")):x for x in fetch("/games/weather",{"year":season},key)}
  except Exception:weather={};weather_ok=False
  for g in season_games:
   gid=str(g.get("id"));wx=weather.get(gid,{});start=g.get("startDate");hour=None
   try:
    from zoneinfo import ZoneInfo
    dt=datetime.fromisoformat(start.replace("Z","+00:00")).astimezone(ZoneInfo("America/New_York"));hour=dt.hour+dt.minute/60
   except Exception:pass
   week=int(g.get("week")or 0);hr=ranks.get((week,g.get("homeTeam")),ranks.get((max(0,week-1),g.get("homeTeam"))));ar=ranks.get((week,g.get("awayTeam")),ranks.get((max(0,week-1),g.get("awayTeam"))))
   games.append({"game_id":gid,"sport":"cfb","season":season,"start_date":start,"eastern_hour":hour,"home_conference":g.get("homeConference"),"away_conference":g.get("awayConference"),"home_classification":group(g.get("homeConference"),g.get("homeClassification")),"away_classification":group(g.get("awayConference"),g.get("awayClassification")),"home_rank":hr,"away_rank":ar,"indoor":wx.get("gameIndoors"),"temperature_f":wx.get("temperature"),"wind_mph":wx.get("windSpeed"),"precipitation":wx.get("precipitation"),"weather_condition":wx.get("weatherCondition")})
 try:cbb_games,cbb_ranking_seasons,cbb_ranking_failures=cbb_ranked_games(cbb_key,a.start_season,a.end_season)
 except Exception as exc:
  cbb_games=[];cbb_ranking_seasons=[];cbb_ranking_failures=[{"error":f"{type(exc).__name__}: {exc}"}];rankings_ok=False
 if cbb_ranking_failures or not cbb_ranking_seasons:rankings_ok=False
 games.extend(cbb_games)
 cbb_ranked_count=sum(bool(g.get("home_rank")or g.get("away_rank"))for g in cbb_games)
 payload={"meta":{"version":"thi-variance-context-v1.0","generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"cfb_games_status":"ready","classifications_status":"ready","rankings_status":"ready"if rankings_ok else"partial","weather_status":"ready"if weather_ok else"partial","cbb_context_games":len(cbb_games),"cbb_ranked_games":cbb_ranked_count,"cbb_ranking_seasons":cbb_ranking_seasons,"cbb_ranking_failures":cbb_ranking_failures,"game_count":len(games)},"games":games};a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(payload,indent=2)+"\n");print(len(games))
if __name__=="__main__":main()
