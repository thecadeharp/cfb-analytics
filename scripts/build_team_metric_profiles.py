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
    "yards_per_play": {"label": "Yards / Play", "format": "decimal", "offense_high": True, "defense_high": False},
    "yards_per_rush": {"label": "Yards / Carry", "format": "decimal", "offense_high": True, "defense_high": False},
    "yards_per_pass_play": {"label": "Yards / Pass Play", "format": "decimal", "offense_high": True, "defense_high": False},
    "epa_play": {"label": "EPA / Play", "format": "epa", "offense_high": True, "defense_high": False},
    "success_rate": {"label": "Success Rate", "format": "percent", "offense_high": True, "defense_high": False},
    "iso_ppp": {"label": "IsoPPP", "format": "epa", "offense_high": True, "defense_high": False},
    "explosive_rate": {"label": "Explosive Rate", "format": "percent", "offense_high": True, "defense_high": False},
    "early_down_epa": {"label": "Early-Down EPA", "format": "epa", "offense_high": True, "defense_high": False},
    "late_down_epa": {"label": "Late-Down EPA", "format": "epa", "offense_high": True, "defense_high": False},
    "standard_down_epa": {"label": "Standard-Down EPA", "format": "epa", "offense_high": True, "defense_high": False},
    "standard_down_success_rate": {"label": "Standard-Down Success", "format": "percent", "offense_high": True, "defense_high": False},
    "passing_down_epa": {"label": "Passing-Down EPA", "format": "epa", "offense_high": True, "defense_high": False},
    "passing_down_success_rate": {"label": "Passing-Down Success", "format": "percent", "offense_high": True, "defense_high": False},
    "stuff_rate": {"label": "Stuff Rate", "format": "percent", "offense_high": False, "defense_high": True},
    "opportunity_rate": {"label": "Opportunity Rate", "format": "percent", "offense_high": True, "defense_high": False},
    "sack_rate": {"label": "Sack Rate", "format": "percent", "offense_high": False, "defense_high": True},
    "adjusted_sack_rate": {"label": "Adjusted Sack Rate", "format": "percent", "offense_high": False, "defense_high": True},
    "tfl_rate": {"label": "TFL Rate", "format": "percent", "offense_high": False, "defense_high": True},
    "havoc_rate": {"label": "Havoc Rate", "format": "percent", "offense_high": False, "defense_high": True},
    "front_seven_havoc_rate": {"label": "Front-Seven Havoc", "format": "percent", "offense_high": False, "defense_high": True},
    "secondary_havoc_rate": {"label": "Secondary Havoc", "format": "percent", "offense_high": False, "defense_high": True},
    "power_success_rate": {"label": "Power Success", "format": "percent", "offense_high": True, "defense_high": False},
    "line_yards_per_rush": {"label": "Line Yards / Rush", "format": "decimal", "offense_high": True, "defense_high": False},
    "second_level_yards_per_rush": {"label": "Second-Level Yards / Rush", "format": "decimal", "offense_high": True, "defense_high": False},
    "open_field_yards_per_rush": {"label": "Open-Field Yards / Rush", "format": "decimal", "offense_high": True, "defense_high": False},
    "available_yards_pct": {"label": "Available Yards", "format": "percent", "offense_high": True, "defense_high": False},
    "drive_scoring_rate": {"label": "Drive Scoring Rate", "format": "percent", "offense_high": True, "defense_high": False},
    "points_per_opportunity": {"label": "Points / Opportunity", "format": "decimal", "offense_high": True, "defense_high": False},
    "red_zone_td_rate": {"label": "Red-Zone TD Rate", "format": "percent", "offense_high": True, "defense_high": False},
    "red_zone_scoring_rate": {"label": "Red-Zone Scoring Rate", "format": "percent", "offense_high": True, "defense_high": False},
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
                    "percentile": round(pct, 1) if pct is not None else None,
                    "band": color_band(pct),
                    "eligible": eligible,
                }

        offense_epa = team_output["offense"]["epa_play"]["value"]
        defense_epa = team_output["defense"]["epa_play"]["value"]
        team_output["net_epa_play"] = (
            round(offense_epa - defense_epa, 4)
            if finite(offense_epa) and finite(defense_epa)
            else None
        )
        output_teams[name] = team_output

    net_values = [
        float(team["net_epa_play"])
        for team in output_teams.values()
        if finite(team.get("net_epa_play"))
        and int(team["sample"]["offense_plays"] or 0) >= 35
        and int(team["sample"]["defense_plays"] or 0) >= 35
    ]
    for team in output_teams.values():
        value = team.get("net_epa_play")
        eligible = (
            finite(value)
            and int(team["sample"]["offense_plays"] or 0) >= 35
            and int(team["sample"]["defense_plays"] or 0) >= 35
        )
        pct = percentile(net_values, float(value), True) if eligible and net_values else None
        team["net_epa"] = {
            "value": value,
            "rank": rank(net_values, float(value), True) if pct is not None else None,
            "percentile": round(pct, 1) if pct is not None else None,
            "band": color_band(pct),
            "eligible": eligible,
        }

    payload = {
        "meta": {
            "season": 2026,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "through_week": advanced.get("meta", {}).get("through_week"),
            "source": advanced.get("meta", {}).get("source"),
            "sample": sample_name,
            "minimum_ranked_plays": 35,
            "model_usage": "display_only_not_used_by_model_a",
            "percentile_meaning": "100 is best after accounting for metric direction.",
            "color_bands": {
                "elite": "85-100",
                "strong": "70-84.9",
                "above": "55-69.9",
                "average": "45-54.9",
                "below": "30-44.9",
                "poor": "15-29.9",
                "critical": "0-14.9",
            },
            "metrics": METRICS,
        },
        "teams": output_teams,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    eligible = sum(team["net_epa"]["eligible"] for team in output_teams.values())
    print(f"Wrote {OUTPUT.relative_to(ROOT)} for {len(output_teams)} teams ({eligible} ranked samples).")


if __name__ == "__main__":
    main()
