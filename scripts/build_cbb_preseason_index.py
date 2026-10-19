#!/usr/bin/env python3
"""Build a validated, display-only CBB preseason strength index.

This rating is deliberately isolated from the game projection engine.  It fits
team-season outcomes using only the prior season, current-roster continuity and
preseason personnel fields, then reports validation and out-of-time results.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.build_cbb_walk_forward_model import fit_ridge, finite, predict
except ModuleNotFoundError:  # Direct workflow execution adds scripts/ to sys.path.
    from build_cbb_walk_forward_model import fit_ridge, finite, predict


ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-preseason-index-v2.0-research"
DISPLAY_CARRY_WEIGHT = 0.55
TRAIN_SEASONS = set(range(2019, 2025))
VALIDATION_SEASONS = {2025}
TEST_SEASONS = {2026}
RIDGE = 100.0
FEATURES = (
    "prior_net", "prior_offense", "prior_defense",
    "returning_minutes", "returning_points", "returning_usage",
    "prior_net_x_returning",
    "recruit_rating", "recruit_mean", "recruit_top", "recruit_count",
    "four_star_count", "five_star_count",
    "transfer_minutes", "transfer_points", "transfer_usage",
    "transfer_rating", "transfer_top", "transfer_count", "transfer_matched",
)


def load_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def load_seasons(directory: Path) -> dict[int, dict[str, Any]]:
    rows = {}
    for path in sorted(directory.glob("season_*.json.gz")):
        payload = load_gzip(path)
        rows[int(payload["meta"]["season"])] = payload
    return rows


def median(values: list[float | None], fallback: float = 0.0) -> float:
    usable = [value for value in values if value is not None]
    return statistics.median(usable) if usable else fallback


def personnel_fallbacks(rows: dict[str, dict[str, Any]]) -> dict[str, float]:
    blocks = list(rows.values())
    return {
        "recruit_rating": median([finite((row.get("recruiting") or {}).get("team_rating")) for row in blocks]),
        "recruit_mean": median([finite((row.get("recruiting") or {}).get("mean_player_rating")) for row in blocks]),
        "recruit_top": median([finite((row.get("recruiting") or {}).get("top_player_rating")) for row in blocks]),
        "transfer_rating": median([finite((row.get("transfers") or {}).get("mean_incoming_rating")) for row in blocks]),
        "transfer_top": median([finite((row.get("transfers") or {}).get("top_incoming_rating")) for row in blocks]),
    }


def value(block: dict[str, Any], key: str, fallback: float = 0.0) -> float:
    parsed = finite(block.get(key))
    return fallback if parsed is None else parsed


def feature_row(
    previous: dict[str, Any], continuity: dict[str, Any], personnel: dict[str, Any],
    fallbacks: dict[str, float],
) -> dict[str, float]:
    recruiting = personnel.get("recruiting") or {}
    transfers = personnel.get("transfers") or {}
    returning_minutes = value(continuity, "returning_minutes_pct") / 100.0
    returning_points = value(continuity, "returning_points_pct", returning_minutes * 100.0) / 100.0
    returning_usage = value(continuity, "returning_usage_mass_pct", returning_minutes * 100.0) / 100.0
    prior_net = value(previous, "adjusted_net")
    return {
        "prior_net": prior_net,
        "prior_offense": value(previous, "adjusted_offense", 100.0),
        "prior_defense": value(previous, "adjusted_defense", 100.0),
        "returning_minutes": returning_minutes,
        "returning_points": returning_points,
        "returning_usage": returning_usage,
        "prior_net_x_returning": prior_net * returning_minutes,
        "recruit_rating": value(recruiting, "team_rating", fallbacks["recruit_rating"]),
        "recruit_mean": value(recruiting, "mean_player_rating", fallbacks["recruit_mean"]),
        "recruit_top": value(recruiting, "top_player_rating", fallbacks["recruit_top"]),
        "recruit_count": value(recruiting, "class_player_count"),
        "four_star_count": value(recruiting, "four_star_count"),
        "five_star_count": value(recruiting, "five_star_count"),
        "transfer_minutes": math.log1p(value(transfers, "prior_minutes")),
        "transfer_points": math.log1p(value(transfers, "prior_points")),
        "transfer_usage": math.log1p(value(transfers, "prior_usage_mass")),
        "transfer_rating": value(transfers, "mean_incoming_rating", fallbacks["transfer_rating"]),
        "transfer_top": value(transfers, "top_incoming_rating", fallbacks["transfer_top"]),
        "transfer_count": value(transfers, "incoming_count"),
        "transfer_matched": value(transfers, "prior_production_match_count"),
    }


def historical_examples(
    history: dict[int, dict[str, Any]], personnel: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    examples = []
    for season in sorted(set(history) & set(personnel)):
        if season - 1 not in history:
            continue
        previous = {str(row["team_id"]): row for row in history[season - 1].get("season_end_teams") or []}
        current = {str(row["team_id"]): row for row in history[season].get("season_end_teams") or []}
        people = {str(row["team_id"]): row for row in personnel[season].get("teams") or []}
        fallbacks = personnel_fallbacks(people)
        for team_id, target in current.items():
            if team_id not in previous:
                continue
            continuity = target.get("continuity_from_prior") or {}
            features = feature_row(previous[team_id], continuity, people.get(team_id, {}), fallbacks)
            returning = features["returning_minutes"]
            examples.append({
                "season": season,
                "team_id": target.get("team_id"),
                "team": target.get("team"),
                "features": features,
                "target_net": finite(target.get("adjusted_net")),
                "target_offense": finite(target.get("adjusted_offense")),
                "target_defense": finite(target.get("adjusted_defense")),
                "carry_forward_net": features["prior_net"] * (0.25 + 0.50 * returning),
            })
    return examples


def spearman(rows: list[dict[str, Any]], predicted_key: str, target_key: str) -> float:
    predicted = sorted(rows, key=lambda row: (-float(row[predicted_key]), str(row.get("team"))))
    actual = sorted(rows, key=lambda row: (-float(row[target_key]), str(row.get("team"))))
    predicted_rank = {id(row): rank for rank, row in enumerate(predicted, 1)}
    actual_rank = {id(row): rank for rank, row in enumerate(actual, 1)}
    n = len(rows)
    if n < 2:
        return 0.0
    squared = sum((predicted_rank[id(row)] - actual_rank[id(row)]) ** 2 for row in rows)
    return 1.0 - (6.0 * squared) / (n * (n * n - 1.0))


def evaluation(rows: list[dict[str, Any]], predicted_key: str = "predicted_net") -> dict[str, Any]:
    paired_improvements = [
        abs(row["carry_forward_net"] - row["target_net"])
        - abs(row[predicted_key] - row["target_net"])
        for row in rows
    ]
    rng = random.Random(20271012)
    bootstrap = sorted(
        statistics.fmean(paired_improvements[rng.randrange(len(rows))] for _ in rows)
        for _ in range(5000)
    ) if rows else []
    lower = bootstrap[int(0.025 * len(bootstrap))] if bootstrap else None
    upper = bootstrap[min(len(bootstrap) - 1, int(0.975 * len(bootstrap)))] if bootstrap else None
    return {
        "teams": len(rows),
        "rating_mae": round(statistics.fmean(abs(row[predicted_key] - row["target_net"]) for row in rows), 4),
        "carry_forward_mae": round(statistics.fmean(abs(row["carry_forward_net"] - row["target_net"]) for row in rows), 4),
        "rank_correlation": round(spearman(rows, predicted_key, "target_net"), 4),
        "descriptive_end_season_top_25_overlap": len(
            {row["team_id"] for row in sorted(rows, key=lambda row: -row[predicted_key])[:25]}
            & {row["team_id"] for row in sorted(rows, key=lambda row: -row["target_net"])[:25]}
        ),
        "bias": round(statistics.fmean(row[predicted_key] - row["target_net"] for row in rows), 4),
        "paired_team_season_mae_improvement": round(statistics.fmean(paired_improvements), 4),
        "paired_team_season_bootstrap_95_interval": [round(lower, 4), round(upper, 4)] if lower is not None else None,
        "overlap_interpretation": "Descriptive only. End-of-season top-25 membership is not the preseason power-rating target and is not a promotion criterion.",
    }


def current_rows(
    history: dict[int, dict[str, Any]], personnel: dict[int, dict[str, Any]],
    profiles: dict[str, Any], players: dict[str, Any], models: dict[str, dict[str, Any]],
    roster_audit_passed: bool,
) -> list[dict[str, Any]]:
    season = int(profiles["meta"]["season"])
    prior_season = max(history)
    previous = {str(row["team_id"]): row for row in history[prior_season].get("season_end_teams") or []}
    published_people = {str(row["team_id"]): row for row in personnel[season].get("teams") or []}
    rosters = {str(row["team_id"]): row for row in players.get("team_rosters") or []}
    player_rows: dict[str, list[dict[str, Any]]] = {}
    for row in players.get("players") or []:
        player_rows.setdefault(str(row.get("team_id")), []).append(row)

    # The broad portal endpoint can include commitments that do not appear on
    # the verified active roster.  Build the current personnel block from the
    # roster join so a stale portal record cannot move the published index.
    people: dict[str, dict[str, Any]] = {}
    for team_id, roster in rosters.items():
        active = player_rows.get(team_id, [])
        transfers = [row for row in active if row.get("transfer_between_seasons")]
        recruits = [
            row for row in active
            if (row.get("projection_context") or {}).get("basis") == "freshman projection"
        ]
        transfer_ratings = [
            rating for row in transfers
            if (rating := finite((row.get("projection_context") or {}).get("portal_rating"))) is not None
        ]
        recruit_ratings = [
            rating for row in recruits
            if (rating := finite((row.get("projection_context") or {}).get("recruit_rating"))) is not None
        ]
        transfer_minutes = sum(finite((row.get("sample") or {}).get("minutes")) or 0.0 for row in transfers)
        transfer_points = sum(
            (finite((row.get("sample") or {}).get("minutes")) or 0.0)
            * (finite((row.get("metrics") or {}).get("points_per_40")) or 0.0) / 40.0
            for row in transfers
        )
        transfer_usage = sum(
            (finite((row.get("sample") or {}).get("minutes")) or 0.0)
            * (finite((row.get("metrics") or {}).get("usage")) or 0.0)
            for row in transfers
        )
        people[team_id] = {
            "recruiting": {
                "team_rating": None,
                "mean_player_rating": statistics.fmean(recruit_ratings) if recruit_ratings else None,
                "top_player_rating": max(recruit_ratings) if recruit_ratings else None,
                "class_player_count": len(recruits),
                "four_star_count": sum((finite((row.get("projection_context") or {}).get("recruit_stars")) or 0) >= 4 for row in recruits),
                "five_star_count": sum((finite((row.get("projection_context") or {}).get("recruit_stars")) or 0) >= 5 for row in recruits),
            },
            "transfers": {
                "incoming_count": len(transfers),
                "rated_incoming_count": len(transfer_ratings),
                "mean_incoming_rating": statistics.fmean(transfer_ratings) if transfer_ratings else None,
                "top_incoming_rating": max(transfer_ratings) if transfer_ratings else None,
                "prior_production_match_count": sum((finite((row.get("sample") or {}).get("minutes")) or 0) > 0 for row in transfers),
                "prior_minutes": transfer_minutes,
                "prior_points": transfer_points,
                "prior_usage_mass": transfer_usage,
            },
            "source": "verified_active_roster_join",
            "published_feed_reference": published_people.get(team_id, {}),
        }
    fallbacks = personnel_fallbacks(people)
    profile_by_id = {str(row["team_id"]): row for row in profiles.get("teams") or []}
    rows = []
    for team_id, profile in profile_by_id.items():
        if team_id not in previous:
            continue
        roster = rosters.get(team_id) or {}
        returning = finite(roster.get("returning_minutes_pct"))
        continuity = {
            "returning_minutes_pct": returning,
            # Minutes are the only nationally verified current-roster continuity
            # denominator.  Use it as a conservative proxy for points and usage.
            "returning_points_pct": returning,
            "returning_usage_mass_pct": returning,
        }
        features = feature_row(previous[team_id], continuity, people.get(team_id, {}), fallbacks)
        net = predict({"features": features}, models["net"])
        raw_offense = predict({"features": features}, models["offense"])
        raw_defense = predict({"features": features}, models["defense"])
        midpoint = (raw_offense + raw_defense) / 2.0
        offense = midpoint + net / 2.0
        defense = midpoint - net / 2.0
        carry_forward = features["prior_net"] * (0.25 + 0.50 * features["returning_minutes"])
        roster_power = (1.0 - DISPLAY_CARRY_WEIGHT) * net + DISPLAY_CARRY_WEIGHT * carry_forward
        rows.append({
            "team_id": profile.get("team_id"),
            "team": profile.get("team"),
            "conference": profile.get("conference"),
            "rating": round(net, 4),
            "carry_forward_rating": round(carry_forward, 4),
            "roster_power_rating": round(roster_power, 4),
            "projected_offense": round(offense, 4),
            "projected_defense": round(defense, 4),
            "returning_minutes_pct": returning,
            # Provider verification is necessary but insufficient. Public THI
            # verification remains false until the independent national audit
            # passes; otherwise the research artifact overstates input quality.
            "roster_verified": roster_audit_passed,
            "personnel": people.get(team_id, {}),
        })
    rows.sort(key=lambda row: (-row["rating"], str(row["team"])))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        row["tier"] = "elite" if row["rating"] >= 15 else "top-25 caliber" if row["rating"] >= 10 else "tournament caliber" if row["rating"] >= 5 else "national field"
    return rows


def build(
    history_dir: Path, personnel_dir: Path, profiles_path: Path, players_path: Path,
    roster_audit_path: Path,
) -> dict[str, Any]:
    history = load_seasons(history_dir)
    personnel = load_seasons(personnel_dir)
    profiles = json.loads(profiles_path.read_text())
    players = json.loads(players_path.read_text())
    roster_audit = json.loads(roster_audit_path.read_text())
    roster_audit_status = roster_audit.get("meta", {}).get("status")
    roster_audit_passed = roster_audit_status == "passed" and all((roster_audit.get("checks") or {}).values())
    roster_verification_status = "provider_verified" if roster_audit_passed else "withheld_by_thi_audit"
    examples = historical_examples(history, personnel)
    training = [row for row in examples if row["season"] in TRAIN_SEASONS]
    models = {
        "net": fit_ridge(training, FEATURES, "target_net", RIDGE),
        "offense": fit_ridge(training, FEATURES, "target_offense", RIDGE),
        "defense": fit_ridge(training, FEATURES, "target_defense", RIDGE),
    }
    for row in examples:
        row["predicted_net"] = predict(row, models["net"])
        row["roster_power_net"] = (
            (1.0 - DISPLAY_CARRY_WEIGHT) * row["predicted_net"]
            + DISPLAY_CARRY_WEIGHT * row["carry_forward_net"]
        )
    validation_rows = [row for row in examples if row["season"] in VALIDATION_SEASONS]
    test_rows = [row for row in examples if row["season"] in TEST_SEASONS]
    validation = evaluation(validation_rows)
    test = evaluation(test_rows)
    display_validation = evaluation(validation_rows, "roster_power_net")
    display_test = evaluation(test_rows, "roster_power_net")
    rows = current_rows(history, personnel, profiles, players, models, roster_audit_passed)
    promotion_blockers = [
        "Historical personnel snapshots are not point-in-time certified.",
        "The analyzed 2026 test season cannot be reused as a fresh holdout.",
        "Current active-roster personnel features do not yet have a like-for-like frozen historical archive.",
    ]
    if not roster_audit_passed:
        promotion_blockers.append("The current national roster audit has not passed.")
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "season": profiles.get("meta", {}).get("season"),
            "status": "preseason_model_v2_candidate_not_published",
            "model_usage": "display_only; does not feed Model A or CBB game projections",
            "ranking_policy": "Model order only; no manual team rearrangement and no poll input.",
            "uncertainty_note": "Adjacent ranks outside the elite tier are not materially distinct when rating gaps are small.",
            "feature_policy": "Prior opponent-adjusted efficiency, verified returning minutes, recruiting and transfer production. Conference identity is not a model feature.",
            "historical_timing_limitation": "Historical personnel archives are reproducible but not certified snapshots of their original preseason publication dates; official promotion remains blocked.",
            "test_status": "The 2026 holdout has now been analyzed and is no longer untouched. A later season is required for fresh confirmation.",
            "training_seasons": sorted(TRAIN_SEASONS),
            "validation_seasons": sorted(VALIDATION_SEASONS),
            "out_of_time_test_seasons": sorted(TEST_SEASONS),
            "provider_roster_verification_status": players.get("meta", {}).get("roster_verification_status"),
            "roster_verification_status": roster_verification_status,
            "roster_audit_status": roster_audit_status,
            "team_count": len(rows),
            "display_carry_weight": DISPLAY_CARRY_WEIGHT,
        },
        "evaluation": {
            "validation": validation,
            "out_of_time_test": test,
            "roster_power_display_validation": display_validation,
            "roster_power_display_out_of_time_test": display_test,
            "beats_carry_forward_on_validation": validation["rating_mae"] < validation["carry_forward_mae"],
            "beats_carry_forward_on_test": test["rating_mae"] < test["carry_forward_mae"],
            "promotion_eligible": False,
            "promotion_blockers": promotion_blockers,
        },
        "models": models,
        "prospective_protocol": {
            "candidate_state": "research_awaiting_preseason_freeze" if roster_audit_passed else "research_blocked_roster_audit",
            "target": "game-level scoring margin for Division I versus Division I games",
            "primary_comparison": "paired absolute-error difference versus the frozen production baseline",
            "primary_interval": "95% game-level bootstrap interval",
            "secondary_cohorts": [
                "first 100 eligible games", "early season", "midseason", "neutral site",
                "campus site", "conference", "projected spread band", "team-strength tier",
            ],
            "checkpoints": [
                {"name": "preseason_freeze", "decision_allowed": False, "retuning_allowed": False},
                {"name": "100_eligible_games", "decision_allowed": False, "retuning_allowed": False},
                {"name": "midseason", "decision_allowed": False, "retuning_allowed": False},
                {"name": "end_of_season", "decision_allowed": True, "retuning_allowed": False},
            ],
            "versioning_rule": "Any parameter or input-rule change creates a new candidate and starts a new prospective clock.",
            "governance_document": "docs/model-validation-promotion-standard.md",
        },
        "teams": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-dir", type=Path, default=ROOT / "data/cbb/history")
    parser.add_argument("--personnel-dir", type=Path, default=ROOT / "data/cbb/personnel")
    parser.add_argument("--profiles", type=Path, default=ROOT / "data/cbb/team_profiles.json")
    parser.add_argument("--players", type=Path, default=ROOT / "data/cbb/player_ratings.json")
    parser.add_argument("--roster-audit", type=Path, default=ROOT / "data/cbb/roster_audit.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/cbb/model/preseason_index_candidate.json")
    args = parser.parse_args()
    payload = build(args.history_dir, args.personnel_dir, args.profiles, args.players, args.roster_audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n")
    print(VERSION, payload["evaluation"], "top25", [row["team"] for row in payload["teams"][:25]])


if __name__ == "__main__":
    main()
