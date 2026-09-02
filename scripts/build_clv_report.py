"""
CFB ANALYTICS
build_clv_report.py

Build a deterministic prospective CLV report by joining:

    data/snapshots/projection_market_snapshots.jsonl
    data/snapshots/closing_lines.jsonl

This script does NOT call CFBD, Odds API, ESPN, or any other external source.
It only evaluates information that has already been captured prospectively.

CLV convention:
- If the model preferred the HOME team:
      CLV = snapshot_home_spread - closing_home_spread
- If the model preferred the AWAY team:
      CLV = closing_home_spread - snapshot_home_spread

Positive CLV means the number captured at the snapshot was better than the
near-kickoff closing proxy for the model's preferred side.

Outputs:
    data/reports/clv_report.json
    data/reports/clv_snapshot_rows.csv
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_LEDGER = ROOT / "data" / "snapshots" / "projection_market_snapshots.jsonl"
CLOSING_LEDGER = ROOT / "data" / "snapshots" / "closing_lines.jsonl"
REPORT_DIR = ROOT / "data" / "reports"
REPORT_JSON = REPORT_DIR / "clv_report.json"
REPORT_CSV = REPORT_DIR / "clv_snapshot_rows.csv"

SIGNAL_ORDER = [
    "ALIGNED",
    "SLIGHT EDGE",
    "EDGE",
    "STRONG EDGE",
    "OUTLIER",
    "NO MARKET",
]


def load_jsonl(path):
    if not path.exists():
        return []

    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Invalid JSONL in {path.relative_to(ROOT)} line {line_number}"
                ) from exc
    return rows


def game_key(row):
    gid = row.get("game_id")
    if gid is not None:
        return str(gid)

    explicit = row.get("game_key")
    if explicit:
        return str(explicit)

    away = str(row.get("away_team") or "").strip()
    home = str(row.get("home_team") or "").strip()
    start = str(
        row.get("start_date")
        or row.get("scheduled_kickoff_utc")
        or ""
    )
    return f"{away}@{home}|{start}"


def safe_round(value, digits=3):
    if value is None:
        return None
    return round(float(value), digits)


def classify_beat_close(clv):
    if clv is None:
        return None
    if clv > 0:
        return True
    if clv < 0:
        return False
    return None


def calculate_clv(snapshot, closing):
    snap_market = snapshot.get("market_at_snapshot") or {}
    close_market = closing.get("closing_market") or {}

    snapshot_home_spread = snap_market.get("home_spread")
    closing_home_spread = close_market.get("home_spread")

    if snapshot_home_spread is None or closing_home_spread is None:
        return None

    preferred = (
        (snapshot.get("comparison_at_snapshot") or {}).get("preferred_side")
    )
    home = snapshot.get("home_team")
    away = snapshot.get("away_team")

    if preferred == home:
        return float(snapshot_home_spread) - float(closing_home_spread)

    if preferred == away:
        return float(closing_home_spread) - float(snapshot_home_spread)

    return None


def closing_model_edge(snapshot, closing):
    model_home = (snapshot.get("model") or {}).get("home_spread")
    close_home = (closing.get("closing_market") or {}).get("home_spread")

    if model_home is None or close_home is None:
        return None

    preferred = (
        (snapshot.get("comparison_at_snapshot") or {}).get("preferred_side")
    )
    home = snapshot.get("home_team")
    away = snapshot.get("away_team")

    raw_difference = float(model_home) - float(close_home)

    if preferred == home:
        return -raw_difference
    if preferred == away:
        return raw_difference

    return abs(raw_difference)


def movement_toward_model(snapshot, closing):
    model_home = (snapshot.get("model") or {}).get("home_spread")
    snap_home = (snapshot.get("market_at_snapshot") or {}).get("home_spread")
    close_home = (closing.get("closing_market") or {}).get("home_spread")

    if model_home is None or snap_home is None or close_home is None:
        return None

    before = abs(float(model_home) - float(snap_home))
    after = abs(float(model_home) - float(close_home))
    return before - after


def summarize(rows):
    settled = [r for r in rows if r.get("clv_points") is not None]
    clv_values = [r["clv_points"] for r in settled]

    wins = sum(1 for r in settled if r.get("beat_close") is True)
    losses = sum(1 for r in settled if r.get("beat_close") is False)
    pushes = sum(1 for r in settled if r.get("clv_points") == 0)

    non_push = wins + losses

    return {
        "rows": len(rows),
        "settled_clv_rows": len(settled),
        "average_clv_points": safe_round(mean(clv_values)) if clv_values else None,
        "median_clv_points": safe_round(median(clv_values)) if clv_values else None,
        "beat_close_count": wins,
        "worse_than_close_count": losses,
        "same_as_close_count": pushes,
        "beat_close_pct_ex_pushes": (
            safe_round(100.0 * wins / non_push, 1) if non_push else None
        ),
        "positive_or_push_pct": (
            safe_round(
                100.0 * sum(1 for v in clv_values if v >= 0) / len(clv_values),
                1,
            )
            if clv_values
            else None
        ),
    }


def main():
    snapshots = load_jsonl(SNAPSHOT_LEDGER)
    closings = load_jsonl(CLOSING_LEDGER)

    closing_by_game = {}
    for row in closings:
        key = game_key(row)
        # The closing capture script intentionally records each game once.
        # If duplicates ever exist, keep the capture closest to kickoff.
        current = closing_by_game.get(key)
        if current is None:
            closing_by_game[key] = row
            continue

        current_minutes = abs(float(current.get("minutes_to_kickoff") or 999999))
        new_minutes = abs(float(row.get("minutes_to_kickoff") or 999999))
        if new_minutes < current_minutes:
            closing_by_game[key] = row

    report_rows = []

    for snapshot in snapshots:
        key = game_key(snapshot)
        closing = closing_by_game.get(key)
        comparison = snapshot.get("comparison_at_snapshot") or {}
        market = snapshot.get("market_at_snapshot") or {}
        model = snapshot.get("model") or {}

        clv = calculate_clv(snapshot, closing) if closing else None
        move_to_model = movement_toward_model(snapshot, closing) if closing else None
        close_edge = closing_model_edge(snapshot, closing) if closing else None

        report_rows.append({
            "snapshot_id": snapshot.get("snapshot_id"),
            "game_key": key,
            "captured_at_utc": snapshot.get("captured_at_utc"),
            "model_version": snapshot.get("model_version"),
            "week": snapshot.get("week"),
            "start_date": snapshot.get("start_date"),
            "away_team": snapshot.get("away_team"),
            "home_team": snapshot.get("home_team"),
            "preferred_side": comparison.get("preferred_side"),
            "signal": (
                comparison.get("signal")
                or comparison.get("market_disagreement_status")
            ),
            "status_system": comparison.get("status_system"),
            "model_home_spread": model.get("home_spread"),
            "snapshot_home_spread": market.get("home_spread"),
            "snapshot_total": market.get("total"),
            "snapshot_bookmaker": market.get("bookmaker"),
            "closing_home_spread": (
                (closing.get("closing_market") or {}).get("home_spread")
                if closing else None
            ),
            "closing_total": (
                (closing.get("closing_market") or {}).get("total")
                if closing else None
            ),
            "closing_bookmaker": (
                (closing.get("closing_market") or {}).get("bookmaker")
                if closing else None
            ),
            "closing_captured_at_utc": (
                closing.get("captured_at_utc") if closing else None
            ),
            "closing_minutes_to_kickoff": (
                closing.get("minutes_to_kickoff") if closing else None
            ),
            "same_bookmaker": (
                market.get("bookmaker")
                == (closing.get("closing_market") or {}).get("bookmaker")
                if closing else None
            ),
            "clv_points": safe_round(clv),
            "beat_close": classify_beat_close(clv),
            "market_move_toward_model_points": safe_round(move_to_model),
            "closing_model_edge_points": safe_round(close_edge),
            "clv_settled": clv is not None,
        })

    # First timestamped snapshot for each game = clean initial published reference.
    first_by_game = {}
    for row in sorted(
        report_rows,
        key=lambda r: (str(r.get("captured_at_utc") or ""), str(r.get("snapshot_id") or "")),
    ):
        first_by_game.setdefault(row["game_key"], row)

    initial_rows = list(first_by_game.values())

    by_signal = {}
    grouped = defaultdict(list)
    for row in initial_rows:
        grouped[row.get("signal") or "UNKNOWN"].append(row)

    ordered_signals = SIGNAL_ORDER + sorted(
        signal for signal in grouped if signal not in SIGNAL_ORDER
    )
    for signal in ordered_signals:
        if signal in grouped:
            by_signal[signal] = summarize(grouped[signal])

    same_book_initial = [
        r for r in initial_rows
        if r.get("same_bookmaker") is True
    ]

    report = {
        "report_version": "clv-report-v1",
        "methodology": {
            "closing_line": (
                "Near-kickoff closing proxy captured by "
                "scripts/capture_closing_lines.py"
            ),
            "positive_clv": (
                "Positive means the snapshot line was better than the closing "
                "proxy for the model-preferred side."
            ),
            "closing_lines_are_features": False,
            "initial_snapshot_definition": (
                "Earliest timestamped prospective snapshot available for each game."
            ),
        },
        "counts": {
            "total_snapshot_rows": len(report_rows),
            "unique_games_with_snapshots": len(first_by_game),
            "games_with_closing_capture": len(closing_by_game),
            "initial_snapshots_with_clv": sum(
                1 for r in initial_rows if r.get("clv_settled")
            ),
        },
        "initial_snapshot_summary": summarize(initial_rows),
        "same_book_initial_snapshot_summary": summarize(same_book_initial),
        "initial_snapshot_by_signal": by_signal,
        "all_snapshot_summary": summarize(report_rows),
        "rows": report_rows,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    REPORT_JSON.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    fields = [
        "snapshot_id",
        "game_key",
        "captured_at_utc",
        "model_version",
        "week",
        "start_date",
        "away_team",
        "home_team",
        "preferred_side",
        "signal",
        "status_system",
        "model_home_spread",
        "snapshot_home_spread",
        "snapshot_total",
        "snapshot_bookmaker",
        "closing_home_spread",
        "closing_total",
        "closing_bookmaker",
        "closing_captured_at_utc",
        "closing_minutes_to_kickoff",
        "same_bookmaker",
        "clv_points",
        "beat_close",
        "market_move_toward_model_points",
        "closing_model_edge_points",
        "clv_settled",
    ]

    with REPORT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report_rows)

    print("=" * 72)
    print("PROSPECTIVE CLV REPORT COMPLETE")
    print("=" * 72)
    print("Snapshots:", len(report_rows))
    print("Unique games:", len(first_by_game))
    print("Games with closing captures:", len(closing_by_game))
    print(
        "Initial snapshots with CLV:",
        report["counts"]["initial_snapshots_with_clv"],
    )
    print("JSON:", REPORT_JSON.relative_to(ROOT))
    print("CSV:", REPORT_CSV.relative_to(ROOT))


if __name__ == "__main__":
    main()
