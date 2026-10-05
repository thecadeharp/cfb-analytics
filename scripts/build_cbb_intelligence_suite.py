#!/usr/bin/env python3
"""Build coordinated CBB player, home-court, market and dossier research views."""

from __future__ import annotations

import argparse, json, math, tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-intelligence-suite-v1.0"

def num(value: Any) -> float | None:
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError): return None

def national_hca(model: dict[str, Any]) -> float | None:
    margin = (model.get("models") or {}).get("margin") or {}
    names, coefs = margin.get("feature_names") or [], margin.get("coefficients") or []
    if "home_court" not in names or len(coefs) != len(names) + 1: return None
    index = names.index("home_court")
    scale = num((margin.get("scales") or {}).get("home_court")) or 1.0
    mean = num((margin.get("means") or {}).get("home_court")) or 0.0
    coefficient = num(coefs[index + 1])
    return round(coefficient * (1.0 - mean) / scale, 2) if coefficient is not None else None

def project_players(players: dict[str, Any], priors: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    team_tempo = {str(row.get("team_id")): num(row.get("prior_tempo")) or 68.0 for row in priors.get("teams") or []}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for player in players.get("players") or []: grouped[str(player.get("team_id"))].append(player)
    projections, rotations = [], []
    for team_id, rows in grouped.items():
        rows.sort(key=lambda row: -(num((row.get("research_scores") or {}).get("thi_player_rating")) or 0))
        raw_minutes = []
        for index, row in enumerate(rows):
            mpg = num((row.get("sample") or {}).get("minutes_per_game"))
            rating = num((row.get("research_scores") or {}).get("thi_player_rating")) or 40
            baseline = mpg if mpg is not None else max(6.0, 29.0 - index * 2.4)
            raw_minutes.append(max(2.0, min(34.0, .72 * baseline + .28 * (10 + rating * .25))))
        scale = 200.0 / sum(raw_minutes[:10]) if raw_minutes[:10] else 1.0
        team_rows = []
        for index, (row, raw) in enumerate(zip(rows, raw_minutes)):
            minutes = round(min(36.0, raw * scale), 1) if index < 10 else 0.0
            metrics = row.get("metrics") or {}
            reliability = num((row.get("data_quality") or {}).get("reliability")) or 0
            qualified = num(metrics.get("points_per_40")) is not None and minutes > 0
            stat = lambda key: round((num(metrics.get(key)) or 0) * minutes / 40.0, 1) if qualified and num(metrics.get(key)) is not None else None
            projected = {
                "player_season_id": row.get("player_season_id"), "team_id": row.get("team_id"), "team": row.get("team"),
                "name": row.get("name"), "position": row.get("position"), "role": row.get("role"),
                "projected_minutes": minutes, "projected_points": stat("points_per_40"),
                "projected_rebounds": stat("rebounds_per_40"), "projected_assists": stat("assists_per_40"),
                "projected_steals": stat("steals_per_40"), "projected_blocks": stat("blocks_per_40"),
                "projected_turnovers": stat("turnovers_per_40"), "thi_impact": (row.get("research_scores") or {}).get("thi_player_rating"),
                "tempo_context": round(team_tempo.get(team_id, 68.0), 1), "projection_state": "statistical_prior" if qualified else "role_only",
                "reliability": reliability,
            }
            projections.append(projected); team_rows.append(projected)
        rotations.append({"team_id": rows[0].get("team_id"), "team": rows[0].get("team"), "players": team_rows[:12], "projected_rotation_minutes": round(sum(row["projected_minutes"] for row in team_rows[:10]), 1)})
    projections.sort(key=lambda row: (-(num(row.get("thi_impact")) or 0), str(row.get("name") or "")))
    rotations.sort(key=lambda row: str(row.get("team") or ""))
    return projections, rotations

def build_suite(profiles: dict[str, Any], priors: dict[str, Any], players: dict[str, Any], board: dict[str, Any], tracking: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    player_rows, rotations = project_players(players, priors)
    projection_by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)
    market_rows = []
    for game in board.get("games") or []:
        projection = game.get("projection") or {}
        for side in ("home", "away"):
            projection_by_team[str((game.get(side) or {}).get("team_id"))].append({"game_id": game.get("game_id"), "opponent": (game.get("away" if side == "home" else "home") or {}).get("team"), "site": "neutral" if game.get("neutral_site") else side, "projected_margin": (num(projection.get("home_margin")) or 0) * (1 if side == "home" else -1), "win_probability": projection.get("home_win_probability") if side == "home" else (round(100 - num(projection.get("home_win_probability")), 1) if num(projection.get("home_win_probability")) is not None else None)})
        market = game.get("market") or {}
        market_rows.append({"game_id": game.get("game_id"), "start_date": game.get("start_date"), "away_team": (game.get("away") or {}).get("team"), "home_team": (game.get("home") or {}).get("team"), "opening_spread": market.get("opening_home_spread"), "current_spread": market.get("consensus_home_spread"), "spread_move": market.get("spread_move"), "opening_total": market.get("opening_total"), "current_total": market.get("consensus_total"), "total_move": market.get("total_move"), "model_edge": projection.get("spread_edge"), "signal": projection.get("spread_signal_tier"), "confidence": projection.get("signal_confidence")})
    profile_map = {str(row.get("team_id")): row for row in profiles.get("teams") or []}
    rotation_map = {str(row.get("team_id")): row for row in rotations}
    dossiers = []
    for prior in priors.get("teams") or []:
        team_id = str(prior.get("team_id")); profile = profile_map.get(team_id, {})
        dossiers.append({"team_id": prior.get("team_id"), "team": prior.get("team"), "conference": prior.get("conference"), "ratings": {"net": prior.get("prior_net"), "offense": prior.get("prior_offense"), "defense": prior.get("prior_defense"), "tempo": prior.get("prior_tempo")}, "record": profile.get("record"), "four_factors": prior.get("prior_four_factors"), "shot_profile": (profile.get("shot_profile") if int((profile.get("shot_profile") or {}).get("tracked_shots") or 0) >= 25 else (profile.get("preseason_prior") or {}).get("shot_profile")), "personnel": prior.get("personnel"), "continuity": {"returning_minutes_pct": prior.get("returning_minutes_pct"), "source": prior.get("continuity_source")}, "rotation": rotation_map.get(team_id, {}).get("players", []), "schedule_window": projection_by_team.get(team_id, [])})
    return {"meta": {"version": VERSION, "season": priors.get("meta", {}).get("season"), "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "player_projection_policy": "Qualified prior production receives per-game counting-stat projections; unverified statistical profiles receive role and impact context only.", "home_court_policy": "National effect learned by the walk-forward model; neutral-site games receive zero. Team venue effects remain withheld pending sample thresholds.", "market_policy": "Market prices are comparison and accountability fields, never predictive features."}, "home_court": {"national_points": national_hca(model), "team_specific_status": "withheld_until_qualified_sample", "neutral_site_points": 0.0}, "player_projections": player_rows, "team_rotations": rotations, "market_board": market_rows, "market_summary": tracking.get("summary") or {}, "team_dossiers": dossiers}

def write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False); handle.write("\n"); temp = Path(handle.name)
    temp.replace(path)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT / "data" / "cbb"); parser.add_argument("--output", type=Path, default=ROOT / "data" / "cbb" / "intelligence_suite.json")
    args = parser.parse_args(); root = args.root
    load = lambda path: json.loads(path.read_text())
    payload = build_suite(load(root/"team_profiles.json"), load(root/"model/current_priors.json"), load(root/"player_ratings.json"), load(root/"projection_board.json"), load(root/"model_tracking.json"), load(root/"model/model_card.json"))
    write(args.output, payload); print(f"{VERSION}: {len(payload['player_projections'])} players, {len(payload['team_dossiers'])} dossiers")

if __name__ == "__main__": main()
