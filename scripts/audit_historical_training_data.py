"""
CFB ANALYTICS
audit_historical_training_data.py

Diagnostic audit for the canonical historical training table.

IMPORTANT:
- Does NOT train or tune any model.
- Does NOT use 2025 for tuning.
- Writes its report even when checks fail so failures can be inspected.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "training" / "historical_games.csv"
MANIFEST = ROOT / "data" / "training" / "historical_training_manifest.json"
OUT = ROOT / "data" / "training" / "historical_training_audit.json"

SEALED_SEASON = 2025


def py(v):
    if pd.isna(v):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def row_dict(row, cols):
    return {c: py(row.get(c)) for c in cols if c in row.index}


def main():
    df = pd.read_csv(DATA)
    with MANIFEST.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    report = {
        "status": "PASS",
        "builder_version": manifest.get("builder_version"),
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "sealed_season": SEALED_SEASON,
        "hard_failures": [],
        "integrity": {},
        "score_diagnostics": {},
        "rolling_feature_diagnostics": {},
        "prior_diagnostics": {},
        "market_diagnostics": {},
    }

    # ---------------------------------------------------------------
    # Basic integrity
    # ---------------------------------------------------------------
    duplicate_ids = int(df["game_id"].duplicated().sum())
    seasons = sorted(df["season"].dropna().astype(int).unique().tolist())

    report["integrity"] = {
        "duplicate_game_ids": duplicate_ids,
        "seasons": seasons,
        "season_counts": {
            str(int(k)): int(v)
            for k, v in df.groupby("season").size().items()
        },
        "sealed_2025_rows": int((df["season"] == SEALED_SEASON).sum()),
    }

    if duplicate_ids:
        report["hard_failures"].append("duplicate_game_ids")

    # ---------------------------------------------------------------
    # SCORE DIAGNOSTICS
    # Do not merely call >100 impossible. College football can exceed 100.
    # Instead distinguish internal inconsistency from extreme-but-possible.
    # ---------------------------------------------------------------
    hs = pd.to_numeric(df["home_score"], errors="coerce")
    aw = pd.to_numeric(df["away_score"], errors="coerce")
    margin = pd.to_numeric(df["actual_home_margin"], errors="coerce")
    total = pd.to_numeric(df["actual_total"], errors="coerce")

    negative_mask = ((hs < 0) | (aw < 0)).fillna(False)
    margin_mismatch_mask = (
        hs.notna()
        & aw.notna()
        & margin.notna()
        & ((margin - (hs - aw)).abs() > 1e-9)
    )
    total_mismatch_mask = (
        hs.notna()
        & aw.notna()
        & total.notna()
        & ((total - (hs + aw)).abs() > 1e-9)
    )
    extreme_mask = ((hs > 100) | (aw > 100) | (total > 150)).fillna(False)

    score_cols = [
        "game_id", "season", "week", "home_team", "away_team",
        "home_score", "away_score", "actual_home_margin", "actual_total",
    ]

    report["score_diagnostics"] = {
        "negative_score_rows": int(negative_mask.sum()),
        "margin_mismatch_rows": int(margin_mismatch_mask.sum()),
        "total_mismatch_rows": int(total_mismatch_mask.sum()),
        "extreme_score_rows_for_review": int(extreme_mask.sum()),
        "negative_examples": [
            row_dict(r, score_cols)
            for _, r in df.loc[negative_mask, score_cols].head(20).iterrows()
        ],
        "margin_mismatch_examples": [
            row_dict(r, score_cols)
            for _, r in df.loc[margin_mismatch_mask, score_cols].head(20).iterrows()
        ],
        "total_mismatch_examples": [
            row_dict(r, score_cols)
            for _, r in df.loc[total_mismatch_mask, score_cols].head(20).iterrows()
        ],
        "extreme_examples": [
            row_dict(r, score_cols)
            for _, r in df.loc[extreme_mask, score_cols]
            .sort_values("actual_total", ascending=False)
            .head(30)
            .iterrows()
        ],
    }

    if negative_mask.any() or margin_mismatch_mask.any() or total_mismatch_mask.any():
        report["hard_failures"].append("score_internal_consistency")

    # ---------------------------------------------------------------
    # ROLLING FEATURE DIAGNOSTICS
    # ---------------------------------------------------------------
    home_pre = [c for c in df.columns if c.startswith("home_pregame_")]
    away_pre = [c for c in df.columns if c.startswith("away_pregame_")]
    pre_cols = home_pre + away_pre

    home_prev = [c for c in df.columns if c.startswith("home_prev_season_")]
    away_prev = [c for c in df.columns if c.startswith("away_prev_season_")]
    prev_cols = home_prev + away_prev

    week1 = df[df["week"] == 1]
    later = df[df["week"] >= 2]

    week1_non_null = int(week1[pre_cols].notna().sum().sum()) if pre_cols else 0
    later_rows_any = int(later[pre_cols].notna().any(axis=1).sum()) if pre_cols else 0
    later_cells = int(later[pre_cols].notna().sum().sum()) if pre_cols else 0

    feature_non_null_counts = {
        c: int(df[c].notna().sum())
        for c in pre_cols
    }

    prior_week_distribution = {
        "home": {
            str(k): int(v)
            for k, v in pd.to_numeric(df["home_prior_weeks"], errors="coerce")
            .value_counts(dropna=False)
            .sort_index()
            .items()
        },
        "away": {
            str(k): int(v)
            for k, v in pd.to_numeric(df["away_prior_weeks"], errors="coerce")
            .value_counts(dropna=False)
            .sort_index()
            .items()
        },
    }

    by_season_week = {}
    for (season, week), g in df.groupby(["season", "week"]):
        key = f"{int(season)}-W{int(week)}"
        by_season_week[key] = {
            "games": int(len(g)),
            "rows_with_any_pregame_feature": (
                int(g[pre_cols].notna().any(axis=1).sum()) if pre_cols else 0
            ),
            "home_prior_weeks_min": py(pd.to_numeric(g["home_prior_weeks"], errors="coerce").min()),
            "home_prior_weeks_max": py(pd.to_numeric(g["home_prior_weeks"], errors="coerce").max()),
            "away_prior_weeks_min": py(pd.to_numeric(g["away_prior_weeks"], errors="coerce").min()),
            "away_prior_weeks_max": py(pd.to_numeric(g["away_prior_weeks"], errors="coerce").max()),
        }

    report["rolling_feature_diagnostics"] = {
        "pregame_feature_columns": len(pre_cols),
        "week1_rows": int(len(week1)),
        "week1_non_null_pregame_cells": week1_non_null,
        "later_week_rows": int(len(later)),
        "later_week_rows_with_any_pregame_feature": later_rows_any,
        "later_week_non_null_pregame_cells": later_cells,
        "feature_non_null_counts": feature_non_null_counts,
        "prior_week_counter_distribution": prior_week_distribution,
        "by_season_week": by_season_week,
    }

    if week1_non_null != 0:
        report["hard_failures"].append("week1_same_season_leakage")
    if later_rows_any == 0:
        report["hard_failures"].append("same_season_features_missing_after_week1")

    # ---------------------------------------------------------------
    # PRIOR-SEASON DIAGNOSTICS
    # ---------------------------------------------------------------
    prior_by_season = {}
    for season, g in df.groupby("season"):
        w1 = g[g["week"] == 1]
        prior_by_season[str(int(season))] = {
            "games": int(len(g)),
            "week1_games": int(len(w1)),
            "week1_rows_with_any_previous_season_feature": (
                int(w1[prev_cols].notna().any(axis=1).sum()) if prev_cols else 0
            ),
            "all_rows_with_any_previous_season_feature": (
                int(g[prev_cols].notna().any(axis=1).sum()) if prev_cols else 0
            ),
        }

    report["prior_diagnostics"] = {
        "previous_season_feature_columns": len(prev_cols),
        "by_season": prior_by_season,
        "feature_non_null_counts": {
            c: int(df[c].notna().sum())
            for c in prev_cols
        },
    }

    # ---------------------------------------------------------------
    # MARKET DIAGNOSTICS
    # ---------------------------------------------------------------
    spread = pd.to_numeric(df["market_home_spread"], errors="coerce")
    fav_size = pd.to_numeric(df["market_favorite_size"], errors="coerce")
    mf = df["market_favorite"].astype(str)

    sign_bad = (
        spread.notna()
        & (
            ((spread < 0) & (mf != df["home_team"].astype(str)))
            | ((spread > 0) & (mf != df["away_team"].astype(str)))
            | ((spread == 0) & (mf != "PICK"))
        )
    )
    size_bad = (
        spread.notna()
        & fav_size.notna()
        & ((fav_size - spread.abs()).abs() > 1e-9)
    )

    report["market_diagnostics"] = {
        "lined_games": int(spread.notna().sum()),
        "favorite_sign_mismatch_rows": int(sign_bad.sum()),
        "favorite_size_mismatch_rows": int(size_bad.sum()),
        "spread_min": py(spread.min()),
        "spread_max": py(spread.max()),
        "favorite_size_max": py(fav_size.max()),
    }

    if sign_bad.any():
        report["hard_failures"].append("market_favorite_sign")
    if size_bad.any():
        report["hard_failures"].append("market_favorite_size")

    # ---------------------------------------------------------------
    # Final
    # ---------------------------------------------------------------
    report["hard_failures"] = sorted(set(report["hard_failures"]))
    report["status"] = "PASS" if not report["hard_failures"] else "FAIL"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("=" * 78)
    print("HISTORICAL TRAINING DATA DIAGNOSTIC AUDIT")
    print("=" * 78)
    print("Status:", report["status"])
    print("Rows:", len(df))
    print("Duplicate IDs:", duplicate_ids)
    print("Negative score rows:", int(negative_mask.sum()))
    print("Margin mismatch rows:", int(margin_mismatch_mask.sum()))
    print("Total mismatch rows:", int(total_mismatch_mask.sum()))
    print("Extreme score rows for review:", int(extreme_mask.sum()))
    print("Week 1 pregame non-null cells:", week1_non_null)
    print("Later-week rows with pregame history:", later_rows_any)
    print("Later-week pregame non-null cells:", later_cells)
    print("Hard failures:", report["hard_failures"])
    print("Wrote:", OUT.relative_to(ROOT))

    # IMPORTANT: do not exit 1 here.
    # The workflow must commit the diagnostic report even when data checks fail.


if __name__ == "__main__":
    main()
