#!/usr/bin/env python3
"""Build one compact, deduplicated archive of frozen THI predictions."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(cfb: dict, cbb: dict) -> dict:
    first: dict[str, dict] = {}
    for row in cfb.get("rows", []):
        key = str(row.get("game_key") or row.get("snapshot_id"))
        stamp = str(row.get("captured_at_utc") or "")
        if key not in first or stamp < str(first[key].get("captured_at_utc") or ""):
            first[key] = row
    rows = []
    for key, row in first.items():
        rows.append({
            "sport": "cfb", "game_id": key, "captured_at_utc": row.get("captured_at_utc"),
            "start_date": row.get("start_date"), "week": row.get("week"),
            "away_team": row.get("away_team"), "home_team": row.get("home_team"),
            "model_version": row.get("model_version"), "model_home_spread": row.get("model_home_spread"),
            "model_total": row.get("model_total"), "market_home_spread": row.get("snapshot_home_spread"),
            "market_total": row.get("snapshot_total"), "market_book": row.get("snapshot_bookmaker"),
            "closing_home_spread": row.get("closing_home_spread"), "preferred_side": row.get("preferred_side"),
            "signal": row.get("signal"), "settled": bool(row.get("result_settled")),
            "home_points": row.get("home_points"), "away_points": row.get("away_points"),
            "ats_result": row.get("ats_result"), "total_result": row.get("total_result"),
            "clv_points": row.get("clv_points"), "model_abs_error": row.get("model_abs_error"),
        })
    for kind in ("spread_decisions", "total_decisions"):
        for row in cbb.get(kind, []):
            item = dict(row)
            item.update({"sport": "cbb", "decision_type": kind.replace("_decisions", "")})
            rows.append(item)
    rows.sort(key=lambda row: (str(row.get("start_date") or row.get("game_date") or ""), str(row.get("sport")), str(row.get("game_id") or "")))
    return {
        "meta": {
            "version": "thi-prediction-archive-v1.0",
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "definition": "One earliest frozen CFB snapshot per game plus every frozen CBB grading decision. Later model snapshots never replace the original forecast.",
            "rows": len(rows), "cfb_games": len(first), "cbb_decisions": len(rows) - len(first),
        },
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cfb", type=Path, default=ROOT / "data/reports/settled_results.json")
    parser.add_argument("--cbb", type=Path, default=ROOT / "data/cbb/model_tracking.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/reports/prediction_archive.json")
    args = parser.parse_args()
    payload = build(json.loads(args.cfb.read_text()), json.loads(args.cbb.read_text()))
    if args.output.exists():
        previous = json.loads(args.output.read_text())
        if previous.get("rows") == payload.get("rows"):
            print(previous.get("meta")); return
    args.output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(payload["meta"])


if __name__ == "__main__":
    main()
