#!/usr/bin/env python3
"""Research-only audit of tagged scoring events assigned to 2025 possessions.

No score-delta inferred offensive points, expected-score fit, or production edits.
"""

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from build_historical_training_data import download_season, get_release_assets
from reconstruct_scoring_events import SOURCE_COLUMNS, final_score_by_period, reconstructed_events
from verify_historical_scores_ncaa import REPORT as NCAA_REPORT, ncaa_week, team_key

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data/research/verified_possession_points_2025.json"


def validate_scores(raw, ncaa_report):
    """Recheck every admitted game against an independently saved NCAA final.

    The prior report stores only aggregates and mismatch samples, so do not
    assume its 654 count identifies specific games. Re-fetch the NCAA scores
    to obtain the eligible game IDs rather than train on a count alone.
    """
    import requests
    from collections import defaultdict

    official = defaultdict(list)
    with requests.Session() as session:
        for week in range(1, 16):
            for game in ncaa_week(session, week):
                if game.get("gameState") != "F":
                    continue
                teams = game.get("teams") or []
                home = next((t for t in teams if t.get("isHome") is True), None)
                away = next((t for t in teams if t.get("isHome") is False), None)
                if not home or not away or home.get("score") is None or away.get("score") is None:
                    continue
                official[(team_key(away.get("nameShort")), team_key(home.get("nameShort")))].append(
                    (int(home["score"]), int(away["score"]))
                )
    plays = raw.loc[raw.seasonType.eq(2) & raw.status_type_completed.fillna(False)].copy()
    events = reconstructed_events(plays)
    invalid_games = set(events.loc[events.points.isna() | events.scoring_side.eq("unknown"), "game_id"])
    scored = events.loc[~events.game_id.isin(invalid_games)].groupby(
        ["game_id", "scoring_side"]
    ).points.sum().unstack(fill_value=0)
    final = final_score_by_period(plays).join(scored, how="left").fillna({"home": 0, "away": 0})
    ids = set()
    for game_id, row in final.iterrows():
        pair = (team_key(row.awayTeamName), team_key(row.homeTeamName))
        candidate = official.get(pair, [])
        if (len(candidate) == 1 and candidate[0] == (int(row.homeScore), int(row.awayScore))
                and game_id not in invalid_games and row.homeScore == row.home
                and row.awayScore == row.away):
            ids.add(game_id)
    expected = ncaa_report["comparison"]["independently_confirmed_and_reconciled"]
    if len(ids) != expected:
        raise RuntimeError(f"NCAA verified games changed: {len(ids)} versus committed {expected}")
    return plays.loc[plays.game_id.isin(ids)].copy(), events.loc[events.game_id.isin(ids)].copy(), ids


def audit(plays, events, ids):
    counts = Counter()
    counts["verified_games"] = len(ids)
    counts["tagged_scoring_events"] = len(events)
    regulation = events.loc[pd.to_numeric(events.period, errors="coerce").between(1, 4)]
    overtime = events.loc[~events.index.isin(regulation.index)]
    counts["overtime_scoring_events_kept_separate"] = len(overtime)
    points_by_channel = events.groupby("channel").points.sum().to_dict()
    regulation_points_by_channel = regulation.groupby("channel").points.sum().to_dict()

    # A drive key must be unique within its game and map to exactly one
    # possession team. Never assign a score to an ambiguous or absent drive.
    possession_types = {
    "Rush", "Pass Reception", "Pass Incompletion", "Pass Completion", "Sack",
    "Rushing Touchdown", "Passing Touchdown", "Field Goal Good",
    "Field Goal Missed", "Punt",
}
drive_rows = plays.loc[
    plays["drive.id"].notna() & plays.pos_team_id.notna()
    & plays["type.text"].isin(possession_types),
    ["game_id", "drive.id", "pos_team_id"],
]
    drive_teams = drive_rows.groupby(["game_id", "drive.id"]).pos_team_id.agg(
        lambda values: frozenset(values)
    )
    offense = regulation.loc[regulation.channel.isin(["offense", "field_goal"])].copy()
    assigned = Counter()
    for _, event in offense.iterrows():
        drive = event["drive.id"]
        if pd.isna(drive):
            counts["offensive_events_missing_drive"] += 1
            continue
        key = (event.game_id, drive)
        teams = drive_teams.get(key, frozenset())
        if len(teams) != 1:
            counts["offensive_events_ambiguous_drive"] += 1
            continue
        scorer = event.homeTeamId if event.scoring_side == "home" else event.awayTeamId
        if scorer not in teams or scorer != event.pos_team_id:
            counts["offensive_events_wrong_possession_team"] += 1
            continue
        counts["offensive_events_assigned"] += 1
        assigned[key] += float(event.points)
    counts["regulation_possessions_with_assigned_points"] = len(assigned)
    counts["regulation_offensive_points_assigned"] = int(sum(assigned.values()))
    counts["regulation_offensive_points_unassigned"] = int(
        offense.points.sum() - sum(assigned.values())
    )
    counts["regulation_nonoffensive_or_unknown_events"] = int(
        (~regulation.channel.isin(["offense", "field_goal"])).sum()
    )
    counts["regulation_nonoffensive_or_unknown_points"] = int(
        regulation.loc[~regulation.channel.isin(["offense", "field_goal"]), "points"].sum()
    )
    # Event-to-drive mapping is an audit, not a training-ready feature table.
    # Some ESPN drive IDs change across correction events, and a positive
    # assignment alone cannot prove a complete set of possessions.
    return {"counts": dict(counts),
            "points_by_channel_all_periods": {k: int(v) for k, v in points_by_channel.items()},
            "points_by_channel_regulation": {k: int(v) for k, v in regulation_points_by_channel.items()}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-parquet", type=Path)
    args = parser.parse_args()
    prior = json.loads(NCAA_REPORT.read_text())
    if prior["meta"]["status"] != "research_only_cross_source_score_check":
        raise RuntimeError("Independent score audit missing or invalid")
    if args.local_parquet:
        path = args.local_parquet
    else:
        with tempfile.TemporaryDirectory() as tmp:
            path = download_season(2025, get_release_assets(), Path(tmp))[0]
            raw = pd.read_parquet(path, columns=SOURCE_COLUMNS + ["homeTeamName", "awayTeamName"])
    if args.local_parquet:
        raw = pd.read_parquet(path, columns=SOURCE_COLUMNS + ["homeTeamName", "awayTeamName"])
    plays, events, ids = validate_scores(raw, prior)
    result = audit(plays, events, ids)
    report = {"meta": {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "research_only_verified_possession_points_audit",
        "eligibility": "2025 games with unique NCAA final and complete scoring-event reconciliation",
        "limits": "Only tagged scoring events with an unambiguous possession team are assigned. Overtime and nonoffensive scores are separate. Completeness, duplicate scores, and drive chronology need further inspection before model training.",
        "production_use": "none; Model A and site unchanged",
    }, **result}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    if result["counts"]["offensive_events_assigned"] < 1000:
        raise RuntimeError("Too few scoring events assigned; inspect drive mapping")


if __name__ == "__main__":
    main()
