#!/usr/bin/env python3
"""Build one display-only percentile/rank contract for every THI surface."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "team_metric_profiles.json"

METRICS = {
    "epa_play": {"label": "EPA / Play", "format": "epa", "offense_high": True, "defense_high": False},
    "success_rate": {"label": "Success Rate", "format": "percent", "offense_high": True, "defense_high": False},
    "explosive_rate": {"label": "Explosive Rate", "format": "percent", "offense_high": True, "defense_high": False},
    "early_down_epa": {"label": "Early-Down EPA", "format": "epa", "offense_high": True, "defense_high": False},
    "standard_down_success_rate": {"label": "Standard-Down Success", "format": "percent", "offense_high": True, "defense_high": False},
    "passing_down_success_rate": {"label": "Passing-Down Success", "format": "percent", "offense_high": True, "defense_high": False},
    "stuff_rate": {"label": "Stuff Rate", "format": "percent", "offense_high": False, "defense_high": True},
    "sack_rate": {"label": "Sack Rate", "format": "percent", "offense_high": False, "defense_high": True},
    "tfl_rate": {"label": "TFL Rate", "format": "percent", "offense_high": False, "defense_high": True},
    "line_yards_per_rush": {"label": "Line Yards / Rush", "format": "decimal", "offense_high": True, "defense_high": False},
    "red_zone_epa": {"label": "Red-Zone EPA", "format": "epa", "offense_high": True, "defense_high": False},
    "red_zone_success_rate": {"label": "Red-Zone Success", "format": "percent", "offense_high": True, "defense_high": False},
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def percentile(values: list[float], target: float, higher_is_better: bool) -> float:
    """Percentile where 100 always means best, with average ties."""
    if not values:
        return 0.0
    if len(values) == 1:
        return 50.0
    less = sum(value < target for value in values)
    equal = sum(value == target for value in values)
    raw = 100.0 * (less + 0.5 * equal) / len(values)
    return raw if higher_is_better else 100.0 - raw


def rank(values: list[float], target: float, higher_is_better: bool) -> int:
    better = sum(value > target if higher_is_better else value < target for value in values)
    return better + 1


def color_band(pct: float | None) -> str:
    if pct is None:
        return "missing"
    if pct >= 85:
        return "elite"
    if pct >= 70:
        return "strong"
    if pct >= 55:
        return "above"
    if pct >= 45:
        return "average"
    if pct >= 30:
        return "below"
    if pct >= 15:
        return "poor"
    return "critical"


def main() -> None:
    advanced = load(DATA / "advanced_metrics.json")
    model = load(DATA / "cfb_metrics.json")
    external = load(DATA / "external_ratings.json") if (DATA / "external_ratings.json").exists() else {"teams": {}}
    sample_name = str(advanced.get("meta", {}).get("default_view") or "non_garbage")
    source_teams = advanced.get("teams", {})

    distributions: dict[tuple[str, str], list[float]] = {}
    for side in ("offense", "defense"):
        for field in METRICS:
            distributions[(side, field)] = [
                float(team.get(sample_name, {}).get(side, {}).get(field))
                for team in source_teams.values()
                if finite(team.get(sample_name, {}).get(side, {}).get(field))
                and int(team.get(sample_name, {}).get(side, {}).get("n_plays") or 0) >= 35
            ]

    output_teams: dict[str, Any] = {}
    all_team_names = sorted(set(model.get("teams", {})) | set(source_teams))
    for name in all_team_names:
        model_team = model.get("teams", {}).get(name, {})
        advanced_team = source_teams.get(name, {}).get(sample_name, {})
        external_team = external.get("teams", {}).get(name, {})
        team_output: dict[str, Any] = {
            "team": name,
            "conference": model_team.get("conference"),
            "power_rating": model_team.get("power_rating"),
            "power_rank": model_team.get("power_rating_rank"),
            "sos_rank": external_team.get("sos_rank"),
            "sample": {
                "offense_plays": advanced_team.get("offense", {}).get("n_plays", 0),
                "defense_plays": advanced_team.get("defense", {}).get("n_plays", 0),
                "minimum_ranked_plays": 35,
            },
            "offense": {},
            "defense": {},
        }
        for side in ("offense", "defense"):
            side_data = advanced_team.get(side, {})
            plays = int(side_data.get("n_plays") or 0)
            for field, definition in METRICS.items():
                value = side_data.get(field)
                eligible = finite(value) and plays >= 35
                higher = bool(definition[f"{side}_high"])
                values = distributions[(side, field)]
                pct = percentile(values, float(value), higher) if eligible and values else None
                metric_rank = rank(values, float(value), higher) if eligible and values else None
                team_output[side][field] = {
                    "value": round(float(value), 4) if finite(value) else None,
                    "rank": metric_rank,
