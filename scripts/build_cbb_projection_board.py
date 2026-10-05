#!/usr/bin/env python3
"""Build the public THI CBB projection board from validated research artifacts."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-projection-board-v0.3"
SETTLED_MIN_GAMES = 6
SPREAD_SIGNAL_EDGE = 5.0


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def predict(features: dict[str, float], model: dict[str, Any]) -> float:
    value = float(model["coefficients"][0])
    for coefficient, name in zip(model["coefficients"][1:], model["feature_names"]):
        feature = features.get(name, float(model["means"][name]))
        value += float(coefficient) * (feature - float(model["means"][name])) / float(model["scales"][name])
    return value


def feature_contributions(features: dict[str, float], model: dict[str, Any], limit: int = 6) -> list[dict[str, Any]]:
    rows = []
    for coefficient, name in zip(model["coefficients"][1:], model["feature_names"]):
        feature = features.get(name, float(model["means"][name]))
        points = float(coefficient) * (feature - float(model["means"][name])) / float(model["scales"][name])
        rows.append({"feature": name, "value": round(feature, 3), "margin_points": round(points, 2)})
    rows.sort(key=lambda row: (-abs(row["margin_points"]), row["feature"]))
    return rows[:limit]


def personnel_features(home: dict[str, Any], away: dict[str, Any], early_weight: float) -> dict[str, float]:
    hr, ar = (home.get("personnel") or {}).get("recruiting") or {}, (away.get("personnel") or {}).get("recruiting") or {}
    ht, at = (home.get("personnel") or {}).get("transfers") or {}, (away.get("personnel") or {}).get("transfers") or {}

    def value(block: dict[str, Any], key: str) -> float:
        return finite(block.get(key)) or 0.0

    return {
        "personnel_recruit_rating": early_weight * (value(hr, "team_rating") - value(ar, "team_rating")),
        "personnel_transfer_minutes": early_weight * (math.log1p(value(ht, "prior_minutes")) - math.log1p(value(at, "prior_minutes"))),
        "personnel_transfer_points": early_weight * (math.log1p(value(ht, "prior_points")) - math.log1p(value(at, "prior_points"))),
        "personnel_transfer_rating": early_weight * (value(ht, "mean_incoming_rating") - value(at, "mean_incoming_rating")),
        "personnel_recruit_count": early_weight * (value(hr, "class_player_count") - value(ar, "class_player_count")),
        "personnel_transfer_count": early_weight * (value(ht, "incoming_count") - value(at, "incoming_count")),
    }


def team_state(profile: dict[str, Any], prior: dict[str, Any], league_tempo: float) -> dict[str, Any]:
    games = int((profile.get("record") or {}).get("games") or 0)
    current = profile.get("current_efficiency") or {}
    adjusted = current.get("adjusted") or {}
    current_ready = bool(profile.get("sample_ready")) and finite(adjusted.get("offense")) is not None and finite(adjusted.get("defense")) is not None
    factors = profile.get("four_factor_edges") or {}
    return {
        "team_id": profile.get("team_id"),
        "team": profile.get("team"),
        "games": games,
        "offense": finite(adjusted.get("offense")) if current_ready else finite(prior.get("prior_offense")),
        "defense": finite(adjusted.get("defense")) if current_ready else finite(prior.get("prior_defense")),
        "tempo": finite(current.get("pace_per_40")) if current_ready else finite(prior.get("prior_tempo")) or league_tempo,
        "rating_source": "current_adjusted" if current_ready else "preseason_prior",
        "factors": {key: finite(value) for key, value in factors.items()},
        "personnel": prior.get("personnel") or {},
    }


def matchup_features(game: dict[str, Any], home: dict[str, Any], away: dict[str, Any], league_efficiency: float) -> dict[str, float]:
    pace = 2.0 / ((1.0 / max(home["tempo"], 1.0)) + (1.0 / max(away["tempo"], 1.0)))
    home_eff = clip(home["offense"] + away["defense"] - league_efficiency, 70.0, 145.0)
    away_eff = clip(away["offense"] + home["defense"] - league_efficiency, 70.0, 145.0)
    raw_home = pace * home_eff / 100.0
    raw_away = pace * away_eff / 100.0
    raw_margin = raw_home - raw_away
    minimum_games = min(home["games"], away["games"])
    early_weight = 1.0 / (1.0 + minimum_games)
    home_court = 0.0 if game.get("neutral_site") else 1.0

    def factor_edge(key: str) -> float:
        left, right = home["factors"].get(key), away["factors"].get(key)
        return left - right if left is not None and right is not None else 0.0

    features = {
        "raw_margin": raw_margin,
        "raw_margin_curve": raw_margin * abs(raw_margin),
        "raw_total": raw_home + raw_away,
        "home_court": home_court,
        "experience_diff": math.log1p(home["games"]) - math.log1p(away["games"]),
        "experience_sum": math.log1p(home["games"]) + math.log1p(away["games"]),
        "early_strength_margin": raw_margin * early_weight,
        "early_home": home_court * early_weight,
        "nonconference_home": home_court * (0.0 if game.get("conference_game") else 1.0),
        "projected_pace": pace,
        "efg_edge": factor_edge("effective_fg_pct"),
        "turnover_edge": factor_edge("turnover_pct"),
        "rebound_edge": factor_edge("offensive_rebound_pct"),
        "free_throw_edge": factor_edge("free_throw_rate"),
    }
    features.update(personnel_features(home, away, early_weight))
    return features


def sample_state(minimum_games: int) -> str:
    if minimum_games == 0:
        return "preseason"
    if minimum_games <= 2:
        return "early_sample"
    if minimum_games <= 5:
        return "developing_sample"
    return "tracked_sample"


def spread_signal_tier(edge: float | None) -> str:
    if edge is None:
        return "no_line"
    absolute = abs(edge)
    if absolute <= 2.5:
        return "aligned"
    if absolute <= 5.0:
        return "small"
    if absolute <= 7.0:
        return "play"
    if absolute <= 10.0:
        return "material"
    return "outlier"


def total_research_tier(edge: float | None) -> str:
    if edge is None or abs(edge) < 4.0:
        return "none"
    return "watch" if abs(edge) < 7.0 else "play_threshold"


def build_board(
    games_payload: dict[str, Any],
    profiles_payload: dict[str, Any],
    priors_payload: dict[str, Any],
    model_card: dict[str, Any],
    existing_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model_version = model_card.get("meta", {}).get("model_version")
    if model_version != "thi-cbb-walk-forward-v0.6-research":
        raise RuntimeError("projection board requires thi-cbb-walk-forward-v0.6-research")
    if priors_payload.get("meta", {}).get("model_version") != model_version:
        raise RuntimeError("current priors and model card versions do not match")

    priors = {str(row.get("team_id")): row for row in priors_payload.get("teams") or []}
    profiles = {str(row.get("team_id")): row for row in profiles_payload.get("teams") or []}
    tempos = [finite(row.get("prior_tempo")) for row in priors.values()]
    tempos = [value for value in tempos if value is not None]
    league_tempo = statistics.median(tempos) if tempos else 68.0
    efficiencies = [finite(row.get(key)) for row in priors.values() for key in ("prior_offense", "prior_defense")]
    efficiencies = [value for value in efficiencies if value is not None]
    league_efficiency = statistics.median(efficiencies) if efficiencies else 100.0
    margin_model = model_card["models"]["margin"]
    total_model = model_card["models"]["total"]
    residual_sd = float(model_card["models"]["margin_residual_sd"])
    output = []
    existing = {
        str(row.get("game_id")): row
        for row in (existing_payload or {}).get("games") or []
        if isinstance(row, dict) and row.get("projection")
    }
    seen: set[str] = set()

    for game in games_payload.get("games") or []:
        game_id = str(game.get("game_id"))
        seen.add(game_id)
        status = str(game.get("status") or "").lower().replace("_", "")
        if status != "scheduled":
            frozen = existing.get(game_id)
            if frozen:
                output.append({**frozen, **game, "market": frozen.get("market"), "projection": frozen["projection"]})
            continue
        home_id = str((game.get("home") or {}).get("team_id"))
        away_id = str((game.get("away") or {}).get("team_id"))
        if home_id not in profiles or away_id not in profiles or home_id not in priors or away_id not in priors:
            continue
        home = team_state(profiles[home_id], priors[home_id], league_tempo)
        away = team_state(profiles[away_id], priors[away_id], league_tempo)
        if home["offense"] is None or home["defense"] is None or away["offense"] is None or away["defense"] is None:
            continue
        features = matchup_features(game, home, away, league_efficiency)
        margin = predict(features, margin_model)
        total = predict(features, total_model)
        home_points = (total + margin) / 2.0
        away_points = (total - margin) / 2.0
        probability = clip(0.5 * (1.0 + math.erf((margin / max(residual_sd, 1.0)) / math.sqrt(2.0))), 0.001, 0.999)
        minimum_games = min(home["games"], away["games"])
        state = sample_state(minimum_games)
        market = game.get("market") or {}
        market_spread = finite(market.get("consensus_home_spread"))
        edge = margin + market_spread if market_spread is not None else None
        market_total = finite(market.get("consensus_total"))
        total_edge = total - market_total if market_total is not None else None
        signal_eligible = state == "tracked_sample" and edge is not None and abs(edge) >= SPREAD_SIGNAL_EDGE
        home_quality = home["offense"] - home["defense"]
        away_quality = away["offense"] - away["defense"]
        watchability = round(clip(62.0 - abs(margin) * 2.0 + max(0.0, (home_quality + away_quality) / 2.0), 1.0, 99.0))
        output.append({
            **game,
            "projection": {
                "model_version": model_version,
                "home_points": round(home_points, 1),
                "away_points": round(away_points, 1),
                "home_margin": round(margin, 1),
                "total": round(total, 1),
                "home_win_probability": round(100 * probability, 1),
                "projected_possessions": round(features["projected_pace"], 1),
                "sample_state": state,
                "model_input_label": "prior_based" if state == "preseason" else state,
                "minimum_team_games": minimum_games,
                "home_rating_source": home["rating_source"],
                "away_rating_source": away["rating_source"],
                "spread_signal_eligible": signal_eligible,
                "spread_edge": round(edge, 1) if edge is not None else None,
                "spread_signal_tier": spread_signal_tier(edge),
                "signal_confidence": "developing" if signal_eligible else "research",
                "totals_signal_eligible": False,
                "total_edge": round(total_edge, 1) if total_edge is not None else None,
                "total_research_tier": total_research_tier(total_edge),
                "watchability_score": watchability,
                "game_classification": "conference" if game.get("conference_game") else "nonconference",
                "matchup_context": {
                    "home": {"offense": round(home["offense"], 2), "defense": round(home["defense"], 2), "tempo": round(home["tempo"], 2), "games": home["games"], "rating_source": home["rating_source"]},
                    "away": {"offense": round(away["offense"], 2), "defense": round(away["defense"], 2), "tempo": round(away["tempo"], 2), "games": away["games"], "rating_source": away["rating_source"]},
                    "margin_drivers": feature_contributions(features, margin_model),
                },
            },
        })

    for game_id, frozen in existing.items():
        frozen_status = str(frozen.get("status") or "").lower().replace("_", "")
        if game_id not in seen and frozen_status in {"final", "completed", "complete"}:
            output.append(frozen)

    output.sort(key=lambda row: (str(row.get("start_date") or ""), str(row.get("game_id") or "")))
    status_counts = {
        "upcoming": sum(str(row.get("status") or "").lower().replace("_", "") == "scheduled" for row in output),
        "live": sum(str(row.get("status") or "").lower().replace("_", "") in {"live", "inprogress", "halftime"} for row in output),
        "final": sum(str(row.get("status") or "").lower().replace("_", "") in {"final", "completed", "complete"} for row in output),
    }

    return {
        "meta": {
            "version": VERSION,
            "model_version": model_version,
            "season": games_payload.get("meta", {}).get("season"),
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "game_count": len(output),
            "status_counts": status_counts,
            "settled_minimum_games": SETTLED_MIN_GAMES,
            "spread_signal_minimum_edge": SPREAD_SIGNAL_EDGE,
            "spread_signal_policy": "Only tracked-sample games with at least a five-point model-versus-market disagreement are eligible.",
            "totals_signal_policy": "Withheld until totals validation clears its independent promotion gate.",
            "projection_state": "research projections; sample-gated spread signals",
        },
        "games": output,
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
    parser.add_argument("--games", type=Path, default=ROOT / "data" / "cbb" / "game_board.json")
    parser.add_argument("--profiles", type=Path, default=ROOT / "data" / "cbb" / "team_profiles.json")
    parser.add_argument("--priors", type=Path, default=ROOT / "data" / "cbb" / "model" / "current_priors.json")
    parser.add_argument("--model-card", type=Path, default=ROOT / "data" / "cbb" / "model" / "model_card.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "cbb" / "projection_board.json")
    args = parser.parse_args()
    existing_payload = json.loads(args.output.read_text()) if args.output.exists() else None
    payload = build_board(
        json.loads(args.games.read_text()),
        json.loads(args.profiles.read_text()),
        json.loads(args.priors.read_text()),
        json.loads(args.model_card.read_text()),
        existing_payload,
    )
    atomic_write(args.output, payload)
    print(f"{VERSION}: {payload['meta']['game_count']} frozen and upcoming games")


if __name__ == "__main__":
    main()
