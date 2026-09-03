"""
CFB ANALYTICS
build_signal_report.py

Build the public Signal System v1 accountability report from the existing
prospective settlement + CLV reports.

This script DOES NOT:
- call an external API
- rebuild Model A
- change fair lines
- rewrite historical snapshots
- alter closing lines or settled results

It translates legacy stored signal labels into the public Signal System v1:

    ALIGNED
    SMALL EDGE
    PLAY
    MATERIAL DISAGREEMENT
    OUTLIER

Signal Confidence is evaluated independently for each signal tier:

    DEVELOPING
        Default state while evidence accumulates.

    VALIDATED
        50+ ATS decisions
        ATS win rate >= 52.5%
        positive average CLV
        beat-close rate >= 52.5%

    ESTABLISHED
        100+ ATS decisions
        ATS win rate >= 53.0%
        positive average CLV
        beat-close rate >= 55.0%

The thresholds above are intentionally fixed in code before Week 1 results.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]

SETTLED_REPORT = ROOT / "data" / "reports" / "settled_results.json"
CLV_REPORT = ROOT / "data" / "reports" / "clv_report.json"

OUTPUT_DIR = ROOT / "data" / "reports"
OUTPUT_JSON = OUTPUT_DIR / "signal_report.json"

REPORT_VERSION = "signal-system-v1"

SIGNAL_ORDER = [
    "ALIGNED",
    "SMALL EDGE",
    "PLAY",
    "MATERIAL DISAGREEMENT",
    "OUTLIER",
]

LEGACY_TO_PUBLIC = {
    "ALIGNED": "ALIGNED",
    "AGREE W/ MARKET": "ALIGNED",
    "SLIGHT EDGE": "SMALL EDGE",
    "LEAN": "SMALL EDGE",
    "SMALL EDGE": "SMALL EDGE",
    "EDGE": "PLAY",
    "PLAY": "PLAY",
    "STRONG EDGE": "MATERIAL DISAGREEMENT",
    "MATERIAL DISAGREEMENT": "MATERIAL DISAGREEMENT",
    "OUTLIER": "OUTLIER",
}

SIGNAL_THRESHOLDS = {
    "ALIGNED": {"min": 0.0, "max": 2.5},
    "SMALL EDGE": {"min": 3.0, "max": 5.0},
    "PLAY": {"min": 5.5, "max": 7.0},
    "MATERIAL DISAGREEMENT": {"min": 7.5, "max": 10.0},
    "OUTLIER": {"min": 10.5, "max": None},
}

CONFIDENCE_RULES = {
    "DEVELOPING": {
        "description": "Prospective evidence is still accumulating.",
    },
    "VALIDATED": {
        "minimum_decisions": 50,
        "minimum_ats_win_pct": 52.5,
        "minimum_average_clv": 0.0,
        "average_clv_must_be_strictly_positive": True,
        "minimum_beat_close_pct": 52.5,
    },
    "ESTABLISHED": {
        "minimum_decisions": 100,
        "minimum_ats_win_pct": 53.0,
        "minimum_average_clv": 0.0,
        "average_clv_must_be_strictly_positive": True,
        "minimum_beat_close_pct": 55.0,
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_signal(value):
    if value is None:
        return None
    key = str(value).strip().upper()
    return LEGACY_TO_PUBLIC.get(key)


def safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def first_snapshot_rows(report):
    rows = report.get("rows") or []
    ordered = sorted(
        rows,
        key=lambda r: (
            str(r.get("captured_at_utc") or ""),
            str(r.get("snapshot_id") or ""),
        ),
    )

    first = {}
    for row in ordered:
        key = str(row.get("game_key") or row.get("game_id") or "")
        if not key:
            continue
        first.setdefault(key, row)
    return first


def confidence_for(decisions, ats_pct, avg_clv, beat_close_pct):
    established = CONFIDENCE_RULES["ESTABLISHED"]
    if (
        decisions >= established["minimum_decisions"]
        and ats_pct is not None
        and ats_pct >= established["minimum_ats_win_pct"]
        and avg_clv is not None
        and avg_clv > established["minimum_average_clv"]
        and beat_close_pct is not None
        and beat_close_pct >= established["minimum_beat_close_pct"]
    ):
        return "ESTABLISHED"

    validated = CONFIDENCE_RULES["VALIDATED"]
    if (
        decisions >= validated["minimum_decisions"]
        and ats_pct is not None
        and ats_pct >= validated["minimum_ats_win_pct"]
        and avg_clv is not None
        and avg_clv > validated["minimum_average_clv"]
        and beat_close_pct is not None
        and beat_close_pct >= validated["minimum_beat_close_pct"]
    ):
        return "VALIDATED"

    return "DEVELOPING"


def blank_signal(signal):
    return {
        "signal": signal,
        "threshold": SIGNAL_THRESHOLDS[signal],
        "sample": {
            "settled_games": 0,
            "ats_decisions": 0,
        },
        "record": {
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "record_text": "0-0",
            "ats_win_pct_ex_pushes": None,
        },
        "clv": {
            "rows_with_clv": 0,
            "average_clv_points": None,
            "beat_close_wins": 0,
            "worse_than_close": 0,
            "same_as_close": 0,
            "beat_close_pct_ex_pushes": None,
        },
        "confidence": "DEVELOPING",
    }


def main():
    settled = load_json(SETTLED_REPORT)
    clv = load_json(CLV_REPORT)

    settled_first = first_snapshot_rows(settled)
    clv_first = first_snapshot_rows(clv)

    grouped = {signal: [] for signal in SIGNAL_ORDER}

    for game_key, row in settled_first.items():
        signal = normalize_signal(row.get("signal"))
        if signal not in grouped:
            continue

        clv_row = clv_first.get(game_key) or {}

        clv_points = safe_float(
            clv_row.get("clv_points")
            if clv_row.get("clv_points") is not None
            else row.get("clv_points")
        )

        beat_close = clv_row.get("beat_close")
        if beat_close is None and clv_points is not None:
            if clv_points > 0:
                beat_close = True
            elif clv_points < 0:
                beat_close = False

        grouped[signal].append({
            "game_key": game_key,
            "ats_result": row.get("ats_result"),
            "result_settled": bool(row.get("result_settled")),
            "clv_points": clv_points,
            "beat_close": beat_close,
        })

    signals = {}

    for signal in SIGNAL_ORDER:
        rows = grouped[signal]
        output = blank_signal(signal)

        settled_rows = [r for r in rows if r["result_settled"]]
        ats = [r["ats_result"] for r in settled_rows if r["ats_result"] in {"W", "L", "P"}]

        wins = ats.count("W")
        losses = ats.count("L")
        pushes = ats.count("P")
        decisions = wins + losses
        ats_pct = round(100.0 * wins / decisions, 1) if decisions else None

        clv_values = [r["clv_points"] for r in rows if r["clv_points"] is not None]
        avg_clv = round(mean(clv_values), 3) if clv_values else None

        beat_wins = sum(1 for r in rows if r["beat_close"] is True)
        beat_losses = sum(1 for r in rows if r["beat_close"] is False)
        beat_pushes = sum(
            1 for r in rows
            if r["clv_points"] is not None and float(r["clv_points"]) == 0.0
        )
        beat_decisions = beat_wins + beat_losses
        beat_pct = (
            round(100.0 * beat_wins / beat_decisions, 1)
            if beat_decisions
            else None
        )

        confidence = confidence_for(decisions, ats_pct, avg_clv, beat_pct)

        record_text = f"{wins}-{losses}"
        if pushes:
            record_text += f"-{pushes}"

        output["sample"] = {
            "settled_games": len(settled_rows),
            "ats_decisions": decisions,
        }
        output["record"] = {
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "record_text": record_text,
            "ats_win_pct_ex_pushes": ats_pct,
        }
        output["clv"] = {
            "rows_with_clv": len(clv_values),
            "average_clv_points": avg_clv,
            "beat_close_wins": beat_wins,
            "worse_than_close": beat_losses,
            "same_as_close": beat_pushes,
            "beat_close_pct_ex_pushes": beat_pct,
        }
        output["confidence"] = confidence

        signals[signal] = output

    report = {
        "report_version": REPORT_VERSION,
        "generated_at_utc": utc_now(),
        "model_scope": "Prospective Model A accountability layer",
        "signal_system": {
            "order": SIGNAL_ORDER,
            "thresholds": SIGNAL_THRESHOLDS,
            "legacy_label_translation": LEGACY_TO_PUBLIC,
            "meaning": (
                "Signal tier measures the magnitude of separation between the "
                "model fair line and the market. A larger tier does not by "
                "itself imply greater validated betting confidence."
            ),
        },
        "confidence_system": {
            "order": ["DEVELOPING", "VALIDATED", "ESTABLISHED"],
            "rules": CONFIDENCE_RULES,
            "meaning": (
                "Signal Confidence measures the prospective evidence supporting "
                "each signal tier using sample size, ATS performance, CLV and "
                "beat-close rate."
            ),
        },
        "signals": signals,
        "source_status": {
            "settled_report_found": SETTLED_REPORT.exists(),
            "clv_report_found": CLV_REPORT.exists(),
        },
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 72)
    print("SIGNAL SYSTEM V1 REPORT COMPLETE")
    print("=" * 72)
    print("Output:", OUTPUT_JSON.relative_to(ROOT))
    for signal in SIGNAL_ORDER:
        item = signals[signal]
        print(
            f"{signal:24s} "
            f"{item['record']['record_text']:8s} "
            f"ATS={item['record']['ats_win_pct_ex_pushes']} "
            f"CLV={item['clv']['average_clv_points']} "
            f"BeatClose={item['clv']['beat_close_pct_ex_pushes']} "
            f"{item['confidence']}"
        )


if __name__ == "__main__":
    main()
