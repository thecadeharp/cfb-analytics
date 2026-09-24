#!/usr/bin/env python3
"""Research-only CFB scoring-event reconstruction and quality audit.

Never use raw score deltas as offensive possession points: source score stamps
can go backward and source rows can arrive out of period order. Only complete
games whose tagged scoring events reproduce the final score are eligible for
later research. This script does not modify the live model or publish scores.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data/research/scoring_reconstruction_audit.json"
SOURCE_COLUMNS = [
    "game_id", "game_play_number", "period", "seasonType",
    "status_type_completed", "homeTeamId", "awayTeamId", "pos_team_id",
    "def_pos_team_id", "scoringType.name", "type.text", "text",
    "pointAfterAttempt.value", "offense_score_play", "defense_score_play",
    "homeScore", "awayScore", "start.homeScore", "start.awayScore",
    "clock.minutes", "clock.seconds", "drive.id",
]


def reconstructed_events(plays: pd.DataFrame) -> pd.DataFrame:
    """Infer points and scorer from scored play tags, not score differences."""
    source_type = plays["scoringType.name"].fillna("").str.lower()
    play_type = plays["type.text"].fillna("").str.lower()
    flags = (source_type.ne("") | plays["offense_score_play"].fillna(False)
             | plays["defense_score_play"].fillna(False))
    scoring = plays.loc[flags].copy()
    st = source_type.loc[flags]
    pt = play_type.loc[flags]
    pat = pd.to_numeric(scoring["pointAfterAttempt.value"], errors="coerce")
    scoring["kind"] = np.select(
        [st.eq("touchdown") | pt.str.contains("touchdown", regex=False),
         st.eq("field-goal") | pt.eq("field goal good"),
         st.eq("safety") | pt.eq("safety") | pt.eq("punt (safety)"),
         st.eq("defensive-two-point-conversion") | pt.eq("defensive 2pt conversion")],
        ["touchdown", "field_goal", "safety", "defensive_two_point"],
        default="unknown",
    )
    scoring["points"] = np.select(
        [scoring.kind.eq("touchdown"), scoring.kind.eq("field_goal"),
         scoring.kind.eq("safety"), scoring.kind.eq("defensive_two_point")],
        [6 + pat.fillna(0), 3, 2, 2], default=np.nan,
    ).astype(float)
    # Older seasons omit PAT disposition. A score delta may fill it ONLY on
    # the tagged touchdown event, for the identified scoring team, when it is
    # a plausible 6/7/8. Never use a delta on an unrelated play or a negative
    # score correction as evidence of points.

    # These source tags occasionally omit defense_score_play on return TDs.
    defensive_return = pt.isin({
        "fumble recovery (opponent)", "interception return",
        "blocked field goal", "fumble recovery (opponent) touchdown",
        "interception return touchdown", "fumble return touchdown",
        "blocked punt touchdown", "punt return touchdown",
        "blocked field goal touchdown",
    })
    defense = scoring["defense_score_play"].fillna(False) | defensive_return
    scorer_id = np.where(defense, scoring["def_pos_team_id"], scoring["pos_team_id"])
    scoring["scoring_side"] = np.where(
        scorer_id == scoring["homeTeamId"], "home",
        np.where(scorer_id == scoring["awayTeamId"], "away", "unknown"),
    )
    home_delta = (pd.to_numeric(scoring["homeScore"], errors="coerce")
                  - pd.to_numeric(scoring["start.homeScore"], errors="coerce"))
    away_delta = (pd.to_numeric(scoring["awayScore"], errors="coerce")
                  - pd.to_numeric(scoring["start.awayScore"], errors="coerce"))
    scorer_delta = pd.Series(np.where(scoring.scoring_side.eq("home"), home_delta,
                                      away_delta), index=scoring.index)
    missing_pat = scoring.kind.eq("touchdown") & ~pat.isin([0, 1, 2])
    scoring.loc[missing_pat, "points"] = scorer_delta.where(
        scorer_delta.isin([6, 7, 8])
    ).loc[missing_pat]
    scoring["touchdown_pat_from_event_delta"] = missing_pat & scoring.points.notna()
    scoring["channel"] = np.select(
        [scoring.kind.eq("field_goal"), scoring.kind.eq("safety") | defense,
         pt.str.contains("kickoff|punt|blocked", regex=True),
         pt.isin({"rushing touchdown", "passing touchdown"})],
        ["field_goal", "defense", "special_teams", "offense"],
        default="unclassified",
    )
    return scoring


def final_score_by_period(plays: pd.DataFrame) -> pd.DataFrame:
    """Pick latest period and clock, never highest game_play_number alone."""
    ordered = plays.sort_values(
        ["game_id", "period", "clock.minutes", "clock.seconds", "game_play_number"],
        ascending=[True, True, False, False, True], kind="stable",
        na_position="first",
    )
    return ordered.groupby("game_id", sort=False).tail(1).set_index("game_id")


def audit_season(raw: pd.DataFrame, year: int) -> dict:
    missing = set(SOURCE_COLUMNS) - set(raw.columns)
    if missing:
        raise ValueError(f"{year} source missing scoring fields: {sorted(missing)}")
    plays = raw.loc[
        raw["seasonType"].eq(2) & raw["status_type_completed"].fillna(False),
        SOURCE_COLUMNS,
    ].copy()
    if plays.empty:
        raise ValueError(f"{year} has no completed regular season plays")
    events = reconstructed_events(plays)
    invalid_event = events.points.isna() | events.scoring_side.eq("unknown")
    invalid_games = set(events.loc[invalid_event, "game_id"])
    points = events.loc[~invalid_event].groupby(
        ["game_id", "scoring_side"]
    ).points.sum().unstack(fill_value=0)
    for side in ("home", "away"):
        if side not in points:
            points[side] = 0.0
    final = final_score_by_period(plays)
    comparison = final[["homeScore", "awayScore"]].join(
        points[["home", "away"]], how="left"
    ).fillna({"home": 0.0, "away": 0.0})
    comparison["reconciled"] = (
        comparison.homeScore.eq(comparison.home)
        & comparison.awayScore.eq(comparison.away)
        & ~comparison.index.isin(invalid_games)
    )
    complete_ids = set(comparison.index[comparison.reconciled])
    # The only reliable possession-point target is a tagged, reconciled event.
    # Never count opposing points scored on this possession as offensive points.
    approved = events.loc[events.game_id.isin(complete_ids)]
    out_of_order = plays.sort_values(["game_id", "game_play_number"]).groupby(
        "game_id", sort=False
    ).period.diff().lt(0)
    results = {
        "season": year,
        "completed_regular_season_games": int(len(comparison)),
        "reconciled_games": len(complete_ids),
        "unreconciled_games": int(len(comparison) - len(complete_ids)),
        "unknown_scoring_events": int(invalid_event.sum()),
        "touchdowns_with_pat_inferred_from_tagged_event_score_delta": int(
            events["touchdown_pat_from_event_delta"].sum()
        ),
        "games_with_unknown_scoring_events": len(invalid_games),
        "games_with_period_reversals_in_play_order": int(plays.loc[out_of_order, "game_id"].nunique()),
        "reconciled_scoring_events": int(len(approved)),
        "reconciled_points_by_channel": {
            key: int(value) for key, value in approved.groupby("channel").points.sum().items()
        },
        "unreconciled_samples": [str(v) for v in comparison.index[~comparison.reconciled][:12]],
    }
    return results


def main():
    from build_historical_training_data import download_season, get_release_assets

    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", nargs="+", type=int, default=list(range(2019, 2026)))
    parser.add_argument("--local-parquet", type=Path,
                        help="Local source for one season; does not call the network")
    args = parser.parse_args()
    years = sorted(set(args.seasons))
    if not years or any(year < 2019 or year > 2025 for year in years):
        parser.error("Expected seasons within 2019–2025")
    if args.local_parquet and len(years) != 1:
        parser.error("--local-parquet requires exactly one --seasons year")
    assets = {} if args.local_parquet else get_release_assets()
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for year in years:
            path = args.local_parquet or download_season(year, assets, Path(tmp))[0]
            raw = pd.read_parquet(path, columns=SOURCE_COLUMNS)
            results.append(audit_season(raw, year))
            print(json.dumps(results[-1], indent=2), flush=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "research_only_scoring_reconstruction_audit",
            "source": "SportsDataverse ESPN CFB annual play-by-play release",
            "decision_rule": "Only games where identified scoring-event points equal both period-and-clock final scores and all event labels are known are eligible for later research.",
            "limitations": "Final scores still come from this same feed; cross-source validation, duplicate scoring corrections, and complete possession attribution remain for the next gate. Exclusions may be nonrandom.",
            "production_use": "none; Model A and published postgame metrics unchanged",
        },
        "seasons": results,
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
