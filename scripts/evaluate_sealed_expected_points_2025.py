#!/usr/bin/env python3
"""One-time sealed evaluation of the frozen expected-points candidate on 2025.

All inputs are immutable repository artifacts. No mutable remote play-by-play is
downloaded, and nothing here changes Model A, projections, ratings, or the site.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import research_expected_points_score_margin as base
from fit_repaired_expected_points_candidate import FEATURES, calibration, predict

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "data/research/repaired_expected_points_candidate.json"
AUDIT = ROOT / "data/research/all_possession_start_score_audit.json"
HISTORICAL = ROOT / "data/research/expected_points_clean_games_2019_2024.csv.gz"
HOLDOUT = ROOT / "data/research/sealed_expected_points_holdout_input_2025.csv.gz"
OUT = ROOT / "data/research/sealed_expected_points_holdout_2025.json"

EXPECTED_CANDIDATE_SHA256 = "ab525744fee8d093ad73fe7612a4ab4f0006187e006ff63c2ceb7d3db753372a"
EXPECTED_AUDIT_SHA256 = "fcc491a08ba1a64eb4411308c4c343fe9edc4b6cf91a54d95576c9e5caea899a"
EXPECTED_HISTORICAL_SHA256 = "983f967620d63173e2c105defc9e537d6c32789bf23c56f9d608cb289598c141"
EXPECTED_HOLDOUT_SHA256 = "df29d003dc215b71b3619b3cf97a28b110e892590c5a40c840dc9b2eb6369928"
EXPECTED_HOLDOUT_GAMES = 213
EXPECTED_HOLDOUT_POSSESSIONS = 4696


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def assert_digest(path: Path, expected: str, label: str):
    if digest(path) != expected:
        raise ValueError(f"{label} checksum changed; refusing sealed evaluation")


def load_locked_candidate():
    assert_digest(CANDIDATE, EXPECTED_CANDIDATE_SHA256, "Frozen candidate")
    report = json.loads(CANDIDATE.read_text())
    coefficients = np.asarray(
        report.get("coefficients_fit_on_all_approved_2019_2024_rows"), dtype=float)
    if (report.get("meta", {}).get("status") !=
            "research_only_repaired_expected_points_candidate_v1"
            or report.get("meta", {}).get("training_ready") is not False
            or report.get("features") != FEATURES
            or coefficients.shape != (len(FEATURES),)
            or not np.isfinite(coefficients).all()):
        raise ValueError("Frozen candidate contract is invalid")
    return report, coefficients


def load_matched_historical(candidate_report):
    """Recover the exact approved sample without reopening mutable raw files."""
    assert_digest(HISTORICAL, EXPECTED_HISTORICAL_SHA256, "Frozen historical target")
    assert_digest(AUDIT, EXPECTED_AUDIT_SHA256, "Historical repair audit")
    frozen = pd.read_csv(HISTORICAL, dtype={"game_id": str, "drive_id": str,
                                            "possession_team_id": str})
    frozen["season"] = pd.to_numeric(frozen.season, errors="raise").astype(int)
    audit = json.loads(AUDIT.read_text())
    if audit.get("meta", {}).get("status") != "research_only_all_possession_start_score_audit":
        raise ValueError("Historical repair audit contract is invalid")
    audited = {(int(item["season"]), str(item["game_id"])): bool(item["recoverable"])
               for item in audit["games"]}
    approved = [audited.get((int(season), str(game_id)), True)
                for season, game_id in zip(frozen.season, frozen.game_id)]
    table = frozen.loc[approved].copy()
    expected = candidate_report["approved_sample"]
    coverage = []
    for season, group in table.groupby("season", sort=True):
        repaired = sum(year == int(season) and recoverable
                       for (year, _), recoverable in audited.items())
        coverage.append({"season": int(season),
                         "eligible_games": int(group.game_id.nunique()),
                         "eligible_rows": len(group),
                         "repaired_games": repaired})
    if (len(table) != int(expected["possessions"])
            or table.game_id.nunique() != int(expected["games"])
            or coverage != expected["coverage"]):
        raise ValueError("Recovered historical sample does not match frozen candidate")
    return table, coverage


def load_sealed_holdout():
    assert_digest(HOLDOUT, EXPECTED_HOLDOUT_SHA256, "Frozen 2025 holdout input")
    frame = pd.read_csv(HOLDOUT, dtype={"game_id": str, "drive_id": str})
    required = {"game_id", "drive_id", "start_yards_to_endzone", "start_period",
                "start_score_margin", "target_offensive_points"}
    if set(frame.columns) != required:
        raise ValueError("Frozen 2025 holdout columns changed")
    numeric = ["start_yards_to_endzone", "start_period", "start_score_margin",
               "target_offensive_points"]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="raise")
    if (len(frame) != EXPECTED_HOLDOUT_POSSESSIONS
            or frame.game_id.nunique() != EXPECTED_HOLDOUT_GAMES
            or frame.duplicated(["game_id", "drive_id"]).any()
            or not np.isfinite(frame[numeric].to_numpy(float)).all()
            or not frame.start_period.between(1, 4).all()
            or not frame.target_offensive_points.between(0, 8).all()):
        raise ValueError("Frozen 2025 holdout contract is invalid")
    return frame


def fit_baseline(train):
    x = base.design(train)
    penalty = np.eye(x.shape[1])
    penalty[0, 0] = 0
    return np.linalg.solve(x.T @ x + 10.0 * penalty,
                           x.T @ train.target_offensive_points.to_numpy(float))


def predict_baseline(frame, coefficients):
    return np.clip(base.design(frame) @ coefficients, 0, 8)


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
    if OUT.exists():
        raise RuntimeError("Sealed 2025 holdout report already exists; refusing a repeat evaluation")

    # Candidate and historical sample are locked before the sealed 2025 input opens.
    candidate_report, candidate_coefficients = load_locked_candidate()
    historical, historical_coverage = load_matched_historical(candidate_report)
    baseline_coefficients = fit_baseline(historical)
    holdout = load_sealed_holdout()

    actual = holdout.target_offensive_points.to_numpy(float)
    baseline_prediction = predict_baseline(holdout, baseline_coefficients)
    candidate_prediction = predict(holdout, candidate_coefficients)
    baseline_metrics = base.score(actual, baseline_prediction)
    candidate_metrics = base.score(actual, candidate_prediction)
    interval = game_bootstrap_interval(holdout, baseline_prediction, candidate_prediction)
    mae_improvement = baseline_metrics["mae"] - candidate_metrics["mae"]
    rmse_improvement = baseline_metrics["rmse"] - candidate_metrics["rmse"]
    passed = bool(mae_improvement > 0 and rmse_improvement > 0 and interval[0] > 0)

    report = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "research_only_sealed_expected_points_holdout_2025",
            "training_ready": False,
            "production_use": "none; Model A, projections, ratings, and site untouched",
            "evaluation_policy": "One sealed 2025 evaluation of the checksum-locked candidate; no tuning after results.",
            "candidate_sha256": EXPECTED_CANDIDATE_SHA256,
            "historical_repair_audit_sha256": EXPECTED_AUDIT_SHA256,
            "historical_target_sha256": EXPECTED_HISTORICAL_SHA256,
            "holdout_input_sha256": EXPECTED_HOLDOUT_SHA256,
            "candidate_status": candidate_report["meta"]["status"],
        },
        "input_provenance": {
            "historical": "Frozen 2019-2024 target table filtered by the frozen all-game repair audit.",
            "holdout": "Frozen 2025 verified possession ledger; whole-game admission required exact regulation drive-start score reconciliation.",
            "remote_downloads": False,
        },
        "historical_training_coverage": historical_coverage,
        "holdout_coverage": {
            "context_eligible_games": int(holdout.game_id.nunique()),
            "context_eligible_possessions": len(holdout),
            "context_quarantined_games": 257,
            "context_quarantined_possessions": 5712,
            "context_rule": "Every regulation drive start in the game exactly matched the accumulated frozen scoring-event ledger; no 2025 score repair or imputation.",
        },
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
            "Results apply only to games with fully reconciled frozen score context and verified possession labels.",
            "Whole-game quarantine reduces coverage and may leave selection bias.",
            "A passed holdout gate does not authorize production use or changes to Model A.",
            "A failed holdout gate must be reported as-is; 2025 may not be used to retune this candidate.",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"holdout_coverage": report["holdout_coverage"],
                      "matched_baseline": baseline_metrics,
                      "frozen_candidate": candidate_metrics,
                      "mae_improvement": mae_improvement,
                      "rmse_improvement": rmse_improvement,
                      "mae_improvement_game_bootstrap_95_interval": interval,
                      "holdout_gate_passed": passed}, indent=2), flush=True)


if __name__ == "__main__":
    main()
