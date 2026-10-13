#!/usr/bin/env python3
"""Validate the timestamped CBB availability registry."""
from __future__ import annotations
import argparse,json
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STATUSES={"out","doubtful","questionable","probable","available","suspended","personal","game_time_decision"}

def timestamp(value):
    try:return datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except (TypeError,ValueError):return None

def validate(payload):
    errors=[]; seen=set()
    for index,row in enumerate(payload.get("reports") or []):
        required=("game_id","team_id","player_id","player","status","verified_source_url","verified_at_utc","expires_at_utc")
        missing=[key for key in required if row.get(key) in (None,"")]
        if missing:errors.append(f"row {index}: missing {','.join(missing)}")
        if row.get("status") not in STATUSES:errors.append(f"row {index}: unsupported status")
        verified,expires=timestamp(row.get("verified_at_utc")),timestamp(row.get("expires_at_utc"))
        if not verified or not expires or expires<=verified:errors.append(f"row {index}: invalid verification window")
        key=(str(row.get("game_id")),str(row.get("player_id")))
        if key in seen:errors.append(f"row {index}: duplicate game/player report")
        seen.add(key)
        if row.get("model_adjustment") is not None:errors.append(f"row {index}: model adjustment must remain null")
    return errors

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--input",type=Path,default=ROOT/"data/cbb/verified_availability.json");args=parser.parse_args()
    errors=validate(json.loads(args.input.read_text()))
    if errors:raise SystemExit("\n".join(errors))
    print(f"CBB availability registry valid: {args.input}")
if __name__=="__main__":main()
