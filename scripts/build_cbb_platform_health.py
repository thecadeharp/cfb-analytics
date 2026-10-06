#!/usr/bin/env python3
"""Publish actionable CBB data-quality checks."""
import argparse,json
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; VERSION="thi-cbb-platform-health-v1.0"
def build(board,profiles,players,tracking,operations,foundation=None,readiness=None):
 foundation=foundation or {}; readiness=readiness or {}; games=board.get("games",[]); ids=[str(g.get("game_id")) for g in games]; teams=profiles.get("teams",[]); team_ids=[str(t.get("team_id")) for t in teams]; finals=[g for g in games if str(g.get("status","")).lower() in {"final","completed","complete"}]
 roster_errors=(foundation.get("coverage") or {}).get("roster_fetch_errors",0)
 checks={"unique_games":len(ids)==len(set(ids)),"unique_teams":len(team_ids)==len(set(team_ids)),"team_directory_complete":len(teams)>=300,"active_roster_coverage":len(players.get("players",[]))>=1500,"source_requests_completed":roster_errors==0,"final_scores_complete":all((g.get("home") or {}).get("score") is not None and (g.get("away") or {}).get("score") is not None for g in finals),"finals_reconciled_to_tracking":len(tracking.get("spread_decisions",[]))<=len(finals),"travel_context_matches_board":len(operations.get("games",[]))==len(games),"game_day_contract_ready":not readiness or (readiness.get("meta") or {}).get("status")=="ready"}
 notices=[]
 if not any(g.get("market") for g in games):notices.append("No current market lines are posted; this is expected before books open and becomes actionable near tipoff.")
 if (operations.get("coverage") or {}).get("sides_with_verified_mileage",0)==0:notices.append("Away and neutral travel mileage is awaiting the verified coordinate registry; no distance adjustment is applied.")
 if (operations.get("coverage") or {}).get("verified_availability_reports",0)==0:notices.append("No timestamped availability reports are loaded; no injury adjustment is applied.")
 return {"meta":{"version":VERSION,"generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"status":"healthy" if all(checks.values()) else "attention_required"},"checks":checks,"coverage":{"games":len(games),"finals":len(finals),"teams":len(teams),"players":len(players.get("players",[])),"games_with_market":sum(bool(g.get("market")) for g in games),"games_with_broadcast":sum(bool(g.get("broadcasts")) for g in games),**(operations.get("coverage") or {})},"alerts":[k for k,v in checks.items() if not v],"notices":notices}
def main():
 p=argparse.ArgumentParser();p.add_argument("--root",type=Path,default=ROOT/"data/cbb");a=p.parse_args();load=lambda n:json.loads((a.root/n).read_text());x=build(load("projection_board.json"),load("team_profiles.json"),load("player_ratings.json"),load("model_tracking.json"),load("operations_context.json"),load("foundation_status.json"),load("game_day_readiness.json"));(a.root/"platform_health.json").write_text(json.dumps(x,indent=2)+"\n");print(VERSION,x["meta"]["status"])
if __name__=="__main__":main()
