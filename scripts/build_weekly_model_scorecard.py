"""Publish Model A's first frozen projection per game by week; no API calls."""

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/reports/settled_results.json"
OUTPUT = ROOT / "data/reports/weekly_model_scorecard.json"


def numeric(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def main():
    rows = json.loads(SOURCE.read_text())["rows"]
    first = {}
    for row in rows:
        key = str(row.get("game_key") or "")
        if not key or not row.get("captured_at_utc"):
            continue
        if key not in first or row["captured_at_utc"] < first[key]["captured_at_utc"]:
            first[key] = row
    weeks = defaultdict(list)
    for row in first.values():
        if row.get("week") is not None:
            weeks[int(row["week"])].append(row)
    output = []
    for week, games in sorted(weeks.items()):
        settled = [r for r in games if r.get("result_settled")]
        margins = [numeric(r.get("model_abs_error")) for r in settled]
        margins = [m for m in margins if m is not None]
        totals = [abs(numeric(r["model_total"]) - numeric(r["actual_total"]))
                  for r in settled if numeric(r.get("model_total")) is not None
                  and numeric(r.get("actual_total")) is not None]
        output.append({
            "week": week,
            "games_with_frozen_snapshots": len(games),
            "settled_games": len(settled),
            "unsettled_or_unmatched": len(games) - len(settled),
            "margin_mae_points": round(sum(margins) / len(margins), 2) if margins else None,
            "margin_sample": len(margins),
            "total_mae_points": round(sum(totals) / len(totals), 2) if totals else None,
            "total_sample": len(totals),
        })
    payload = {
        "latest_settled_kickoff_utc": max(
            (r.get("start_date") for r in first.values()
             if r.get("result_settled") and r.get("start_date")), default=None),
        "definition": "First captured prospective Model A snapshot per game. MAE is mean absolute error against the final margin or total. Incomplete and unmatched games are excluded from MAE and counted separately. Later model snapshots never replace the first one.",
        "weeks": output,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n")
    print("Wrote weekly scorecard for", len(output), "weeks")


if __name__ == "__main__":
    main()
