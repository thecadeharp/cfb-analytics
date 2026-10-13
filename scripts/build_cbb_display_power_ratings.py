#!/usr/bin/env python3
"""Build the display-only THI CBB structural power board.

This artifact is deliberately isolated from current_priors.json and Model A.  It
uses only completed-season, opponent-adjusted team efficiencies; current roster
data, polls, market prices, and third-party ratings are excluded.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-display-power-v2.0"
WEIGHTS = (0.70, 0.20, 0.10)
PRESEASON_SHRINKAGE = 0.88


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def load_history(history_dir: Path) -> dict[int, list[dict[str, Any]]]:
    seasons: dict[int, list[dict[str, Any]]] = {}
    for path in sorted(history_dir.glob("season_*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        version = payload.get("meta", {}).get("builder_version")
        if version not in {"cbb-history-v1.1", "cbb-history-v1.2"}:
            raise RuntimeError(f"unsupported history archive {path}: {version}")
        seasons[int(payload["meta"]["season"])] = payload["season_end_teams"]
    if len(seasons) < 3:
        raise RuntimeError("three completed CBB seasons are required")
    return seasons


def season_center(rows: list[dict[str, Any]]) -> float:
    values = [
        value
        for row in rows
        for key in ("adjusted_offense", "adjusted_defense")
        if (value := finite(row.get(key))) is not None
    ]
    if not values:
        raise RuntimeError("completed season has no adjusted efficiencies")
    return sum(values) / len(values)


def weighted_team_rating(
    team_id: Any,
    season_rows: list[tuple[int, float, float, dict[str, Any] | None]],
    current_center: float,
) -> dict[str, Any] | None:
    available = [(season, weight, center, row) for season, weight, center, row in season_rows if row]
    if not available:
        return None
    weight_total = sum(weight for _, weight, _, _ in available)
    offense_delta = sum(weight * ((finite(row.get("adjusted_offense")) or center) - center) for _, weight, center, row in available) / weight_total
    defense_delta = sum(weight * ((finite(row.get("adjusted_defense")) or center) - center) for _, weight, center, row in available) / weight_total
    pace_values = [(weight, finite(row.get("pace"))) for _, weight, _, row in available]
    pace_weight = sum(weight for weight, value in pace_values if value is not None)
    pace = sum(weight * value for weight, value in pace_values if value is not None) / pace_weight if pace_weight else None
    offense = current_center + PRESEASON_SHRINKAGE * offense_delta
    defense = current_center + PRESEASON_SHRINKAGE * defense_delta
    return {
        "team_id": team_id,
        "prior_offense": round(offense, 4),
        "prior_defense": round(defense, 4),
        "prior_net": round(offense - defense, 4),
        "prior_tempo": round(pace, 4) if pace is not None else None,
        "seasons_used": [season for season, _, _, _ in available],
        "normalized_weights": {
            str(season): round(weight / weight_total, 4) for season, weight, _, _ in available
        },
    }


def rankdata(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and values[order[end]] == values[order[cursor]]:
            end += 1
        rank = (cursor + end - 1) / 2.0 + 1.0
        for offset in range(cursor, end):
            ranks[order[offset]] = rank
        cursor = end
    return ranks


def spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(left) != len(right):
        return None
    x, y = rankdata(left), rankdata(right)
    x_mean, y_mean = sum(x) / len(x), sum(y) / len(y)
    numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y))
    denominator = math.sqrt(sum((a - x_mean) ** 2 for a in x) * sum((b - y_mean) ** 2 for b in y))
    return numerator / denominator if denominator else None


def validate_order(history: dict[int, list[dict[str, Any]]], target: int) -> dict[str, Any] | None:
    prior_seasons = [target - offset for offset in (1, 2, 3)]
    if target not in history or any(season not in history for season in prior_seasons):
        return None
    target_map = {str(row.get("team_id")): row for row in history[target]}
    maps = {season: {str(row.get("team_id")): row for row in history[season]} for season in prior_seasons}
    centers = {season: season_center(history[season]) for season in prior_seasons}
    current_center = centers[prior_seasons[0]]
    structural, legacy, actual = [], [], []
    structural_pairs: list[tuple[str, float]] = []
    legacy_pairs: list[tuple[str, float]] = []
    actual_pairs: list[tuple[str, float]] = []
    for team_id, row in target_map.items():
        actual_net = finite(row.get("adjusted_net"))
        latest = maps[prior_seasons[0]].get(team_id)
        if actual_net is None or not latest:
            continue
        rating = weighted_team_rating(team_id, [
            (season, weight, centers[season], maps[season].get(team_id))
            for season, weight in zip(prior_seasons, WEIGHTS)
        ], current_center)
        if not rating:
            continue
        returning = finite((row.get("continuity_from_prior") or {}).get("returning_minutes_pct")) or 0.0
        carry = 0.25 + 0.50 * max(0.0, min(1.0, returning / 100.0))
        legacy_net = carry * (finite(latest.get("adjusted_net")) or 0.0)
        structural.append(rating["prior_net"])
        legacy.append(legacy_net)
        actual.append(actual_net)
        structural_pairs.append((team_id, rating["prior_net"]))
        legacy_pairs.append((team_id, legacy_net))
        actual_pairs.append((team_id, actual_net))
    actual_top = {team_id for team_id, _ in sorted(actual_pairs, key=lambda item: item[1], reverse=True)[:25]}
    structural_top = {team_id for team_id, _ in sorted(structural_pairs, key=lambda item: item[1], reverse=True)[:25]}
    legacy_top = {team_id for team_id, _ in sorted(legacy_pairs, key=lambda item: item[1], reverse=True)[:25]}
    return {
        "season": target,
        "teams": len(actual),
        "structural_spearman": round(spearman(structural, actual) or 0.0, 4),
        "legacy_spearman": round(spearman(legacy, actual) or 0.0, 4),
        "structural_top_25_overlap": len(structural_top & actual_top),
        "legacy_top_25_overlap": len(legacy_top & actual_top),
    }


def build(history_dir: Path, profiles_path: Path) -> dict[str, Any]:
    history = load_history(history_dir)
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    latest = max(history)
    source_seasons = [latest - offset for offset in range(3)]
    if any(season not in history for season in source_seasons):
        raise RuntimeError(f"missing source seasons for {latest}: {source_seasons}")
    centers = {season: season_center(history[season]) for season in source_seasons}
    maps = {season: {str(row.get("team_id")): row for row in history[season]} for season in source_seasons}
    current_center = centers[latest]
    teams = []
    for profile in profiles.get("teams", []):
        team_id = profile.get("team_id")
        rating = weighted_team_rating(team_id, [
            (season, weight, centers[season], maps[season].get(str(team_id)))
            for season, weight in zip(source_seasons, WEIGHTS)
        ], current_center)
        if not rating:
            continue
        teams.append({
            **rating,
            "team": profile.get("team"),
            "conference": profile.get("conference"),
            "rating_type": "display_only_structural_power",
        })
    teams.sort(key=lambda row: (-row["prior_net"], str(row.get("team") or "")))
    for rank, row in enumerate(teams, 1):
        row["power_rank"] = rank
    validations = [result for target in (latest - 1, latest) if (result := validate_order(history, target))]
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "season": profiles.get("meta", {}).get("season"),
            "latest_completed_season": latest,
            "source_seasons": source_seasons,
            "season_weights": {str(season): weight for season, weight in zip(source_seasons, WEIGHTS)},
            "preseason_shrinkage": PRESEASON_SHRINKAGE,
            "team_count": len(teams),
            "status": "provisional_structural_power",
            "model_usage": "display_only; does not feed Model A, game projections, signals, or bracketology",
            "methodology": "Three-season blend of THI opponent-adjusted offensive and defensive efficiency, centered within each season's scoring environment and conservatively shrunk 12% toward the national mean.",
            "excluded_inputs": ["polls", "market prices", "third-party ratings", "unverified current rosters", "returning-minutes multipliers"],
            "validation_target": "future-season rank ordering, not betting ROI",
            "validation": validations,
        },
        "teams": teams,
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
    parser.add_argument("--history-dir", type=Path, default=ROOT / "data/cbb/history")
    parser.add_argument("--profiles", type=Path, default=ROOT / "data/cbb/team_profiles.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/cbb/model/display_power_ratings.json")
    args = parser.parse_args()
    payload = build(args.history_dir, args.profiles)
    atomic_write(args.output, payload)
    leader = payload["teams"][0]
    print(f"{VERSION}: {len(payload['teams'])} teams · #1 {leader['team']} {leader['prior_net']:+.2f}")


if __name__ == "__main__":
    main()
