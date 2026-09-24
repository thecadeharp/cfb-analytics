#!/usr/bin/env python3
"""Read-only forensic audit of repeated ESPN drive IDs in historical PBP.

This does not repair, merge, promote, or exclude ledger rows. Its purpose is
to determine whether the existing clock-sorted ``drive_reappears_after_other_drive``
flag identifies a source-order anomaly or a genuinely non-contiguous drive.
2025 is deliberately out of scope.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from audit_historical_ledger_coverage import official_scores, verified_plays
from build_historical_training_data import download_season, get_release_assets
from build_verified_possession_ledger import CORE_TYPES, boolish, identifier
from reconstruct_scoring_events import SOURCE_COLUMNS

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data/research/reappearing_drive_forensics_2022.json"
DEFAULT_SEASON = 2022
SAMPLES_PER_EVIDENCE = 10
FIELDS = [
    "drive.id", "id", "sequenceNumber", "period", "clock.minutes",
    "clock.seconds", "pos_team_id", "homeTeamName", "awayTeamName",
    "type.text", "text", "drive.result", "game_play_number",
    "penalty_no_play",
]


def block_rows(frame: pd.DataFrame, order: list[str],
               ascending: list[bool]) -> list[dict]:
    """Return contiguous core-play drive blocks in the requested ordering."""
    ordered = frame.sort_values(
        order, ascending=ascending, kind="stable", na_position="last"
    )
    blocks, current = [], []
    for item in ordered.to_dict(orient="records"):
        if not current or item["drive.id"] == current[-1]["drive.id"]:
            current.append(item)
        else:
            blocks.append(current)
            current = [item]
    if current:
        blocks.append(current)
    return blocks


def block_summary(block: list[dict]) -> dict:
    first, last = block[0], block[-1]
    return {
        "drive_id": first["drive.id"],
        "plays": len(block),
        "sequence_start": first.get("sequenceNumber"),
        "sequence_end": last.get("sequenceNumber"),
        "start": {
            "period": first.get("period"),
            "minutes": first.get("clock.minutes"),
            "seconds": first.get("clock.seconds"),
        },
        "end": {
            "period": last.get("period"),
            "minutes": last.get("clock.minutes"),
            "seconds": last.get("clock.seconds"),
        },
        "possession_teams": sorted({
            str(x["pos_team_id"])
            for x in block
            if pd.notna(x.get("pos_team_id"))
        }),
        "first_type": first.get("type.text"),
        "last_type": last.get("type.text"),
        "play_ids": [
            str(x["id"]) for x in block if pd.notna(x.get("id"))
        ],
    }


def repeated_ids(blocks: list[list[dict]]) -> set[str]:
    ids = [str(block[0]["drive.id"]) for block in blocks]
    return {drive for drive, count in Counter(ids).items() if count > 1}


def analyze_game(game: str, active: pd.DataFrame) -> list[dict]:
    # Compare ESPN source sequence to chronological clock order. Neither one
    # silently overrides the other.
    source_blocks = block_rows(
        active, ["sequenceNumber", "game_play_number"], [True, True]
    )
    clock_blocks = block_rows(
        active,
        ["period", "clock.minutes", "clock.seconds",
         "sequenceNumber", "game_play_number"],
        [True, False, False, True, True],
    )
    clock_ids = repeated_ids(clock_blocks)
    source_ids = repeated_ids(source_blocks)
    cases = []

    for drive in sorted(clock_ids):
        clock_positions = [
            i for i, block in enumerate(clock_blocks)
            if str(block[0]["drive.id"]) == drive
        ]
        source_positions = [
            i for i, block in enumerate(source_blocks)
            if str(block[0]["drive.id"]) == drive
        ]
        classification = (
            "source_order_reappearance"
            if drive in source_ids
            else "clock_order_only"
        )
        intervening = [
            block_summary(source_blocks[i])
            for i in range(min(source_positions) + 1, max(source_positions))
        ] if source_positions else []
        related_source_blocks = [source_blocks[i] for i in source_positions]
        intervening_raw = [
            source_blocks[i]
            for i in range(min(source_positions) + 1, max(source_positions))
        ] if source_positions else []
        all_related = [
            row
            for block in related_source_blocks + intervening_raw
            for row in block
        ]
        clocks = {
            (row.get("period"), row.get("clock.minutes"), row.get("clock.seconds"))
            for row in all_related
        }
        drive_teams = {
            str(row["pos_team_id"])
            for block in related_source_blocks
            for row in block
            if pd.notna(row.get("pos_team_id"))
        }
        interruption_teams = {
            str(row["pos_team_id"])
            for block in intervening_raw
            for row in block
            if pd.notna(row.get("pos_team_id"))
        }

        if classification == "clock_order_only":
            evidence = "clock_order_anomaly"
        elif len(clocks) == 1:
            evidence = "same_clock_source_cluster"
        elif (
            drive_teams
            and interruption_teams
            and drive_teams.isdisjoint(interruption_teams)
        ):
            evidence = "opponent_interruption"
        else:
            evidence = "multi_timestamp_source_split"

        cases.append({
            "game_id": game,
            "drive_id": drive,
            "classification": classification,
            "evidence": evidence,
            "clock_block_count": len(clock_positions),
            "source_block_count": len(source_positions),
            "clock_blocks": [
                block_summary(clock_blocks[i]) for i in clock_positions
            ],
            "source_blocks": [
                block_summary(source_blocks[i]) for i in source_positions
            ],
            "intervening_source_blocks": intervening,
        })

    return cases


def audit(season: int, path: Path, asset_url: str | None) -> dict:
    columns = list(dict.fromkeys(SOURCE_COLUMNS + FIELDS))
    raw = pd.read_parquet(path, columns=columns)
    official, _ = official_scores(season)
    plays, _, game_ids, rejection_counts = verified_plays(raw, official)

    for column in ("game_id", "drive.id", "id", "pos_team_id"):
        plays[column] = plays[column].map(identifier)
    for column in (
        "period", "clock.minutes", "clock.seconds",
        "sequenceNumber", "game_play_number",
    ):
        plays[column] = pd.to_numeric(plays[column], errors="coerce")

    regulation = plays.loc[plays.period.between(1, 4)].copy()
    active = regulation.loc[
        regulation["type.text"].isin(CORE_TYPES)
        & ~boolish(regulation.penalty_no_play)
        & regulation["drive.id"].notna()
    ]

    cases = []
    for game, game_active in active.groupby("game_id", sort=True):
        cases.extend(analyze_game(game, game_active))

    counts = Counter(case["classification"] for case in cases)
    evidence_counts = Counter(case["evidence"] for case in cases)

    # Keep the committed report readable; the full public-source audit remains
    # reproducible whenever needed.
    sample_cases = []
    for evidence in sorted(evidence_counts):
        sample_cases.extend([
            case for case in cases
            if case["evidence"] == evidence
        ][:SAMPLES_PER_EVIDENCE])

    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "research_only_reappearing_drive_forensic_audit",
            "scope": (
                f"{season} independently score-verified games only; "
                "2025 excluded and sealed"
            ),
            "production_use": (
                "none; does not alter Model A, projections, site files, "
                "or ledger eligibility"
            ),
            "training_ready": False,
            "method": (
                "Compares contiguous core-play drive-ID blocks in ESPN "
                "sequenceNumber order with the ledger's chronological clock "
                "order. Classifications describe evidence; they do not "
                "authorize repairs."
            ),
        },
        "season": season,
        "source_asset": asset_url or "local_parquet",
        "verified_games": len(game_ids),
        "cross_source_rejections": dict(rejection_counts),
        "reappearing_drive_cases": len(cases),
        "classification_counts": dict(counts),
        "evidence_counts": dict(evidence_counts),
        "sample_cases": sample_cases,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=DEFAULT_SEASON)
    parser.add_argument("--local-parquet", type=Path)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()

    if args.season != DEFAULT_SEASON:
        parser.error(
            "This first forensic audit is intentionally limited to 2022. "
            "2025 is sealed."
        )

    with tempfile.TemporaryDirectory() as tmp:
        if args.local_parquet:
            path, asset = args.local_parquet, None
        else:
            path, asset = download_season(
                args.season, get_release_assets(), Path(tmp)
            )
        report = audit(
            args.season,
            path,
            asset["browser_download_url"] if asset else None,
        )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        key: report[key]
        for key in (
            "verified_games",
            "reappearing_drive_cases",
            "classification_counts",
        )
    }, indent=2))


if __name__ == "__main__":
    main()
