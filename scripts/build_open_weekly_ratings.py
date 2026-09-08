"""Build display-only weekly ratings from the free SportsDataverse feed.

This is an isolated fallback for the public Ratings and Team Dossier views.
It never writes cfb_metrics.json, projections.json, or any frozen Model A file.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "data" / "cfb_metrics.json"
ADVANCED_PATH = ROOT / "data" / "advanced_metrics.json"
OUTPUT_PATH = ROOT / "data" / "open_weekly_ratings.json"
MIN_PLAYS_PER_SIDE = 35

# A compact, transparent efficiency rating. Each component is standardized
# across teams before weighting, so source scale cannot dominate the result.
WEIGHTS = {
    "net_epa": 0.50,
    "net_success": 0.25,
    "explosive_margin": 0.15,
    "disruption_margin": 0.10,
}


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def number(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def z_score(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    deviation = numeric.std(ddof=0)
    if pd.isna(deviation) or deviation == 0:
        return numeric * 0.0
    return (numeric - numeric.mean()) / deviation


def main() -> None:
    core = load(CORE_PATH)
    advanced = load(ADVANCED_PATH)
    core_teams = core.get("teams") or {}
    baseline = core.get("baseline_snapshot") or {}
    advanced_teams = advanced.get("teams") or {}

    if len(core_teams) < 100 or len(advanced_teams) < 100:
        raise RuntimeError("Team coverage is incomplete; no output published")

    rows = []
    samples = {}

    for team in sorted(core_teams):
        profile = (advanced_teams.get(team) or {}).get("non_garbage") or {}
        offense = profile.get("offense") or {}
        defense = profile.get("defense") or {}
        off_plays = int(number(offense.get("n_plays")) or 0)
        def_plays = int(number(defense.get("n_plays")) or 0)

        samples[team] = {"offense": off_plays, "defense": def_plays}
        if off_plays < MIN_PLAYS_PER_SIDE or def_plays < MIN_PLAYS_PER_SIDE:
            continue

        off_epa = number(offense.get("epa_play"))
        def_epa = number(defense.get("epa_play"))
        off_success = number(offense.get("success_rate"))
        def_success = number(defense.get("success_rate"))
        off_explosive = number(offense.get("explosive_rate"))
        def_explosive = number(defense.get("explosive_rate"))
        off_disruption = number(offense.get("tfl_rate"))
        def_disruption = number(defense.get("tfl_rate"))

        values = (
            off_epa, def_epa, off_success, def_success,
            off_explosive, def_explosive, off_disruption, def_disruption,
        )
        if any(value is None for value in values):
            continue

        rows.append({
            "team": team,
            "net_epa": off_epa - def_epa,
            "net_success": off_success - def_success,
            "explosive_margin": off_explosive - def_explosive,
            # Fewer offensive disruptions and more defensive disruptions are good.
            "disruption_margin": def_disruption - off_disruption,
        })

    if len(rows) < 20:
        raise RuntimeError(
            f"Only {len(rows)} teams passed the sample guard; no output published"
        )

    frame = pd.DataFrame(rows).set_index("team")
    live_rating = sum(z_score(frame[column]) * weight for column, weight in WEIGHTS.items())
    frame["live_rating"] = live_rating

    through_week = int(number((advanced.get("meta") or {}).get("through_week")) or 0)
    blend_weight = min(1.0, through_week / 10.0)
    output_teams = {}

    for team in sorted(core_teams):
        baseline_team = baseline.get(team) or core_teams.get(team) or {}
        base_rating = number(baseline_team.get("power_rating"))
        if base_rating is None:
            continue

        live = number(frame.at[team, "live_rating"]) if team in frame.index else None
        blended = (
            base_rating * (1.0 - blend_weight) + live * blend_weight
            if live is not None else base_rating
        )

        item = {
            "team": team,
            "conference": core_teams.get(team, {}).get("conference"),
            "rating": round(blended, 3),
            "rank": None,
            "preseason_rating": round(base_rating, 3),
            "live_rating": round(live, 3) if live is not None else None,
            "sample": samples.get(team, {"offense": 0, "defense": 0}),
        }
        if team in frame.index:
            item["components"] = {
                key: round(number(frame.at[team, key]), 3)
                for key in WEIGHTS
            }
        output_teams[team] = item

    ranked = sorted(output_teams.values(), key=lambda item: item["rating"], reverse=True)
    for rank, item in enumerate(ranked, 1):
        item["rank"] = rank

    output = {
        "meta": {
            "year": 2026,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "through_week": through_week,
            "completed_games": (advanced.get("meta") or {}).get("completed_games"),
            "blend_weight": blend_weight,
            "eligible_teams": len(frame),
            "minimum_plays_per_side": MIN_PLAYS_PER_SIDE,
            "source": "SportsDataverse cfbfastR ESPN-derived play-by-play",
            "rating_type": "display_only_open_data_fallback",
            "model_a_touched": False,
            "weights": WEIGHTS,
        },
        "teams": output_teams,
    }

    OUTPUT_PATH.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} with {len(output_teams)} teams")
    print(f"Eligible live samples: {len(frame)}; blend weight: {blend_weight:.0%}")
    print("Model A files were not touched")


if __name__ == "__main__":
    main()
