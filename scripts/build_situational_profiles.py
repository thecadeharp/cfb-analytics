#!/usr/bin/env python3
"""Build research-only weekly team situational profiles from verified possessions.

The frozen expected-points candidate is applied descriptively after games are
complete. This script never reads or writes Model A, projections, ratings, or
site files. Games with unresolved scores, possession labels, or start context
are quarantined as a whole.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from build_historical_training_data import download_season, get_release_assets
from build_verified_possession_ledger import EXTRA_COLUMNS, build_ledger, identifier
from reconstruct_scoring_events import SOURCE_COLUMNS, final_score_by_period, reconstructed_events
from research_expected_points_score_margin import game_margins
from verify_historical_scores_ncaa import HASH as NCAA_QUERY_HASH, team_key

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATE = ROOT / "data/research/repaired_expected_points_candidate.json"
DEFAULT_OUTPUT = ROOT / "data/research/situational_profiles_2026.json"
EXPECTED_CANDIDATE_SHA256 = "ab525744fee8d093ad73fe7612a4ab4f0006187e006ff63c2ceb7d3db753372a"
EXPECTED_FEATURES = [
    "intercept", "yards_to_endzone_0_1", "yards_to_endzone_squared",
    "period_2", "period_3", "period_4", "possession_score_margin_div_28",
]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def ncaa_week(session: requests.Session, season: int, week: int):
    params = {
        "extensions": json.dumps(
            {"persistedQuery": {"version": 1, "sha256Hash": NCAA_QUERY_HASH}},
            separators=(",", ":"),
        ),
        "variables": json.dumps(
            {"sportCode": "MFB", "division": 11, "seasonYear": season, "week": week},
            separators=(",", ":"),
        ),
    }
    for attempt in range(3):
        try:
            response = session.get("https://sdataprod.ncaa.com/", params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
            contests = payload.get("data", {}).get("contests")
            if payload.get("errors") or not isinstance(contests, list):
                raise ValueError(f"NCAA response missing contests for {season} week {week}")
            return contests
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise


def official_finals(season: int, through_week: int):
    index = defaultdict(list)
    weekly = []
    with requests.Session() as session:
        for week in range(1, through_week + 1):
            contests = ncaa_week(session, season, week)
            finals = 0
            for game in contests:
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
                finals += 1
                index[(week, *pair)].append({
                    "ncaa_id": str(game.get("contestId")),
                    "home": int(home["score"]),
                    "away": int(away["score"]),
                })
            weekly.append({"week": week, "contests": len(contests), "finals": finals})
    return index, weekly


def verified_inputs(raw: pd.DataFrame, season: int, through_week: int):
    completed = raw.loc[
        raw.season.eq(season)
        & raw.seasonType.eq(2)
        & raw.status_type_completed.fillna(False)
        & pd.to_numeric(raw.week, errors="coerce").between(1, through_week)
    ].copy()
    if completed.empty:
        raise RuntimeError("No completed regular-season source games in requested window")
    official, weekly = official_finals(season, through_week)
    events = reconstructed_events(completed)
    invalid = set(events.loc[events.points.isna() | events.scoring_side.eq("unknown"), "game_id"])
    totals = events.loc[~events.game_id.isin(invalid)].groupby(
        ["game_id", "scoring_side"]
    ).points.sum().unstack(fill_value=0)
    final = final_score_by_period(completed).join(totals, how="left").fillna({"home": 0, "away": 0})
    admitted, reasons = set(), Counter()
    for game_id, row in final.iterrows():
        week = int(row.week)
        pair = (team_key(row.awayTeamName), team_key(row.homeTeamName))
        candidates = official.get((week, *pair), [])
        if len(candidates) != 1:
            reasons["unmatched_or_ambiguous_ncaa_final"] += 1
            continue
        candidate = candidates[0]
        if (int(row.homeScore), int(row.awayScore)) != (candidate["home"], candidate["away"]):
            reasons["source_final_disagrees_with_ncaa"] += 1
            continue
        if game_id in invalid or row.homeScore != row.home or row.awayScore != row.away:
            reasons["tagged_scoring_events_do_not_reconcile"] += 1
            continue
        admitted.add(game_id)
    if not admitted:
        raise RuntimeError("No games passed independent final-score verification")
    return (
        completed.loc[completed.game_id.isin(admitted)].copy(),
        events.loc[events.game_id.isin(admitted)].copy(),
        admitted,
        {"weekly_ncaa": weekly, "score_verification_exclusions": dict(reasons),
         "source_completed_games": int(completed.game_id.nunique())},
    )


def load_candidate(path: Path):
    if digest(path) != EXPECTED_CANDIDATE_SHA256:
        raise ValueError("Frozen expected-points candidate checksum changed")
    report = json.loads(path.read_text())
    coefficients = np.asarray(
        report.get("coefficients_fit_on_all_approved_2019_2024_rows"), dtype=float)
    if (report.get("meta", {}).get("status") !=
            "research_only_repaired_expected_points_candidate_v1"
            or report.get("meta", {}).get("training_ready") is not False
            or report.get("features") != EXPECTED_FEATURES
            or coefficients.shape != (len(EXPECTED_FEATURES),)
            or not np.isfinite(coefficients).all()):
        raise ValueError("Frozen expected-points candidate contract is invalid")
    return coefficients


def expected_points(frame: pd.DataFrame, coefficients: np.ndarray):
    yards = frame.start_yards_to_endzone.to_numpy(float) / 100.0
    period = frame.start_period.to_numpy(float)
    margin = frame.start_score_margin.to_numpy(float) / 28.0
    design = np.column_stack([
        np.ones(len(frame)), yards, yards * yards,
        period == 2, period == 3, period == 4, margin,
    ])
    return np.clip(design @ coefficients, 0, 8)


def game_team_map(raw_game: pd.DataFrame):
    values = {}
    for side in ("home", "away"):
        ids = {identifier(value) for value in raw_game[f"{side}TeamId"].dropna()}
        names = {str(value).strip() for value in raw_game[f"{side}TeamName"].dropna()
                    if str(value).strip()}
        if len(ids) != 1 or len(names) != 1:
            raise ValueError("ambiguous_game_team_metadata")
        values[f"{side}_id"] = next(iter(ids))
        values[f"{side}_name"] = next(iter(names))
    if values["home_id"] == values["away_id"]:
        raise ValueError("duplicate_game_team_id")
    return values


def prepare_possessions(raw: pd.DataFrame, ledger: pd.DataFrame, coefficients: np.ndarray):
    eligible = ledger.loc[
        ledger.label_check_passed.astype(str).str.lower().eq("true")
        & ledger.offensive_points.notna()
        & ledger.start_yards_to_endzone.notna()
        & ledger.start_period.notna()
        & ledger.possession_team_id.notna()
    ].copy()
    raw_groups = {str(game): group for game, group in raw.groupby("game_id")}
    admitted, exclusions = [], Counter()
    for game_id, targets in eligible.groupby("game_id", sort=True):
        game_id = str(game_id)
        raw_game = raw_groups.get(game_id)
        if raw_game is None:
            exclusions["missing_verified_source_game"] += 1
            continue
        target = targets[["game_id", "drive_id", "possession_team_id", "start_period",
                          "start_clock_minutes", "start_clock_seconds",
                          "start_yards_to_endzone", "offensive_points"]].copy()
        target = target.rename(columns={"offensive_points": "target_offensive_points"})
        margins, reason = game_margins(raw_game, target)
        if reason:
            exclusions[reason] += 1
            continue
        try:
            teams = game_team_map(raw_game)
        except ValueError as error:
            exclusions[str(error)] += 1
            continue
        target["start_score_margin"] = target.drive_id.astype(str).map(margins)
        target["week"] = int(pd.to_numeric(raw_game.week, errors="coerce").dropna().iloc[0])
        team_names = {teams["home_id"]: teams["home_name"], teams["away_id"]: teams["away_name"]}
        target["team_id"] = target.possession_team_id.map(identifier)
        target["opponent_id"] = target.team_id.map(
            {teams["home_id"]: teams["away_id"], teams["away_id"]: teams["home_id"]})
        target["team"] = target.team_id.map(team_names)
        target["opponent"] = target.opponent_id.map(team_names)
        if target[["start_score_margin", "team", "opponent"]].isna().any().any():
            exclusions["missing_profile_identity_or_context"] += 1
            continue
        admitted.append(target)
    if not admitted:
        raise RuntimeError("No possessions passed the exact situational-context gate")
    frame = pd.concat(admitted, ignore_index=True)
    frame["expected_points"] = expected_points(frame, coefficients)
    frame["points_over_expected"] = frame.target_offensive_points - frame.expected_points
    frame["score_state"] = np.select(
        [frame.start_score_margin.gt(0), frame.start_score_margin.lt(0)],
        ["leading", "trailing"], default="tied",
    )
    frame["half"] = np.where(frame.start_period.le(2), "first_half", "second_half")
    return frame, dict(exclusions)


def rounded(value):
    return round(float(value), 4)


def state_splits(group: pd.DataFrame, defense: bool):
    result = {}
    for state in ("leading", "tied", "trailing"):
        sample = group.loc[group.score_state.eq(state)]
        if sample.empty:
            result[state] = {"possessions": 0}
            continue
        result[state] = {
            "possessions": len(sample),
            "actual_points_per_possession": rounded(sample.target_offensive_points.mean()),
            "expected_start_points_per_possession": rounded(sample.expected_points.mean()),
            ("points_prevented_over_expected_per_possession" if defense
             else "points_over_expected_per_possession"): rounded(
                (-sample.points_over_expected if defense else sample.points_over_expected).mean()),
        }
    return result


def half_splits(group: pd.DataFrame, defense: bool):
    result = {}
    for half in ("first_half", "second_half"):
        sample = group.loc[group.half.eq(half)]
        if sample.empty:
            result[half] = {"possessions": 0}
            continue
        result[half] = {
            "possessions": len(sample),
            "actual_points_per_possession": rounded(sample.target_offensive_points.mean()),
            "expected_start_points_per_possession": rounded(sample.expected_points.mean()),
            ("points_prevented_over_expected_per_possession" if defense
             else "points_over_expected_per_possession"): rounded(
                (-sample.points_over_expected if defense else sample.points_over_expected).mean()),
        }
    return result


def summarize(group: pd.DataFrame, defense: bool):
    actual = group.target_offensive_points
    short = group.loc[group.start_yards_to_endzone.le(40)]
    value = -group.points_over_expected if defense else group.points_over_expected
    result = {
        "games": int(group.game_id.nunique()),
        "possessions": len(group),
        "actual_points_per_possession": rounded(actual.mean()),
        "expected_start_points_per_possession": rounded(group.expected_points.mean()),
        ("points_prevented_over_expected_per_possession" if defense
         else "points_over_expected_per_possession"): rounded(value.mean()),
        "scoring_possession_rate": rounded(actual.gt(0).mean()),
        "touchdown_possession_rate": rounded(actual.ge(6).mean()),
        "empty_possession_rate": rounded(actual.eq(0).mean()),
        "average_start_yards_to_endzone": rounded(group.start_yards_to_endzone.mean()),
        "average_start_field_position": rounded((100 - group.start_yards_to_endzone).mean()),
        "short_field_possessions": len(short),
        "short_field_points_per_possession": (
            rounded(short.target_offensive_points.mean()) if len(short) else None),
        "by_score_state": state_splits(group, defense),
        "by_half": half_splits(group, defense),
    }
    return result


def reliability(possessions: int):
    if possessions >= 50:
        return "established"
    if possessions >= 25:
        return "developing"
    return "limited"


def build_profiles(possessions: pd.DataFrame):
    identities = {}
    for row in possessions[["team_id", "team", "opponent_id", "opponent"]].itertuples():
        identities[str(row.team_id)] = str(row.team)
        identities[str(row.opponent_id)] = str(row.opponent)
    teams = []
    for team_id, team in sorted(identities.items(), key=lambda item: item[1]):
        offense = possessions.loc[possessions.team_id.astype(str).eq(team_id)]
        defense = possessions.loc[possessions.opponent_id.astype(str).eq(team_id)]
        if offense.empty or defense.empty:
            continue
        offensive = summarize(offense, defense=False)
        defensive = summarize(defense, defense=True)
        net = (offensive["points_over_expected_per_possession"]
               + defensive["points_prevented_over_expected_per_possession"])
        sample = min(len(offense), len(defense))
        teams.append({
            "team_id": team_id,
            "team": team,
            "games": int(pd.concat([offense.game_id, defense.game_id]).nunique()),
            "net_possession_value": rounded(net),
            "reliability": reliability(sample),
            "offense": offensive,
            "defense": defensive,
        })
    return sorted(teams, key=lambda item: item["team"])


def excitement_label(score: int):
    if score >= 90:
        return "Instant Classic"
    if score >= 80:
        return "Must Rewatch"
    if score >= 70:
        return "High Drama"
    if score >= 55:
        return "Competitive"
    return "Routine"


def excitement_profile(game: pd.DataFrame, final_margin: int, total_points: int):
    """Describe how compelling an admitted completed game was.

    This is deliberately retrospective. It uses final-score closeness and the
    verified possession sequence; it is never a pregame prediction or a model
    feature.
    """
    ordered = game.sort_values(
        ["start_period", "start_clock_minutes", "start_clock_seconds"],
        ascending=[True, False, False], kind="stable",
    ).copy()
    home_id = str(ordered.home_team_id.iloc[0])
    ordered["home_start_margin"] = np.where(
        ordered.team_id.astype(str).eq(home_id),
        ordered.start_score_margin,
        -ordered.start_score_margin,
    )
    fourth = ordered.loc[ordered.start_period.eq(4)]
    late_one_score = int(fourth.home_start_margin.abs().le(8).sum())
    late_share = late_one_score / len(fourth) if len(fourth) else 0.0

    signs = np.sign(ordered.home_start_margin.to_numpy(float))
    non_tied = signs[signs != 0]
    lead_changes = int(np.sum(non_tied[1:] != non_tied[:-1])) if len(non_tied) > 1 else 0
    tied_starts = int(ordered.home_start_margin.eq(0).sum())
    scoring_rate = float(ordered.target_offensive_points.gt(0).mean())

    components = {
        "final_score_tension": round(max(0.0, 1.0 - final_margin / 28.0) * 35.0, 1),
        "late_game_pressure": round(min(1.0, late_share) * 25.0, 1),
        "lead_exchange": round(min(1.0, (lead_changes + 0.5 * tied_starts) / 4.0) * 20.0, 1),
        "scoring_activity": round(
            min(1.0, total_points / 70.0) * 10.0
            + min(1.0, scoring_rate / 0.45) * 10.0,
            1,
        ),
    }
    score = int(round(min(100.0, sum(components.values()))))
    return {
        "score": score,
        "label": excitement_label(score),
        "components": components,
        "lead_changes": lead_changes,
        "tied_possession_starts": tied_starts,
        "fourth_quarter_one_score_possessions": late_one_score,
        "fourth_quarter_possessions": int(len(fourth)),
        "definition": (
            "Retrospective 0-100 score from final-score tension, verified fourth-quarter "
            "one-score possession share, lead exchanges and scoring activity."
        ),
    }


def game_side_summary(group: pd.DataFrame):
    short = group.loc[group.start_yards_to_endzone.le(40)]
    return {
        "possessions": int(len(group)),
        "points_per_possession": rounded(group.target_offensive_points.mean()),
        "expected_start_points_per_possession": rounded(group.expected_points.mean()),
        "points_over_expected_per_possession": rounded(group.points_over_expected.mean()),
        "scoring_possession_rate": rounded(group.target_offensive_points.gt(0).mean()),
        "empty_possession_rate": rounded(group.target_offensive_points.eq(0).mean()),
        "average_start_field_position": rounded((100 - group.start_yards_to_endzone).mean()),
        "short_field_possessions": int(len(short)),
        "short_field_points_per_possession": (
            rounded(short.target_offensive_points.mean()) if len(short) else None
        ),
    }


def build_game_logs(possessions: pd.DataFrame, verified: pd.DataFrame):
    final = final_score_by_period(verified)
    final.index = final.index.map(identifier)
    games = []
    for game_id, game in possessions.groupby("game_id", sort=True):
        game_id = str(game_id)
        source = final.loc[game_id]
        home_id = identifier(source.homeTeamId)
        away_id = identifier(source.awayTeamId)
        home = game.loc[game.team_id.astype(str).eq(str(home_id))]
        away = game.loc[game.team_id.astype(str).eq(str(away_id))]
        if home.empty or away.empty:
            continue
        home_points = int(source.homeScore)
        away_points = int(source.awayScore)
        home_summary = game_side_summary(home)
        away_summary = game_side_summary(away)
        game = game.copy()
        game["home_team_id"] = home_id
        games.append({
            "game_id": game_id,
            "week": int(game.week.iloc[0]),
            "away_team_id": away_id,
            "away_team": str(source.awayTeamName),
            "away_points": away_points,
            "home_team_id": home_id,
            "home_team": str(source.homeTeamName),
            "home_points": home_points,
            "winner": (str(source.homeTeamName) if home_points > away_points
                       else str(source.awayTeamName) if away_points > home_points else "Tie"),
            "possession_value_edge": rounded(
                home_summary["points_over_expected_per_possession"]
                - away_summary["points_over_expected_per_possession"]
            ),
            "away": away_summary,
            "home": home_summary,
            "excitement": excitement_profile(
                game, abs(home_points - away_points), home_points + away_points
            ),
        })
    return sorted(games, key=lambda row: (row["week"], row["game_id"]))


def run_detailed(raw: pd.DataFrame, season: int, through_week: int,
                 coefficients: np.ndarray):
    verified, events, ids, verification = verified_inputs(raw, season, through_week)
    ledger, scoring, review, ledger_counts = build_ledger(verified, events)
    possessions, context_exclusions = prepare_possessions(verified, ledger, coefficients)
    profiles = build_profiles(possessions)
    games = build_game_logs(possessions, verified)
    coverage = {
        **verification,
        "independently_verified_games": len(ids),
        "observed_regulation_possessions": ledger_counts["observed_regulation_possessions"],
        "ledger_label_checks_passed": ledger_counts["label_checks_passed"],
        "context_eligible_games": int(possessions.game_id.nunique()),
        "context_eligible_possessions": len(possessions),
        "teams_profiled": len(profiles),
        "game_efficiency_logs": len(games),
        "context_exclusions": context_exclusions,
        "review_queue_rows": len(review),
        "scoring_event_rows": len(scoring),
    }
    return profiles, games, coverage


def run(raw: pd.DataFrame, season: int, through_week: int, coefficients: np.ndarray):
    profiles, _games, coverage = run_detailed(raw, season, through_week, coefficients)
    return profiles, coverage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--through-week", type=int, required=True)
    parser.add_argument("--local-parquet", type=Path)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.season != 2026:
        raise ValueError("This v1 weekly profile contract is locked to the 2026 season")
    if not 1 <= args.through_week <= 15:
        raise ValueError("through-week must be between 1 and 15")
    coefficients = load_candidate(args.candidate)
    asset = None
    if args.local_parquet:
        path = args.local_parquet
        raw = pd.read_parquet(path, columns=list(dict.fromkeys(
            SOURCE_COLUMNS + EXTRA_COLUMNS + ["season", "week"])))
    else:
        with tempfile.TemporaryDirectory(prefix="thi-situational-") as temp:
            path, asset = download_season(args.season, get_release_assets(), Path(temp))
            raw = pd.read_parquet(path, columns=list(dict.fromkeys(
                SOURCE_COLUMNS + EXTRA_COLUMNS + ["season", "week"])))
            source_sha = digest(path)
    if args.local_parquet:
        source_sha = digest(path)
    profiles, games, coverage = run_detailed(
        raw, args.season, args.through_week, coefficients
    )
    report = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "research_only_situational_profiles_v1",
            "season": args.season,
            "through_week": args.through_week,
            "candidate_sha256": EXPECTED_CANDIDATE_SHA256,
            "source_parquet_sha256": source_sha,
            "source_asset": asset["browser_download_url"] if asset else "local_parquet",
            "model_a_touched": False,
            "production_use": "descriptive team profiles, game efficiency logs and retrospective excitement only; no projection, rating, or wager input",
            "update_policy": "Completed games only; independently verified finals; whole-game quarantine for unresolved possession or score context.",
            "sample_warning": "Early-season and quarantined-game coverage can be thin. Reliability labels describe sample size; values are not team rankings.",
            "team_scope": "All teams in admitted games are retained, including FCS opponents, for FBS-vs-FCS context.",
        },
        "coverage": coverage,
        "teams": profiles,
        "games": games,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"meta": report["meta"], "coverage": coverage}, indent=2), flush=True)


if __name__ == "__main__":
    main()
