#!/usr/bin/env python3
"""Research-only coverage audit for the 2019-2024 possession-ledger expansion.

This deliberately does not emit training rows or change Model A.  It answers a
single gate question: after cross-source final-score verification, scoring-event
reconciliation, and the existing conservative drive checks, how much observed
data is available in each historical season?
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from build_historical_training_data import download_season, get_release_assets
from build_verified_possession_ledger import EXTRA_COLUMNS, build_ledger
from reconstruct_scoring_events import SOURCE_COLUMNS, final_score_by_period, reconstructed_events
from verify_historical_scores_ncaa import HASH, team_key

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data/research/ledger_coverage_2019_2024.json"
YEARS = list(range(2019, 2025))


def ncaa_week(session: requests.Session, year: int, week: int):
    params = {
        "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": HASH}}, separators=(",", ":")),
        "variables": json.dumps({"sportCode": "MFB", "division": 11, "seasonYear": year, "week": week}, separators=(",", ":")),
    }
    response = session.get("https://sdataprod.ncaa.com/", params=params, timeout=25)
    response.raise_for_status()
    payload = response.json()
    contests = payload.get("data", {}).get("contests")
    if payload.get("errors") or not isinstance(contests, list):
        raise ValueError(f"NCAA response missing contests for {year} week {week}")
    return contests


def official_scores(year: int):
    index = defaultdict(list)
    weekly = []
    with requests.Session() as session:
        for week in range(1, 16):
            games = ncaa_week(session, year, week)
            weekly.append({"week": week, "contests": len(games), "final": sum(g.get("gameState") == "F" for g in games)})
            for game in games:
                if game.get("gameState") != "F":
                    continue
                teams = game.get("teams") or []
                home = next((team for team in teams if team.get("isHome") is True), None)
                away = next((team for team in teams if team.get("isHome") is False), None)
                if not home or not away or home.get("score") is None or away.get("score") is None:
                    continue
                pair = (team_key(away.get("nameShort")), team_key(home.get("nameShort")))
                if all(pair):
                    index[pair].append((int(home["score"]), int(away["score"])))
    return index, weekly


def verified_plays(raw: pd.DataFrame, official):
    plays = raw.loc[raw.seasonType.eq(2) & raw.status_type_completed.fillna(False)].copy()
    events = reconstructed_events(plays)
    invalid = set(events.loc[events.points.isna() | events.scoring_side.eq("unknown"), "game_id"])
    totals = events.loc[~events.game_id.isin(invalid)].groupby(["game_id", "scoring_side"]).points.sum().unstack(fill_value=0)
    final = final_score_by_period(plays).join(totals, how="left").fillna({"home": 0, "away": 0})
    eligible, reasons = set(), Counter()
    for game_id, row in final.iterrows():
        pair = (team_key(row.awayTeamName), team_key(row.homeTeamName))
        candidates = official.get(pair, [])
        if len(candidates) != 1:
            reasons["unmatched_or_ambiguous_ncaa"] += 1
        elif game_id in invalid:
            reasons["unknown_scoring_event"] += 1
        elif (int(row.homeScore), int(row.awayScore)) != candidates[0]:
            reasons["feed_final_mismatch"] += 1
        elif row.homeScore != row.home or row.awayScore != row.away:
            reasons["tagged_scores_not_reconciled"] += 1
        else:
            eligible.add(game_id)
    return plays.loc[plays.game_id.isin(eligible)].copy(), events.loc[events.game_id.isin(eligible)].copy(), eligible, reasons


def audit_year(year: int, path: Path, asset_url: str | None):
    columns = list(dict.fromkeys(SOURCE_COLUMNS + EXTRA_COLUMNS))
    raw = pd.read_parquet(path, columns=columns)
    official, weeks = official_scores(year)
    plays, events, ids, rejection_counts = verified_plays(raw, official)
    if not ids:
        raise RuntimeError(f"{year}: no games passed independent score verification")
    ledger, scoring, review, summary = build_ledger(plays, events)
    if summary["verified_games"] != len(ids):
        raise RuntimeError(f"{year}: ledger coverage mismatch")
    return {
        "season": year,
        "source_asset": asset_url or "local_parquet",
        "ncaa_weeks": weeks,
        "cross_source_rejections": dict(rejection_counts),
        "counts": summary,
        "review_issue_counts": dict(Counter(review.reason)) if not review.empty else {},
        "coverage": {
            "verified_games": len(ids),
            "label_check_rate": summary["label_checks_passed"] / summary["observed_regulation_possessions"],
            "unresolved_possession_rate": summary["unresolved_possessions"] / summary["observed_regulation_possessions"],
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", nargs="+", type=int, default=YEARS)
    parser.add_argument("--local-parquet", type=Path, help="One local source; requires exactly one season")
    args = parser.parse_args()
    years = sorted(set(args.seasons))
    if not years or any(year not in YEARS for year in years):
        parser.error("Expected seasons within 2019-2024; 2025 is deliberately sealed.")
    if args.local_parquet and len(years) != 1:
        parser.error("--local-parquet requires exactly one season")

    assets = {} if args.local_parquet else get_release_assets()
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for year in years:
            path, asset = (args.local_parquet, None) if args.local_parquet else download_season(year, assets, Path(tmp))
            result = audit_year(year, path, asset["browser_download_url"] if asset else None)
            results.append(result)
            print(json.dumps({"season": year, "coverage": result["coverage"]}, indent=2), flush=True)

    report = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "research_only_historical_ledger_coverage_audit",
            "scope": "2019-2024 only; independently score-verified observed regulation drives",
            "sealed_holdout": "2025 is excluded and remains untouched.",
            "production_use": "none; no Model A, projection, postgame, or site changes",
            "training_ready": False,
            "limits": "Coverage is a gate, not a training clearance. Drive rows are observed, exclusions may be biased, and no possession labels are promoted.",
        },
        "seasons": results,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
