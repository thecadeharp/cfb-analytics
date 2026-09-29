#!/usr/bin/env python3
"""Freeze a conservative 2025 possession holdout from the verified ledger.

This is data preparation only. It never loads or evaluates the expected-points
candidate. A game is admitted only when every regulation drive-start score in
the frozen ledger exactly reconciles to the frozen scoring-event sequence.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
POSITIONS = ROOT / "research_artifacts/verified_possession_ledger_2025/possessions.csv"
EVENTS = ROOT / "research_artifacts/verified_possession_ledger_2025/scoring_events.csv"
LEDGER_REPORT = ROOT / "research_artifacts/verified_possession_ledger_2025/report.json"
OUT = ROOT / "data/research/sealed_expected_points_holdout_input_2025.csv.gz"

EXPECTED_POSSESSIONS_SHA256 = "082a7d965be150d3124b6f4bd7f519b9c539264cb28f49d2d0bb3ae7a180fc7b"
EXPECTED_EVENTS_SHA256 = "cba752b6d08e25e94353a015e4053229c73e5e37c921df6655201b0b0c700728"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def truthy(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().eq("true")


def drive_order(game_id: str, drive_id: str) -> int:
    if not drive_id.startswith(game_id):
        raise ValueError("drive_id does not begin with game_id")
    suffix = drive_id[len(game_id):]
    if not suffix.isdigit():
        raise ValueError("drive_id has no numeric sequence suffix")
    return int(suffix)


def team_map(game: pd.DataFrame, events: pd.DataFrame) -> tuple[str, str]:
    home, away = set(), set()
    assigned_offense = events.loc[
        events.channel.eq("offense") & events.status.eq("assigned")
    ]
    by_drive = {str(row.drive_id): row for row in game.itertuples()
                if pd.notna(row.possession_team_id) and pd.notna(row.opponent_id)}
    for event in assigned_offense.itertuples():
        row = by_drive.get(str(event.drive_id))
        if row is None:
            continue
        possession, opponent = str(row.possession_team_id), str(row.opponent_id)
        if event.scoring_side == "home":
            home.add(possession); away.add(opponent)
        elif event.scoring_side == "away":
            away.add(possession); home.add(opponent)
    if len(home) != 1 or len(away) != 1 or home == away:
        raise ValueError("ambiguous_home_away_team_ids")
    return next(iter(home)), next(iter(away))


def build_holdout(possessions: pd.DataFrame, events: pd.DataFrame):
    eligible = possessions.loc[
        truthy(possessions.label_check_passed)
        & possessions.offensive_points.notna()
        & possessions.start_yards_to_endzone.notna()
        & possessions.start_period.notna()
        & possessions.possession_team_id.notna()
    ].copy()
    admitted, quarantine = [], []
    for game_id, targets in eligible.groupby("game_id", sort=True):
        game_id = str(game_id)
        game = possessions.loc[possessions.game_id.eq(game_id)].copy()
        scoring = events.loc[events.game_id.eq(game_id)].copy()
        reason = None
        try:
            if scoring.status.eq("unassigned").any():
                raise ValueError("unassigned_scoring_event")
            home_id, away_id = team_map(game, scoring)
            game["_drive_order"] = [drive_order(game_id, str(value))
                                    for value in game.drive_id]
            if game._drive_order.duplicated().any():
                raise ValueError("duplicate_drive_order")
            regulation = scoring.loc[~scoring.status.eq("overtime_separate")]
            if not set(regulation.drive_id.astype(str)).issubset(set(game.drive_id.astype(str))):
                raise ValueError("scoring_event_without_observed_drive")
            home_score = away_score = 0.0
            margins = {}
            for row in game.sort_values("_drive_order").itertuples():
                raw_home = float(row.raw_start_home_score)
                raw_away = float(row.raw_start_away_score)
                if raw_home != home_score or raw_away != away_score:
                    raise ValueError("drive_start_score_disagreement")
                possession = str(row.possession_team_id)
                if possession == home_id:
                    margins[str(row.drive_id)] = home_score - away_score
                elif possession == away_id:
                    margins[str(row.drive_id)] = away_score - home_score
                elif str(row.drive_id) in set(targets.drive_id.astype(str)):
                    raise ValueError("unknown_possession_side")
                drive_events = regulation.loc[regulation.drive_id.astype(str).eq(str(row.drive_id))]
                home_score += float(drive_events.loc[
                    drive_events.scoring_side.eq("home"), "points"].sum())
                away_score += float(drive_events.loc[
                    drive_events.scoring_side.eq("away"), "points"].sum())
            frame = targets[["game_id", "drive_id", "start_yards_to_endzone",
                             "start_period", "offensive_points"]].copy()
            frame["start_score_margin"] = frame.drive_id.astype(str).map(margins)
            frame = frame.rename(columns={"offensive_points": "target_offensive_points"})
            if frame.start_score_margin.isna().any():
                raise ValueError("missing_start_score_margin")
            admitted.append(frame)
        except (TypeError, ValueError) as error:
            reason = str(error)
        if reason:
            quarantine.append({"game_id": game_id, "eligible_possessions": len(targets),
                               "reason": reason})
    if not admitted:
        raise RuntimeError("No games passed the frozen holdout context gate")
    holdout = pd.concat(admitted, ignore_index=True)
    numeric = ["start_yards_to_endzone", "start_period", "start_score_margin",
               "target_offensive_points"]
    holdout[numeric] = holdout[numeric].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(holdout[numeric].to_numpy(float)).all():
        raise ValueError("Non-finite holdout value")
    holdout["_drive_order"] = [drive_order(str(g), str(d))
                               for g, d in zip(holdout.game_id, holdout.drive_id)]
    holdout = holdout.sort_values(["game_id", "_drive_order"]).drop(columns="_drive_order")
    if holdout.duplicated(["game_id", "drive_id"]).any():
        raise ValueError("Duplicate holdout possession key")
    return holdout.reset_index(drop=True), quarantine


def write_deterministic_gzip(frame: pd.DataFrame, path: Path):
    text = frame.to_csv(index=False, lineterminator="\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            zipped.write(text.encode("utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    if digest(POSITIONS) != EXPECTED_POSSESSIONS_SHA256:
        raise ValueError("Frozen 2025 possession ledger checksum changed")
    if digest(EVENTS) != EXPECTED_EVENTS_SHA256:
        raise ValueError("Frozen 2025 scoring-event ledger checksum changed")
    ledger_report = json.loads(LEDGER_REPORT.read_text())
    if ledger_report.get("meta", {}).get("source_parquet_sha256") != \
            "740566c0d034fa767008a40797dd491acb91dee47934cefb4225494f71c42853":
        raise ValueError("Frozen ledger provenance is invalid")
    possessions = pd.read_csv(POSITIONS, dtype={"game_id": str, "drive_id": str,
                                                "possession_team_id": str, "opponent_id": str})
    events = pd.read_csv(EVENTS, dtype={"game_id": str, "drive_id": str})
    holdout, quarantine = build_holdout(possessions, events)
    write_deterministic_gzip(holdout, args.output)
    print(json.dumps({
        "status": "sealed_input_created_without_loading_candidate",
        "admitted_games": int(holdout.game_id.nunique()),
        "admitted_possessions": len(holdout),
        "quarantined_games": len(quarantine),
        "quarantined_possessions": int(sum(x["eligible_possessions"] for x in quarantine)),
        "output": str(args.output),
        "sha256": digest(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
