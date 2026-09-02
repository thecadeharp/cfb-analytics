"""
CFB ANALYTICS
settle_results.py

Settles prospective Model A snapshots against completed game results.

NO CFBD CALLS.
NO ODDS API CALLS.
NO MODEL REBUILD.

The script reads already-captured local files and writes a deterministic
postgame report. It is deliberately source-flexible so we can feed it a
results file without changing the prospective snapshot ledger.

Accepted results sources, in priority order:
    data/results.json
    data/completed_games.json
    data/schedule.json
    data/projections.json

A completed-game record needs:
    game_id
    home_team
    away_team
    home_points
    away_points

Common aliases such as home_score / away_score are accepted.

Inputs:
    data/snapshots/projection_market_snapshots.jsonl
    data/snapshots/closing_lines.jsonl           (optional)
    data/reports/clv_report.json                 (optional)
    one of the results sources above

Outputs:
    data/reports/settled_results.json
    data/reports/settled_snapshot_rows.csv
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_LEDGER = ROOT / "data" / "snapshots" / "projection_market_snapshots.jsonl"
CLOSING_LEDGER = ROOT / "data" / "snapshots" / "closing_lines.jsonl"
CLV_REPORT = ROOT / "data" / "reports" / "clv_report.json"

RESULT_SOURCES = [
    ROOT / "data" / "results.json",
    ROOT / "data" / "completed_games.json",
    ROOT / "data" / "schedule.json",
    ROOT / "data" / "projections.json",
]

REPORT_DIR = ROOT / "data" / "reports"
REPORT_JSON = REPORT_DIR / "settled_results.json"
REPORT_CSV = REPORT_DIR / "settled_snapshot_rows.csv"


def load_json(path):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path):
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Invalid JSONL: {path.relative_to(ROOT)} line {line_number}"
                ) from exc
    return rows


def first_value(obj, keys):
    for key in keys:
        if isinstance(obj, dict) and obj.get(key) is not None:
            return obj.get(key)
    return None


def as_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def flatten_records(obj):
    """Recursively yield dictionaries that look like game records."""
    if isinstance(obj, list):
        for item in obj:
            yield from flatten_records(item)
        return

    if not isinstance(obj, dict):
        return

    home = first_value(obj, ["home_team", "homeTeam", "home"])
    away = first_value(obj, ["away_team", "awayTeam", "away"])
    gid = first_value(obj, ["game_id", "gameId", "id"])

    if gid is not None or (home is not None and away is not None):
        yield obj

    for key, value in obj.items():
        if key in {
            "model", "market", "market_at_snapshot", "comparison_at_snapshot",
            "clv", "result", "team", "home", "away"
        }:
            continue
        if isinstance(value, (list, dict)):
            yield from flatten_records(value)


def normalize_team(value):
    if isinstance(value, dict):
        return first_value(value, ["school", "team", "name", "displayName"])
    return value


def extract_score(row, side):
    direct = first_value(
        row,
        [
            f"{side}_points",
            f"{side}Points",
            f"{side}_score",
            f"{side}Score",
            f"{side}_final",
        ],
    )
    number = as_number(direct)
    if number is not None:
        return number

    nested = row.get(side)
    if isinstance(nested, dict):
        number = as_number(
            first_value(nested, ["points", "score", "final", "total"])
        )
        if number is not None:
            return number

    result = row.get("result")
    if isinstance(result, dict):
        number = as_number(
            first_value(
                result,
                [
                    f"{side}_points",
                    f"{side}Points",
                    f"{side}_score",
                    f"{side}Score",
                ],
            )
        )
        if number is not None:
            return number

    return None


def is_completed(row, home_points, away_points):
    if home_points is None or away_points is None:
        return False

    completed = first_value(
        row, ["completed", "is_completed", "isCompleted", "final"]
    )
    if completed is True:
        return True

    status = str(
        first_value(row, ["status", "game_status", "state", "status_type"]) or ""
    ).lower()

    if any(word in status for word in ["final", "completed", "complete", "post"]):
        return True

    # If both final scores are present in a dedicated results file, accept them.
    return True


def game_key(row):
    gid = first_value(row, ["game_id", "gameId", "id"])
    if gid is not None:
        return str(gid)

    home = normalize_team(first_value(row, ["home_team", "homeTeam", "home"]))
    away = normalize_team(first_value(row, ["away_team", "awayTeam", "away"]))
    start = first_value(
        row, ["start_date", "startDate", "scheduled_kickoff_utc", "date"]
    )
    return f"{away}@{home}|{start}"


def normalize_result(row):
    home = normalize_team(first_value(row, ["home_team", "homeTeam", "home"]))
    away = normalize_team(first_value(row, ["away_team", "awayTeam", "away"]))
    home_points = extract_score(row, "home")
    away_points = extract_score(row, "away")

    if not is_completed(row, home_points, away_points):
        return None

    return {
        "game_key": game_key(row),
        "game_id": first_value(row, ["game_id", "gameId", "id"]),
        "home_team": home,
        "away_team": away,
        "home_points": home_points,
        "away_points": away_points,
        "actual_home_margin": home_points - away_points,
    }


def load_completed_results():
    for path in RESULT_SOURCES:
        data = load_json(path)
        if data is None:
            continue

        results = {}
        for row in flatten_records(data):
            normalized = normalize_result(row)
            if normalized is None:
                continue
            results[normalized["game_key"]] = normalized

        if results:
            return path, results

    return None, {}


def preferred_side(snapshot):
    return (snapshot.get("comparison_at_snapshot") or {}).get("preferred_side")


def ats_result(snapshot, result):
    market_home = as_number(
        (snapshot.get("market_at_snapshot") or {}).get("home_spread")
    )
    if market_home is None:
        return None

    actual_home_margin = result["actual_home_margin"]
    home_cover_margin = actual_home_margin + market_home
    preferred = preferred_side(snapshot)

    if preferred == snapshot.get("home_team"):
        cover_margin = home_cover_margin
    elif preferred == snapshot.get("away_team"):
        cover_margin = -home_cover_margin
    else:
        return None

    if cover_margin > 0:
        return "W"
    if cover_margin < 0:
        return "L"
    return "P"


def model_margin_error(snapshot, result):
    model_home_spread = as_number((snapshot.get("model") or {}).get("home_spread"))
    if model_home_spread is None:
        return None

    # Spread is the negative of projected home margin.
    projected_home_margin = -model_home_spread
    return result["actual_home_margin"] - projected_home_margin


def market_margin_error(snapshot, result):
    market_home_spread = as_number(
        (snapshot.get("market_at_snapshot") or {}).get("home_spread")
    )
    if market_home_spread is None:
        return None

    projected_home_margin = -market_home_spread
    return result["actual_home_margin"] - projected_home_margin


def closing_margin_error(closing, result):
    if not closing:
        return None
    close_home = as_number((closing.get("closing_market") or {}).get("home_spread"))
    if close_home is None:
        return None
    projected_home_margin = -close_home
    return result["actual_home_margin"] - projected_home_margin


def calc_clv(snapshot, closing):
    if not closing:
        return None

    snap_home = as_number(
        (snapshot.get("market_at_snapshot") or {}).get("home_spread")
    )
    close_home = as_number(
        (closing.get("closing_market") or {}).get("home_spread")
    )
    if snap_home is None or close_home is None:
        return None

    preferred = preferred_side(snapshot)
    if preferred == snapshot.get("home_team"):
        return snap_home - close_home
    if preferred == snapshot.get("away_team"):
        return close_home - snap_home
    return None


def rmse(values):
    if not values:
        return None
    return math.sqrt(mean(v * v for v in values))


def round_or_none(value, digits=3):
    return None if value is None else round(float(value), digits)


def summarize(rows):
    settled = [r for r in rows if r.get("result_settled")]
    model_errors = [
        r["model_margin_error"]
        for r in settled
        if r.get("model_margin_error") is not None
    ]
    market_errors = [
        r["market_margin_error"]
        for r in settled
        if r.get("market_margin_error") is not None
    ]
    closing_errors = [
        r["closing_margin_error"]
        for r in settled
        if r.get("closing_margin_error") is not None
    ]
    ats = [r["ats_result"] for r in settled if r.get("ats_result")]

    wins = ats.count("W")
    losses = ats.count("L")
    pushes = ats.count("P")
    decisions = wins + losses

    return {
        "rows": len(rows),
        "settled_rows": len(settled),
        "model_mae": round_or_none(mean(abs(v) for v in model_errors))
        if model_errors else None,
        "model_rmse": round_or_none(rmse(model_errors)),
        "market_snapshot_mae": round_or_none(mean(abs(v) for v in market_errors))
        if market_errors else None,
        "market_snapshot_rmse": round_or_none(rmse(market_errors)),
        "closing_proxy_mae": round_or_none(mean(abs(v) for v in closing_errors))
        if closing_errors else None,
        "closing_proxy_rmse": round_or_none(rmse(closing_errors)),
        "model_beats_snapshot_market_count": sum(
            1
            for r in settled
            if r.get("model_abs_error") is not None
            and r.get("market_abs_error") is not None
            and r["model_abs_error"] < r["market_abs_error"]
        ),
        "snapshot_market_beats_model_count": sum(
            1
            for r in settled
            if r.get("model_abs_error") is not None
            and r.get("market_abs_error") is not None
            and r["market_abs_error"] < r["model_abs_error"]
        ),
        "prediction_error_ties": sum(
            1
            for r in settled
            if r.get("model_abs_error") is not None
            and r.get("market_abs_error") is not None
            and r["market_abs_error"] == r["model_abs_error"]
        ),
        "ats_wins": wins,
        "ats_losses": losses,
        "ats_pushes": pushes,
        "ats_win_pct_ex_pushes": round_or_none(100.0 * wins / decisions, 1)
        if decisions else None,
    }


def main():
    snapshots = load_jsonl(SNAPSHOT_LEDGER)
    closings = load_jsonl(CLOSING_LEDGER)
    results_source, results = load_completed_results()

    closing_by_game = {}
    for row in closings:
        key = game_key(row)
        current = closing_by_game.get(key)
        if current is None:
            closing_by_game[key] = row
            continue
        old_mins = abs(as_number(current.get("minutes_to_kickoff")) or 999999)
        new_mins = abs(as_number(row.get("minutes_to_kickoff")) or 999999)
        if new_mins < old_mins:
            closing_by_game[key] = row

    rows = []

    for snapshot in snapshots:
        key = game_key(snapshot)
        result = results.get(key)
        closing = closing_by_game.get(key)
        comparison = snapshot.get("comparison_at_snapshot") or {}
        market = snapshot.get("market_at_snapshot") or {}
        model = snapshot.get("model") or {}

        model_error = model_margin_error(snapshot, result) if result else None
        market_error = market_margin_error(snapshot, result) if result else None
        close_error = closing_margin_error(closing, result) if result else None
        clv = calc_clv(snapshot, closing)

        rows.append({
            "snapshot_id": snapshot.get("snapshot_id"),
            "game_key": key,
            "captured_at_utc": snapshot.get("captured_at_utc"),
            "model_version": snapshot.get("model_version"),
            "week": snapshot.get("week"),
            "start_date": snapshot.get("start_date"),
            "away_team": snapshot.get("away_team"),
            "home_team": snapshot.get("home_team"),
            "preferred_side": preferred_side(snapshot),
            "signal": (
                comparison.get("signal")
                or comparison.get("market_disagreement_status")
            ),
            "model_home_spread": model.get("home_spread"),
            "snapshot_home_spread": market.get("home_spread"),
            "snapshot_bookmaker": market.get("bookmaker"),
            "closing_home_spread": (
                (closing.get("closing_market") or {}).get("home_spread")
                if closing else None
            ),
            "clv_points": round_or_none(clv),
            "home_points": result.get("home_points") if result else None,
            "away_points": result.get("away_points") if result else None,
            "actual_home_margin": (
                result.get("actual_home_margin") if result else None
            ),
            "ats_result": ats_result(snapshot, result) if result else None,
            "model_margin_error": round_or_none(model_error),
            "model_abs_error": round_or_none(abs(model_error))
            if model_error is not None else None,
            "market_margin_error": round_or_none(market_error),
            "market_abs_error": round_or_none(abs(market_error))
            if market_error is not None else None,
            "closing_margin_error": round_or_none(close_error),
            "closing_abs_error": round_or_none(abs(close_error))
            if close_error is not None else None,
            "model_beats_snapshot_market": (
                abs(model_error) < abs(market_error)
                if model_error is not None and market_error is not None
                else None
            ),
            "result_settled": result is not None,
        })

    # Earliest prospective snapshot per game is our clean Week 1 reference.
    first_by_game = {}
    for row in sorted(
        rows,
        key=lambda r: (
            str(r.get("captured_at_utc") or ""),
            str(r.get("snapshot_id") or ""),
        ),
    ):
        first_by_game.setdefault(row["game_key"], row)

    initial_rows = list(first_by_game.values())

    by_signal_groups = defaultdict(list)
    for row in initial_rows:
        by_signal_groups[row.get("signal") or "UNKNOWN"].append(row)

    by_signal = {
        signal: summarize(group)
        for signal, group in sorted(by_signal_groups.items())
    }

    report = {
        "report_version": "prospective-settlement-v1",
        "methodology": {
            "primary_reference": (
                "Earliest timestamped prospective snapshot for each game."
            ),
            "model_error": (
                "Actual home margin minus Model A projected home margin."
            ),
            "market_error": (
                "Actual home margin minus market-implied home margin at snapshot."
            ),
            "ats_result": (
                "Result for the model-preferred side using the market spread "
                "captured in that prospective snapshot."
            ),
            "closing_line": (
                "Near-kickoff closing proxy, not asserted to be the canonical close."
            ),
            "no_retroactive_model_changes": True,
        },
        "results_source": (
            str(results_source.relative_to(ROOT)) if results_source else None
        ),
        "counts": {
            "total_snapshot_rows": len(rows),
            "unique_snapshot_games": len(first_by_game),
            "completed_games_found": len(results),
            "initial_snapshots_settled": sum(
                1 for r in initial_rows if r["result_settled"]
            ),
        },
        "initial_snapshot_summary": summarize(initial_rows),
        "initial_snapshot_by_signal": by_signal,
        "all_snapshot_summary": summarize(rows),
        "rows": rows,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    fields = [
        "snapshot_id", "game_key", "captured_at_utc", "model_version",
        "week", "start_date", "away_team", "home_team", "preferred_side",
        "signal", "model_home_spread", "snapshot_home_spread",
        "snapshot_bookmaker", "closing_home_spread", "clv_points",
        "home_points", "away_points", "actual_home_margin", "ats_result",
        "model_margin_error", "model_abs_error", "market_margin_error",
        "market_abs_error", "closing_margin_error", "closing_abs_error",
        "model_beats_snapshot_market", "result_settled",
    ]

    with REPORT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print("=" * 72)
    print("PROSPECTIVE RESULT SETTLEMENT COMPLETE")
    print("=" * 72)
    print("Snapshots:", len(rows))
    print("Unique games:", len(first_by_game))
    print(
        "Results source:",
        report["results_source"] or "NONE — waiting for completed-game data",
    )
    print(
        "Initial snapshots settled:",
        report["counts"]["initial_snapshots_settled"],
    )
    print("JSON:", REPORT_JSON.relative_to(ROOT))
    print("CSV:", REPORT_CSV.relative_to(ROOT))


if __name__ == "__main__":
    main()
