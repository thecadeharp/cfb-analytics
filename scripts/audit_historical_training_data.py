"""
CFB ANALYTICS
audit_historical_training_data.py

Audit the canonical SportsDataverse historical training table BEFORE any
sealed-2025 model evaluation.

Reads:
    data/training/historical_games.csv
    data/training/historical_training_manifest.json

Writes:
    data/training/historical_training_audit.json

This audit does NOT train or tune a model.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "training" / "historical_games.csv"
MANIFEST = ROOT / "data" / "training" / "historical_training_manifest.json"
OUT = ROOT / "data" / "training" / "historical_training_audit.json"

SEALED_SEASON = 2025


def pct(n, d):
    if not d:
        return 0.0
    return round(100.0 * n / d, 2)


def finite_summary(series):
    s = pd.to_numeric(series, errors="coerce")
    s = s[np.isfinite(s)]
    if s.empty:
        return {
            "n": 0,
            "min": None,
            "p01": None,
            "median": None,
            "p99": None,
            "max": None,
            "mean": None,
        }
    return {
        "n": int(len(s)),
        "min": round(float(s.min()), 6),
        "p01": round(float(s.quantile(0.01)), 6),
        "median": round(float(s.median()), 6),
        "p99": round(float(s.quantile(0.99)), 6),
        "max": round(float(s.max()), 6),
        "mean": round(float(s.mean()), 6),
    }


def main():
    if not DATA.exists():
        raise SystemExit(f"Missing {DATA}")
    if not MANIFEST.exists():
        raise SystemExit(f"Missing {MANIFEST}")

    df = pd.read_csv(DATA)

    with MANIFEST.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    audit = {
        "meta": {
            "source_csv": str(DATA.relative_to(ROOT)),
            "source_manifest": str(MANIFEST.relative_to(ROOT)),
            "rows": int(len(df)),
            "columns": int(len(df.columns)),
            "sealed_season": SEALED_SEASON,
            "builder_version": manifest.get("builder_version"),
        },
        "checks": {},
        "season_counts": {},
        "week_counts": {},
        "missingness": {},
        "range_checks": {},
        "market_checks": {},
        "leakage_checks": {},
        "prior_coverage": {},
        "team_name_checks": {},
        "warnings": [],
        "status": "PASS",
    }

    # ------------------------------------------------------------------
    # Basic integrity
    # ------------------------------------------------------------------
    duplicate_ids = int(df["game_id"].duplicated().sum())
    seasons = sorted(df["season"].dropna().astype(int).unique().tolist())

    audit["checks"]["duplicate_game_ids"] = {
        "count": duplicate_ids,
        "pass": duplicate_ids == 0,
    }
    audit["checks"]["expected_seasons_present"] = {
        "seasons": seasons,
        "pass": set(range(2019, 2026)).issubset(set(seasons)),
    }
    audit["checks"]["sealed_2025_present"] = {
        "rows": int((df["season"] == SEALED_SEASON).sum()),
        "pass": int((df["season"] == SEALED_SEASON).sum()) > 0,
    }

    # ------------------------------------------------------------------
    # Counts by season/week
    # ------------------------------------------------------------------
    for season, g in df.groupby("season"):
        season = int(season)
        audit["season_counts"][str(season)] = int(len(g))
        audit["week_counts"][str(season)] = {
            str(int(week)): int(len(wg))
            for week, wg in g.groupby("week")
            if not pd.isna(week)
        }

    # ------------------------------------------------------------------
    # Team names
    # ------------------------------------------------------------------
    blank_home = int(df["home_team"].isna().sum() + df["home_team"].astype(str).str.strip().eq("").sum())
    blank_away = int(df["away_team"].isna().sum() + df["away_team"].astype(str).str.strip().eq("").sum())
    home_feature_mismatch = int(
        (
            df["home_feature_team"].notna()
            & df["home_team"].notna()
            & (df["home_feature_team"] != df["home_team"])
        ).sum()
    )
    away_feature_mismatch = int(
        (
            df["away_feature_team"].notna()
            & df["away_team"].notna()
            & (df["away_feature_team"] != df["away_team"])
        ).sum()
    )

    audit["team_name_checks"] = {
        "blank_home_team_rows": blank_home,
        "blank_away_team_rows": blank_away,
        "home_feature_team_mismatches": home_feature_mismatch,
        "away_feature_team_mismatches": away_feature_mismatch,
    }

    # ------------------------------------------------------------------
    # Final score sanity
    # ------------------------------------------------------------------
    hs = pd.to_numeric(df["home_score"], errors="coerce")
    aw = pd.to_numeric(df["away_score"], errors="coerce")
    actual_margin = pd.to_numeric(df["actual_home_margin"], errors="coerce")
    actual_total = pd.to_numeric(df["actual_total"], errors="coerce")

    score_bad = int(((hs < 0) | (aw < 0) | (hs > 100) | (aw > 100)).fillna(False).sum())
    margin_mismatch = int(
        (
            actual_margin.notna()
            & hs.notna()
            & aw.notna()
            & ((actual_margin - (hs - aw)).abs() > 1e-9)
        ).sum()
    )
    total_mismatch = int(
        (
            actual_total.notna()
            & hs.notna()
            & aw.notna()
            & ((actual_total - (hs + aw)).abs() > 1e-9)
        ).sum()
    )

    audit["checks"]["score_sanity"] = {
        "implausible_score_rows": score_bad,
        "margin_mismatch_rows": margin_mismatch,
        "total_mismatch_rows": total_mismatch,
        "pass": score_bad == 0 and margin_mismatch == 0 and total_mismatch == 0,
    }

    # ------------------------------------------------------------------
    # Missingness by key feature families
    # ------------------------------------------------------------------
    feature_groups = {
        "home_pregame": [c for c in df.columns if c.startswith("home_pregame_")],
        "away_pregame": [c for c in df.columns if c.startswith("away_pregame_")],
        "home_prev_season": [c for c in df.columns if c.startswith("home_prev_season_")],
        "away_prev_season": [c for c in df.columns if c.startswith("away_prev_season_")],
    }

    for name, cols in feature_groups.items():
        if not cols:
            continue
        audit["missingness"][name] = {
            "columns": len(cols),
            "cell_missing_pct": round(float(df[cols].isna().mean().mean() * 100), 2),
        }

    by_season = {}
    for season, g in df.groupby("season"):
        season = int(season)
        by_season[str(season)] = {}
        for name, cols in feature_groups.items():
            if cols:
                by_season[str(season)][name] = round(
                    float(g[cols].isna().mean().mean() * 100), 2
                )
    audit["missingness"]["by_season_pct"] = by_season

    # ------------------------------------------------------------------
    # Leakage checks
    # Week 1 must have no same-season pregame features.
    # Later weeks should increasingly have same-season features.
    # ------------------------------------------------------------------
    pregame_cols = (
        feature_groups["home_pregame"] + feature_groups["away_pregame"]
    )

    week1 = df[df["week"] == 1]
    week1_non_null = int(week1[pregame_cols].notna().sum().sum()) if pregame_cols else 0

    later = df[df["week"] >= 2]
    later_non_null_rows = int(
        later[pregame_cols].notna().any(axis=1).sum()
    ) if pregame_cols else 0

    audit["leakage_checks"]["week1_same_season_features"] = {
        "rows": int(len(week1)),
        "non_null_cells": week1_non_null,
        "pass": week1_non_null == 0,
    }
    audit["leakage_checks"]["later_weeks_have_history"] = {
        "rows": int(len(later)),
        "rows_with_any_pregame_feature": later_non_null_rows,
        "coverage_pct": pct(later_non_null_rows, len(later)),
        "pass": later_non_null_rows > 0,
    }

    # Prior-week counters should be zero in week 1.
    hpw = pd.to_numeric(df["home_prior_weeks"], errors="coerce")
    apw = pd.to_numeric(df["away_prior_weeks"], errors="coerce")
    bad_week1_prior_counter = int(
        (
            (df["week"] == 1)
            & (
                hpw.fillna(0).ne(0)
                | apw.fillna(0).ne(0)
            )
        ).sum()
    )
    audit["leakage_checks"]["week1_prior_week_counters"] = {
        "bad_rows": bad_week1_prior_counter,
        "pass": bad_week1_prior_counter == 0,
    }

    # ------------------------------------------------------------------
    # Previous-season coverage, especially Week 1
    # ------------------------------------------------------------------
    home_prev = feature_groups["home_prev_season"]
    away_prev = feature_groups["away_prev_season"]
    prev_cols = home_prev + away_prev

    for season in seasons:
        g = df[df["season"] == season]
        w1 = g[g["week"] == 1]
        audit["prior_coverage"][str(season)] = {
            "week1_games": int(len(w1)),
            "week1_rows_with_any_prev_prior": int(
                w1[prev_cols].notna().any(axis=1).sum()
            ) if prev_cols else 0,
            "week1_prev_prior_coverage_pct": pct(
                int(w1[prev_cols].notna().any(axis=1).sum()) if prev_cols else 0,
                len(w1),
            ),
        }

    # ------------------------------------------------------------------
    # Range checks for core metrics
    # ------------------------------------------------------------------
    range_targets = [
        c for c in df.columns
        if any(
            key in c
            for key in [
                "off_epa",
                "def_epa_allowed",
                "success_rate",
                "explosive_rate",
                "havoc",
                "line_yards",
                "scoring_opp",
                "drives",
                "plays_per_drive",
            ]
        )
        and (c.startswith("home_") or c.startswith("away_"))
    ]

    for col in range_targets:
        audit["range_checks"][col] = finite_summary(df[col])

    # Explicit probability/rate bounds.
    rate_cols = [
        c for c in range_targets
        if any(k in c for k in ["success_rate", "explosive_rate", "havoc", "scoring_opp"])
    ]
    rate_out_of_bounds = {}
    for col in rate_cols:
        s = pd.to_numeric(df[col], errors="coerce")
        bad = int(((s < 0) | (s > 1)).fillna(False).sum())
        if bad:
            rate_out_of_bounds[col] = bad
    audit["checks"]["rate_features_with_out_of_bounds_values"] = {
        "columns": rate_out_of_bounds,
        "pass": len(rate_out_of_bounds) == 0,
    }

    # ------------------------------------------------------------------
    # Market checks
    # ------------------------------------------------------------------
    spread = pd.to_numeric(df["market_home_spread"], errors="coerce")
    total = pd.to_numeric(df["market_total"], errors="coerce")

    lined = df[spread.notna()].copy()
    audit["market_checks"]["lined_games"] = int(len(lined))
    audit["market_checks"]["lined_pct"] = pct(len(lined), len(df))
    audit["market_checks"]["spread_summary"] = finite_summary(spread)
    audit["market_checks"]["total_summary"] = finite_summary(total)

    # Market-favorite consistency with signed home spread.
    mf = df["market_favorite"].astype(str)
    sign_bad = (
        spread.notna()
        & (
            ((spread < 0) & (mf != df["home_team"].astype(str)))
            | ((spread > 0) & (mf != df["away_team"].astype(str)))
            | ((spread == 0) & (mf != "PICK"))
        )
    )
    audit["market_checks"]["favorite_sign_mismatch_rows"] = int(sign_bad.sum())

    favorite_size = pd.to_numeric(df["market_favorite_size"], errors="coerce")
    size_bad = int(
        (
            spread.notna()
            & favorite_size.notna()
            & ((favorite_size - spread.abs()).abs() > 1e-9)
        ).sum()
    )
    audit["market_checks"]["favorite_size_mismatch_rows"] = size_bad

    bins = [-0.001, 3, 7, 14, 21, 28, 40, np.inf]
    labels = ["0-3", "3-7", "7-14", "14-21", "21-28", "28-40", "40+"]
    bucket = pd.cut(favorite_size, bins=bins, labels=labels, right=True)
    audit["market_checks"]["favorite_size_counts"] = {
        str(label): int((bucket == label).sum())
        for label in labels
    }

    # ------------------------------------------------------------------
    # Sealed-season guard
    # ------------------------------------------------------------------
    sealed_flag = df["sealed_test_season"].astype(str).str.lower().isin(["true", "1"])
    wrong_sealed_flags = int(
        (
            sealed_flag
            != df["season"].eq(SEALED_SEASON)
        ).sum()
    )
    audit["checks"]["sealed_flag_consistency"] = {
        "mismatch_rows": wrong_sealed_flags,
        "pass": wrong_sealed_flags == 0,
    }

    # ------------------------------------------------------------------
    # Final status
    # ------------------------------------------------------------------
    hard_failures = []

    for name, result in audit["checks"].items():
        if isinstance(result, dict) and result.get("pass") is False:
            hard_failures.append(name)

    if audit["market_checks"]["favorite_sign_mismatch_rows"] != 0:
        hard_failures.append("market_favorite_sign")
    if audit["market_checks"]["favorite_size_mismatch_rows"] != 0:
        hard_failures.append("market_favorite_size")
    if home_feature_mismatch or away_feature_mismatch:
        hard_failures.append("feature_team_mapping")

    if hard_failures:
        audit["status"] = "FAIL"
        audit["hard_failures"] = hard_failures
    else:
        audit["hard_failures"] = []

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2)

    print("=" * 78)
    print("HISTORICAL TRAINING DATA AUDIT")
    print("=" * 78)
    print("Status:", audit["status"])
    print("Rows:", len(df))
    print("Seasons:", seasons)
    print("Duplicate game IDs:", duplicate_ids)
    print("Week 1 same-season feature non-null cells:", week1_non_null)
    print("Later-week rows with any same-season feature:", later_non_null_rows)
    print("Market favorite sign mismatches:", audit["market_checks"]["favorite_sign_mismatch_rows"])
    print("Market favorite size mismatches:", size_bad)
    print("Home feature-team mismatches:", home_feature_mismatch)
    print("Away feature-team mismatches:", away_feature_mismatch)
    print("Hard failures:", audit["hard_failures"])
    print("Wrote:", OUT.relative_to(ROOT))

    if audit["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
