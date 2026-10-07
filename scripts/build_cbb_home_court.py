#!/usr/bin/env python3
"""Estimate team-specific CBB home-court value with multi-season shrinkage.

The point estimate is a regularized team/season margin model. Team-season strength
and each program's campus effect are solved together, so a strong home record is
not mistaken for a strong arena. Four Factor splits are descriptive explanations
and do not add a second adjustment to the projection.
"""

from __future__ import annotations

import argparse, gzip, json, math, statistics, tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-home-court-v1.0"
HALF_LIFE_SEASONS = 2.0
HCA_PRIOR_GAMES = 35.0
STRENGTH_PRIOR_GAMES = 0.25


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def weighted_mean(rows: list[tuple[float, float]]) -> float | None:
    total_weight = sum(weight for _value, weight in rows)
    return sum(value * weight for value, weight in rows) / total_weight if total_weight else None


def load_games(history_dir: Path, seasons: int = 5) -> tuple[list[dict[str, Any]], list[int]]:
    manifest = json.loads((history_dir / "manifest.json").read_text())
    available = sorted(int(row["season"]) for row in manifest.get("seasons") or [])
    selected = available[-seasons:]
    games: list[dict[str, Any]] = []
    for season in selected:
        with gzip.open(history_dir / f"season_{season}.json.gz", "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        for game in payload.get("games") or []:
            margin = finite((game.get("outcome") or {}).get("home_margin"))
            if game.get("neutral_site") or margin is None or str(game.get("season_type") or "regular") != "regular":
                continue
            home_id, away_id = game.get("home_team_id"), game.get("away_team_id")
            if home_id is None or away_id is None:
                continue
            games.append({**game, "season": season, "margin": margin})
    return games, selected


def fit_home_court(games: list[dict[str, Any]], seasons: list[int]) -> tuple[float, dict[str, float], dict[tuple[int, str], float], float]:
    latest = max(seasons)
    season_weight = {season: 0.5 ** ((latest - season) / HALF_LIFE_SEASONS) for season in seasons}
    team_ids = {str(game[side]) for game in games for side in ("home_team_id", "away_team_id")}
    strength = {(season, team_id): 0.0 for season in seasons for team_id in team_ids}
    raw_home_margins = [(game["margin"], season_weight[game["season"]]) for game in games]
    national = max(1.0, min(5.0, weighted_mean(raw_home_margins) or 3.0))
    home_effect = {team_id: national for team_id in team_ids}

    for _iteration in range(35):
        sums: dict[tuple[int, str], float] = defaultdict(float)
        weights: dict[tuple[int, str], float] = defaultdict(float)
        for game in games:
            season = game["season"]; weight = season_weight[season]
            home, away = str(game["home_team_id"]), str(game["away_team_id"])
            sums[(season, home)] += weight * (game["margin"] - home_effect[home] + strength[(season, away)])
            sums[(season, away)] += weight * (strength[(season, home)] + home_effect[home] - game["margin"])
            weights[(season, home)] += weight; weights[(season, away)] += weight
        for key in strength:
            strength[key] = sums[key] / (weights[key] + STRENGTH_PRIOR_GAMES)
        for season in seasons:
            values = [(strength[(season, team_id)], weights[(season, team_id)]) for team_id in team_ids if weights[(season, team_id)] > 0]
            center = weighted_mean(values) or 0.0
            for team_id in team_ids:
                strength[(season, team_id)] -= center

        residuals = []
        by_home: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for game in games:
            season = game["season"]; weight = season_weight[season]
            home, away = str(game["home_team_id"]), str(game["away_team_id"])
            residual = game["margin"] - (strength[(season, home)] - strength[(season, away)])
            residuals.append((residual, weight)); by_home[home].append((residual, weight))
        ordered = sorted(residuals, key=lambda row: row[0])
        trim = ordered[max(0, len(ordered)//50):len(ordered)-max(0, len(ordered)//50)] or ordered
        national = max(1.0, min(5.0, weighted_mean(trim) or national))
        for team_id in team_ids:
            rows = by_home.get(team_id, [])
            total_weight = sum(weight for _value, weight in rows)
            estimate = (sum(value * weight for value, weight in rows) + HCA_PRIOR_GAMES * national) / (total_weight + HCA_PRIOR_GAMES)
            home_effect[team_id] = max(0.5, min(5.5, estimate))

    errors = []
    for game in games:
        season = game["season"]; home, away = str(game["home_team_id"]), str(game["away_team_id"])
        errors.append(game["margin"] - (strength[(season, home)] - strength[(season, away)] + home_effect[home]))
    residual_sd = statistics.pstdev(errors) if len(errors) > 1 else 11.0
    return national, home_effect, strength, residual_sd


def factor_splits(games: list[dict[str, Any]], current_ids: set[str]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for game in games:
        home_id, away_id = str(game["home_team_id"]), str(game["away_team_id"])
        home, away = game.get("home") or {}, game.get("away") or {}
        if home_id in current_ids:
            for key in ("effective_fg_pct", "free_throw_rate"):
                value = finite(home.get(key))
                if value is not None: buckets[home_id][f"home_{key}"].append(value)
            value = finite(away.get("turnover_pct"))
            if value is not None: buckets[home_id]["opponent_turnover_at_home"].append(value)
        if away_id in current_ids:
            for key in ("effective_fg_pct", "free_throw_rate"):
                value = finite(away.get(key))
                if value is not None: buckets[away_id][f"road_{key}"].append(value)
            value = finite(home.get("turnover_pct"))
            if value is not None: buckets[away_id]["opponent_turnover_on_road"].append(value)

    output = {}
    for team_id, row in buckets.items():
        mean = lambda key: statistics.fmean(row[key]) if row.get(key) else None
        home_n = len(row.get("home_effective_fg_pct", [])); road_n = len(row.get("road_effective_fg_pct", []))
        shrink = min(home_n, road_n) / (min(home_n, road_n) + 30.0)
        delta = lambda home_key, road_key: round(((mean(home_key) or 0) - (mean(road_key) or 0)) * shrink, 2) if mean(home_key) is not None and mean(road_key) is not None else None
        output[team_id] = {
            "home_games": home_n, "road_games": road_n,
            "home_efg_delta_pct_points": delta("home_effective_fg_pct", "road_effective_fg_pct"),
            "home_free_throw_rate_delta": delta("home_free_throw_rate", "road_free_throw_rate"),
            "opponent_turnover_delta_pct_points": delta("opponent_turnover_at_home", "opponent_turnover_on_road"),
            "usage": "descriptive_explanation_only",
        }
    return output


def build(history_dir: Path, priors_path: Path) -> dict[str, Any]:
    games, seasons = load_games(history_dir)
    model_games = [game for game in games if game.get("conference_game")]
    priors = json.loads(priors_path.read_text())
    current = {str(row.get("team_id")): row for row in priors.get("teams") or []}
    national, effects, _strength, residual_sd = fit_home_court(model_games, seasons)
    factors = factor_splits(games, set(current))
    counts = defaultdict(int)
    latest_counts = defaultdict(int)
    latest = max(seasons)
    for game in model_games:
        team_id = str(game["home_team_id"]); counts[team_id] += 1
        if game["season"] == latest: latest_counts[team_id] += 1
    teams = []
    for team_id, prior in current.items():
        sample = counts[team_id]
        effective_sample = sum((0.5 ** ((latest-game["season"])/HALF_LIFE_SEASONS)) for game in model_games if str(game["home_team_id"]) == team_id)
        points = effects.get(team_id, national)
        standard_error = residual_sd / math.sqrt(effective_sample + HCA_PRIOR_GAMES)
        state = "established" if sample >= 60 else "qualified" if sample >= 35 else "developing"
        tier = "elite" if points >= 4.25 else "strong" if points >= 3.5 else "above_average" if points >= 3.0 else "standard" if points >= 2.0 else "modest"
        teams.append({
            "team_id": prior.get("team_id"), "team": prior.get("team"), "conference": prior.get("conference"),
            "home_court_points": round(points, 2), "national_points": round(national, 2),
            "difference_from_national": round(points-national, 2), "tier": tier, "evidence_state": state,
            "sample": {"campus_games": sample, "latest_season_games": latest_counts[team_id], "effective_weighted_games": round(effective_sample, 1)},
            "uncertainty": {"standard_error": round(standard_error, 2), "low_95": round(max(0.5, points-1.96*standard_error), 2), "high_95": round(min(5.5, points+1.96*standard_error), 2)},
            "four_factor_home_road": factors.get(team_id, {"usage":"descriptive_explanation_only"}),
        })
    teams.sort(key=lambda row: (-row["home_court_points"], row["team"]))
    return {
        "meta": {
            "version": VERSION, "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
            "seasons": seasons, "game_count": len(model_games), "all_campus_games_for_factor_splits": len(games), "national_points": round(national,2),
            "methodology": "Alternating regularized least squares estimates team-season strength and program-specific campus value together from conference games, reducing buy-game schedule bias. Five seasons receive exponential recency weighting; team effects shrink toward the national mean.",
            "projection_policy": "Team-specific point values replace the national effect on campus; neutral-site games receive zero. Four Factor splits explain the observed home/road profile and are not double-counted.",
            "half_life_seasons": HALF_LIFE_SEASONS, "home_effect_prior_games": HCA_PRIOR_GAMES,
        },
        "teams": teams,
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",",":"), allow_nan=False); handle.write("\n"); temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-dir", type=Path, default=ROOT/"data/cbb/history")
    parser.add_argument("--priors", type=Path, default=ROOT/"data/cbb/model/current_priors.json")
    parser.add_argument("--output", type=Path, default=ROOT/"data/cbb/home_court_advantage.json")
    args = parser.parse_args(); payload = build(args.history_dir, args.priors); atomic_write(args.output, payload)
    print(f"{VERSION}: {len(payload['teams'])} teams from {payload['meta']['game_count']} campus games")


if __name__ == "__main__": main()
