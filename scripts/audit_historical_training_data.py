"""
CFB ANALYTICS
audit_historical_training_data.py

V4 diagnostic audit for the canonical historical training table.

Validates:
- core integrity / scores
- leakage-safe rolling features
- previous-season priors
- market sign conventions
- REALIZED drive/scoring targets added in V4
- no accidental current-game target -> pregame leakage
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

REALIZED = [
    "actual_drives",
    "actual_scoring_opportunities",
    "actual_scoring_opportunity_rate",
    "actual_points_on_scoring_opportunities",
    "actual_points_per_scoring_opportunity",
    "actual_scoring_opportunity_conversion_rate",
]


def py(v):
    if pd.isna(v):
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.bool_):
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
        "realized_drive_diagnostics": {},
        "rolling_feature_diagnostics": {},
        "prior_diagnostics": {},
        "market_diagnostics": {},
    }

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

    hs = pd.to_numeric(df["home_score"], errors="coerce")
    aw = pd.to_numeric(df["away_score"], errors="coerce")
    margin = pd.to_numeric(df["actual_home_margin"], errors="coerce")
    total = pd.to_numeric(df["actual_total"], errors="coerce")

    negative_mask = ((hs < 0) | (aw < 0)).fillna(False)
    margin_mismatch = (
        hs.notna() & aw.notna() & margin.notna()
        & ((margin - (hs-aw)).abs() > 1e-9)
    )
    total_mismatch = (
        hs.notna() & aw.notna() & total.notna()
        & ((total - (hs+aw)).abs() > 1e-9)
    )
    extreme_mask = ((hs > 100) | (aw > 100) | (total > 150)).fillna(False)

    score_cols = [
        "game_id", "season", "week", "home_team", "away_team",
        "home_score", "away_score", "actual_home_margin", "actual_total",
    ]

    report["score_diagnostics"] = {
        "negative_score_rows": int(negative_mask.sum()),
        "margin_mismatch_rows": int(margin_mismatch.sum()),
        "total_mismatch_rows": int(total_mismatch.sum()),
        "extreme_score_rows_for_review": int(extreme_mask.sum()),
        "extreme_examples": [
            row_dict(r, score_cols)
            for _, r in df.loc[extreme_mask, score_cols]
            .sort_values("actual_total", ascending=False)
            .head(30).iterrows()
        ],
    }

    if negative_mask.any() or margin_mismatch.any() or total_mismatch.any():
        report["hard_failures"].append("score_internal_consistency")

    # ------------------------------------------------------------------
    # V4 REALIZED DRIVE / SCORING TARGETS
    # ------------------------------------------------------------------
    target_cols = [
        f"{side}_{metric}"
        for side in ["home", "away"]
        for metric in REALIZED
    ]
    missing_targets = [c for c in target_cols if c not in df.columns]

    realized = {
        "required_target_columns": target_cols,
        "missing_target_columns": missing_targets,
        "non_null_counts": {},
        "range_checks": {},
    }

    if missing_targets:
        report["hard_failures"].append("realized_drive_target_columns_missing")
    else:
        realized["non_null_counts"] = {
            c: int(df[c].notna().sum()) for c in target_cols
        }

        if all(df[c].notna().sum() == 0 for c in target_cols):
            report["hard_failures"].append("realized_drive_targets_all_null")

        range_failures = []

        for side in ["home", "away"]:
            drives = pd.to_numeric(
                df[f"{side}_actual_drives"], errors="coerce"
            )
            opps = pd.to_numeric(
                df[f"{side}_actual_scoring_opportunities"], errors="coerce"
            )
            rate = pd.to_numeric(
                df[f"{side}_actual_scoring_opportunity_rate"], errors="coerce"
            )
            pts = pd.to_numeric(
                df[f"{side}_actual_points_on_scoring_opportunities"],
                errors="coerce",
            )
            ppso = pd.to_numeric(
                df[f"{side}_actual_points_per_scoring_opportunity"],
                errors="coerce",
            )
            conv = pd.to_numeric(
                df[f"{side}_actual_scoring_opportunity_conversion_rate"],
                errors="coerce",
            )

            bad_negative = (
                (drives < 0) | (opps < 0) | (pts < 0) | (ppso < 0)
            ).fillna(False)
            bad_opp_gt_drives = (
                drives.notna() & opps.notna() & (opps > drives)
            )
            bad_rate = ((rate < 0) | (rate > 1)).fillna(False)
            bad_conv = ((conv < 0) | (conv > 1)).fillna(False)

            recomputed_rate_bad = (
                drives.gt(0) & opps.notna() & rate.notna()
                & ((rate - (opps / drives)).abs() > 1e-9)
            )

            side_report = {
                "rows_with_drives": int(drives.notna().sum()),
                "median_drives": py(drives.median()),
                "min_drives": py(drives.min()),
                "max_drives": py(drives.max()),
                "median_scoring_opportunities": py(opps.median()),
                "max_scoring_opportunities": py(opps.max()),
                "median_scoring_opportunity_rate": py(rate.median()),
                "median_points_per_scoring_opportunity": py(ppso.median()),
                "negative_value_rows": int(bad_negative.sum()),
                "opportunities_greater_than_drives_rows": int(
                    bad_opp_gt_drives.sum()
                ),
                "rate_out_of_range_rows": int(bad_rate.sum()),
                "conversion_out_of_range_rows": int(bad_conv.sum()),
                "rate_recompute_mismatch_rows": int(
                    recomputed_rate_bad.sum()
                ),
            }
            realized["range_checks"][side] = side_report

            if (
                bad_negative.any()
                or bad_opp_gt_drives.any()
                or bad_rate.any()
                or bad_conv.any()
                or recomputed_rate_bad.any()
            ):
                range_failures.append(side)

        if range_failures:
            report["hard_failures"].append(
                "realized_drive_target_internal_consistency"
            )

    report["realized_drive_diagnostics"] = realized

    # ------------------------------------------------------------------
    # ROLLING LEAKAGE-SAFE FEATURES
    # ------------------------------------------------------------------
    home_pre = [c for c in df.columns if c.startswith("home_pregame_")]
    away_pre = [c for c in df.columns if c.startswith("away_pregame_")]
    pre_cols = home_pre + away_pre

    home_prev = [c for c in df.columns if c.startswith("home_prev_season_")]
    away_prev = [c for c in df.columns if c.startswith("away_prev_season_")]
    prev_cols = home_prev + away_prev

    week1 = df[df["week"] == 1]
    later = df[df["week"] >= 2]

    week1_non_null = (
        int(week1[pre_cols].notna().sum().sum()) if pre_cols else 0
    )
    later_rows_any = (
        int(later[pre_cols].notna().any(axis=1).sum()) if pre_cols else 0
    )
    later_cells = (
        int(later[pre_cols].notna().sum().sum()) if pre_cols else 0
    )

    v4_pregame_expected = [
        f"{side}_pregame_{metric}"
        for side in ["home", "away"]
        for metric in REALIZED
    ]
    v4_prev_expected = [
        f"{side}_prev_season_{metric}"
        for side in ["home", "away"]
        for metric in REALIZED
    ]

    missing_v4_pregame = [
        c for c in v4_pregame_expected if c not in df.columns
    ]
    missing_v4_prev = [
        c for c in v4_prev_expected if c not in df.columns
    ]

    report["rolling_feature_diagnostics"] = {
        "pregame_feature_columns": len(pre_cols),
        "week1_rows": int(len(week1)),
        "week1_non_null_pregame_cells": week1_non_null,
        "later_week_rows": int(len(later)),
        "later_week_rows_with_any_pregame_feature": later_rows_any,
        "later_week_non_null_pregame_cells": later_cells,
        "missing_v4_realized_pregame_columns": missing_v4_pregame,
        "v4_realized_pregame_non_null_counts": {
            c: int(df[c].notna().sum())
            for c in v4_pregame_expected if c in df.columns
        },
    }

    if week1_non_null != 0:
        report["hard_failures"].append("week1_same_season_leakage")
    if later_rows_any == 0:
        report["hard_failures"].append(
            "same_season_features_missing_after_week1"
        )
    if missing_v4_pregame:
        report["hard_failures"].append(
            "v4_realized_pregame_features_missing"
        )

    report["prior_diagnostics"] = {
        "previous_season_feature_columns": len(prev_cols),
        "missing_v4_realized_previous_season_columns": missing_v4_prev,
        "v4_realized_previous_season_non_null_counts": {
            c: int(df[c].notna().sum())
            for c in v4_prev_expected if c in df.columns
        },
    }

    if missing_v4_prev:
        report["hard_failures"].append(
            "v4_realized_previous_season_features_missing"
        )

    # ------------------------------------------------------------------
    # MARKET
    # ------------------------------------------------------------------
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
        spread.notna() & fav_size.notna()
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

    report["hard_failures"] = sorted(set(report["hard_failures"]))
    report["status"] = (
        "PASS" if not report["hard_failures"] else "FAIL"
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("=" * 78)
    print("HISTORICAL TRAINING DATA V4 AUDIT")
    print("=" * 78)
    print("Status:", report["status"])
    print("Builder:", report["builder_version"])
    print("Rows:", len(df))
    print("Duplicate IDs:", duplicate_ids)
    print("Week 1 pregame non-null cells:", week1_non_null)
    print("Later-week rows with pregame history:", later_rows_any)
    print("Missing realized targets:", missing_targets)
    print("Hard failures:", report["hard_failures"])
    print("Wrote:", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
