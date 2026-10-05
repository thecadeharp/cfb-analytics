#!/usr/bin/env python3
"""Build THI's display-only CBB possession and matchup research layer."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-matchup-engine-v1.0"


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def choose_profile(profile: dict[str, Any]) -> tuple[dict[str, Any], str]:
    current = profile.get("shot_profile") or {}
    prior = (profile.get("preseason_prior") or {}).get("shot_profile") or {}
    if int(current.get("tracked_shots") or 0) >= 25:
        return current, "current_observed"
    if int(prior.get("tracked_shots") or 0) >= 25:
        return prior, "prior_season"
    return {}, "unavailable"


def pace_environment(projected: float | None, home_tempo: float | None, away_tempo: float | None) -> dict[str, Any]:
    if projected is None:
        return {"projected_possessions": None, "band": "unavailable", "clash": None}
    if projected < 64:
        band = "grind"
    elif projected < 68:
        band = "controlled"
    elif projected < 72:
        band = "average"
    elif projected < 76:
        band = "fast"
    else:
        band = "track_meet"
    clash = abs(home_tempo - away_tempo) if home_tempo is not None and away_tempo is not None else None
    return {
        "projected_possessions": round(projected, 1),
        "band": band,
        "clash": round(clash, 1) if clash is not None else None,
        "clash_label": "strong" if clash is not None and clash >= 7 else ("moderate" if clash is not None and clash >= 4 else ("low" if clash is not None else "unavailable")),
    }


def dimension(name: str, home_value: float | None, away_value: float | None, home_team: str, away_team: str, lower_better: bool = False) -> dict[str, Any]:
    if home_value is None or away_value is None:
        return {"dimension": name, "home_value": home_value, "away_value": away_value, "advantage_team": None, "edge": None, "magnitude": "unavailable"}
    edge = (away_value - home_value) if lower_better else (home_value - away_value)
    absolute = abs(edge)
    return {
        "dimension": name,
        "home_value": round(home_value, 2),
        "away_value": round(away_value, 2),
        "advantage_team": home_team if edge > 0.25 else (away_team if edge < -0.25 else "Even"),
        "edge": round(edge, 2),
        "magnitude": "strong" if absolute >= 5 else ("meaningful" if absolute >= 2.5 else ("slight" if absolute >= .75 else "even")),
    }


def style_block(profile: dict[str, Any], play_style: dict[str, Any] | None) -> dict[str, Any]:
    source_profile, source = choose_profile(profile)
    if play_style and int(play_style.get("tracked_shots") or 0) >= 25:
        source_profile = {
            "tracked_shots": play_style.get("tracked_shots"),
            "at_rim_rate": play_style.get("rim_rate"),
            "midrange_rate": play_style.get("midrange_rate"),
            "three_point_rate": play_style.get("three_rate"),
            "assisted_pct": play_style.get("assisted_rate"),
        }
        source = "current_play_by_play"
    return {
        "source": source,
        "sample_state": (play_style or {}).get("sample_state") if source == "current_play_by_play" else ("tracked" if int(source_profile.get("tracked_shots") or 0) >= 100 else ("developing" if source_profile else "unavailable")),
        "tracked_shots": int(source_profile.get("tracked_shots") or 0),
        "rim_rate": finite(source_profile.get("at_rim_rate")),
        "midrange_rate": finite(source_profile.get("midrange_rate")),
        "three_rate": finite(source_profile.get("three_point_rate")),
        "assisted_rate": finite(source_profile.get("assisted_pct")),
        "explicit_transition_rate": finite((play_style or {}).get("explicit_transition_rate")),
        "lineup_coverage_pct": finite((play_style or {}).get("on_floor_coverage_pct")),
    }


def build_matchups(
    projection_board: dict[str, Any],
    team_profiles: dict[str, Any],
    play_style_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profiles = {str(row.get("team_id")): row for row in team_profiles.get("teams") or []}
    styles = {str(row.get("team_id")): row for row in (play_style_payload or {}).get("teams") or []}
    games = []
    for game in projection_board.get("games") or []:
        projection = game.get("projection") or {}
        if not projection:
            continue
        context = projection.get("matchup_context") or {}
        factors = context.get("four_factor_matchup") or {}
        home_id, away_id = str((game.get("home") or {}).get("team_id")), str((game.get("away") or {}).get("team_id"))
        home_team, away_team = str((game.get("home") or {}).get("team") or "Home"), str((game.get("away") or {}).get("team") or "Away")
        home_factors, away_factors = factors.get("home") or {}, factors.get("away") or {}
        dimensions = [
            dimension("shooting", finite(home_factors.get("effective_fg_pct")), finite(away_factors.get("effective_fg_pct")), home_team, away_team),
            dimension("ball_security", finite(home_factors.get("turnover_pct")), finite(away_factors.get("turnover_pct")), home_team, away_team, True),
            dimension("offensive_glass", finite(home_factors.get("offensive_rebound_pct")), finite(away_factors.get("offensive_rebound_pct")), home_team, away_team),
            dimension("foul_pressure", finite(home_factors.get("free_throw_rate")), finite(away_factors.get("free_throw_rate")), home_team, away_team),
        ]
        home_style = style_block(profiles.get(home_id, {}), styles.get(home_id))
        away_style = style_block(profiles.get(away_id, {}), styles.get(away_id))
        games.append({
            "game_id": game.get("game_id"),
            "start_date": game.get("start_date"),
            "status": game.get("status"),
            "home": {"team_id": (game.get("home") or {}).get("team_id"), "team": home_team},
            "away": {"team_id": (game.get("away") or {}).get("team_id"), "team": away_team},
            "pace_environment": pace_environment(finite(projection.get("projected_possessions")), finite((context.get("home") or {}).get("tempo")), finite((context.get("away") or {}).get("tempo"))),
            "factor_advantages": dimensions,
            "shot_style": {"home": home_style, "away": away_style},
            "research_status": {
                "feeds_public_spread": False,
                "reason": "Matchup components remain an explanation layer until out-of-sample validation clears promotion gates.",
                "transition_coverage": "explicit_play_types_only" if home_style["explicit_transition_rate"] is not None or away_style["explicit_transition_rate"] is not None else "unavailable",
            },
        })
    return {
        "meta": {
            "version": VERSION,
            "projection_board_version": projection_board.get("meta", {}).get("version"),
            "play_style_version": (play_style_payload or {}).get("meta", {}).get("version"),
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "game_count": len(games),
            "model_usage": "display_only_research_layer",
            "promotion_gate": "No matchup component enters the published spread or total until historical walk-forward validation demonstrates incremental value.",
        },
        "games": games,
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
    parser.add_argument("--projections", type=Path, default=ROOT / "data" / "cbb" / "projection_board.json")
    parser.add_argument("--profiles", type=Path, default=ROOT / "data" / "cbb" / "team_profiles.json")
    parser.add_argument("--play-style", type=Path, default=ROOT / "data" / "cbb" / "play_style.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "cbb" / "matchup_engine.json")
    args = parser.parse_args()
    play_style = json.loads(args.play_style.read_text()) if args.play_style.exists() else None
    payload = build_matchups(json.loads(args.projections.read_text()), json.loads(args.profiles.read_text()), play_style)
    atomic_write(args.output, payload)
    print(f"{VERSION}: {payload['meta']['game_count']} game matchup explanations")


if __name__ == "__main__":
    main()
