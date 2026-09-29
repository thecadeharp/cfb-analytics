#!/usr/bin/env python3
"""One-time sealed 2025 evaluation of the frozen expected-points candidate.

The candidate specification and coefficients are loaded from the committed
2019-2024 artifact. 2025 is used only after those locks pass. Nothing in this
script changes Model A, projections, site data, or the candidate formula.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlretrieve

import numpy as np
import pandas as pd

import research_expected_points_score_margin as base
from audit_all_possession_start_scores import audit_game, normalized_ids
from audit_verified_possession_points import validate_scores
from build_historical_training_data import boolish
from build_verified_possession_ledger import EXTRA_COLUMNS, build_ledger
from evaluate_repaired_score_margin import build_repaired_table
from fit_repaired_expected_points_candidate import FEATURES, calibration, predict
from reconstruct_scoring_events import SOURCE_COLUMNS
from verify_historical_scores_ncaa import REPORT as NCAA_REPORT

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "data/research/repaired_expected_points_candidate.json"
AUDIT = ROOT / "data/research/all_possession_start_score_audit.json"
OUT = ROOT / "data/research/sealed_expected_points_holdout_2025.json"
EXPECTED_CANDIDATE_SHA256 = "ab525744fee8d093ad73fe7612a4ab4f0006187e006ff63c2ceb7d3db753372a"
EXPECTED_AUDIT_SHA256 = "fcc491a08ba1a64eb4411308c4c343fe9edc4b6cf91a54d95576c9e5caea899a"
EXPECTED_NCAA_AUDIT_SHA256 = "38330aa2d8b6a5035b247aa85d1051f5c2dd953c59b913bb2f3451f45993e2b6"
EXPECTED_SOURCE_SHA256 = {
    "2019": "d683cd317c80937a243b17c8f5a1ffe661037dfafd7c6161c24bce392f725a4e",
    "2020": "285eb74675fa6abd9b623b6a7c17c8b425a295de332618ce1778e818a7eafcc0",
    "2021": "bc00390948b827d3f1e134a69a91546858264ebaa0281baa936e03602a093bf4",
    "2022": "c592cf3c8eb6c5e6c55979ffcba92665e01816672ad0e168ec4a5ede7f9dacd1",
    "2023": "0a6f11dcd0790580a71ece68e9da54d00245e87588b0e56209f03782bf1944e6",
    "2024": "6405f37bdcd1576451c46d803725adc0c01fce5e1f5e9666b7208991bcc16b3a",
    "2025": "740566c0d034fa767008a40797dd491acb91dee47934cefb4225494f71c42853",
}
YEARS = tuple(range(2019, 2026))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def download_sources(source_dir):
    source_dir.mkdir(parents=True, exist_ok=True)
    sources = {}
    for year in YEARS:
        path = source_dir / f"thi-pbp-{year}.parquet"
        url = ("https://github.com/sportsdataverse/sportsdataverse-data/releases/"
               f"download/espn_cfb_pbp/play_by_play_{year}.parquet")
        if not path.exists():
            temporary = path.with_suffix(".download")
            urlretrieve(url, temporary)
            temporary.replace(path)
        source_hash = digest(path)
        if source_hash != EXPECTED_SOURCE_SHA256[str(year)]:
            raise ValueError(f"Source checksum changed for {year}; refusing sealed evaluation")
        sources[str(year)] = {"url": url, "sha256": source_hash}
    return sources


def load_locked_candidate():
    if digest(CANDIDATE) != EXPECTED_CANDIDATE_SHA256:
        raise ValueError("Frozen candidate checksum changed; refusing to open 2025")
    if digest(AUDIT) != EXPECTED_AUDIT_SHA256:
        raise ValueError("Historical repair audit checksum changed; refusing to open 2025")
    if digest(NCAA_REPORT) != EXPECTED_NCAA_AUDIT_SHA256:
        raise ValueError("Independent 2025 score audit changed; refusing to open 2025")
    if base.digest(base.TABLE) != base.EXPECTED_SHA:
        raise ValueError("Frozen 2019-2024 target table changed; refusing to open 2025")
    report = json.loads(CANDIDATE.read_text())
    meta = report.get("meta", {})
    coefficients = np.asarray(report.get("coefficients_fit_on_all_approved_2019_2024_rows"), dtype=float)
    if (meta.get("status") != "research_only_repaired_expected_points_candidate_v1"
            or meta.get("training_ready") is not False
            or report.get("features") != FEATURES
            or coefficients.shape != (len(FEATURES),)
            or not np.isfinite(coefficients).all()):
        raise ValueError("Frozen candidate contract is invalid")
    return report, coefficients


def fit_baseline(train):
    x = base.design(train)
    penalty = np.eye(x.shape[1])
    penalty[0, 0] = 0
    return np.linalg.solve(x.T @ x + 10.0 * penalty,
                           x.T @ train.target_offensive_points.to_numpy(float))


def predict_baseline(frame, coefficients):
    return np.clip(base.design(frame) @ coefficients, 0, 8)


def context_rows(targets, findings, raw_game):
    """Attach reconstructed pre-possession margin or quarantine the whole game."""
    by_drive = {str(item["drive_id"]): item for item in findings}
    accepted = {"raw_confirmed", "repairable_stale_stamp"}
    if any(by_drive.get(str(row.drive_id), {}).get("status") not in accepted
           for row in targets.itertuples()):
        raise ValueError("unresolved_score_context")
    home_ids = normalized_ids(raw_game.homeTeamId.dropna()).unique()
    away_ids = normalized_ids(raw_game.awayTeamId.dropna()).unique()
    if len(home_ids) != 1 or len(away_ids) != 1:
        raise ValueError("ambiguous_game_teams")
    home_id, away_id = home_ids[0], away_ids[0]
    margins, repaired = {}, 0
    for row in targets.itertuples():
        item = by_drive[str(row.drive_id)]
        home, away = float(item["reconstructed_home"]), float(item["reconstructed_away"])
        team = str(row.possession_team_id)
        if team == home_id:
            margins[str(row.drive_id)] = home - away
        elif team == away_id:
            margins[str(row.drive_id)] = away - home
        else:
            raise ValueError("unknown_possession_side")
        repaired += item["status"] == "repairable_stale_stamp"
    result = targets.copy()
    result["start_score_margin"] = result.drive_id.map(margins)
    if result.start_score_margin.isna().any():
        raise ValueError("missing_reconstructed_margin")
    return result, repaired


def prepare_holdout(raw, independent_report):
    plays, events, verified_ids = validate_scores(raw, independent_report)
    ledger, _, _, ledger_counts = build_ledger(plays, events)
    eligible = ledger.loc[
        boolish(ledger.label_check_passed)
        & ledger.offensive_points.notna()
        & ledger.start_yards_to_endzone.notna()
        & ledger.start_period.notna()
        & ledger.possession_team_id.notna()
    ].copy()
    eligible["game_id"] = normalized_ids(eligible.game_id)
    eligible["drive_id"] = normalized_ids(eligible.drive_id)
    eligible["possession_team_id"] = normalized_ids(eligible.possession_team_id)
    eligible["target_offensive_points"] = pd.to_numeric(eligible.offensive_points, errors="raise")
    plays = plays.copy()
    plays["game_id"] = normalized_ids(plays.game_id)
    groups = {str(game): frame for game, frame in plays.groupby("game_id")}
    admitted, quarantine, status_counts = [], [], Counter()
    repaired_starts = 0
    for game_id, targets in eligible.groupby("game_id"):
        raw_game = groups.get(str(game_id))
        if raw_game is None:
            quarantine.append({"game_id": str(game_id), "possessions": len(targets),
                               "reason": "missing_verified_source_game"})
            continue
        findings = audit_game(raw_game, targets)
        status_counts.update(item["status"] for item in findings)
        try:
            rows, repaired = context_rows(targets, findings, raw_game)
        except ValueError as error:
            quarantine.append({"game_id": str(game_id), "possessions": len(targets),
                               "reason": str(error)})
            continue
        admitted.append(rows)
        repaired_starts += repaired
    if not admitted:
        raise RuntimeError("No sealed holdout rows passed the independent context gate")
    holdout = pd.concat(admitted, ignore_index=True)
    if holdout.duplicated(["game_id", "drive_id"]).any():
        raise RuntimeError("Duplicate sealed holdout possession key")
    coverage = {
        "independently_verified_games": len(verified_ids),
        "observed_regulation_possessions": ledger_counts["observed_regulation_possessions"],
        "ledger_label_checks_passed": ledger_counts["label_checks_passed"],
        "context_eligible_games": int(holdout.game_id.nunique()),
        "context_eligible_possessions": len(holdout),
        "context_quarantined_games": len(quarantine),
        "context_quarantined_possessions": int(sum(item["possessions"] for item in quarantine)),
        "corroborated_stale_start_repairs": int(repaired_starts),
        "context_status_counts": dict(status_counts),
    }
    return holdout, coverage, quarantine


def game_bootstrap_interval(frame, baseline, candidate):
    actual = frame.target_offensive_points.to_numpy(float)
    errors = pd.DataFrame({"game": frame.game_id.to_numpy(),
                           "delta": np.abs(baseline - actual) - np.abs(candidate - actual)})
    groups = errors.groupby("game").delta.agg(["sum", "count"]).to_numpy()
    rng = np.random.default_rng(20260929)
    draws = rng.integers(len(groups), size=(2000, len(groups)))
    improvements = groups[draws, 0].sum(axis=1) / groups[draws, 1].sum(axis=1)
    return np.quantile(improvements, [.025, .975]).tolist()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()

    if OUT.exists():
        raise RuntimeError("Sealed 2025 holdout report already exists; refusing a repeat evaluation")
    candidate_report, candidate_coefficients = load_locked_candidate()
    if args.download:
        sources = download_sources(args.source_dir)
    else:
        sources = {}
        for year in YEARS:
            source_hash = digest(args.source_dir / f"thi-pbp-{year}.parquet")
            if source_hash != EXPECTED_SOURCE_SHA256[str(year)]:
                raise ValueError(f"Source checksum changed for {year}; refusing sealed evaluation")
            sources[str(year)] = {"url": None, "sha256": source_hash}

    # The matched baseline is fit on the same approved 2019-2024 rows. The
    # frozen candidate coefficients are loaded, never refit after opening 2025.
    historical, historical_coverage = build_repaired_table(args.source_dir)
    baseline_coefficients = fit_baseline(historical)

    columns = list(dict.fromkeys(SOURCE_COLUMNS + EXTRA_COLUMNS + base.COLUMNS))
    raw_2025 = pd.read_parquet(args.source_dir / "thi-pbp-2025.parquet", columns=columns)
    independent = json.loads(NCAA_REPORT.read_text())
    if independent.get("meta", {}).get("status") != "research_only_cross_source_score_check":
        raise ValueError("Independent 2025 score audit missing or invalid")
    holdout, coverage, quarantine = prepare_holdout(raw_2025, independent)

    actual = holdout.target_offensive_points.to_numpy(float)
    baseline_prediction = predict_baseline(holdout, baseline_coefficients)
    candidate_prediction = predict(holdout, candidate_coefficients)
    baseline_metrics = base.score(actual, baseline_prediction)
    candidate_metrics = base.score(actual, candidate_prediction)
    interval = game_bootstrap_interval(holdout, baseline_prediction, candidate_prediction)
    mae_improvement = baseline_metrics["mae"] - candidate_metrics["mae"]
    rmse_improvement = baseline_metrics["rmse"] - candidate_metrics["rmse"]
    passed = mae_improvement > 0 and rmse_improvement > 0 and interval[0] > 0

    report = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "research_only_sealed_expected_points_holdout_2025",
            "training_ready": False,
            "production_use": "none; Model A, projections, ratings, and site untouched",
            "evaluation_policy": "One sealed 2025 evaluation of the checksum-locked candidate; no tuning after results.",
            "candidate_sha256": EXPECTED_CANDIDATE_SHA256,
            "historical_repair_audit_sha256": EXPECTED_AUDIT_SHA256,
            "candidate_status": candidate_report["meta"]["status"],
        },
        "source_hashes": sources,
        "historical_training_coverage": historical_coverage,
        "holdout_coverage": coverage,
        "quarantined_games": quarantine,
        "matched_baseline": baseline_metrics,
        "frozen_candidate": candidate_metrics,
        "mae_improvement": mae_improvement,
        "rmse_improvement": rmse_improvement,
        "mae_improvement_game_bootstrap_95_interval": interval,
        "holdout_gate_passed": passed,
        "field_position_calibration": calibration(
            holdout, candidate_prediction, "start_yards_to_endzone", [0, 20, 40, 60, 80, 100]),
        "score_margin_calibration": calibration(
            holdout, candidate_prediction, "start_score_margin", [-100, -15, -8, -1, 0, 7, 14, 100]),
        "limitations": [
            "Results apply only to independently verified games and fully checked possession labels.",
            "Corroborating later rows are used only to validate stale source stamps; they are not model inputs.",
            "A passed holdout gate does not authorize production use or changes to Model A.",
            "A failed holdout gate must be reported as-is; the 2025 result may not be used to retune this candidate.",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"holdout_coverage": coverage,
                      "matched_baseline": baseline_metrics,
                      "frozen_candidate": candidate_metrics,
                      "mae_improvement": mae_improvement,
                      "rmse_improvement": rmse_improvement,
                      "mae_improvement_game_bootstrap_95_interval": interval,
                      "holdout_gate_passed": passed}, indent=2), flush=True)


if __name__ == "__main__":
    main()
