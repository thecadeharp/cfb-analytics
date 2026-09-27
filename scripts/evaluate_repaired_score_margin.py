#!/usr/bin/env python3
"""Evaluate the locked score-margin challenger with fully audited repairs."""
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
import research_expected_points_score_margin as base  # noqa: E402

AUDIT = ROOT / "data/research/all_possession_start_score_audit.json"
OUT = ROOT / "data/research/repaired_score_margin_challenger.json"


def repaired_rows(targets, game_audit, raw_game):
    findings = {str(item["drive_id"]): item for item in game_audit["findings"]}
    enriched = targets.copy()
    margins = {}
    home_id = base.identifier(raw_game.homeTeamId.dropna().iloc[0])
    away_id = base.identifier(raw_game.awayTeamId.dropna().iloc[0])
    for row in targets.itertuples():
        item = findings.get(str(row.drive_id))
        if not item or item["status"] not in {"raw_confirmed", "repairable_stale_stamp"}:
            raise ValueError(f"Unaudited drive in recoverable game: {row.game_id}/{row.drive_id}")
        home, away = item["reconstructed_home"], item["reconstructed_away"]
        if str(row.possession_team_id) == home_id:
            margins[str(row.drive_id)] = home - away
        elif str(row.possession_team_id) == away_id:
            margins[str(row.drive_id)] = away - home
        else:
            raise ValueError(f"Unknown possession side: {row.game_id}/{row.drive_id}")
    enriched["start_score_margin"] = enriched.drive_id.map(margins)
    return enriched


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    args = parser.parse_args()
    audit = json.loads(AUDIT.read_text())
    recoverable = {(int(g["season"]), str(g["game_id"])): g for g in audit["games"] if g["recoverable"]}
    frozen = pd.read_csv(base.TABLE, dtype={"game_id": str, "drive_id": str, "possession_team_id": str})
    frames, coverage = [], []
    for year in base.YEARS:
        season = frozen.loc[frozen.season.eq(year)].copy()
        raw = pd.read_parquet(args.source_dir / f"thi-pbp-{year}.parquet", columns=base.COLUMNS)
        raw["game_id"] = raw.game_id.map(base.identifier)
        groups = {game: frame for game, frame in raw.loc[raw.game_id.isin(season.game_id)].groupby("game_id")}
        accepted, repaired = [], 0
        for game_id, targets in season.groupby("game_id"):
            margins, reason = base.game_margins(groups.get(game_id, raw.iloc[:0]), targets)
            if reason is None:
                rows = targets.copy()
                rows["start_score_margin"] = rows.drive_id.map(margins)
                accepted.append(rows)
            elif (year, game_id) in recoverable:
                accepted.append(repaired_rows(targets, recoverable[(year, game_id)], groups[game_id]))
                repaired += 1
        frame = pd.concat(accepted, ignore_index=True)
        frames.append(frame)
        coverage.append({"season": year, "eligible_games": int(frame.game_id.nunique()),
                         "eligible_rows": len(frame), "repaired_games": repaired})
        print(json.dumps(coverage[-1]), flush=True)
    table = pd.concat(frames, ignore_index=True)
    folds = base.evaluate(table)
    report = {"meta": {"generated_at": datetime.now(timezone.utc).isoformat(),
              "status": "research_only_repaired_score_margin_challenger",
              "training_ready": False,
              "production_use": "none; no Model A, site, frozen targets, or 2025 access",
              "specification": "Locked original challenger; only sample coverage changes through audited stale-score repairs.",
              "repair_evidence": str(AUDIT.relative_to(ROOT))},
              "coverage": coverage, "folds": folds,
              "all_folds_improve_both": all(f["improves_both"] for f in folds)}
    OUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"all_folds_improve_both": report["all_folds_improve_both"], "folds": folds}, indent=2))


if __name__ == "__main__":
    main()
