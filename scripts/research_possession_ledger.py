#!/usr/bin/env python3
"""Research-only possession ledger audit. Does not alter live game data.

Downloads the same SportsDataverse ESPN season assets as the historical
training builder. The drive-level CSV stays in the Actions workspace; only
the aggregate quality report may be committed. Possessing-team score deltas
are *not* automatically classified as offensive points.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data/research/possession_ledger_audit.json"


def first_number(values):
    v = pd.to_numeric(values, errors="coerce").dropna()
    return float(v.iloc[0]) if len(v) else None


def last_number(values):
    v = pd.to_numeric(values, errors="coerce").dropna()
    return float(v.iloc[-1]) if len(v) else None


def extract_drives(plays):
    """Keep unknown score/field position as missing; never turn it into zero."""
    valid = plays.loc[
        plays["drive_id"].notna() & plays["offense"].notna()
        & plays["play_order"].notna() & plays["period_number"].between(1, 4)
    ]
    rows = []
    for (game, team, drive), group in valid.groupby(
        ["game_id", "offense", "drive_id"], sort=False
    ):
        ordered = group.sort_values("play_order", kind="stable")
        first, last = ordered.iloc[0], ordered.iloc[-1]
        home, away = first["home_team"], first["away_team"]
        if team not in (home, away):
            continue
        # End scores sometimes are absent; the last post-play score is fallback.
        before_home = first_number(ordered["home_score_play"])
        before_away = first_number(ordered["away_score_play"])
        end_home = last_number(ordered["end_home_score_play"])
        end_away = last_number(ordered["end_away_score_play"])
        if end_home is None:
            end_home = last_number(ordered["post_home_score_play"])
        if end_away is None:
            end_away = last_number(ordered["post_away_score_play"])
        scores = (before_home, before_away, end_home, end_away)
        known = all(value is not None for value in scores)
        home_delta, away_delta = (
            (end_home - before_home, end_away - before_away)
            if known else (None, None)
        )
        valid_score = bool(known and home_delta >= 0 and away_delta >= 0
                           and home_delta <= 8 and away_delta <= 8)
        same = home_delta if team == home else away_delta
        other = away_delta if team == home else home_delta
        scrimmage = ordered.loc[ordered["valid_scrimmage"]]
        scrimmage = scrimmage.loc[scrimmage["epa"].notna()]
        chance = pd.to_numeric(ordered["scoring_opp"], errors="coerce")
        first_period = first_number(ordered["period_number"])
        rows.append({
            "season": int(first["season"]), "game_id": game,
            "team": team, "opponent": away if team == home else home,
            "home_team": home, "away_team": away, "drive_id": drive,
            "start_play": first_number(ordered["play_order"]),
            "end_play": last_number(ordered["play_order"]),
            "first_period": first_period, "last_period": last_number(ordered["period_number"]),
            "first_clock_minutes": first_number(pd.Series([first["clock.minutes"]])),
            "first_clock_seconds": first_number(pd.Series([first["clock.seconds"]])),
            "start_yards_to_endzone": first_number(pd.Series([first["yards_to_endzone"]])),
            "start_home_score": before_home, "start_away_score": before_away,
            "end_home_score": end_home, "end_away_score": end_away,
            "scrimmage_plays_with_epa": len(scrimmage),
            "scrimmage_epa_sum": float(scrimmage["epa"].sum()) if len(scrimmage) else None,
            "scrimmage_success_rate": float(scrimmage["success"].mean()) if
                scrimmage["success"].notna().any() else None,
            "scoring_opportunity": bool(chance.gt(0).any()),
            "garbage_plays": int(ordered["situational_garbage"].sum()),
            "score_known_and_plausible": valid_score,
            "possessing_team_score_delta": same if valid_score else None,
            "opponent_score_delta": other if valid_score else None,
            "opponent_scored_on_drive": bool(valid_score and other > 0),
            "interpretation": "score_delta_proxy_not_verified_offensive_points",
        })
    return pd.DataFrame(rows)


def summarize(ledger, season, plays=None):
    valid = ledger.loc[ledger["score_known_and_plausible"]]
    summary = {
        "season": season, "drives": len(ledger),
        "games": int(ledger["game_id"].nunique()),
        "valid_score_drives": len(valid),
        "missing_or_implausible_score_drives": int(len(ledger) - len(valid)),
        "opponent_scored_on_drive": int(valid["opponent_scored_on_drive"].sum()),
        "missing_start_field_position": int(ledger["start_yards_to_endzone"].isna().sum()),
        "drives_with_no_scrimmage_epa": int(ledger["scrimmage_plays_with_epa"].eq(0).sum()),
        "scoring_opportunity_drives": int(ledger["scoring_opportunity"].sum()),
        "garbage_affected_drives": int(ledger["garbage_plays"].gt(0).sum()),
    }
    if plays is not None:
        reconciled = 0
        missing = 0
        residuals = []
        # The ledger excludes overtime drives; compare only regulation scores.
        regulation = plays.loc[plays["period_number"].between(1, 4)]
        valid_by_game = dict(tuple(valid.groupby("game_id", sort=False)))
        for game, group in regulation.groupby("game_id", sort=False):
            ordered = group.sort_values("play_order", kind="stable")
            end_home = last_number(ordered["end_home_score_play"])
            end_away = last_number(ordered["end_away_score_play"])
            if end_home is None:
                end_home = last_number(ordered["post_home_score_play"])
            if end_away is None:
                end_away = last_number(ordered["post_away_score_play"])
            drives = valid_by_game.get(game)
            if end_home is None or end_away is None or drives is None or drives.empty:
                missing += 1
                continue
            home = ordered["home_team"].iloc[0]
            away = ordered["away_team"].iloc[0]
            home_points = drives.loc[drives["team"].eq(home), "possessing_team_score_delta"].sum()
            away_points = drives.loc[drives["team"].eq(away), "possessing_team_score_delta"].sum()
            if end_home == home_points and end_away == away_points:
                reconciled += 1
            residuals.append(abs(end_home - home_points) + abs(end_away - away_points))
        summary["score_reconciliation"] = {
            "games_with_score_comparison": len(residuals),
            "games_without_score_comparison": missing,
            "games_fully_reconciled": reconciled,
            "mean_absolute_unassigned_points_per_game": round(float(sum(residuals) / len(residuals)), 2) if residuals else None,
            "interpretation": "Unassigned points may reflect returns, special teams, missing drives, or scoring-stamp problems; investigate before labeling offensive points.",
        }
    return summary


def main():
    from build_historical_training_data import (
        download_season, get_release_assets, normalize_season,
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", nargs="+", type=int, default=list(range(2019, 2026)))
    args = parser.parse_args()
    if not args.seasons or any(year < 2019 or year > 2025 for year in args.seasons):
        parser.error("Research seasons must be within 2019–2025")
    assets = get_release_assets()
    summaries = []
    with tempfile.TemporaryDirectory() as tmp:
        for season in sorted(set(args.seasons)):
            path, _ = download_season(season, assets, Path(tmp))
            raw = pd.read_parquet(path)
            plays = normalize_season(raw, season)
            del raw
            # Audit only regular-season completed FBS/FCS games. Model training
            # eligibility is a separate, later decision.
            plays = plays.loc[plays["season_type"].eq(2) & plays["completed"]]
            ledger = extract_drives(plays)
            if ledger.empty:
                raise RuntimeError(f"No usable possession drives for {season}")
            ledger.to_csv(Path(tmp) / f"possession_ledger_{season}.csv.gz", index=False,
                          compression="gzip")
            summaries.append(summarize(ledger, season, plays))
            print(f"{season}: {len(ledger)} drives / {summaries[-1]['games']} games", flush=True)
            del plays, ledger
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "research_only_possession_ledger_quality_audit",
            "source": "SportsDataverse ESPN CFB play-by-play annual release",
            "source_schema": "scripts/build_historical_training_data.py normalize_season",
            "point_rule": "Possessing-team score delta is a proxy, not validated offensive points; opponent scores and uncaptured scores require attribution before modeling.",
            "output_rule": "Possession CSVs remain temporary; only this aggregate audit is committed.",
        }, "seasons": summaries,
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
