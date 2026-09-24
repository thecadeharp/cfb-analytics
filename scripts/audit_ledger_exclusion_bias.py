#!/usr/bin/env python3
"""Research-only exclusion-bias audit for the 2019-2024 possession ledger.

Measures where conservative ledger checks quarantine observed possessions. It
does not fit a model, repair rows, or change any production surface. 2025 is
intentionally excluded as the sealed holdout.
"""

from __future__ import annotations

import argparse
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
REPORT = ROOT / "data/research/ledger_exclusion_bias_2019_2024.json"
YEARS = list(range(2019, 2025))


def bucket(value, *, kind):
    if kind == "start_period":
        return f"Q{int(value)}" if pd.notna(value) else "missing"
    if kind == "first_observed_down":
        return (
            "first_down" if value == 1
            else "later_down" if pd.notna(value)
            else "missing"
        )
    if kind == "core_plays":
        return (
            "1" if value == 1
            else "2-4" if value <= 4
            else "5-8" if value <= 8
            else "9+"
        )
    raise ValueError(kind)


def strata(frame: pd.DataFrame, column: str, kind: str | None = None):
    rows = []
    observed = frame.loc[frame.observed_possession].copy()

    if kind:
        observed["stratum"] = observed[column].map(
            lambda value: bucket(value, kind=kind)
        )
    else:
        observed["stratum"] = observed[column]

    for name, group in observed.groupby("stratum", dropna=False, sort=True):
        total = len(group)
        passed = int(group.label_check_passed.sum())
        rows.append({
            "stratum": str(name),
            "observed": total,
            "passed": passed,
            "unresolved": total - passed,
            "unresolved_rate": (total - passed) / total,
        })

    return rows


def summarize(ledger: pd.DataFrame):
    observed = ledger.loc[ledger.observed_possession].copy()
    observed["scoring_drive"] = observed.assigned_offensive_points.gt(0).map({
        True: "scoring",
        False: "scoreless",
    })
    observed["terminal_status"] = (
        observed["flags"]
        .fillna("")
        .str.contains("terminal_not_observed")
        .map({
            True: "terminal_missing",
            False: "terminal_observed",
        })
    )

    game_rates = observed.groupby("game_id").label_check_passed.agg(
        ["count", "sum"]
    )
    game_rates["unresolved_rate"] = 1 - game_rates["sum"] / game_rates["count"]

    return {
        "observed_possessions": len(observed),
        "passed": int(observed.label_check_passed.sum()),
        "unresolved": int((~observed.label_check_passed).sum()),
        "unresolved_rate": float((~observed.label_check_passed).mean()),
        "by_start_period": strata(observed, "start_period", "start_period"),
        "by_scoring_status": strata(observed, "scoring_drive"),
        "by_first_observed_down": strata(
            observed, "first_observed_down", "first_observed_down"
        ),
        "by_core_plays": strata(observed, "core_plays", "core_plays"),
        "by_terminal_status": strata(observed, "terminal_status"),
        "game_unresolved_rate": {
            "median": float(game_rates.unresolved_rate.median()),
            "p90": float(game_rates.unresolved_rate.quantile(0.90)),
            "games_over_25pct": int(
                (game_rates.unresolved_rate > 0.25).sum()
            ),
        },
    }


def audit_year(year: int, path: Path, asset_url: str | None):
    columns = list(dict.fromkeys(SOURCE_COLUMNS + EXTRA_COLUMNS))
    raw = pd.read_parquet(path, columns=columns)
    official, _ = official_scores(year)
    plays, events, game_ids, rejected = verified_plays(raw, official)

    ledger, _, _, summary = build_ledger(plays, events)
    if summary["verified_games"] != len(game_ids):
        raise RuntimeError(f"{year}: verified-game coverage mismatch")

    return {
        "season": year,
        "source_asset": asset_url or "local_parquet",
        "verified_games": len(game_ids),
        "cross_source_rejections": dict(rejected),
        "bias": summarize(ledger),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", nargs="+", type=int, default=YEARS)
    args = parser.parse_args()

    years = sorted(set(args.seasons))
    if years != YEARS:
        parser.error(
            "This audit intentionally covers exactly 2019-2024; 2025 is sealed."
        )

    results = []
    with tempfile.TemporaryDirectory() as tmp:
        assets = get_release_assets()
        for year in years:
            path, asset = download_season(year, assets, Path(tmp))
            result = audit_year(year, path, asset["browser_download_url"])
            results.append(result)
            print(json.dumps({
                "season": year,
                "unresolved_rate": result["bias"]["unresolved_rate"],
            }), flush=True)

    report = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "research_only_historical_ledger_exclusion_bias_audit",
            "scope": (
                "2019-2024 independently score-verified observed regulation "
                "possessions only; 2025 excluded and sealed"
            ),
            "production_use": (
                "none; no Model A, projection, postgame, site, or "
                "ledger-eligibility changes"
            ),
            "training_ready": False,
            "interpretation": (
                "Differences identify potential selection bias to investigate; "
                "they do not authorize row repair or model fitting."
            ),
        },
        "seasons": results,
    }

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
