#!/usr/bin/env python3
"""Observed 2025 possession ledger and review queue; never a training clearance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from audit_verified_possession_points import validate_scores
from build_historical_training_data import boolish, download_season, get_release_assets
from reconstruct_scoring_events import SOURCE_COLUMNS
from verify_historical_scores_ncaa import REPORT as NCAA_REPORT

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data/research/verified_possession_ledger_2025.json"
CORE_TYPES = {
    "Rush", "Pass Reception", "Pass Incompletion", "Pass Completion", "Sack",
    "Rushing Touchdown", "Passing Touchdown", "Field Goal Good", "Field Goal Missed",
    "Punt", "Interception Return", "Interception Return Touchdown",
    "Fumble Recovery (Opponent)", "Fumble Recovery (Own)", "Fumble",
    "Fumble Return Touchdown", "Fumble Recovery (Opponent) Touchdown",
    "Fumble Recovery (Own) Touchdown", "Safety", "Blocked Field Goal",
    "Blocked Field Goal Touchdown", "Blocked Punt", "Blocked Punt Touchdown",
    "Punt (Safety)", "Missed Field Goal Return", "Punt Team Fumble Recovery",
    "Punt Team Fumble Recovery Touchdown", "Punt Return", "Punt Return Touchdown",
}
TRANSITION_TYPES = {"Timeout", "Kickoff", "Kickoff Return (Offense)",
                    "Kickoff Return Touchdown", "Kickoff Team Fumble Recovery",
                    "Defensive 2pt Conversion"}
EXTRA_COLUMNS = ["id", "sequenceNumber", "homeTeamName", "awayTeamName",
                 "start.yardsToEndzone", "start.down", "EPA", "EPA_success",
                 "scrimmage_play", "penalty_no_play", "kneel_down", "downs_turnover",
                 "is_pos_team_turnover", "drive.result", "drive.offensivePlays"]


def number(value):
    value = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(value) else float(value)


def identifier(value):
    if pd.isna(value) or str(value).strip() == "":
        return None
    value = str(value).strip()
    return value[:-2] if value.endswith(".0") else value


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_ledger(plays, events):
    """Keep every observed regulation drive ID; quarantine uncertainty, retain evidence."""
    plays = plays.copy().reset_index(drop=True)
    events = events.copy().reset_index(drop=True)
    for frame in (plays, events):
        for col in ("game_id", "drive.id", "pos_team_id", "homeTeamId", "awayTeamId", "id"):
            frame[col] = frame[col].map(identifier)
        frame["period"] = pd.to_numeric(frame["period"], errors="coerce")
    ledger, event_rows, issues = [], [], []
    game_flags = defaultdict(set)

    def issue(game, reason, drive=None, play=None):
        game_flags[game].add(reason)
        issues.append({"game_id": game, "drive_id": drive, "play_id": play, "reason": reason})

    # Never silently remove duplicate IDs: they may be conflicting corrections.
    duplicates = plays.loc[plays.id.notna() & plays.duplicated(["game_id", "id"], keep=False)]
    compare_cols = [c for c in SOURCE_COLUMNS + EXTRA_COLUMNS if c in plays]
    compare_cols = list(dict.fromkeys(compare_cols))
    for (game, play_id), group in duplicates.groupby(["game_id", "id"]):
        kind = "duplicate_play_id" if len(group[compare_cols].drop_duplicates()) == 1 else "conflicting_play_id"
        issue(game, kind, play=play_id)
    # A repeated scoring fingerprint can also have different source IDs.
    fingerprint = ["game_id", "period", "clock.minutes", "clock.seconds", "type.text",
                   "text", "scoring_side", "points"]
    for _, event in events.loc[events.duplicated(fingerprint, keep=False)].iterrows():
        issue(event.game_id, "duplicate_scoring_fingerprint", event["drive.id"], event.id)

    for game, all_game in plays.groupby("game_id", sort=True):
        if all_game.period.isna().any():
            issue(game, "missing_period")
        reg = all_game.loc[all_game.period.between(1, 4)].copy()
        for col in ("clock.minutes", "clock.seconds", "sequenceNumber", "game_play_number"):
            reg[col] = pd.to_numeric(reg[col], errors="coerce")
        core = reg["type.text"].isin(CORE_TYPES) & ~boolish(reg.penalty_no_play)
        reg["core"] = core
        reg["elapsed"] = (reg.period - 1) * 900 + 900 - reg["clock.minutes"] * 60 - reg["clock.seconds"]
        clock_valid = (reg["clock.minutes"].between(0, 15) & reg["clock.seconds"].between(0, 59)
                       & (reg["clock.minutes"].ne(15) | reg["clock.seconds"].eq(0)))
        if (~clock_valid & core).any():
            issue(game, "invalid_core_clock")
        if (reg.id.isna() & core).any():
            issue(game, "missing_core_play_id")
        if (reg.sequenceNumber.isna() & core).any():
            issue(game, "missing_core_sequence")
        for _, row in reg.loc[core & reg["drive.id"].isna()].iterrows():
            issue(game, "core_play_missing_drive", play=row.id)
        unknown = ~reg["type.text"].isin(CORE_TYPES | TRANSITION_TYPES | {"Penalty"})
        for _, row in reg.loc[unknown].iterrows():
            issue(game, "unrecognized_play_type", row["drive.id"], row.id)
        ordered = reg.sort_values(["period", "clock.minutes", "clock.seconds", "sequenceNumber", "game_play_number"],
                                  ascending=[True, False, False, True, True], kind="stable", na_position="last")
        active = ordered.loc[ordered.core & ordered["drive.id"].notna()].copy()
        by_sequence = active.sort_values("sequenceNumber", kind="stable")
        if by_sequence.elapsed.diff().lt(0).any():
            issue(game, "clock_reversal_in_source_sequence")
        if active.sequenceNumber.duplicated().any():
            issue(game, "duplicate_core_sequence")
        blocks = active.loc[active["drive.id"].ne(active["drive.id"].shift()), "drive.id"]
        repeated = set(blocks.loc[blocks.duplicated(keep=False)])
        for drive in repeated:
            issue(game, "drive_reappears_after_other_drive", drive)

        for drive, group in ordered.loc[ordered["drive.id"].notna()].groupby("drive.id", sort=False):
            evidence = group.loc[group.core]
            if evidence.empty:
                # Retain this key in the ledger, but never manufacture a possession.
                flags = {"no_possession_evidence"}
                if not group["type.text"].isin(TRANSITION_TYPES).all():
                    issue(game, "drive_without_possession_evidence", drive)
            else:
                flags = set()
            teams = set(evidence.pos_team_id.dropna())
            home, away = group.homeTeamId.iloc[0], group.awayTeamId.iloc[0]
            team = next(iter(teams)) if len(teams) == 1 and teams <= {home, away} else None
            if not evidence.empty and (team is None or evidence.pos_team_id.isna().any()):
                flags.add("ambiguous_possession_team")
                issue(game, "ambiguous_possession_team", drive)
            if drive in repeated:
                flags.add("drive_reappears_after_other_drive")
            first = evidence.iloc[0] if len(evidence) else group.iloc[0]
            last = evidence.iloc[-1] if len(evidence) else group.iloc[-1]
            if len(evidence) and evidence.period.le(2).any() and evidence.period.ge(3).any():
                flags.add("drive_crosses_halftime")
                issue(game, "drive_crosses_halftime", drive)
            scrimmage = evidence.loc[boolish(evidence.scrimmage_play) & ~boolish(evidence.kneel_down)]
            epa = pd.to_numeric(scrimmage.EPA, errors="coerce")
            success = pd.to_numeric(scrimmage.EPA_success, errors="coerce")
            field = number(first["start.yardsToEndzone"])
            field = field if field is not None and 0 <= field <= 100 else None
            down = number(first["start.down"])
            # Diagnostic evidence only: a first observed down >1 may reflect missing plays.
            if len(evidence) and down != 1:
                flags.add("first_observed_down_not_one")
            terminal = (str(last["type.text"]) in {
                "Punt", "Punt Return", "Punt Return Touchdown", "Blocked Punt", "Blocked Punt Touchdown",
                "Punt (Safety)", "Field Goal Good", "Field Goal Missed", "Blocked Field Goal",
                "Missed Field Goal Return", "Interception Return", "Interception Return Touchdown",
                "Fumble Recovery (Opponent)", "Fumble Recovery (Opponent) Touchdown", "Fumble Return Touchdown",
                "Rushing Touchdown", "Passing Touchdown", "Safety"}
                or boolish(pd.Series([last.downs_turnover, last.is_pos_team_turnover])).any()
                or (last.period in (2, 4) and number(last["clock.minutes"]) == 0
                    and number(last["clock.seconds"]) == 0))
            if len(evidence) and not terminal:
                flags.add("terminal_not_observed")
            ledger.append({"game_id": game, "drive_id": drive, "possession_team_id": team,
                           "opponent_id": away if team == home else home if team == away else None,
                           "home_team": group.homeTeamName.iloc[0], "away_team": group.awayTeamName.iloc[0],
                           "observed_possession": bool(len(evidence)), "core_plays": len(evidence),
                           "first_play_id": first.id, "last_play_id": last.id,
                           "start_period": number(first.period), "end_period": number(last.period),
                           "start_clock_minutes": number(first["clock.minutes"]),
                           "start_clock_seconds": number(first["clock.seconds"]),
                           "start_yards_to_endzone": field, "first_observed_down": down,
                           "last_play_type": last["type.text"], "source_drive_result": last["drive.result"],
                           "source_reported_offensive_plays": number(last["drive.offensivePlays"]),
                           "scrimmage_plays_with_epa": int(epa.notna().sum()),
                           "epa_sum": float(epa.sum()) if epa.notna().any() else None,
                           "success_rate": float(success.mean()) if success.notna().any() else None,
                           "raw_start_home_score": number(first["start.homeScore"]),
                           "raw_start_away_score": number(first["start.awayScore"]),
                           "garbage_time_verified": None, "flags": flags,
                           "assigned_offensive_points": 0, "assigned_offensive_events": 0})

    lookup = {(r["game_id"], r["drive_id"]): r for r in ledger}
    for _, event in events.iterrows():
        game, drive = event.game_id, event["drive.id"]
        row = lookup.get((game, drive))
        scorer = event.homeTeamId if event.scoring_side == "home" else event.awayTeamId if event.scoring_side == "away" else None
        regulation = pd.notna(event.period) and 1 <= event.period <= 4
        offensive = event.channel in ("offense", "field_goal")
        status = "overtime_separate" if pd.notna(event.period) and event.period > 4 else "invalid_period"
        if regulation:
            status = "nonoffensive_separate"
            if offensive:
                status = "unassigned"
                if (row and row["possession_team_id"] is not None
                        and row["possession_team_id"] == scorer == event.pos_team_id):
                    status = "assigned"
                    row["assigned_offensive_points"] += float(event.points)
                    row["assigned_offensive_events"] += 1
                else:
                    issue(game, "unassigned_offensive_scoring_event", drive, event.id)
        if status == "invalid_period":
            issue(game, "invalid_scoring_period", drive, event.id)
        event_rows.append({"game_id": game, "drive_id": drive, "play_id": event.id,
                           "period": number(event.period), "channel": event.channel,
                           "scoring_side": event.scoring_side, "points": number(event.points),
                           "status": status})
    for row in ledger:
        flags = row["flags"]
        if row["assigned_offensive_events"] > 1:
            flags.add("multiple_offensive_scores_on_drive")
            issue(row["game_id"], "multiple_offensive_scores_on_drive", row["drive_id"])
        if row["start_yards_to_endzone"] is None:
            flags.add("missing_start_field_position")
    for row in ledger:
        row["game_flags"] = "|".join(sorted(game_flags[row["game_id"]]))
        row["flags"] = "|".join(sorted(row["flags"]))
        row["label_check_passed"] = bool(row["observed_possession"] and not row["flags"] and not row["game_flags"])
        row["offensive_points"] = row["assigned_offensive_points"] if row["label_check_passed"] else None
        row["training_eligible"] = False
    result = pd.DataFrame(ledger)
    event_frame = pd.DataFrame(event_rows)
    if result.empty or event_frame.empty:
        raise RuntimeError("No ledger or scoring events produced")
    if result.duplicated(["game_id", "drive_id"]).any():
        raise RuntimeError("Duplicate ledger keys")
    assigned = event_frame.loc[event_frame.status.eq("assigned"), "points"].sum()
    if abs(result.assigned_offensive_points.sum() - assigned) > 1e-9:
        raise RuntimeError("Assigned event/ledger points do not reconcile")
    # Every input event is retained once, including overtime and nonoffensive scores.
    if len(event_frame) != len(events) or abs(event_frame.points.sum() - events.points.sum()) > 1e-9:
        raise RuntimeError("Scoring-event conservation failed")
    summary = {
        "verified_games": int(plays.game_id.nunique()), "observed_drive_keys": len(result),
        "observed_regulation_possessions": int(result.observed_possession.sum()),
        "keys_without_possession_evidence": int((~result.observed_possession).sum()),
        "label_checks_passed": int(result.label_check_passed.sum()),
        "checked_scoreless_possessions": int(result.offensive_points.eq(0).sum()),
        "unresolved_possessions": int((result.observed_possession & ~result.label_check_passed).sum()),
        "scoring_events": len(event_frame), "assigned_offensive_events": int(event_frame.status.eq("assigned").sum()),
        "assigned_offensive_points": int(assigned),
        "unassigned_offensive_events": int(event_frame.status.eq("unassigned").sum()),
        "unassigned_offensive_points": int(event_frame.loc[event_frame.status.eq("unassigned"), "points"].sum()),
        "event_status_counts": dict(Counter(event_frame.status)),
        "games_with_review_flags": sum(bool(flags) for flags in game_flags.values()),
        "issue_counts": dict(Counter(i["reason"] for i in issues)),
        "possession_flag_counts": dict(Counter(flag for flags in result["flags"].tolist() for flag in flags.split("|") if flag)),
        "training_eligible_possessions": 0,
    }
    return result, event_frame, pd.DataFrame(issues, columns=["game_id", "drive_id", "play_id", "reason"]), summary


def review_records(frame):
    """Keep missing review identifiers as JSON null across pandas dtypes."""
    return frame.astype(object).where(frame.notna(), None).to_dict(orient="records")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-parquet", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "research_artifacts/verified_possession_ledger_2025")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        asset = None
        if args.local_parquet:
            path = args.local_parquet
        else:
            path, asset = download_season(2025, get_release_assets(), Path(tmp))
        raw = pd.read_parquet(path, columns=list(dict.fromkeys(SOURCE_COLUMNS + EXTRA_COLUMNS)))
        prior = json.loads(NCAA_REPORT.read_text())
        if prior["meta"]["status"] != "research_only_cross_source_score_check":
            raise RuntimeError("Independent score audit missing or invalid")
        plays, events, ids = validate_scores(raw, prior)
        ledger, scoring, review, summary = build_ledger(plays, events)
        if summary["verified_games"] != len(ids):
            raise RuntimeError("Verified game coverage mismatch")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        outputs = {}
        for name, frame in (("possessions", ledger), ("scoring_events", scoring), ("review_queue", review),
                            ("verified_game_ids", pd.DataFrame({"game_id": sorted(map(str, ids))}))):
            target = args.output_dir / f"{name}.csv"
            frame.to_csv(target, index=False)
            outputs[target.name] = {"rows": len(frame), "sha256": file_hash(target)}
        report = {"meta": {"generated_at": datetime.now(timezone.utc).isoformat(),
                            "status": "research_only_observed_possession_ledger",
                            "builder_version": "verified_ledger_v1",
                            "source_commit": os.environ.get("GITHUB_SHA"),
                            "source_parquet_sha256": file_hash(path),
                            "script_sha256": file_hash(__file__),
                            "source_asset": asset["browser_download_url"] if asset else "local_parquet",
                            "production_use": "none; no model fit or site changes",
                            "training_ready": False,
                            "scope": "2025 independently verified games; regulation ledger; all scoring events retained separately",
                            "limits": "Observed drive IDs cannot prove absent possessions do not exist. Clock and sequence conflicts, duplicate IDs, unassigned scoring and incomplete drive boundaries are flagged. Raw score stamps and EPA are diagnostic, not approved predictors. Special-teams channel labels are inherited from the prior reconstruction and still require review. 2025 remains held out; this is data-quality work only.",
                            "zero_rule": "Zero only when drive and game checks pass; unresolved labels are null, never zero."},
                  "counts": summary, "artifacts": outputs,
                  "review_samples": review_records(review.head(30))}
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        (args.output_dir / "report.json").write_text(REPORT.read_text())
        print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
