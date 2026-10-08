#!/usr/bin/env python3
"""Import timestamped, source-cited CBB availability reports."""
from __future__ import annotations
import argparse,csv,json
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];ALLOWED={"available","probable","questionable","doubtful","out","suspended","unknown"}
def source_rows(path):
 if path.suffix.lower()==".json":
  data=json.loads(path.read_text());return data.get("reports",data) if isinstance(data,dict) else data
 with path.open(newline="",encoding="utf-8-sig") as h:return list(csv.DictReader(h))
def validate(items,board):
 games={str(g.get("game_id")) for g in board.get("games",[])};out=[];errors=[];seen=set()
 for i,row in enumerate(items,2):
  gid=str(row.get("game_id") or "").strip();team=str(row.get("team") or "").strip();player=str(row.get("player") or "").strip();status=str(row.get("status") or "").strip().lower();url=str(row.get("verified_source_url") or row.get("source_url") or "").strip();stamp=str(row.get("verified_at_utc") or "").strip();key=(gid,team.lower(),player.lower())
  if gid not in games:errors.append(f"row {i}: unknown game_id {gid}")
  if not team or not player:errors.append(f"row {i}: team and player are required")
  if status not in ALLOWED:errors.append(f"row {i}: unsupported status {status}")
  if not url.startswith("https://"):errors.append(f"row {i}: verified source URL must use https")
  try:datetime.fromisoformat(stamp.replace("Z","+00:00"))
  except Exception:errors.append(f"row {i}: invalid verified_at_utc")
  if key in seen:errors.append(f"row {i}: duplicate game/team/player report")
  seen.add(key);out.append({"game_id":gid,"team":team,"player":player,"status":status,"note":str(row.get("note") or "").strip() or None,"verified_source_url":url,"verified_at_utc":stamp,"model_adjustment":None})
 if errors:raise ValueError("\n".join(errors))
 return out
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("input",type=Path);p.add_argument("--board",type=Path,default=ROOT/"data/cbb/projection_board.json");p.add_argument("--output",type=Path,default=ROOT/"data/cbb/verified_availability.json");a=p.parse_args();reports=validate(source_rows(a.input),json.loads(a.board.read_text()));payload={"meta":{"version":"thi-cbb-verified-availability-v1.0","generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"status":"active" if reports else "source_required","policy":"Every report requires a known game, player, team, status, HTTPS source and verification time. Reports are display-only and never create an automatic model adjustment."},"reports":reports};a.output.write_text(json.dumps(payload,indent=2)+"\n");print(len(reports))
