#!/usr/bin/env python3
"""Join canonical odds and public-split feeds and append synchronized RLM snapshots.

Each configured endpoint must return a JSON array (or {events:[...]}) keyed by
sport + event_id. Secrets stay in environment variables. This small boundary
lets THI use any licensed provider without coupling the research rule to one vendor.
"""
from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
try:from scripts.build_rlm_monitor import sharp_book_identity
except ModuleNotFoundError:from build_rlm_monitor import sharp_book_identity
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/"data/market/rlm_snapshots.jsonl"
def fetch(url,token):
 headers={"Accept":"application/json","User-Agent":"THI-RLM/1.0"}
 if token:headers["Authorization"]=f"Bearer {token}"
 with urlopen(Request(url,headers=headers),timeout=30)as r:payload=json.load(r)
 return payload.get("events",[])if isinstance(payload,dict)else payload
def captured(value):
 try:return datetime.fromisoformat(str(value).replace("Z","+00:00"))
 except Exception:return None
def main():
 odds_url=os.environ.get("THI_ODDS_FEED_URL","").strip();splits_url=os.environ.get("THI_SPLITS_FEED_URL","").strip()
 if not odds_url or not splits_url:raise SystemExit("THI_ODDS_FEED_URL and THI_SPLITS_FEED_URL are required")
 odds=fetch(odds_url,os.environ.get("THI_ODDS_FEED_TOKEN"));splits=fetch(splits_url,os.environ.get("THI_SPLITS_FEED_TOKEN"));split_index={(str(x.get("sport")),str(x.get("event_id"))):x for x in splits};now=datetime.now(timezone.utc).isoformat().replace("+00:00","Z");added=[]
 for market in odds:
  public=split_index.get((str(market.get("sport")),str(market.get("event_id"))))
  if not public:continue
  sharp_book=sharp_book_identity(market.get("book"))
  if not sharp_book:continue
  market_time=captured(market.get("captured_at_utc"));public_time=captured(public.get("captured_at_utc"))
  if not market_time or not public_time or abs((market_time-public_time).total_seconds())>300:continue
  added.append({"captured_at_utc":now,"odds_captured_at_utc":market.get("captured_at_utc"),"splits_captured_at_utc":public.get("captured_at_utc"),"sport":market.get("sport"),"event_id":market.get("event_id"),"start_date":market.get("start_date"),"away_team":market.get("away_team"),"home_team":market.get("home_team"),"sharp_book":sharp_book,"opening_home_spread":market.get("opening_home_spread"),"current_home_spread":market.get("current_home_spread"),"public_source":public.get("source"),"public_side":public.get("public_side"),"public_ticket_pct":public.get("public_ticket_pct"),"public_handle_pct":public.get("public_handle_pct")})
 OUT.parent.mkdir(parents=True,exist_ok=True)
 with OUT.open("a")as h:
  for row in added:h.write(json.dumps(row,separators=(",",":"))+"\n")
 print(len(added))
if __name__=="__main__":main()
