#!/usr/bin/env python3
"""Create an immutable Week 1-3 Model A evidence package.

This script never edits projections, results, grading, or postgame analytics. It
only reads the existing ledgers and writes a compact, checksummed checkpoint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SNAPSHOTS = DATA / "snapshots"
FROZEN = DATA / "frozen"
REPORTS = DATA / "reports"

BASELINE_PATH = FROZEN / "2026_week3_modelA_baseline.json"
HASH_PATH = FROZEN / "2026_week3_modelA_baseline.sha256"
MANIFEST_PATH = FROZEN / "2026_week3_modelA_baseline_manifest.txt"
AUDIT_PATH = REPORTS / "week3_integrity_audit.json"


def verify_frozen_baseline() -> None:
    if not BASELINE_PATH.exists() or not HASH_PATH.exists():
        raise SystemExit("Frozen Week 3 baseline or checksum is missing.")
    expected = HASH_PATH.read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(BASELINE_PATH.read_bytes()).hexdigest()
    if expected != actual:
        raise SystemExit(
            "Frozen Week 3 baseline checksum mismatch: "
            f"expected {expected}, received {actual}."
        )
    print(f"Verified immutable Week 3 baseline: {actual}")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if isinstance(value, dict):
            rows.append(value)
    return rows


def game_key(row: dict[str, Any]) -> str:
    value = row.get("game_id") or row.get("game_key") or row.get("result_game_id")
    return str(value or "").strip()


TEAM_ALIASES = {
    "armywestpoint": "army",
    "fiu": "floridainternational",
    "flaintl": "floridainternational",
    "floridainternational": "floridainternational",
    "floridainternationaluniversity": "floridainternational",
    "flaatlantic": "floridaatlantic",
    "floridaatlantic": "floridaatlantic",
    "gasouthern": "georgiasouthern",
    "georgiasouthern": "georgiasouthern",
    "hawaii": "hawaii",
    "miamioh": "miamiohio",
    "miamiohio": "miamiohio",
    "middletenn": "middletennessee",
    "middletennessee": "middletennessee",
    "mississippist": "mississippistate",
    "mississippistate": "mississippistate",
    "ncstate": "northcarolinastate",
    "ncarolinast": "northcarolinastate",
    "olemiss": "mississippi",
    "niu": "northernillinois",
    "northernillinois": "northernillinois",
    "southfla": "southflorida",
    "southflorida": "southflorida",
    "jacksonvillest": "jacksonvillestate",
    "jacksonvillestate": "jacksonvillestate",
    "southernmiss": "southernmississippi",
    "ulmonroe": "ulmonroe",
    "ulm": "ulmonroe",
    "westernky": "westernkentucky",
    "westernkentucky": "westernkentucky",
}


def team_key(value: Any) -> str:
    key = re.sub(r"[^a-z0-9]+", "", str(value or "").lower().replace("university", ""))
    return TEAM_ALIASES.get(key, key)


def matchup_key(row: dict[str, Any]) -> tuple[int, tuple[str, str]]:
    away = row.get("away_team") or (row.get("away") or {}).get("team")
    home = row.get("home_team") or (row.get("home") or {}).get("team")
    return int(row.get("week") or 0), tuple(sorted((team_key(away), team_key(home))))


def iso_key(value: Any) -> str:
    return str(value or "9999-12-31T23:59:59Z")


def unique_counts(rows: list[dict[str, Any]], field: str) -> list[str]:
    counts = Counter(str(row.get(field) or "") for row in rows)
    return sorted(key for key, count in counts.items() if key and count > 1)


def main() -> None:
    projection_data = load_json(DATA / "projections.json", {})
    result_data = load_json(DATA / "results.json", {})
    postgame_data = load_json(DATA / "postgame_analytics.json", {})
    settled_data = load_json(REPORTS / "settled_results.json", {})
    snapshots = load_jsonl(SNAPSHOTS / "projection_market_snapshots.jsonl")
    closings = load_jsonl(SNAPSHOTS / "closing_lines.jsonl")

    projection_games = [
        game
        for game in projection_data.get("games", [])
        if int(game.get("week") or 0) <= 3
        and str(game.get("opponent_type") or "").upper() == "FBS"
        and bool(game.get("tracking_eligible", True))
    ]
    snapshot_rows = [row for row in snapshots if int(row.get("week") or 0) <= 3]
    closing_rows = [row for row in closings if int(row.get("week") or 0) <= 3]
    result_rows = [
        row
        for row in result_data.get("games", [])
        if int(row.get("week") or 0) <= 3
    ]

    snapshots_by_game: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in snapshot_rows:
        if game_key(row):
            snapshots_by_game[game_key(row)].append(row)

    initial_snapshots: list[dict[str, Any]] = []
    model_variants: dict[str, list[dict[str, Any]]] = {}
    for key, rows in snapshots_by_game.items():
        ordered = sorted(rows, key=lambda row: iso_key(row.get("captured_at_utc")))
        initial_snapshots.append(ordered[0])
        variants = {
            json.dumps(row.get("model") or {}, sort_keys=True)
            for row in ordered
        }
        if len(variants) > 1:
            model_variants[key] = [json.loads(value) for value in sorted(variants)]

    closings_by_game: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in closing_rows:
        if game_key(row):
            closings_by_game[game_key(row)].append(row)

    final_closings = [
        sorted(rows, key=lambda row: iso_key(row.get("captured_at_utc")))[-1]
        for rows in closings_by_game.values()
    ]

    result_by_id = {game_key(row): row for row in result_rows if game_key(row)}
    result_by_matchup = {matchup_key(row): row for row in result_rows}
    postgame_games = postgame_data.get("games", {})
    if isinstance(postgame_games, list):
        postgame_values = postgame_games
    else:
        postgame_values = list(postgame_games.values())

    postgame_status = [
        {
            "game_id": str(row.get("game_id") or ""),
            "pbp_game_id": str(row.get("pbp_game_id") or ""),
            "week": row.get("week"),
            "away_team": row.get("away_team"),
            "home_team": row.get("home_team"),
            "analysis_status": row.get("analysis_status"),
            "analysis_level": row.get("analysis_level"),
            "generated_at": row.get("generated_at"),
        }
        for row in postgame_values
        if int(row.get("week") or 0) <= 3
    ]

    missing_initial = []
    for game in projection_games:
        key = game_key(game)
        if key not in snapshots_by_game:
            missing_initial.append(
                {
                    "game_id": key,
                    "week": game.get("week"),
                    "away_team": game.get("away", {}).get("team"),
                    "home_team": game.get("home", {}).get("team"),
                }
            )

    missing_results = []
    for row in initial_snapshots:
        key = game_key(row)
        if key not in result_by_id and matchup_key(row) not in result_by_matchup:
            missing_results.append(
                {
                    "game_id": key,
                    "week": row.get("week"),
                    "away_team": row.get("away_team"),
                    "home_team": row.get("home_team"),
                }
            )

    non_final_results = [
        game_key(row)
        for row in result_rows
        if str(row.get("game_state") or row.get("status") or "").lower()
        not in {"final", "completed"}
    ]

    settled_summary = settled_data.get("initial_snapshot_summary", {})
    status = "PASS"
    failures = []
    warnings = []
    if unique_counts(snapshot_rows, "snapshot_id"):
        failures.append("Duplicate projection snapshot IDs detected.")
    if unique_counts(closing_rows, "closing_id"):
        failures.append("Duplicate closing-line capture IDs detected.")
    if unique_counts(result_rows, "game_id"):
        failures.append("Duplicate final-result game IDs detected.")
    if non_final_results:
        failures.append("Non-final games are present in the final-results ledger.")
    if missing_initial:
        warnings.append("Some eligible Week 1-3 FBS games have no prospective snapshot.")
    if missing_results:
        warnings.append("Some snapshotted Week 1-3 games do not have a final result match.")
    if model_variants:
        warnings.append("Some games have multiple stored Model A values; variants are preserved for review.")
    if failures:
        status = "FAIL"
    elif warnings:
        status = "WARN"

    created_at = datetime.now(timezone.utc).isoformat()
    baseline = {
        "meta": {
            "season": 2026,
            "through_week": 3,
            "created_at": created_at,
            "purpose": "Immutable prospective Model A evidence checkpoint before Week 4 feature development.",
            "model_a_touched": False,
            "source_files": [
                "data/projections.json",
                "data/results.json",
                "data/snapshots/projection_market_snapshots.jsonl",
                "data/snapshots/closing_lines.jsonl",
                "data/reports/settled_results.json",
                "data/postgame_analytics.json",
            ],
        },
        "initial_projection_snapshots": sorted(
            initial_snapshots,
            key=lambda row: (int(row.get("week") or 0), iso_key(row.get("start_date")), game_key(row)),
        ),
        "closing_line_captures": sorted(
            final_closings,
            key=lambda row: (int(row.get("week") or 0), iso_key(row.get("scheduled_kickoff_utc")), game_key(row)),
        ),
        "final_results": sorted(
            result_rows,
            key=lambda row: (int(row.get("week") or 0), iso_key(row.get("start_date")), game_key(row)),
        ),
        "postgame_status": sorted(
            postgame_status,
            key=lambda row: (int(row.get("week") or 0), str(row.get("game_id") or "")),
        ),
        "settled_initial_snapshot_summary": settled_summary,
    }

    baseline_text = json.dumps(baseline, indent=2) + "\n"
    digest = hashlib.sha256(baseline_text.encode("utf-8")).hexdigest()

    audit = {
        "meta": {
            "season": 2026,
            "through_week": 3,
            "generated_at": created_at,
            "status": status,
            "model_a_touched": False,
        },
        "counts": {
            "eligible_fbs_projection_games": len(projection_games),
            "snapshot_rows": len(snapshot_rows),
            "games_with_initial_snapshot": len(initial_snapshots),
            "closing_line_captures": len(final_closings),
            "final_results": len(result_rows),
            "postgame_records": len(postgame_status),
            "postgame_available": sum(row.get("analysis_status") == "available" for row in postgame_status),
            "postgame_pending": sum(row.get("analysis_status") == "pending" for row in postgame_status),
        },
        "checks": {
            "duplicate_snapshot_ids": unique_counts(snapshot_rows, "snapshot_id"),
            "duplicate_closing_ids": unique_counts(closing_rows, "closing_id"),
            "duplicate_result_game_ids": unique_counts(result_rows, "game_id"),
            "non_final_result_game_ids": sorted(filter(None, non_final_results)),
            "missing_initial_snapshots": missing_initial,
            "missing_final_results": missing_results,
            "model_value_variants": model_variants,
        },
        "failures": failures,
        "warnings": warnings,
        "baseline_sha256": digest,
    }

    FROZEN.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(baseline_text, encoding="utf-8")
    HASH_PATH.write_text(
        f"{digest}  data/frozen/{BASELINE_PATH.name}\n",
        encoding="utf-8",
    )
    MANIFEST_PATH.write_text(
        "\n".join(
            [
                "THE HAMMER INDEX — 2026 WEEK 3 MODEL A BASELINE",
                f"Created: {created_at}",
                "Scope: Weeks 1-3, prospective evidence only",
                "Model A modified: NO",
                f"SHA-256: {digest}",
                f"Initial snapshots: {len(initial_snapshots)}",
                f"Closing captures: {len(final_closings)}",
                f"Final results: {len(result_rows)}",
                f"Integrity status: {status}",
                "",
                "This checkpoint is evidence. Future UI, metric, and data-source changes",
                "must not rewrite these frozen pregame records.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    AUDIT_PATH.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")

    print(f"Week 3 baseline written: {BASELINE_PATH.relative_to(ROOT)}")
    print(f"SHA-256: {digest}")
    print(f"Integrity audit: {status}")
    print(json.dumps(audit["counts"], indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify the committed immutable baseline without rewriting it.",
    )
    arguments = parser.parse_args()
    if arguments.verify:
        verify_frozen_baseline()
    else:
        main()
