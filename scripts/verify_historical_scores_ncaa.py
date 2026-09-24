#!/usr/bin/env python3
"""Research-only, independent NCAA final-score check for reconstructed 2025 games.

Never treat an unmatched game or an incomplete scoreboard as verified. This
report does not feed production or the expected-score training target.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from reconstruct_scoring_events import (
    SOURCE_COLUMNS, final_score_by_period, reconstructed_events,
)
from build_historical_training_data import download_season, get_release_assets

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data/research/independent_score_audit_2025.json"
HASH = "7287cda610a9326931931080cb3a604828febe6fe3c9016a7e4a36db99efdb7c"
ALIASES = {
    "olemiss": "mississippi", "miamifl": "miami", "miamiflorida": "miami",
    "usc": "southerncalifornia", "lsu": "louisianastate",
    "byu": "brighamyoung", "smu": "southernmethodist",
    "tcu": "texaschristian", "ucf": "centralflorida",
    "utsa": "texassanantonio", "utep": "texaselpaso",
}


def team_key(name):
    name = str(name or "").lower().replace("&", "and")
    name = re.sub(r"\bst\.?\b", "state", name)
    name = re.sub(r"\buniversity\b", "", name)
    key = re.sub(r"[^a-z0-9]", "", name)
    return ALIASES.get(key, key)


def ncaa_week(session, week):
    params = {
        "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": HASH}}, separators=(",", ":")),
        "variables": json.dumps({"sportCode": "MFB", "division": 11, "seasonYear": 2025, "week": week}, separators=(",", ":")),
    }
    # Current NCAA query rather than archived Casablanca snapshots: the latter
    # can be frozen before the games were played.
    for attempt in range(3):
        try:
            response = session.get("https://sdataprod.ncaa.com/", params=params, timeout=25)
            response.raise_for_status()
            payload = response.json()
            if payload.get("errors") or not isinstance(payload.get("data", {}).get("contests"), list):
                raise ValueError(f"NCAA response missing contests for week {week}")
            return payload["data"]["contests"]
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise


def official_scores(session):
    index = defaultdict(list)
    weekly = []
    for week in range(1, 16):
        games = ncaa_week(session, week)
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
            if not all(pair):
                continue
            index[pair].append({"ncaa_id": str(game.get("contestId")), "week": week,
                                "home": int(home["score"]), "away": int(away["score"])})
        print(f"NCAA week {week}: {weekly[-1]}", flush=True)
    return index, weekly


def compare(raw, official):
    plays = raw.loc[raw.seasonType.eq(2) & raw.status_type_completed.fillna(False)].copy()
    final = final_score_by_period(plays)
    events = reconstructed_events(plays)
    invalid = set(events.loc[events.points.isna() | events.scoring_side.eq("unknown"), "game_id"])
    totals = events.loc[~events.game_id.isin(invalid)].groupby(["game_id", "scoring_side"]).points.sum().unstack(fill_value=0)
    final = final.join(totals, how="left").fillna({"home": 0, "away": 0})
    final["reconciled"] = (final.homeScore.eq(final.home) & final.awayScore.eq(final.away) & ~final.index.isin(invalid))
    counts = Counter()
    mismatches = []
    sample_unmatched = []
    for game_id, row in final.iterrows():
        pair = (team_key(row.awayTeamName), team_key(row.homeTeamName))
        candidates = official.get(pair, [])
        # A rematch or ambiguous alias cannot be silently matched by name.
        if len(candidates) != 1:
            counts["unmatched_or_ambiguous"] += 1
            if len(sample_unmatched) < 12:
                sample_unmatched.append({"game_id": str(game_id), "away": str(row.awayTeamName), "home": str(row.homeTeamName), "candidate_count": len(candidates)})
            continue
        counts["matched_official_final"] += 1
        official_game = candidates[0]
        if (int(row.homeScore), int(row.awayScore)) != (official_game["home"], official_game["away"]):
            counts["feed_final_mismatch"] += 1
            if len(mismatches) < 15:
                mismatches.append({"game_id": str(game_id), "ncaa_id": official_game["ncaa_id"],
                                   "away": str(row.awayTeamName), "home": str(row.homeTeamName),
                                   "feed_final": [int(row.awayScore), int(row.homeScore)],
                                   "ncaa_final": [official_game["away"], official_game["home"]],
                                   "tagged_events_reconcile_to_feed": bool(row.reconciled)})
        elif row.reconciled:
            counts["independently_confirmed_and_reconciled"] += 1
        else:
            counts["official_score_matches_but_events_not_reconciled"] += 1
    return {"pbp_completed_regular_games": int(len(final)), **dict(counts),
            "mismatch_samples": mismatches, "unmatched_samples": sample_unmatched}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-parquet", type=Path)
    args = parser.parse_args()
    if args.local_parquet:
        path = args.local_parquet
    else:
        import tempfile
        temp = tempfile.TemporaryDirectory()
        path = download_season(2025, get_release_assets(), Path(temp.name))[0]
    raw = pd.read_parquet(path, columns=SOURCE_COLUMNS + ["homeTeamName", "awayTeamName"])
    with requests.Session() as session:
        official, weekly = official_scores(session)
    result = compare(raw, official)
    report = {
        "meta": {"generated_at": datetime.now(timezone.utc).isoformat(),
                 "status": "research_only_cross_source_score_check",
                 "source": "NCAA scoreboard final versus SportsDataverse ESPN play-by-play tagged events",
                 "scope": "2025 completed regular-season PBP; NCAA FBS scoreboard only; exact team-name pair, unique matchup",
                 "production_use": "none; does not retrain or alter Model A, scores, projections, or site",
                 "limitations": "Unmatched games, ambiguous rematches, and failures are not independently verified. Cross-source score agreement does not establish correct possession attribution or unbiased sample coverage."},
        "weeks": weekly, "comparison": result,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    if result.get("matched_official_final", 0) < 300:
        raise RuntimeError("Insufficient independently matched games; inspect source and alias coverage")


if __name__ == "__main__":
    main()
