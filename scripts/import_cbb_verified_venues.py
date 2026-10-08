#!/usr/bin/env python3
"""Import source-cited CBB venue coordinates into the verified registry."""
from __future__ import annotations
import argparse,csv,json
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FIELDS=("venue_name","city","state","latitude","longitude","source_url","verified_at_utc")
def rows(path):
 if path.suffix.lower()==".json":
  data=json.loads(path.read_text()); return data.get("venues",data) if isinstance(data,dict) else data
 with path.open(newline="",encoding="utf-8-sig") as h:return list(csv.DictReader(h))
def validate(items):
 out={};errors=[]
 for i,row in enumerate(items,2):
  missing=[k for k in FIELDS if str(row.get(k) or "").strip()==""]
  if missing:errors.append(f"row {i}: missing {', '.join(missing)}");continue
  try:lat=float(row["latitude"]);lon=float(row["longitude"]);datetime.fromisoformat(str(row["verified_at_utc"]).replace("Z","+00:00"))
  except Exception:errors.append(f"row {i}: invalid coordinates or verification timestamp");continue
  if not(-90<=lat<=90 and -180<=lon<=180):errors.append(f"row {i}: coordinates out of range");continue
  if not str(row["source_url"]).startswith("https://"):errors.append(f"row {i}: source_url must use https");continue
  key="|".join(str(row[k]).strip() for k in ("venue_name","city","state"))
  if key in out:errors.append(f"row {i}: duplicate venue key {key}");continue
  out[key]={"latitude":lat,"longitude":lon,"source_url":row["source_url"],"verified_at_utc":row["verified_at_utc"]}
 if errors:raise ValueError("\n".join(errors))
 return out
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("input",type=Path);p.add_argument("--output",type=Path,default=ROOT/"data/cbb/verified_venue_geocodes.json");a=p.parse_args();venues=validate(rows(a.input));payload={"meta":{"version":"thi-cbb-verified-venues-v1.0","generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"status":"active" if venues else "source_required","policy":"Coordinates require a source URL and verification timestamp. City centroids and inferred coordinates are prohibited."},"venues":venues};a.output.write_text(json.dumps(payload,indent=2)+"\n");print(len(venues))
