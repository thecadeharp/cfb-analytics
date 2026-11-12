#!/usr/bin/env python3
"""Build coach ATS profiles only from explicitly verified tenure records."""
from __future__ import annotations

import argparse
import gzip
import json
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.build_cbb_situational_profiles import finite, summarize
except ModuleNotFoundError:
    from build_cbb_situational_profiles import finite, summarize

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-coach-profiles-v1.0"


def build(predictions: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    verified = [row for row in verification.get("tenures") or [] if row.get("source_url") and row.get("verified_at") and row.get("coach")]
    stores: dict[str, dict[str, Any]] = {}
    for tenure in verified:
        key = str(tenure.get("tenure_id") or f"{tenure.get('team_id')}:{tenure.get('coach')}")
        stores[key] = {**tenure, "segments": defaultdict(list)}
    for game in predictions.get("games") or []:
        spread, margin, season = finite(game.get("market_home_spread")), finite(game.get("actual_home_margin")), int(game.get("season") or 0)
        if spread is None or margin is None:
            continue
        for side, sign in (("home", 1.0), ("away", -1.0)):
            team_id = str(game.get(f"{side}_team_id"))
            match = next((row for row in stores.values() if str(row.get("team_id")) == team_id and int(row.get("start_season") or 0) <= season <= int(row.get("end_season") or 9999)), None)
            if not match:
                continue
            value = sign * (margin + spread)
            team_spread = spread if side == "home" else -spread
            match["segments"]["overall"].append(value)
            match["segments"]["neutral" if game.get("neutral_site") else side].append(value)
            match["segments"]["favorite" if team_spread < 0 else "underdog" if team_spread > 0 else "pickem"].append(value)
            match["segments"]["conference" if game.get("conference_game") else "nonconference"].append(value)
    coaches = []
    for row in stores.values():
        coaches.append({key: row.get(key) for key in ("tenure_id", "team_id", "team", "coach", "start_season", "end_season", "source_url", "verified_at")} | {"splits": {key: summarize(values) for key, values in sorted(row["segments"].items())}})
    return {"meta": {"version": VERSION, "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "status": "verified_profiles_available" if coaches else "awaiting_verified_tenures", "policy": "Coach labels are published only when the tenure source and verification timestamp are present. Program history is never relabeled as coach history."}, "coaches": coaches}


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False); handle.write("\n"); temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, default=ROOT / "data/cbb/model/walk_forward_predictions.json.gz")
    parser.add_argument("--tenures", type=Path, default=ROOT / "data/cbb/verified_coach_tenures.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/cbb/coach_profiles.json")
    args = parser.parse_args()
    with gzip.open(args.predictions, "rt", encoding="utf-8") as handle: predictions = json.load(handle)
    verification = json.loads(args.tenures.read_text()) if args.tenures.exists() else {"tenures": []}
    payload = build(predictions, verification); atomic_write(args.output, payload)
    print(f"{VERSION}: {len(payload['coaches'])} verified coach profiles")


if __name__ == "__main__": main()
