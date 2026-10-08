#!/usr/bin/env python3
"""Score a licensed weekly CFBD pack locally without publishing raw rows."""
from __future__ import annotations

import argparse, csv, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def number(value):
    try: return float(value)
    except (TypeError, ValueError): return None


def build(pack: Path, settled: dict, audit: dict) -> dict:
    with pack.open(newline="", encoding="utf-8-sig") as handle: source = list(csv.DictReader(handle))
    first = {}
    for row in settled.get("rows", []):
        key = str(row.get("game_key") or "")
        if key and (key not in first or str(row.get("captured_at_utc") or "") < str(first[key].get("captured_at_utc") or "")): first[key] = row
    evaluated = []
    for row in source:
        result = first.get(str(row.get("id") or ""))
        if not result or not result.get("result_settled"): continue
        actual = number(result.get("actual_home_margin")); opening = number(row.get("spread")); model = number(result.get("model_home_spread")); current = number(result.get("snapshot_home_spread"))
        if actual is None: continue
        evaluated.append({"actual": actual, "opening": opening, "model": model, "current": current})
    def mae(field):
        vals=[abs(x["actual"] + x[field]) for x in evaluated if x[field] is not None]
        return round(sum(vals)/len(vals),3) if vals else None
    total = len(source); done = len(evaluated)
    return {"meta":{"version":"thi-cfbd-weekly-challenger-scorecard-v1.0","generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"status":"COMPLETE" if done==total else ("IN_PROGRESS" if done else "AWAITING_RESULTS"),"raw_rows_published":False,"production_model_changed":False,"interpretation":"The licensed opening line is an evaluation baseline only. This report does not train or promote a model."},"scope":{"week":(audit.get("scope") or {}).get("weeks"),"games":total,"settled":done,"remaining":total-done,"source_audit_status":(audit.get("meta") or {}).get("status")},"mae_points":{"thi_frozen_model":mae("model"),"licensed_opening_market":mae("opening"),"thi_same_snapshot_market":mae("current")}}


if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("pack",type=Path); p.add_argument("--settled",type=Path,default=ROOT/"data/reports/settled_results.json"); p.add_argument("--audit",type=Path,default=ROOT/"data/research/cfbd_training_pack_audit.json"); p.add_argument("--output",type=Path,default=ROOT/"data/research/cfbd_weekly_challenger_scorecard.json"); a=p.parse_args()
    payload=build(a.pack,json.loads(a.settled.read_text()),json.loads(a.audit.read_text())); a.output.write_text(json.dumps(payload,indent=2,allow_nan=False)+"\n"); print(payload["meta"]["status"],payload["scope"])
