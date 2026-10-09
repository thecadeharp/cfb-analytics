#!/usr/bin/env python3
"""Build THI's preseason 68-team NCAA tournament strength forecast."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-bracketology-v0.3"
REGIONS = ("East", "South", "Midwest", "West")
FIELD_SIZE = 68
AT_LARGE_COUNT = 36


def rating(row: dict[str, Any]) -> float:
    try:
        value = float(row.get("selection_score", row.get("prior_net")))
        return value if math.isfinite(value) else -999.0
    except (TypeError, ValueError):
        return -999.0


def prior_rating(row: dict[str, Any]) -> float:
    try:
        value = float(row.get("prior_net"))
        return value if math.isfinite(value) else -999.0
    except (TypeError, ValueError):
        return -999.0


def conference_key(row: dict[str, Any]) -> str:
    conference = row.get("conference") or {}
    return str(conference.get("id") or conference.get("abbreviation") or conference.get("name") or "Independent")


def team_row(row: dict[str, Any], bid_type: str) -> dict[str, Any]:
    conference = row.get("conference") or {}
    return {
        "team_id": row.get("team_id"),
        "team": row.get("team"),
        "conference": {
            "id": conference.get("id"),
            "name": conference.get("name"),
            "abbreviation": conference.get("abbreviation") or conference.get("name") or "Independent",
        },
        "prior_net": round(prior_rating(row), 3),
        "strength_score": row.get("strength_score"),
        "roster_score": row.get("roster_score"),
        "roster_adjustment": row.get("roster_adjustment"),
        "resume_score": row.get("resume_score"),
        "selection_score": round(rating(row), 3),
        "selection_state": row.get("selection_state", "strength_only"),
        "bid_type": bid_type,
        "overall_rank": None,
        "seed": None,
        "region": None,
        "first_four": False,
    }


def pair_four(rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    ordered = sorted(rows, key=lambda row: (-row["selection_score"], str(row["team"])))
    return [(ordered[0], ordered[-1]), (ordered[1], ordered[-2])]


def assign_regions(
    direct: list[dict[str, Any]],
    reserved: dict[tuple[int, str], dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    regions: dict[str, list[dict[str, Any]]] = {region: [] for region in REGIONS}
    available: list[tuple[int, str]] = []
    for seed in range(1, 17):
        order = REGIONS if seed % 2 else tuple(reversed(REGIONS))
        available.extend((seed, region) for region in order if (seed, region) not in reserved)

    remaining = sorted(direct, key=lambda row: (-row["selection_score"], str(row["team"])))
    if len(remaining) != len(available):
        raise RuntimeError(f"bracket slot mismatch: {len(remaining)} teams for {len(available)} slots")

    for seed in range(1, 17):
        seed_slots = [slot for slot in available if slot[0] == seed]
        seed_teams = remaining[: len(seed_slots)]
        remaining = remaining[len(seed_slots):]
        unused_regions = [region for _, region in seed_slots]
        for team in seed_teams:
            abbreviation = team["conference"]["abbreviation"]
            preferred = [region for region in unused_regions if all(
                entry.get("conference") != abbreviation for entry in regions[region]
            )]
            region = (preferred or unused_regions)[0]
            unused_regions.remove(region)
            team["seed"] = seed
            team["region"] = region
            regions[region].append({
                "seed": seed,
                "team": team["team"],
                "team_id": team["team_id"],
                "conference": abbreviation,
                "bid_type": team["bid_type"],
                "prior_net": team["prior_net"],
                "first_four": False,
            })

    for (seed, region), slot in reserved.items():
        regions[region].append(slot)
    for region in REGIONS:
        regions[region].sort(key=lambda row: row["seed"])
        if len(regions[region]) != 16:
            raise RuntimeError(f"{region} has {len(regions[region])} bracket slots")
    return regions


def roster_scores(players_payload: dict[str, Any] | None) -> tuple[dict[str, float], float, float]:
    """Return top-eight active-roster rating averages and a national baseline.

    Five rated players are required so a thin or partially matched roster cannot
    receive a misleading boost. The adjustment remains modest and bounded; it
    supplements the team prior rather than replacing it.
    """
    if (players_payload or {}).get("meta", {}).get("roster_verification_status") not in (None, "provider_verified"):
        return {}, 0.0, 1.0
    by_team: dict[str, list[float]] = {}
    for player in (players_payload or {}).get("players") or []:
        if player.get("current_roster_verified") is False:
            continue
        value = (player.get("research_scores") or {}).get("thi_player_rating")
        try:
            score = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(score):
            continue
        by_team.setdefault(str(player.get("team_id")), []).append(score)
    scores = {
        team_id: statistics.mean(sorted(values, reverse=True)[:8])
        for team_id, values in by_team.items()
        if len(values) >= 5
    }
    population = list(scores.values())
    if len(population) < 32:
        return {}, 0.0, 1.0
    center = statistics.median(population)
    spread = statistics.pstdev(population) or 1.0
    return scores, center, spread


def build_bracketology(
    priors_payload: dict[str, Any],
    profiles_payload: dict[str, Any] | None = None,
    players_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model_version = priors_payload.get("meta", {}).get("model_version")
    if model_version != "thi-cbb-walk-forward-v0.6-research":
        raise RuntimeError("bracketology requires thi-cbb-walk-forward-v0.6-research priors")
    profiles = {str(row.get("team_id")): row for row in (profiles_payload or {}).get("teams") or []}
    profile_records = [row.get("record") or {} for row in profiles.values()]
    current_game_count = sum(int(record.get("games") or 0) for record in profile_records)
    teams_with_resume_sample = sum(int(record.get("games") or 0) >= 8 for record in profile_records)
    live_resume_ready = teams_with_resume_sample >= 300
    roster_by_team, roster_center, roster_spread = roster_scores(players_payload)
    roster_active = bool(roster_by_team)
    source = []
    for original in priors_payload.get("teams") or []:
        row = dict(original)
        strength = prior_rating(row)
        record = (profiles.get(str(row.get("team_id"))) or {}).get("record") or {}
        games, wins = int(record.get("games") or 0), int(record.get("wins") or 0)
        weight = min(1.0, games / 12.0)
        resume = (wins / games - .5) * 16.0 if games else 0.0
        roster_score = roster_by_team.get(str(row.get("team_id")))
        roster_adjustment = (
            max(-3.0, min(3.0, ((roster_score - roster_center) / roster_spread) * 1.25))
            if roster_score is not None else 0.0
        )
        row.update({
            "strength_score": round(strength, 3),
            "roster_score": round(roster_score, 3) if roster_score is not None else None,
            "roster_adjustment": round(roster_adjustment, 3),
            "resume_score": round(resume, 3) if games else None,
            "selection_score": round(strength + roster_adjustment + weight * resume, 3),
            "selection_state": ("strength_roster_and_early_resume" if roster_active else "strength_and_early_resume") if games else ("strength_plus_roster" if roster_active else "strength_only"),
        })
        if rating(row) > -999: source.append(row)
    by_conference: dict[str, list[dict[str, Any]]] = {}
    for row in source:
        by_conference.setdefault(conference_key(row), []).append(row)
    if len(by_conference) != 32:
        raise RuntimeError(f"expected 32 conferences, found {len(by_conference)}")

    auto_source = [max(rows, key=lambda row: (rating(row), str(row.get("team")))) for rows in by_conference.values()]
    auto_ids = {str(row.get("team_id")) for row in auto_source}
    at_large_source = sorted(
        (row for row in source if str(row.get("team_id")) not in auto_ids),
        key=lambda row: (-rating(row), str(row.get("team"))),
    )
    selected_at_large = at_large_source[:AT_LARGE_COUNT]
    first_out_source = at_large_source[AT_LARGE_COUNT:AT_LARGE_COUNT + 4]
    next_out_source = at_large_source[AT_LARGE_COUNT + 4:AT_LARGE_COUNT + 8]

    autos = [team_row(row, "automatic") for row in auto_source]
    at_larges = [team_row(row, "at_large") for row in selected_at_large]
    field = sorted(autos + at_larges, key=lambda row: (-row["selection_score"], str(row["team"])))
    if len(field) != FIELD_SIZE:
        raise RuntimeError(f"expected {FIELD_SIZE} selected teams, found {len(field)}")
    for index, row in enumerate(field, start=1):
        row["overall_rank"] = index

    auto_play_in = sorted(autos, key=lambda row: (row["selection_score"], str(row["team"])))[:4]
    at_large_play_in = sorted(at_larges, key=lambda row: (row["selection_score"], str(row["team"])))[:4]
    participant_ids = {str(row["team_id"]) for row in auto_play_in + at_large_play_in}
    direct = [row for row in field if str(row["team_id"]) not in participant_ids]

    first_four = []
    reserved: dict[tuple[int, str], dict[str, Any]] = {}
    specifications = [
        ("at_large", 11, "East", pair_four(at_large_play_in)[0]),
        ("at_large", 11, "Midwest", pair_four(at_large_play_in)[1]),
        ("automatic", 16, "South", pair_four(auto_play_in)[0]),
        ("automatic", 16, "West", pair_four(auto_play_in)[1]),
    ]
    for game_number, (bid_type, seed, region, teams) in enumerate(specifications, start=1):
        for team in teams:
            team["seed"] = seed
            team["region"] = region
            team["first_four"] = True
        matchup = {
            "game": game_number,
            "bid_type": bid_type,
            "seed": seed,
            "region": region,
            "teams": teams,
        }
        first_four.append(matchup)
        reserved[(seed, region)] = {
            "seed": seed,
            "team": " / ".join(team["team"] for team in teams),
            "team_id": None,
            "team_ids": [team["team_id"] for team in teams],
            "conference": " / ".join(team["conference"]["abbreviation"] for team in teams),
            "bid_type": bid_type,
            "prior_net": None,
            "first_four": True,
        }

    regions = assign_regions(direct, reserved)
    counts = Counter(row["conference"]["abbreviation"] for row in field)
    auto_counts = Counter(row["conference"]["abbreviation"] for row in autos)
    conference_bids = [{
        "conference": conference,
        "bids": count,
        "automatic": auto_counts[conference],
        "at_large": count - auto_counts[conference],
    } for conference, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]

    return {
        "meta": {
            "version": VERSION,
            "model_version": model_version,
            "season": priors_payload.get("meta", {}).get("season"),
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "forecast_type": "live_resume_projection" if live_resume_ready else "preseason_strength_scenario",
            "current_game_count": current_game_count,
            "teams_with_resume_sample": teams_with_resume_sample,
            "resume_sample_minimum_games": 8,
            "field_size": FIELD_SIZE,
            "automatic_bid_count": len(autos),
            "at_large_count": len(at_larges),
            "methodology": ("Selection score begins with THI predictive team strength, adds a bounded active-roster quality adjustment from the top eight qualified player projections, and gradually adds current win-loss resume evidence over the first 12 games." if roster_active else "Selection score currently uses THI predictive team strength without a roster adjustment because the active roster source is withheld; current win-loss résumé evidence is added gradually over the first 12 games.") + " Conference leaders receive projected automatic bids; the strongest remaining selection scores receive at-large bids.",
            "limitations": (
                "This is a preseason strength scenario, not a current committee projection. No 2027 results, quadrant records, road wins or neutral-floor evidence are available yet, so THI does not publish seed lines, regions, First Four assignments or a true bubble board in the public preseason view."
                if not live_resume_ready else
                "Quadrant records and road/neutral resume detail remain labeled by sample strength while opponent tiers stabilize."
            ),
        },
        "field": field,
        "first_four": first_four,
        "regions": regions,
        "bubble": {
            "last_four_in": sorted(at_large_play_in, key=lambda row: (-row["selection_score"], str(row["team"]))),
            "first_four_out": [team_row(row, "out") for row in first_out_source],
            "next_four_out": [team_row(row, "out") for row in next_out_source],
        },
        "conference_bids": conference_bids,
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--priors", type=Path, default=ROOT / "data" / "cbb" / "model" / "current_priors.json")
    parser.add_argument("--profiles", type=Path, default=ROOT / "data" / "cbb" / "team_profiles.json")
    parser.add_argument("--players", type=Path, default=ROOT / "data" / "cbb" / "player_ratings.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "cbb" / "bracketology.json")
    args = parser.parse_args()
    payload = build_bracketology(
        json.loads(args.priors.read_text()),
        json.loads(args.profiles.read_text()) if args.profiles.exists() else None,
        json.loads(args.players.read_text()) if args.players.exists() else None,
    )
    atomic_write(args.output, payload)
    print(f"{VERSION}: {len(payload['field'])} teams, {len(payload['conference_bids'])} conferences")


if __name__ == "__main__":
    main()
