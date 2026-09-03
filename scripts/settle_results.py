"""
CFB ANALYTICS
settle_results.py

Settles prospective Model A snapshots against completed game results.

NO CFBD CALLS.
NO ODDS API CALLS.
NO MODEL REBUILD.

Matching hierarchy:
    1. exact game ID
    2. exact normalized home/away teams + week
    3. exact normalized home/away teams + kickoff date
    4. unique high-confidence fuzzy team match within the same week

The fallback hierarchy exists because prospective snapshots and NCAA results
can use different provider-specific game IDs. Every settled row records the
match method so the audit trail stays explicit.

Inputs:
    data/snapshots/projection_market_snapshots.jsonl
    data/snapshots/closing_lines.jsonl           (optional)
    data/reports/clv_report.json                 (optional)
    one completed-results source, prioritized as:
        data/results.json
        data/completed_games.json
        data/schedule.json
        data/projections.json

Outputs:
    data/reports/settled_results.json
    data/reports/settled_snapshot_rows.csv
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
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

# Conservative provider-name aliases only. Do not use broad transformations
# such as deleting "state", which can create false matches.
TEAM_ALIASES = {
    "miamifla": "miamifl",
    "miamiflorida": "miamifl",
    "olemiss": "mississippi",
    "southernmiss": "southernmississippi",
    "utsa": "texassanantonio",
    "utep": "texaselpaso",
    "ucf": "centralflorida",
    "byu": "brighamyoung",
    "lsu": "louisianastate",
    "smu": "southernmethodist",
    "tcu": "texaschristian",
    "usc": "southerncalifornia",
}


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


def as_int(value):
    number = as_number(value)
    return int(number) if number is not None else None


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


def canonical_team(value):
    value = normalize_team(value)
    if value is None:
        return None
    text = str(value).strip().lower()
    text = text.replace("&", "and")
    text = re.sub(r"\buniversity\b", "", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return TEAM_ALIASES.get(text, text) or None


def extract_datetime(row):
    raw = first_value(
        row,
        [
            "start_date", "startDate", "scheduled_kickoff_utc", "kickoff",
            "kickoff_utc", "date", "start_time", "startTime",
        ],
    )
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def date_key(row):
    dt = extract_datetime(row)
    return dt.date().isoformat() if dt else None


def row_week(row):
    return as_int(first_value(row, ["week", "week_number", "weekNumber"]))


def row_game_id(row):
    gid = first_value(row, ["game_id", "gameId", "id"])
    return str(gid) if gid is not None else None


def matchup_key(row):
    home = canonical_team(first_value(row, ["home_team", "homeTeam", "home"]))
    away = canonical_team(first_value(row, ["away_team", "awayTeam", "away"]))
    if not home or not away:
        return None
    return away, home


def game_key(row):
    """Stable provider key used for snapshot grouping/audit display."""
    gid = row_game_id(row)
    if gid is not None:
        return gid

    matchup = matchup_key(row)
    week = row_week(row)
    day = date_key(row)
    if matchup:
        away, home = matchup
        return f"{away}@{home}|w{week}|{day}"
    return f"unknown|w{week}|{day}"


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
        number = as_number(first_value(nested, ["points", "score", "final", "total"]))
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

    completed = first_value(row, ["completed", "is_completed", "isCompleted", "final"])
    if completed is True:
        return True

    status = str(
        first_value(row, ["status", "game_status", "state", "status_type"]) or ""
    ).lower()

    if any(word in status for word in ["final", "completed", "complete", "post"]):
        return True

    # Dedicated results files with both scores are accepted.
    return True


def normalize_result(row):
    home = normalize_team(first_value(row, ["home_team", "homeTeam", "home"]))
    away = normalize_team(first_value(row, ["away_team", "awayTeam", "away"]))
    home_points = extract_score(row, "home")
    away_points = extract_score(row, "away")

    if not home or not away or not is_completed(row, home_points, away_points):
        return None

    return {
        "game_key": game_key(row),
        "game_id": row_game_id(row),
        "week": row_week(row),
        "start_date": first_value(
            row, ["start_date", "startDate", "scheduled_kickoff_utc", "date"]
        ),
        "date_key": date_key(row),
        "home_team": home,
        "away_team": away,
        "home_canonical": canonical_team(home),
        "away_canonical": canonical_team(away),
        "home_points": home_points,
        "away_points": away_points,
        "actual_home_margin": home_points - away_points,
    }


def load_completed_results():
    # Use the first existing source as authoritative, even when it currently
    # contains zero finals. In production, data/results.json is intentionally
    # written before settlement; falling through to schedule/projections when
    # it is empty could mix stale or non-prospective completed games into the
    # settlement report.
    for path in RESULT_SOURCES:
        data = load_json(path)
        if data is None:
            continue

        results = []
        seen = set()
        for row in flatten_records(data):
            normalized = normalize_result(row)
            if normalized is None:
                continue
            dedupe_key = (
                normalized.get("game_id"),
                normalized.get("week"),
                normalized.get("away_canonical"),
                normalized.get("home_canonical"),
                normalized.get("home_points"),
                normalized.get("away_points"),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            results.append(normalized)

        return path, results

    return None, []


def build_result_indexes(results):
    by_id = {}
    by_matchup_week = defaultdict(list)
    by_matchup_date = defaultdict(list)

    for result in results:
        gid = result.get("game_id")
        if gid:
            by_id[str(gid)] = result

        matchup = (result.get("away_canonical"), result.get("home_canonical"))
        if all(matchup):
            week = result.get("week")
            if week is not None:
                by_matchup_week[(matchup[0], matchup[1], week)].append(result)
            day = result.get("date_key")
            if day:
                by_matchup_date[(matchup[0], matchup[1], day)].append(result)

    return by_id, by_matchup_week, by_matchup_date


def similarity(a, b):
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def match_result(snapshot, result_indexes, results):
    """
    Conservative result join.

    Exact provider ID wins. Provider-independent fallbacks require matching
    home/away orientation and either week/date context. Fuzzy matching is only
    accepted when it is unique and both team similarities are >= .92.
    """
    by_id, by_matchup_week, by_matchup_date = result_indexes

    gid = row_game_id(snapshot)
    if gid and gid in by_id:
        return by_id[gid], "exact_game_id"

    matchup = matchup_key(snapshot)
    week = row_week(snapshot)
    day = date_key(snapshot)

    if matchup and week is not None:
        candidates = by_matchup_week.get((matchup[0], matchup[1], week), [])
        if len(candidates) == 1:
            return candidates[0], "exact_teams_week"

    if matchup and day:
        candidates = by_matchup_date.get((matchup[0], matchup[1], day), [])
        if len(candidates) == 1:
            return candidates[0], "exact_teams_date"

    if matchup and week is not None:
        away, home = matchup
        scored = []
        for result in results:
            if result.get("week") != week:
                continue
            away_score = similarity(away, result.get("away_canonical"))
            home_score = similarity(home, result.get("home_canonical"))
            if away_score >= 0.92 and home_score >= 0.92:
                scored.append((min(away_score, home_score), away_score + home_score, result))

        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        if len(scored) == 1:
            return scored[0][2], "fuzzy_teams_week"
        if len(scored) >= 2:
            best, second = scored[0], scored[1]
            if best[0] >= 0.94 and (best[1] - second[1]) >= 0.08:
                return best[2], "fuzzy_teams_week_unique"

    return None, "unmatched"


def preferred_side(snapshot):
    return (snapshot.get("comparison_at_snapshot") or {}).get("preferred_side")


def ats_result(snapshot, result):
    market_home = as_number((snapshot.get("market_at_snapshot") or {}).get("home_spread"))
    if market_home is None:
        return None

    home_cover_margin = result["actual_home_margin"] + market_home
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

    snap_home = as_number((snapshot.get("market_at_snapshot") or {}).get("home_spread"))
    close_home = as_number((closing.get("closing_market") or {}).get("home_spread"))
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
    model_errors = [r["model_margin_error"] for r in settled if r.get("model_margin_error") is not None]
    market_errors = [r["market_margin_error"] for r in settled if r.get("market_margin_error") is not None]
    closing_errors = [r["closing_margin_error"] for r in settled if r.get("closing_margin_error") is not None]
    ats = [r["ats_result"] for r in settled if r.get("ats_result")]

    wins = ats.count("W")
    losses = ats.count("L")
    pushes = ats.count("P")
    decisions = wins + losses

    return {
        "rows": len(rows),
        "settled_rows": len(settled),
        "model_mae": round_or_none(mean(abs(v) for v in model_errors)) if model_errors else None,
        "model_rmse": round_or_none(rmse(model_errors)),
        "market_snapshot_mae": round_or_none(mean(abs(v) for v in market_errors)) if market_errors else None,
        "market_snapshot_rmse": round_or_none(rmse(market_errors)),
        "closing_proxy_mae": round_or_none(mean(abs(v) for v in closing_errors)) if closing_errors else None,
        "closing_proxy_rmse": round_or_none(rmse(closing_errors)),
        "model_beats_snapshot_market_count": sum(
            1 for r in settled
            if r.get("model_abs_error") is not None
            and r.get("market_abs_error") is not None
            and r["model_abs_error"] < r["market_abs_error"]
        ),
        "snapshot_market_beats_model_count": sum(
            1 for r in settled
            if r.get("model_abs_error") is not None
            and r.get("market_abs_error") is not None
            and r["market_abs_error"] < r["model_abs_error"]
        ),
        "prediction_error_ties": sum(
            1 for r in settled
            if r.get("model_abs_error") is not None
            and r.get("market_abs_error") is not None
            and r["market_abs_error"] == r["model_abs_error"]
        ),
        "ats_wins": wins,
        "ats_losses": losses,
        "ats_pushes": pushes,
        "ats_win_pct_ex_pushes": round_or_none(100.0 * wins / decisions, 1) if decisions else None,
    }


def build_closing_index(closings):
    """
    Closings originate from the projection feed, so exact snapshot game IDs
    normally match. Also index provider-independent matchup/week keys.
    """
    by_id = {}
    by_matchup_week = {}

    for row in closings:
        gid = row_game_id(row)
        matchup = matchup_key(row)
        week = row_week(row)

        def better(current, candidate):
            if current is None:
                return candidate
            old_mins = abs(as_number(current.get("minutes_to_kickoff")) or 999999)
            new_mins = abs(as_number(candidate.get("minutes_to_kickoff")) or 999999)
            return candidate if new_mins < old_mins else current

        if gid:
            by_id[gid] = better(by_id.get(gid), row)
        if matchup and week is not None:
            key = (matchup[0], matchup[1], week)
            by_matchup_week[key] = better(by_matchup_week.get(key), row)

    return by_id, by_matchup_week


def match_closing(snapshot, closing_index):
    by_id, by_matchup_week = closing_index
    gid = row_game_id(snapshot)
    if gid and gid in by_id:
        return by_id[gid]

    matchup = matchup_key(snapshot)
    week = row_week(snapshot)
    if matchup and week is not None:
        return by_matchup_week.get((matchup[0], matchup[1], week))
    return None


def main():
    snapshots = load_jsonl(SNAPSHOT_LEDGER)
    closings = load_jsonl(CLOSING_LEDGER)
    results_source, results = load_completed_results()
    result_indexes = build_result_indexes(results)
    closing_index = build_closing_index(closings)

    rows = []
    match_method_counts = defaultdict(int)

    for snapshot in snapshots:
        key = game_key(snapshot)
        result, match_method = match_result(snapshot, result_indexes, results)
        closing = match_closing(snapshot, closing_index)
        comparison = snapshot.get("comparison_at_snapshot") or {}
        market = snapshot.get("market_at_snapshot") or {}
        model = snapshot.get("model") or {}

        match_method_counts[match_method] += 1

        model_error = model_margin_error(snapshot, result) if result else None
        market_error = market_margin_error(snapshot, result) if result else None
        close_error = closing_margin_error(closing, result) if result else None
        clv = calc_clv(snapshot, closing)

        rows.append({
            "snapshot_id": snapshot.get("snapshot_id"),
            "game_key": key,
            "result_game_id": result.get("game_id") if result else None,
            "result_match_method": match_method,
            "captured_at_utc": snapshot.get("captured_at_utc"),
            "model_version": snapshot.get("model_version"),
            "week": snapshot.get("week"),
            "start_date": snapshot.get("start_date"),
            "away_team": snapshot.get("away_team"),
            "home_team": snapshot.get("home_team"),
            "preferred_side": preferred_side(snapshot),
            "signal": comparison.get("signal") or comparison.get("market_disagreement_status"),
            "model_home_spread": model.get("home_spread"),
            "model_total": model.get("total"),
            "model_home_win_probability": model.get("home_win_probability"),
            "snapshot_home_spread": market.get("home_spread"),
            "snapshot_total": market.get("total"),
            "snapshot_bookmaker": market.get("bookmaker"),
            "closing_home_spread": (
                (closing.get("closing_market") or {}).get("home_spread") if closing else None
            ),
            "clv_points": round_or_none(clv),
            "home_points": result.get("home_points") if result else None,
            "away_points": result.get("away_points") if result else None,
            "actual_home_margin": result.get("actual_home_margin") if result else None,
            "ats_result": ats_result(snapshot, result) if result else None,
            "model_margin_error": round_or_none(model_error),
            "model_abs_error": round_or_none(abs(model_error)) if model_error is not None else None,
            "market_margin_error": round_or_none(market_error),
            "market_abs_error": round_or_none(abs(market_error)) if market_error is not None else None,
            "closing_margin_error": round_or_none(close_error),
            "closing_abs_error": round_or_none(abs(close_error)) if close_error is not None else None,
            "model_beats_snapshot_market": (
                abs(model_error) < abs(market_error)
                if model_error is not None and market_error is not None
                else None
            ),
            "result_settled": result is not None,
        })

    # Earliest prospective snapshot per provider game key is the clean reference.
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

    initial_match_counts = defaultdict(int)
    for row in initial_rows:
        initial_match_counts[row.get("result_match_method") or "unknown"] += 1

    report = {
        "report_version": "prospective-settlement-v2-provider-independent-matching",
        "methodology": {
            "primary_reference": "Earliest timestamped prospective snapshot for each game.",
            "result_match_hierarchy": [
                "exact game ID",
                "exact normalized home/away teams + week",
                "exact normalized home/away teams + kickoff date",
                "unique high-confidence fuzzy home/away team match within same week",
            ],
            "fuzzy_match_floor": 0.92,
            "model_error": "Actual home margin minus Model A projected home margin.",
            "market_error": "Actual home margin minus market-implied home margin at snapshot.",
            "ats_result": (
                "Result for the model-preferred side using the market spread "
                "captured in that prospective snapshot."
            ),
            "closing_line": "Near-kickoff closing proxy, not asserted to be the canonical close.",
            "no_retroactive_model_changes": True,
        },
        "results_source": str(results_source.relative_to(ROOT)) if results_source else None,
        "counts": {
            "total_snapshot_rows": len(rows),
            "unique_snapshot_games": len(first_by_game),
            "completed_games_found": len(results),
            "initial_snapshots_settled": sum(1 for r in initial_rows if r["result_settled"]),
            "initial_snapshots_unmatched": sum(1 for r in initial_rows if not r["result_settled"]),
        },
        "result_match_methods_initial": dict(sorted(initial_match_counts.items())),
        "result_match_methods_all_snapshots": dict(sorted(match_method_counts.items())),
        "initial_snapshot_summary": summarize(initial_rows),
        "initial_snapshot_by_signal": by_signal,
        "all_snapshot_summary": summarize(rows),
        "rows": rows,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    fields = [
        "snapshot_id", "game_key", "result_game_id", "result_match_method",
        "captured_at_utc", "model_version", "week", "start_date",
        "away_team", "home_team", "preferred_side", "signal",
        "model_home_spread", "model_total", "model_home_win_probability",
        "snapshot_home_spread", "snapshot_total", "snapshot_bookmaker",
        "closing_home_spread", "clv_points", "home_points", "away_points",
        "actual_home_margin", "ats_result", "model_margin_error",
        "model_abs_error", "market_margin_error", "market_abs_error",
        "closing_margin_error", "closing_abs_error",
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
    print("Results source:", report["results_source"] or "NONE — waiting for completed-game data")
    print("Completed results found:", len(results))
    print("Initial snapshots settled:", report["counts"]["initial_snapshots_settled"])
    print("Initial snapshots unmatched:", report["counts"]["initial_snapshots_unmatched"])
    print("Initial match methods:", dict(sorted(initial_match_counts.items())))
    print("JSON:", REPORT_JSON.relative_to(ROOT))
    print("CSV:", REPORT_CSV.relative_to(ROOT))


if __name__ == "__main__":
    main()
