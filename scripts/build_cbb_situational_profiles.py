#!/usr/bin/env python3
"""Build descriptive program-level CBB ATS splits from frozen historical games."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-program-situational-v1.0"


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def summarize(values: list[float]) -> dict[str, Any]:
    wins = sum(value > .01 for value in values)
    losses = sum(value < -.01 for value in values)
    pushes = len(values) - wins - losses
    decisions = wins + losses
    return {
        "games": len(values), "wins": wins, "losses": losses, "pushes": pushes,
        "cover_pct": round(100 * wins / decisions, 1) if decisions else None,
        "average_cover_margin": round(sum(values) / len(values), 2) if values else None,
        "sample_state": "established" if decisions >= 80 else "tracked" if decisions >= 40 else "developing" if decisions >= 15 else "limited",
    }


def add(store: dict[str, list[float]], key: str, value: float) -> None:
    store[key].append(value)


def build(predictions: dict[str, Any], minimum_season: int = 2022) -> dict[str, Any]:
    programs: dict[str, dict[str, Any]] = {}
    for game in predictions.get("games") or []:
        if int(game.get("season") or 0) < minimum_season:
            continue
        spread = finite(game.get("market_home_spread"))
        margin = finite(game.get("actual_home_margin"))
        if spread is None or margin is None:
            continue
        home_cover = margin + spread
        for side, sign in (("home", 1.0), ("away", -1.0)):
            team_id = str(game.get(f"{side}_team_id"))
            team = game.get(f"{side}_team")
            if not team_id or team_id == "None":
                continue
            program = programs.setdefault(team_id, {"team_id": game.get(f"{side}_team_id"), "team": team, "segments": defaultdict(list)})
            segments = program["segments"]
            cover = sign * home_cover
            team_spread = spread if side == "home" else -spread
            rest = finite(game.get(f"{side}_rest_days"))
            opponent_rest = finite(game.get(f"{'away' if side == 'home' else 'home'}_rest_days"))
            add(segments, "overall", cover)
            add(segments, "neutral" if game.get("neutral_site") else side, cover)
            add(segments, "favorite" if team_spread < 0 else "underdog" if team_spread > 0 else "pickem", cover)
            add(segments, "conference" if game.get("conference_game") else "nonconference", cover)
            if rest is not None:
                add(segments, "back_to_back" if rest <= 1 else "two_days_rest" if rest == 2 else "three_plus_days_rest", cover)
            if rest is not None and opponent_rest is not None:
                add(segments, "rest_advantage" if rest > opponent_rest else "rest_disadvantage" if rest < opponent_rest else "equal_rest", cover)
    rows = []
    for program in programs.values():
        rows.append({
            "team_id": program["team_id"],
            "team": program["team"],
            "seasons": f"{minimum_season}–{max(int(row.get('season') or minimum_season) for row in predictions.get('games') or [])}",
            "splits": {key: summarize(values) for key, values in sorted(program["segments"].items())},
        })
    rows.sort(key=lambda row: str(row.get("team") or ""))
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "minimum_season": minimum_season,
            "policy": "Program-level historical ATS context only. These splits are not attributed to a coach, are not model inputs, and do not imply persistence.",
        },
        "teams": rows,
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
    parser.add_argument("--predictions", type=Path, default=ROOT / "data/cbb/model/walk_forward_predictions.json.gz")
    parser.add_argument("--minimum-season", type=int, default=2022)
    parser.add_argument("--output", type=Path, default=ROOT / "data/cbb/situational_profiles.json")
    args = parser.parse_args()
    with gzip.open(args.predictions, "rt", encoding="utf-8") as handle:
        predictions = json.load(handle)
    payload = build(predictions, args.minimum_season)
    atomic_write(args.output, payload)
    print(f"{VERSION}: {len(payload['teams'])} program profiles")


if __name__ == "__main__":
    main()
