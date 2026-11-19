#!/usr/bin/env python3
"""Publish a verifier-friendly, model-neutral THI forecast packet.

The packet is a projection of the already-public frozen Benchmark Center data.
It never selects, regrades, edits or promotes a forecast.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "reports" / "benchmark_center.json"
JSON_OUTPUT = ROOT / "data" / "reports" / "independent_benchmark_packet.json"
CSV_OUTPUT = ROOT / "data" / "reports" / "independent_benchmark_packet.csv"

FIELDS = [
    "season", "sport", "game_id", "date", "venue", "away_team", "home_team",
    "predicted_margin", "actual_margin", "margin_error", "predicted_total",
    "actual_total", "total_error", "home_win_probability", "brier", "signal",
    "preferred_side", "ats_result", "clv", "line_source", "model_version",
    "freeze_ts", "freeze_ts_status", "market_policy_version",
    "grading_policy_version", "env_status",
]


def main() -> None:
    source = json.loads(SOURCE.read_text())
    rows = [{field: row.get(field) for field in FIELDS} for row in source.get("observations", [])]
    rows.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("sport") or ""), str(row.get("game_id") or "")))
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "meta": {
            "version": "thi-independent-benchmark-packet-v1.0",
            "generated_at_utc": generated,
            "source_version": source.get("meta", {}).get("version"),
            "row_count": len(rows),
            "purpose": "Independent verification of frozen THI forecasts, results, calibration and market translation.",
            "immutability": "Rows are copied from the public prospective audit. This build cannot select, regrade or rewrite them.",
            "license_note": "THI-derived forecasts and audit fields only. No raw third-party sportsbook feed is redistributed.",
            "contracts": source.get("meta", {}).get("contracts", {}),
        },
        "methodology": source.get("methodology", {}),
        "fields": FIELDS,
        "rows": rows,
    }
    JSON_OUTPUT.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n")
    with CSV_OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print({"json": str(JSON_OUTPUT), "csv": str(CSV_OUTPUT), "rows": len(rows)})


if __name__ == "__main__":
    main()
