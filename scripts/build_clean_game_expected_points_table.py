#!/usr/bin/env python3
"""Build a research-only clean-game possession target table for 2019-2024.

No model is fit here.  Rows must come from independently score-verified games
whose observed regulation possessions all pass the conservative ledger checks.
2025 is deliberately excluded and production files are never read or written.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from audit_historical_ledger_coverage import official_scores, verified_plays
from build_historical_training_data import download_season, get_release_assets
from build_verified_possession_ledger import EXTRA_COLUMNS, build_ledger
from reconstruct_scoring_events import SOURCE_COLUMNS

ROOT = Path(__file__).resolve().parents[1]
YEARS = list(range(2019, 2025))
TABLE = ROOT / "data/research/expected_points_clean_games_2019_2024.csv.gz"
REPORT = ROOT / "data/research/expected_points_clean_games_2019_2024.json"
FEATURES = [
    "season", "partition", "game_id", "drive_id", "possession_team_id", "opponent_id",
    "home_team", "away_team", "start_period", "start_yards_to_endzone",
    "target_offensive_points",
]


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rows_for_year(year: int, path: Path, asset_url: str):
    raw = pd.read_parquet(path, columns=list(dict.fromkeys(SOURCE_COLUMNS + EXTRA_COLUMNS)))
    official, _ = official_scores(year)
    plays, events, ids, rejected = verified_plays(raw, official)
    ledger, _, _, summary = build_ledger(plays, events)
    if summary["verified_games"] != len(ids):
        raise RuntimeError(f"{year}: verified-game coverage mismatch")

    observed = ledger.loc[ledger.observed_possession].copy()
    game_quality = observed.groupby("game_id").label_check_passed.agg(["count", "sum"])
    clean_games = set(game_quality.index[game_quality["count"].eq(game_quality["sum"])])
    rows = observed.loc[observed.game_id.isin(clean_games)].copy()
    rows = rows.loc[
        rows.label_check_passed
        & rows.start_period.between(1, 4)
        & rows.start_yards_to_endzone.between(0, 100)
        & rows.offensive_points.notna()
    ].copy()
    if rows.game_id.nunique() != len(clean_games):
        raise RuntimeError(f"{year}: clean game has no usable observed rows")
    rows["season"] = year
    rows["partition"] = "development" if year <= 2022 else "validation"
    rows["target_offensive_points"] = rows.offensive_points.astype(int)
    rows = rows[FEATURES]
    if rows.duplicated(["season", "game_id", "drive_id"]).any():
        raise RuntimeError(f"{year}: duplicate possession key")
    return rows, {
        "season": year, "source_asset": asset_url, "verified_games": len(ids),
        "clean_games": len(clean_games), "clean_possessions": len(rows),
        "cross_source_rejections": dict(rejected),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", nargs="+", type=int, default=YEARS)
    args = parser.parse_args()
    years = sorted(set(args.seasons))
    if years != YEARS:
        parser.error("Expected exactly 2019-2024; 2025 is sealed and excluded.")

    annual, frames = [], []
    with tempfile.TemporaryDirectory() as tmp:
        assets = get_release_assets()
        for year in years:
            path, asset = download_season(year, assets, Path(tmp))
            rows, detail = rows_for_year(year, path, asset["browser_download_url"])
            annual.append(detail)
            frames.append(rows)
            print(json.dumps(detail), flush=True)

    table = pd.concat(frames, ignore_index=True)
    if len(table) == 0 or table.target_offensive_points.isna().any():
        raise RuntimeError("No usable clean-game target rows")
    if table.target_offensive_points.lt(0).any() or table.target_offensive_points.gt(8).any():
        raise RuntimeError("Target outside allowed offensive-points range")
    if set(table.partition) != {"development", "validation"}:
        raise RuntimeError("Missing locked development or validation partition")

    TABLE.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(TABLE, "wt", encoding="utf-8", newline="") as handle:
        table.to_csv(handle, index=False)
    report = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "research_only_clean_game_expected_points_target_table",
            "scope": "2019-2024 clean score-verified regulation possessions; 2025 excluded and sealed",
            "production_use": "none; no model fit, Model A, projection, site, or postgame changes",
            "training_ready": False,
            "target": "offensive points assigned by the verified scoring-event ledger; zero only after all checks pass",
            "features": "possession-start context only; EPA, success, drive length, terminal play, and future-drive information excluded",
            "partitions": "development=2019-2022; validation=2023-2024; no 2025 rows",
        },
        "table": {"path": str(TABLE.relative_to(ROOT)), "rows": len(table), "sha256": sha256(TABLE)},
        "by_season": annual,
        "by_partition": table.groupby("partition").size().to_dict(),
        "target_distribution": table.target_offensive_points.value_counts().sort_index().to_dict(),
    }
    REPORT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
