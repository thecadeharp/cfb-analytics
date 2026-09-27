#!/usr/bin/env python3
"""Report coverage and selection differences after possession-score repairs."""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "data/research/expected_points_clean_games_2019_2024.csv.gz"
STRICT = ROOT / "data/research/expected_points_score_margin_challenger.json"
AUDIT = ROOT / "data/research/all_possession_start_score_audit.json"
OUT = ROOT / "data/research/repaired_sample_bias_audit.json"


def cohort_summary(rows):
    targets = pd.to_numeric(rows.target_offensive_points, errors="raise")
    field = pd.to_numeric(rows.start_yards_to_endzone, errors="coerce")
    periods = pd.to_numeric(rows.start_period, errors="coerce")
    return {
        "games": int(rows.game_id.nunique()), "possessions": len(rows),
        "possessions_per_game": float(len(rows) / rows.game_id.nunique()) if len(rows) else None,
        "mean_offensive_points": float(targets.mean()) if len(rows) else None,
        "scoring_possession_rate": float(targets.gt(0).mean()) if len(rows) else None,
        "touchdown_possession_rate": float(targets.ge(6).mean()) if len(rows) else None,
        "mean_start_yards_to_endzone": float(field.mean()) if len(rows) else None,
        "fourth_quarter_share": float(periods.eq(4).mean()) if len(rows) else None,
        "target_distribution": {str(k): int(v) for k, v in sorted(Counter(targets.astype(int)).items())},
    }


def standardized_differences(full, cohort):
    fields = ["target_offensive_points", "start_yards_to_endzone", "start_period"]
    result = {}
    for field in fields:
        all_values = pd.to_numeric(full[field], errors="coerce")
        values = pd.to_numeric(cohort[field], errors="coerce")
        scale = float(all_values.std(ddof=0))
        result[field] = None if not scale else float((values.mean() - all_values.mean()) / scale)
    return result


def build_report(table, strict_report, audit):
    table = table.copy()
    table["game_id"] = table.game_id.astype(str)
    rejected = {str(row["game_id"]) for row in strict_report["excluded_games"]}
    repaired = {str(row["game_id"]) for row in audit["games"] if row["recoverable"]}
    quarantined = rejected - repaired
    table["cohort"] = np.select(
        [table.game_id.isin(repaired), table.game_id.isin(quarantined)],
        ["repaired", "quarantined"], default="strict_eligible"
    )
    summaries = {}
    for name in ["strict_eligible", "repaired", "quarantined"]:
        rows = table.loc[table.cohort.eq(name)]
        summaries[name] = cohort_summary(rows)
        summaries[name]["standardized_differences_vs_full"] = standardized_differences(table, rows)
        summaries[name]["by_season"] = {
            str(int(year)): {"games": int(group.game_id.nunique()), "possessions": len(group)}
            for year, group in rows.groupby("season")
        }
    if set(table.cohort) != {"strict_eligible", "repaired", "quarantined"}:
        raise ValueError("Missing expected sample cohort")
    return {"meta": {"generated_at": datetime.now(timezone.utc).isoformat(),
                     "status": "research_only_repaired_sample_bias_audit",
                     "training_ready": False,
                     "production_use": "none; no Model A, site, or 2025 access",
                     "interpretation": "Standardized differences compare each cohort with the complete frozen 2019-2024 clean-game table; they describe selection, not causal bias."},
            "full_sample": cohort_summary(table), "cohorts": summaries}


def main():
    table = pd.read_csv(TABLE, dtype={"game_id": str, "drive_id": str, "possession_team_id": str})
    report = build_report(table, json.loads(STRICT.read_text()), json.loads(AUDIT.read_text()))
    OUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"full_sample": report["full_sample"], "cohorts": report["cohorts"]}, indent=2))


if __name__ == "__main__":
    main()
