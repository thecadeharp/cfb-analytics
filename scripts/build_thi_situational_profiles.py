#!/usr/bin/env python3
"""Display-only, sample-shrunk 2026 situational EPA profiles.

This script reads only the completed FBS play-by-play aggregate. It does not
modify Model A, estimate a spread, or assign predictive situational ranks.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/advanced_metrics.json"
OUTPUT = ROOT / "data/thi_situational_profiles.json"
MIN_DISPLAY_PLAYS = 10
MEASURED_PLAYS = 30
GLOBAL_PRIOR_PLAYS = 140
MAX_EPA_DEVIATION = 0.6
SPLITS = {
    "script": ("script_early_epa", "script_early_plays", 60),
    "leverage": ("leverage_epa", "leverage_plays", 50),
    "red_zone": ("situational_red_zone_epa", "situational_red_zone_plays", 70),
}


def finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def national_mean(teams, side):
    weighted = []
    for team in teams.values():
        row = team.get("non_garbage", {}).get(side, {})
        epa, n = finite(row.get("epa_play")), finite(row.get("n_plays"))
        if epa is not None and n is not None and n > 0:
            weighted.append((epa, n))
    if not weighted:
        raise RuntimeError(f"No national {side} sample")
    return sum(v * n for v, n in weighted) / sum(n for _, n in weighted)


def bounded_difference(value):
    return max(-MAX_EPA_DEVIATION, min(MAX_EPA_DEVIATION, value))


def profile_side(team, side, prior):
    row = team.get("non_garbage", {}).get(side, {})
    full_epa, full_n = finite(row.get("epa_play")), finite(row.get("n_plays"))
    full_n = int(full_n or 0)
    full_weight = full_n / (full_n + GLOBAL_PRIOR_PLAYS)
    global_anchor = (
        prior + full_weight * bounded_difference(full_epa - prior)
        if full_epa is not None else prior
    )
    result = {}
    for key, (metric, count_field, k) in SPLITS.items():
        raw, n = finite(row.get(metric)), int(finite(row.get(count_field)) or 0)
        weight = n / (n + k)
        # A tiny or nonexistent split must not display the anchor as though it
        # were an observed team-specific estimate.
        eligible = raw is not None and n >= MIN_DISPLAY_PLAYS
        adjusted = (
            global_anchor + weight * bounded_difference(raw - global_anchor)
            if eligible else None
        )
        result[key] = {
            "epa_per_play": round(adjusted, 3) if eligible else None,
            "sample_plays": n,
            "observed_weight": round(weight, 3) if eligible else 0.0,
            "sample_status": (
                "UNAVAILABLE" if not eligible else
                "DEVELOPING" if n < MEASURED_PLAYS else "MEASURED"
            ),
        }
    return result


def build(payload):
    if payload.get("meta", {}).get("model_usage") != "display_only_not_used_by_model_a":
        raise RuntimeError("Unexpected advanced-metrics source contract")
    teams = payload.get("teams", {})
    if len(teams) < 100:
        raise RuntimeError("FBS team population unexpectedly small")
    first = next(iter(teams.values())).get("non_garbage", {}).get("offense", {})
    if any(name not in first for name, _, _ in SPLITS.values()):
        raise RuntimeError("Historical-aligned situational fields missing; refresh Advanced Metrics v2")
    prior = {side: national_mean(teams, side) for side in ("offense", "defense")}
    output = {
        "meta": {
            "version": "0.1", "season": payload["meta"]["year"],
            "through_week": payload["meta"]["through_week"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "DESCRIPTIVE_BETA_NO_POINT_SCALE",
            "model_usage": "display_only_not_used_by_model_a",
            "definition": "Regulation FBS rush/pass EPA with valid starting down, distance, clock and pre-play score; garbage time excluded.",
            "not_a_spread": "Values are EPA per play, not first-half or full-game spread equivalents.",
            "prior": "Full-game team EPA/play shrunk toward the current FBS play-weighted mean before each split is shrunk toward that team-wide anchor.",
            "global_prior_plays": GLOBAL_PRIOR_PLAYS,
            "maximum_split_epa_deviation_before_shrinkage": MAX_EPA_DEVIATION,
            "split_prior_plays": {key: spec[2] for key, spec in SPLITS.items()},
            "minimum_display_plays": MIN_DISPLAY_PLAYS,
            "measured_sample_plays": MEASURED_PLAYS,
            "national_epa_per_play": {side: round(value, 4) for side, value in prior.items()},
            "no_opponent_adjustment": True,
        },
        "teams": {
            name: {side: profile_side(team, side, prior[side]) for side in prior}
            for name, team in teams.items()
        },
    }
    return output


def main():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    result = build(source)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"THI descriptive situational profiles: {len(result['teams'])} teams through Week {result['meta']['through_week']}")


if __name__ == "__main__":
    main()
