#!/usr/bin/env python3
"""Build the public, auditable THI benchmark-center dataset.

The output is presentation data only. It never changes projections, grading,
signal selection, or model promotion state.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.tracked_decisions import frozen_rows
except ModuleNotFoundError:
    from tracked_decisions import frozen_rows

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "reports" / "benchmark_center.json"
SIGNAL_NAMES = {
    "AGREE W/ MARKET": "ALIGNED", "ALIGNED": "ALIGNED",
    "SLIGHT EDGE": "SMALL EDGE", "LEAN": "SMALL EDGE", "SMALL EDGE": "SMALL EDGE",
    "EDGE": "PLAY", "PLAY": "PLAY",
    "STRONG EDGE": "MATERIAL DISAGREEMENT",
    "MATERIAL DISAGREEMENT": "MATERIAL DISAGREEMENT", "OUTLIER": "OUTLIER",
}
CBB_SIGNAL_NAMES = {
    "aligned": "ALIGNED", "small": "SMALL EDGE", "play": "PLAY",
    "material": "MATERIAL DISAGREEMENT", "outlier": "OUTLIER",
    "total_lean": "TOTAL LEAN", "total_watch": "TOTAL WATCH",
}


def load(path: str) -> Any:
    return json.loads((ROOT / path).read_text())


def num(value: Any) -> float | None:
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def iso_date(value: Any) -> str | None:
    text = str(value or "")
    return text[:10] if len(text) >= 10 else None


def venue_map() -> dict[str, str]:
    schedule = load("data/schedule_context.json").get("games", {})
    return {
        str(key): "neutral" if row.get("neutral_site") else "campus"
        for key, row in schedule.items()
    }


def cfb_rows() -> list[dict[str, Any]]:
    source = load("data/reports/settled_results.json")
    venues = venue_map()
    clv_rows = load("data/reports/clv_report.json").get("rows", [])
    clv_by_snapshot = {
        str(row.get("snapshot_id")): row for row in clv_rows if row.get("snapshot_id")
    }
    output = []
    for key, row in frozen_rows(source.get("rows", [])).items():
        if row.get("tracking_eligible", True) is False or not row.get("result_settled"):
            continue
        spread, actual_margin = num(row.get("model_home_spread")), num(row.get("actual_home_margin"))
        total, actual_total = num(row.get("model_total")), num(row.get("actual_total"))
        probability = num(row.get("model_home_win_probability"))
        predicted_margin = -spread if spread is not None else None
        home_won = actual_margin is not None and actual_margin > 0
        clv_row = clv_by_snapshot.get(str(row.get("snapshot_id") or ""), {})
        clv_points = num(clv_row.get("clv_points") if clv_row.get("clv_points") is not None else row.get("clv_points"))
        output.append({
            "sport": "cfb", "game_id": key, "date": iso_date(row.get("start_date")),
            "venue": venues.get(key, "unknown"), "home_team": row.get("home_team"),
            "away_team": row.get("away_team"), "predicted_margin": predicted_margin,
            "actual_margin": actual_margin, "predicted_total": total, "actual_total": actual_total,
            "home_win_probability": probability,
            "margin_error": predicted_margin - actual_margin if predicted_margin is not None and actual_margin is not None else None,
            "total_error": total - actual_total if total is not None and actual_total is not None else None,
            "brier": (probability / 100 - (1 if home_won else 0)) ** 2 if probability is not None and actual_margin not in (None, 0) else None,
            "signal": SIGNAL_NAMES.get(str(row.get("signal") or "").upper(), str(row.get("signal") or "").upper()),
            "preferred_side": row.get("preferred_side"), "ats_result": row.get("ats_result"),
            "clv": clv_points, "captured_at_utc": row.get("captured_at_utc"),
            "model_version": row.get("model_version"),
        })
    return output


def cbb_rows() -> list[dict[str, Any]]:
    board = load("data/cbb/projection_board.json")
    output = []
    for game in board.get("games", []):
        if game.get("status") != "final":
            continue
        home, away, projection = game.get("home") or {}, game.get("away") or {}, game.get("projection") or {}
        hp, ap = num(home.get("score")), num(away.get("score"))
        margin, total = num(projection.get("home_margin")), num(projection.get("total"))
        probability = num(projection.get("home_win_probability"))
        if hp is None or ap is None:
            continue
        actual_margin, actual_total = hp - ap, hp + ap
        output.append({
            "sport": "cbb", "game_id": str(game.get("game_id")), "date": iso_date(game.get("start_date")),
            "venue": "neutral" if game.get("neutral_site") else "campus",
            "home_team": home.get("team"), "away_team": away.get("team"),
            "predicted_margin": margin, "actual_margin": actual_margin,
            "predicted_total": total, "actual_total": actual_total,
            "home_win_probability": probability,
            "margin_error": margin - actual_margin if margin is not None else None,
            "total_error": total - actual_total if total is not None else None,
            "brier": (probability / 100 - (1 if actual_margin > 0 else 0)) ** 2 if probability is not None and actual_margin != 0 else None,
            "captured_at_utc": (game.get("market") or {}).get("captured_at"),
            "model_version": projection.get("model_version"),
        })
    return output


def cbb_decisions() -> dict[str, list[dict[str, Any]]]:
    tracking = load("data/cbb/model_tracking.json")
    output = {"spread": [], "total": []}
    for kind, source in (("spread", "spread_decisions"), ("total", "total_decisions")):
        for row in tracking.get(source, []):
            signal = row.get("signal_tier") or row.get("total_tier") or row.get("research_tier")
            result = {"win": "W", "loss": "L", "push": "P"}.get(str(row.get("result") or "").lower())
            output[kind].append({
                "sport": "cbb", "decision_type": kind, "game_id": str(row.get("game_id")),
                "date": row.get("game_date_et") or iso_date(row.get("start_date")),
                "venue": "neutral" if row.get("neutral_site") else "campus",
                "away_team": row.get("away_team"), "home_team": row.get("home_team"),
                "signal": CBB_SIGNAL_NAMES.get(str(signal or "").lower(), signal),
                "result": result, "clv": num(row.get("clv")),
                "pregame_line": row.get("pregame_line", row.get("pregame_total")),
                "closing_line": row.get("closing_line", row.get("closing_total")),
            })
    return output


def main() -> None:
    cfb = cfb_rows()
    cbb = cbb_rows()
    decisions = cbb_decisions()
    payload = {
        "meta": {
            "version": "thi-benchmark-center-v1.0",
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "minimum_interpretive_sample": 100,
            "status": "public_prospective_audit",
        },
        "methodology": {
            "cfb_freeze": "The first executable pregame side when one exists; otherwise the earliest pregame Model A forecast. Spread, total and win probability remain attached to that immutable snapshot.",
            "cbb_freeze": "The frozen pregame projection and grading decision retained by CBB Model Tracking. Final scores are joined only after settlement.",
            "clv": "CLV is measured from the tracked side or total at its frozen pregame line to the captured closing line. Positive points mean the frozen number beat the close. Beat-close percentage excludes exact ties.",
            "sample": "Rows with fewer than 100 graded decisions are labeled SMALL SAMPLE. The warning is interpretive and does not change or hide the result.",
            "historical": "Historical backtests are research evidence, not prospective validation. They remain separate from every figure on this page.",
        },
        "observations": cfb + cbb,
        "decisions": {
            "cfb_spread": [row for row in cfb if row.get("preferred_side") and row.get("ats_result")],
            "cbb_spread": decisions["spread"],
            "cbb_total": decisions["total"],
        },
        "active_notes": {
            "cfb": [
                "Every confidence tier remains DEVELOPING until the complete promotion contract clears.",
                "Positive CLV in a small tier is not treated as validation without sufficient sample, stability and price coverage.",
            ],
            "cbb": [
                "Spread tiers are not yet clearing THI's performance and CLV standards.",
                "The middle probability bands currently require continued calibration monitoring; the dashboard reports the gap instead of smoothing it away.",
            ],
        },
    }
    OUTPUT.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n")
    print({"output": str(OUTPUT), "observations": len(payload["observations"])})


if __name__ == "__main__":
    main()
