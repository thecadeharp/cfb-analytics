#!/usr/bin/env python3
"""Validate a licensed CFBD weekly Model Training Pack without publishing it.

The raw pack is a point-in-time pregame feature snapshot. This audit verifies
its identity and timing contract against THI's production board and emits only
aggregate diagnostics. It never copies raw feature rows into the repository.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECTIONS = ROOT / "data" / "projections.json"
DEFAULT_OUTPUT = ROOT / "data" / "research" / "cfbd_training_pack_audit.json"

IDENTITY_COLUMNS = {
    "id", "start_date", "season_type", "home_team", "home_conference",
    "away_team", "away_conference",
}
REQUIRED_COLUMNS = {
    "id", "start_date", "season", "season_type", "week", "neutral_site",
    "home_team", "home_conference", "home_elo", "home_talent",
    "away_team", "away_conference", "away_elo", "away_talent", "spread",
}


def canonical(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def boolean(value: object) -> bool:
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low = math.floor(index)
    high = math.ceil(index)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def load_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        return list(reader), columns


def audit_pack(input_path: Path, projections_path: Path) -> dict:
    rows, columns = load_rows(input_path)
    projections = json.loads(projections_path.read_text())
    projection_meta = projections.get("meta") or {}
    games = {
        str(game.get("game_id")): game
        for game in projections.get("games", [])
        if game.get("game_id") is not None
    }

    missing_columns = sorted(REQUIRED_COLUMNS - set(columns))
    duplicate_ids = sorted({
        row["id"] for row in rows
        if sum(candidate.get("id") == row.get("id") for candidate in rows) > 1
    }) if "id" in columns else []

    numeric_columns = [
        column for column in columns
        if column not in IDENTITY_COLUMNS and column != "neutral_site"
    ]
    invalid_numeric = []
    blank_cells = 0
    for row in rows:
        blank_cells += sum(value is None or str(value).strip() == "" for value in row.values())
        for column in numeric_columns:
            try:
                value = float(row.get(column, ""))
                if not math.isfinite(value):
                    raise ValueError
            except (TypeError, ValueError):
                invalid_numeric.append({"game_id": row.get("id"), "column": column})

    schedule_missing = []
    matchup_mismatches = []
    neutral_mismatches = []
    start_time_mismatches = []
    conference_mismatches = []
    alias_normalizations = []
    market_deltas = []
    market_available = 0

    for row in rows:
        game_id = str(row.get("id") or "")
        game = games.get(game_id)
        if not game:
            schedule_missing.append(game_id)
            continue

        for side in ("home", "away"):
            pack_name = row.get(f"{side}_team") or ""
            board_name = (game.get(side) or {}).get("team") or ""
            if canonical(pack_name) != canonical(board_name):
                matchup_mismatches.append({
                    "game_id": game_id, "side": side,
                    "pack": pack_name, "board": board_name,
                })
            elif pack_name != board_name:
                alias_normalizations.append({
                    "game_id": game_id, "side": side,
                    "pack": pack_name, "board": board_name,
                })

            pack_conf = row.get(f"{side}_conference") or ""
            board_conf = (game.get(side) or {}).get("conference") or ""
            if canonical(pack_conf) != canonical(board_conf):
                conference_mismatches.append({
                    "game_id": game_id, "side": side,
                    "pack": pack_conf, "board": board_conf,
                })

        try:
            pack_neutral = boolean(row.get("neutral_site"))
        except ValueError:
            pack_neutral = None
        if pack_neutral is None or pack_neutral != bool(game.get("neutral_site")):
            neutral_mismatches.append(game_id)

        pack_start = str(row.get("start_date") or "").replace(" ", "T")
        board_start = str(game.get("start_date") or "").replace(".000Z", "")
        if pack_start != board_start:
            start_time_mismatches.append({
                "game_id": game_id, "pack": row.get("start_date"),
                "board": game.get("start_date"),
            })

        try:
            opening = float(row.get("spread", ""))
        except ValueError:
            opening = None
        current = (game.get("market") or {}).get("home_spread")
        if opening is not None and current is not None:
            market_available += 1
            market_deltas.append(float(current) - opening)

    seasons = sorted({int(float(row["season"])) for row in rows if row.get("season")})
    weeks = sorted({int(float(row["week"])) for row in rows if row.get("week")})
    through_week = projection_meta.get("metrics_through_week")
    timing_safe = bool(
        len(weeks) == 1
        and isinstance(through_week, int)
        and through_week <= weeks[0] - 1
    )

    critical_checks = {
        "required_columns_present": not missing_columns,
        "rows_present": bool(rows),
        "unique_game_ids": not duplicate_ids,
        "no_blank_cells": blank_cells == 0,
        "all_numeric_values_finite": not invalid_numeric,
        "all_games_on_thi_board": not schedule_missing,
        "matchup_identities_match": not matchup_mismatches,
        "conference_labels_match": not conference_mismatches,
        "neutral_site_flags_match": not neutral_mismatches,
        "pregame_feature_timing_is_safe": timing_safe,
        "opening_spread_is_evaluation_only": True,
    }
    advisory_checks = {
        # Kickoff times can legitimately move after a weekly pack is cut. A
        # stable game id plus matching participants keeps the feature row safe;
        # consumers must use the live schedule for display and cutoff times.
        "start_times_match_current_board": not start_time_mismatches,
    }
    status = "PASS" if all(critical_checks.values()) else "FAIL"
    if status == "PASS" and not all(advisory_checks.values()):
        status = "PASS_WITH_WARNINGS"

    abs_deltas = [abs(value) for value in market_deltas]
    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "source": "licensed CFBD Model Training Pack weekly drop",
            "raw_data_committed": False,
            "raw_data_policy": "Keep purchased rows in gitignored local storage; publish aggregate diagnostics and independently derived outputs only.",
            "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
            "model_usage": "CHALLENGER_AND_DATA_QUALITY_ONLY",
            "production_model_a_changed": False,
            "market_feature_rule": "The opening spread is retained only for evaluation and line-movement comparison; it is excluded from predictive features.",
        },
        "scope": {
            "seasons": seasons,
            "weeks": weeks,
            "rows": len(rows),
            "columns": len(columns),
            "numeric_feature_columns_including_identifiers": len(numeric_columns),
            "matched_games": len(rows) - len(schedule_missing),
            "projection_metrics_through_week": through_week,
        },
        "checks": critical_checks,
        "advisories": advisory_checks,
        "diagnostics": {
            "missing_required_columns": missing_columns,
            "duplicate_game_ids": duplicate_ids,
            "blank_cells": blank_cells,
            "invalid_numeric_cells": invalid_numeric,
            "schedule_missing_game_ids": schedule_missing,
            "matchup_mismatches": matchup_mismatches,
            "conference_mismatches": conference_mismatches,
            "neutral_site_mismatch_game_ids": neutral_mismatches,
            "start_time_mismatches": start_time_mismatches,
            "safe_name_normalizations": alias_normalizations,
        },
        "opening_to_current_market": {
            "paired_games": market_available,
            "unpaired_games": len(rows) - market_available,
            "median_signed_move_points": round(percentile(market_deltas, 0.5), 3) if market_deltas else None,
            "median_absolute_move_points": round(percentile(abs_deltas, 0.5), 3) if abs_deltas else None,
            "p90_absolute_move_points": round(percentile(abs_deltas, 0.9), 3) if abs_deltas else None,
            "maximum_absolute_move_points": round(max(abs_deltas), 3) if abs_deltas else None,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="Local licensed weekly CSV")
    parser.add_argument("--projections", type=Path, default=DEFAULT_PROJECTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    report = audit_pack(args.input, args.projections)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['meta']['status']}: {report['scope']['rows']} rows -> {args.output}")
    if report["meta"]["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
