#!/usr/bin/env python3
"""Build coordinated CBB player, home-court, market and dossier research views."""

from __future__ import annotations

import argparse, json, math, statistics, tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-intelligence-suite-v1.3"

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
    coefficient = num(coefs[index + 1])
    # Report the counterfactual change from a neutral floor (0) to campus (1).
    # The model standardizes its inputs, so the intercept/mean cancels when the
    # two predictions are differenced and the effect is coefficient / scale.
    return round(coefficient / scale, 2) if coefficient is not None else None

def instant(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None

def ranked(values: dict[str, float | None], reverse: bool = True) -> dict[str, int | None]:
    ordered = sorted(
        ((team_id, value) for team_id, value in values.items() if value is not None),
        key=lambda item: ((-item[1]) if reverse else item[1], item[0]),
    )
    return {team_id: index for index, (team_id, _value) in enumerate(ordered, 1)}

def game_status(game: dict[str, Any]) -> str:
    return str(game.get("status") or "").lower().replace("_", "")

def wl_record(rows: list[dict[str, Any]]) -> dict[str, int]:
    wins = sum(num(row.get("team_score")) is not None and num(row.get("opponent_score")) is not None and num(row.get("team_score")) > num(row.get("opponent_score")) for row in rows)
    losses = sum(num(row.get("team_score")) is not None and num(row.get("opponent_score")) is not None and num(row.get("team_score")) < num(row.get("opponent_score")) for row in rows)
    return {"wins": wins, "losses": losses}

def thi_quadrant(site: str, opponent_rank: int | None) -> str | None:
    if opponent_rank is None:
        return None
    q1 = {"home": 30, "neutral": 50, "away": 75}[site]
    q2 = {"home": 75, "neutral": 100, "away": 135}[site]
    q3 = {"home": 160, "neutral": 200, "away": 240}[site]
    return "q1" if opponent_rank <= q1 else "q2" if opponent_rank <= q2 else "q3" if opponent_rank <= q3 else "q4"

def resume_profile(
    rows: list[dict[str, Any]],
    opponent_ranks: dict[str, int | None],
    opponent_ratings: dict[str, float | None],
    team_count: int,
) -> dict[str, Any]:
    finals = [row for row in rows if row.get("status") in {"final", "completed", "complete"} and num(row.get("team_score")) is not None and num(row.get("opponent_score")) is not None]
    enriched = []
    for row in finals:
        site = str(row.get("site") or "neutral")
        opponent_id = str(row.get("opponent_id"))
        opponent_rank = opponent_ranks.get(opponent_id)
        actual_margin = float(num(row.get("team_score")) or 0) - float(num(row.get("opponent_score")) or 0)
        projected_margin = num(row.get("projected_margin"))
        residual = actual_margin - projected_margin if projected_margin is not None else None
        won = actual_margin > 0
        rank_quality = (team_count + 1 - opponent_rank) / max(team_count, 1) if opponent_rank else .5
        site_multiplier = 1.1 if (won and site == "away") or (not won and site == "home") else .9 if (won and site == "home") or (not won and site == "away") else 1.0
        enriched.append({**row, "opponent_rank": opponent_rank, "opponent_rating": opponent_ratings.get(opponent_id), "actual_margin": round(actual_margin, 1), "performance_vs_projection": round(residual, 2) if residual is not None else None, "quadrant": thi_quadrant(site, opponent_rank), "record_quality_value": (1 if won else -1) * rank_quality * site_multiplier})
    site_records = {site: wl_record([row for row in enriched if row.get("site") == site]) for site in ("home", "away", "neutral")}
    quadrant_records = {q: wl_record([row for row in enriched if row.get("quadrant") == q]) for q in ("q1", "q2", "q3", "q4")}
    top_records = {label: wl_record([row for row in enriched if row.get("opponent_rank") is not None and row["opponent_rank"] <= cutoff]) for label, cutoff in (("top_25", 25), ("top_50", 50), ("top_100", 100))}
    residuals = [row["performance_vs_projection"] for row in enriched if row.get("performance_vs_projection") is not None]
    away_residuals = [row["performance_vs_projection"] for row in enriched if row.get("site") in {"away", "neutral"} and row.get("performance_vs_projection") is not None]
    recent = sorted(enriched, key=lambda row: str(row.get("start_date") or ""), reverse=True)[:5]
    recent_residuals = [row["performance_vs_projection"] for row in recent if row.get("performance_vs_projection") is not None]
    return {
        "overall_record": wl_record(enriched),
        "site_records": site_records,
        "quadrant_records": quadrant_records,
        "opponent_quality_records": top_records,
        "record_quality": round(statistics.mean(row["record_quality_value"] for row in enriched), 3) if enriched else None,
        "away_from_home_performance": round(statistics.mean(away_residuals), 2) if away_residuals else None,
        "overall_performance_vs_projection": round(statistics.mean(residuals), 2) if residuals else None,
        "recent_form_vs_projection": round(statistics.mean(recent_residuals), 2) if recent_residuals else None,
        "games_graded": len(enriched),
        "away_neutral_games_graded": len(away_residuals),
        "recent_games_graded": len(recent_residuals),
        "policy": "THI-calculated résumé context using frozen projections and THI opponent ranks; quadrant-style records are not NCAA NET quadrants.",
    }

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

def build_suite(profiles: dict[str, Any], priors: dict[str, Any], players: dict[str, Any], board: dict[str, Any], tracking: dict[str, Any], model: dict[str, Any], home_court: dict[str, Any] | None = None) -> dict[str, Any]:
    player_rows, rotations = project_players(players, priors)
    prior_rows = priors.get("teams") or []
    prior_map = {str(row.get("team_id")): row for row in prior_rows}
    profile_map = {str(row.get("team_id")): row for row in profiles.get("teams") or []}
    rotation_map = {str(row.get("team_id")): row for row in rotations}
    hca = national_hca(model)
    home_court = home_court or {}
    hca_map = {str(row.get("team_id")): row for row in home_court.get("teams") or []}
    hca_national = num((home_court.get("meta") or {}).get("national_points")) or hca

    rating_ranks = {
        "net": ranked({str(row.get("team_id")): num(row.get("prior_net")) for row in prior_rows}),
        "offense": ranked({str(row.get("team_id")): num(row.get("prior_offense")) for row in prior_rows}),
        "defense": ranked({str(row.get("team_id")): num(row.get("prior_defense")) for row in prior_rows}, reverse=False),
        "tempo": ranked({str(row.get("team_id")): num(row.get("prior_tempo")) for row in prior_rows}),
    }
    current_net = {
        team_id: num((((profile_map.get(team_id) or {}).get("current_efficiency") or {}).get("adjusted") or {}).get("net"))
        for team_id in prior_map
    }
    current_or_prior_net = {team_id: current_net.get(team_id) if current_net.get(team_id) is not None else num(row.get("prior_net")) for team_id, row in prior_map.items()}
    current_ranks = ranked(current_or_prior_net)
    roster_scores = {
        team_id: round(statistics.mean([
            num(row.get("thi_impact")) or 0 for row in rotation.get("players", [])[:8]
        ]), 3)
        for team_id, rotation in rotation_map.items()
        if len(rotation.get("players", [])) >= 5
    }
    roster_ranks = ranked(roster_scores)

    schedules: dict[str, list[dict[str, Any]]] = defaultdict(list)
    projection_by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)
    market_rows, recent_by_team = [], defaultdict(list)
    games = board.get("games") or []
    for game in games:
        projection = game.get("projection") or {}
        start = instant(game.get("start_date"))
        for side in ("home", "away"):
            team = game.get(side) or {}
            opponent_side = "away" if side == "home" else "home"
            opponent = game.get(opponent_side) or {}
            team_id = str(team.get("team_id"))
            win_probability = num(projection.get("home_win_probability"))
            if side == "away" and win_probability is not None:
                win_probability = 100.0 - win_probability
            item = {
                "game_id": game.get("game_id"),
                "start_date": game.get("start_date"),
                "start": start,
                "opponent_id": opponent.get("team_id"),
                "opponent": opponent.get("team"),
                "site": "neutral" if game.get("neutral_site") else side,
                "conference_game": bool(game.get("conference_game")),
                "projected_margin": round((num(projection.get("home_margin")) or 0) * (1 if side == "home" else -1), 2),
                "win_probability": round(win_probability, 1) if win_probability is not None else None,
                "status": game_status(game),
                "team_score": team.get("score"),
                "opponent_score": opponent.get("score"),
            }
            schedules[team_id].append(item)
            projection_by_team[team_id].append({key: value for key, value in item.items() if key != "start"})
            if item["status"] in {"final", "completed", "complete"}:
                recent_by_team[team_id].append({key: value for key, value in item.items() if key != "start"})
        market = game.get("market") or {}
        market_rows.append({"game_id": game.get("game_id"), "start_date": game.get("start_date"), "away_team": (game.get("away") or {}).get("team"), "home_team": (game.get("home") or {}).get("team"), "opening_spread": market.get("opening_home_spread"), "current_spread": market.get("consensus_home_spread"), "spread_move": market.get("spread_move"), "opening_total": market.get("opening_total"), "current_total": market.get("consensus_total"), "total_move": market.get("total_move"), "model_edge": projection.get("spread_edge"), "signal": projection.get("spread_signal_tier"), "confidence": projection.get("signal_confidence")})

    for rows in schedules.values():
        rows.sort(key=lambda row: row.get("start") or datetime.max.replace(tzinfo=timezone.utc))

    game_context = []
    for game in games:
        start = instant(game.get("start_date"))
        projection = game.get("projection") or {}
        projection_hca = ((projection.get("matchup_context") or {}).get("home_court") or {})
        home_team_id = str((game.get("home") or {}).get("team_id"))
        team_hca = hca_map.get(home_team_id) or {}
        context = {
            "game_id": game.get("game_id"),
            "model_usage": "research_context_only",
            "home_court_points": 0.0 if game.get("neutral_site") else num(projection_hca.get("points")) if num(projection_hca.get("points")) is not None else num(team_hca.get("home_court_points")) or hca_national,
            "home_court_state": "neutral_site" if game.get("neutral_site") else "team_specific_regularized" if team_hca else "national_fallback",
            "availability": {"status": "not_sourced", "adjustment_points": None},
            "travel": {"miles": None, "status": "awaiting_verified_team_origin_and_travel_feed"},
            "teams": {},
        }
        for side in ("away", "home"):
            team = game.get(side) or {}
            team_id = str(team.get("team_id"))
            rows = schedules.get(team_id, [])
            index = next((i for i, row in enumerate(rows) if str(row.get("game_id")) == str(game.get("game_id"))), -1)
            previous = rows[index - 1] if index > 0 else None
            following = rows[index + 1] if index >= 0 and index + 1 < len(rows) else None
            rest_days = round((start - previous["start"]).total_seconds() / 86400, 1) if start and previous and previous.get("start") else None
            next_days = round((following["start"] - start).total_seconds() / 86400, 1) if start and following and following.get("start") else None
            opponent_id = str((game.get("home" if side == "away" else "away") or {}).get("team_id"))
            current_opponent = num((prior_map.get(opponent_id) or {}).get("prior_net"))
            next_opponent = num((prior_map.get(str((following or {}).get("opponent_id"))) or {}).get("prior_net"))
            previous_opponent = num((prior_map.get(str((previous or {}).get("opponent_id"))) or {}).get("prior_net"))
            team_net = num((prior_map.get(team_id) or {}).get("prior_net"))
            flags = []
            if rest_days is not None and rest_days <= 1.5: flags.append("back_to_back")
            elif rest_days is not None and rest_days <= 2.5: flags.append("short_rest")
            if game.get("neutral_site"): flags.append("neutral_site")
            if game.get("conference_game"): flags.append("conference_game")
            if next_days is not None and next_days <= 5 and next_opponent is not None and current_opponent is not None and next_opponent >= current_opponent + 8: flags.append("lookahead_spot")
            if previous and rest_days is not None and rest_days <= 5 and previous_opponent is not None and team_net is not None:
                scored = num(previous.get("team_score")); allowed = num(previous.get("opponent_score"))
                if scored is not None and allowed is not None and scored > allowed and previous_opponent >= team_net + 8: flags.append("letdown_watch")
                if scored is not None and allowed is not None and scored < allowed and previous_opponent <= team_net - 8: flags.append("bounce_back_watch")
            context["teams"][side] = {
                "team_id": team.get("team_id"), "team": team.get("team"),
                "rest_days": rest_days, "next_game_days": next_days,
                "previous_opponent": (previous or {}).get("opponent"),
                "next_opponent": (following or {}).get("opponent"),
                "flags": flags,
            }
        game_context.append(context)

    dossiers = []
    for prior in prior_rows:
        team_id = str(prior.get("team_id")); profile = profile_map.get(team_id, {})
        rotation = rotation_map.get(team_id, {}).get("players", [])
        schedule = projection_by_team.get(team_id, [])
        opponent_nets = [num((prior_map.get(str(row.get("opponent_id"))) or {}).get("prior_net")) for row in schedule]
        nc_opponent_nets = [value for row, value in zip(schedule, opponent_nets) if not row.get("conference_game") and value is not None]
        opponent_nets = [value for value in opponent_nets if value is not None]
        expected_wins = sum((num(row.get("win_probability")) or 0) / 100.0 for row in schedule)
        ratings = {"net": prior.get("prior_net"), "offense": prior.get("prior_offense"), "defense": prior.get("prior_defense"), "tempo": prior.get("prior_tempo")}
        ratings["ranks"] = {key: rating_ranks[key].get(team_id) for key in rating_ranks}
        ratings["current_net"] = current_net.get(team_id)
        ratings["current_rank"] = current_ranks.get(team_id)
        ratings["movement_since_preseason"] = round(current_net[team_id] - float(num(prior.get("prior_net")) or 0), 2) if current_net.get(team_id) is not None else None
        ratings["rank_movement_since_preseason"] = rating_ranks["net"].get(team_id) - current_ranks.get(team_id) if current_net.get(team_id) is not None and rating_ranks["net"].get(team_id) and current_ranks.get(team_id) else None
        core = sorted(rotation, key=lambda row: -(num(row.get("projected_minutes")) or 0))[:5]
        resume = resume_profile(schedule, current_ranks, current_or_prior_net, len(prior_rows))
        dossiers.append({
            "team_id": prior.get("team_id"), "team": prior.get("team"), "conference": prior.get("conference"),
            "ratings": ratings, "record": profile.get("record"), "four_factors": prior.get("prior_four_factors"),
            "shot_profile": (profile.get("shot_profile") if int((profile.get("shot_profile") or {}).get("tracked_shots") or 0) >= 25 else (profile.get("preseason_prior") or {}).get("shot_profile")),
            "personnel": prior.get("personnel"), "continuity": {"returning_minutes_pct": prior.get("returning_minutes_pct"), "source": prior.get("continuity_source")},
            "roster_quality": {"top_eight_average": roster_scores.get(team_id), "rank": roster_ranks.get(team_id), "rated_rotation_players": len([row for row in rotation if num(row.get("thi_impact")) is not None])},
            "projected_core_lineup": {"players": core, "combined_impact": round(sum(num(row.get("thi_impact")) or 0 for row in core), 1), "state": "projected_rotation_not_observed_lineup"},
            "schedule_strength": {"average_opponent_thi_net": round(statistics.mean(opponent_nets), 3) if opponent_nets else None, "nonconference_average_opponent_thi_net": round(statistics.mean(nc_opponent_nets), 3) if nc_opponent_nets else None, "scheduled_games": len(schedule)},
            "forecast": {"expected_wins_in_window": round(expected_wins, 2), "games_in_window": len(schedule)},
            "resume": resume,
            "rotation": rotation, "schedule_window": schedule,
            "recent_games": sorted(recent_by_team.get(team_id, []), key=lambda row: str(row.get("start_date") or ""), reverse=True)[:10],
            "home_court": hca_map.get(team_id),
        })
    gate = model.get("promotion_gate") or {}
    gate_checks = gate.get("checks") or {}
    validation_registry = {
        "gate_summary": {
            "eligible_for_public_projection_engine": bool(gate.get("eligible_for_public_projection_engine")),
            "passed": sum(bool(value) for value in gate_checks.values()),
            "total": len(gate_checks),
            "checks": gate_checks,
        },
        "factors": [
            {"factor": "Opponent-adjusted team efficiency", "status": "active", "model_usage": "projection_input", "evidence": "Chronological team state built from possessions completed before tipoff."},
            {"factor": "Tempo and Four Factors", "status": "active", "model_usage": "projection_input", "evidence": "Regressed preseason priors transition into opponent-adjusted current-season observations."},
            {"factor": "Program-specific home-court effect", "status": "active", "model_usage": "projection_input", "evidence": f"Five-season regularized estimates shrink toward a {hca_national:.2f}-point national mean; neutral sites receive zero."},
            {"factor": "Roster continuity and personnel", "status": "active_prior", "model_usage": "preseason_prior", "evidence": "Verified returners, recruiting and matched transfer production shape the opening prior."},
            {"factor": "Market disagreement", "status": "evaluation_only", "model_usage": "signal_and_accountability", "evidence": "Lines define signals, ATS grades and CLV; market prices do not fit the team-strength model."},
            {"factor": "Rest and situational flags", "status": "research_only", "model_usage": "display_only", "evidence": "Back-to-back, short-rest, lookahead, letdown and bounce-back states require incremental walk-forward validation."},
            {"factor": "Totals signal", "status": "withheld", "model_usage": "no_public_play", "evidence": "Independent totals promotion checks have not cleared."},
            {"factor": "Injuries and availability", "status": "unavailable", "model_usage": "no_adjustment", "evidence": "Requires a verified timestamped availability feed and auditable player-value translation."},
            {"factor": "Travel mileage and time zones", "status": "unavailable", "model_usage": "no_adjustment", "evidence": "Requires verified team origin, venue coordinates and chronological travel data."},
            {"factor": "Four Factor home/road profile", "status": "descriptive", "model_usage": "explanation_only", "evidence": "Home/road eFG%, free-throw rate and opponent-turnover splits explain the court profile and are not double-counted."},
        ],
    }
    return {
        "meta": {
            "version": VERSION, "season": priors.get("meta", {}).get("season"), "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "methodology": "THI uses regressed preseason priors, roster continuity and personnel quality, possession-based opponent-adjusted efficiency, Four Factors, pace, regularized program-specific home-court effects and chronological walk-forward updates. Market prices remain evaluation fields. Situational flags are displayed as research context until each feature clears out-of-sample validation.",
            "inspiration_note": "Away-from-home performance, record quality, quadrant-style records, rating movement and recent form are THI calculations inspired by useful public dossier concepts; no external proprietary rating is copied or used as a model input.",
            "player_projection_policy": "Qualified prior production receives per-game counting-stat projections; unverified statistical profiles receive role and impact context only.",
            "home_court_policy": "Program effects use five seasons of conference games, recency weighting and shrinkage toward the national mean; neutral-site games receive zero.",
            "situational_policy": "Rest, back-to-back, lookahead and result-response flags are research context only. Injury and travel adjustments remain unavailable until verified feeds and out-of-sample validation exist.",
            "market_policy": "Market prices are comparison and accountability fields, never predictive features.",
        },
        "home_court": {"national_points": hca_national, "team_specific_status": "active_regularized", "neutral_site_points": 0.0, "programs": home_court.get("teams") or [], "methodology": (home_court.get("meta") or {}).get("methodology")},
        "player_projections": player_rows, "team_rotations": rotations, "game_context": game_context,
        "validation_registry": validation_registry,
        "market_board": market_rows, "market_summary": tracking.get("summary") or {}, "team_dossiers": dossiers,
    }

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
    hca_path = root/"home_court_advantage.json"
    payload = build_suite(load(root/"team_profiles.json"), load(root/"model/current_priors.json"), load(root/"player_ratings.json"), load(root/"projection_board.json"), load(root/"model_tracking.json"), load(root/"model/model_card.json"), load(hca_path) if hca_path.exists() else None)
    write(args.output, payload); print(f"{VERSION}: {len(payload['player_projections'])} players, {len(payload['team_dossiers'])} dossiers")

if __name__ == "__main__": main()
