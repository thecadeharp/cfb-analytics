#!/usr/bin/env python3
"""Audit every frozen possession start in 2019-2024 rejected games.

This is research-only. It records repair evidence but does not change the frozen
target table, fit a model, read 2025 data, or write production files.
"""
import json
import argparse
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
import research_expected_points_score_margin as base  # noqa: E402
from build_historical_training_data import boolish  # noqa: E402

OUT = ROOT / "data/research/all_possession_start_score_audit.json"


def normalized_ids(series):
    """Return object-backed string IDs across pandas/pyarrow versions."""
    return series.map(base.identifier).astype(object)


def audit_game(raw, frozen):
    raw = raw.copy()
    for name in ["game_id", "drive.id", "id", "pos_team_id", "homeTeamId", "awayTeamId"]:
        raw[name] = normalized_ids(raw[name])
    for name in base.ORDER + ["start.homeScore", "start.awayScore"]:
        raw[name] = pd.to_numeric(raw[name], errors="coerce")
    raw = raw.loc[raw.period.between(1, 4)].sort_values(
        base.ORDER, ascending=[True, False, False, True, True], kind="stable"
    )
    core = raw["type.text"].isin(base.CORE_TYPES) & ~boolish(raw.penalty_no_play)
    events = base.reconstructed_events(raw)
    event_positions = {idx: pos for pos, idx in enumerate(raw.index) if idx in events.index}
    event_by_index = {idx: row for idx, row in events.iterrows()}

    starts, home, away = {}, 0.0, 0.0
    for idx, row in raw.iterrows():
        drive = row["drive.id"]
        if core.loc[idx] and drive not in starts:
            starts[drive] = (idx, home, away)
        event = event_by_index.get(idx)
        if event is not None:
            if event.scoring_side == "home": home += float(event.points)
            elif event.scoring_side == "away": away += float(event.points)

    findings = []
    indices = list(raw.index)
    positions = {idx: pos for pos, idx in enumerate(indices)}
    for target in frozen.itertuples():
        drive = str(target.drive_id)
        if drive not in starts:
            findings.append({"drive_id": drive, "status": "unresolved_missing_start"})
            continue
        idx, expected_home, expected_away = starts[drive]
        play = raw.loc[idx]
        raw_home, raw_away = play["start.homeScore"], play["start.awayScore"]
        item = {"drive_id": drive, "play_id": str(play.id),
                "raw_home": None if pd.isna(raw_home) else float(raw_home),
                "raw_away": None if pd.isna(raw_away) else float(raw_away),
                "reconstructed_home": expected_home, "reconstructed_away": expected_away}
        if np.isclose(raw_home, expected_home) and np.isclose(raw_away, expected_away):
            item["status"] = "raw_confirmed"
            findings.append(item)
            continue

        prior = events.loc[[event_positions[e] < positions[idx] for e in events.index]]
        matches_prior_score = False
        if not prior.empty and pd.notna(raw_home) and pd.notna(raw_away):
            last = prior.iloc[-1]
            delta_home, delta_away = expected_home - raw_home, expected_away - raw_away
            matches_prior_score = (
                np.isclose(delta_home, float(last.points) if last.scoring_side == "home" else 0)
                and np.isclose(delta_away, float(last.points) if last.scoring_side == "away" else 0)
            )
            item["preceding_scoring_play"] = str(last.id)

        corroborating = None
        for later_idx in indices[positions[idx] + 1:]:
            if later_idx in event_by_index:
                break
            later = raw.loc[later_idx]
            if later["type.text"] in base.CORE_TYPES and not boolish(pd.Series([later.penalty_no_play])).iloc[0]:
                if np.isclose(later["start.homeScore"], expected_home) and np.isclose(later["start.awayScore"], expected_away):
                    corroborating = str(later.id)
                break
        if matches_prior_score and corroborating:
            item.update(status="repairable_stale_stamp", corroborating_play=corroborating)
        else:
            item["status"] = "unresolved_score_contradiction"
        findings.append(item)
    return findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    args = parser.parse_args()
    frozen = pd.read_csv(base.TABLE, dtype={"game_id": str, "drive_id": str, "possession_team_id": str})
    frozen["season"] = pd.to_numeric(frozen["season"], errors="raise").astype(int)
    for name in ["game_id", "drive_id", "possession_team_id"]:
        frozen[name] = normalized_ids(frozen[name])
    strict_report = json.loads(base.REPORT.read_text())
    rejected_ids = {
        (int(row["season"]), str(row["game_id"]))
        for row in strict_report["excluded_games"]
        if row["reason"] == "start_score_disagreement"
    }
    games, totals = [], Counter()
    for year in base.YEARS:
        season = frozen.loc[frozen.season.eq(year)]
        wanted = {game for y, game in rejected_ids if y == year}
        raw = pd.read_parquet(args.source_dir / f"thi-pbp-{year}.parquet", columns=base.COLUMNS)
        raw["game_id"] = normalized_ids(raw.game_id)
        for game_id, targets in season.loc[season.game_id.isin(wanted)].groupby("game_id"):
            game_id = str(game_id)
            findings = audit_game(raw.loc[raw.game_id.eq(game_id)], targets)
            counts = Counter(item["status"] for item in findings)
            totals.update(counts)
            recoverable = counts["unresolved_score_contradiction"] == 0 and counts["unresolved_missing_start"] == 0
            games.append({"season": year, "game_id": game_id, "recoverable": recoverable,
                          "status_counts": dict(counts), "findings": findings})
        print(year, "audited", flush=True)
    report = {"meta": {"status": "research_only_all_possession_start_score_audit",
                        "scope": "2019-2024 rejected games only; every frozen possession inspected",
                        "production_use": "none; no Model A, site, frozen targets, or 2025 access",
                        "repair_rule": "Reconstructed score must differ by exactly the preceding scoring event and the next core play before another score must corroborate it."},
              "counts": {"games_audited": len(games),
                         "recoverable_games": sum(game["recoverable"] for game in games),
                         "quarantined_games": sum(not game["recoverable"] for game in games),
                         "possession_statuses": dict(totals)}, "games": games}
    OUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report["counts"], indent=2))


if __name__ == "__main__":
    main()
