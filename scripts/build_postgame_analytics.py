#!/usr/bin/env python3
"""
THE HAMMER INDEX
build_postgame_analytics.py

Canonical postgame analytics builder for The Hammer Index.

Builds a retrospective per-game package for every FINAL in data/results.json
using the public SportsDataverse/cfbfastR 2026 play-by-play parquet.

CANONICAL POSTGAME METRICS
- EPA/play and total EPA
- Pass and rush EPA
- Pass and rush success rates
- Explosive-play rate and EPA dependency
- Standard-down and passing-down EPA/success
- Early-down and third/fourth-down performance
- Fourth-down attempts, success rate, and EPA
- Sack rate allowed
- Stuff rate allowed
- TFL rate allowed
- Drive efficiency and drive success rate
- Three-and-out rate
- Scoring-opportunity efficiency
- Red-zone trips and points per trip
- Red-zone overperformance
- Average starting field position
- Turnover EPA impact
- Garbage-time share
- EPA volatility
- Postgame Win Expectancy
- Adjusted Final Score
- THI Reality Check

SAFETY
- No CFBD calls.
- Does not modify Model A.
- Does not rewrite frozen pregame projections.
- Every final receives a postgame record.
- If matching PBP has not arrived yet, the record is pending and automatically
  retried by the existing settlement workflow.
- Postgame Win Expectancy / Adjusted Final Score / Red-Zone Overperformance are
  explicitly BETA until historical calibration is completed.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = ROOT / "data" / "results.json"
OUTPUT_PATH = ROOT / "data" / "postgame_analytics.json"

YEAR = int(os.getenv("CFB_SEASON", "2026"))

PBP_URL = (
    "https://raw.githubusercontent.com/sportsdataverse/"
    f"cfbfastR-cfb-data/main/cfb/pbp/parquet/play_by_play_{YEAR}.parquet"
)

PENDING_RETRY_MINUTES = 15
RED_ZONE_EXPECTED_POINTS_PER_TRIP_BETA = 4.7

SESSION = requests.Session()
SESSION.headers.update(
    {
        "Accept": "*/*",
        "User-Agent": "the-hammer-index-postgame/2.0",
    }
)


# =============================================================================
# BASIC HELPERS
# =============================================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return payload if isinstance(payload, dict) else fallback


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def game_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Accept both the original list schema and the keyed canonical schema."""
    games = payload.get("games") or []
    if isinstance(games, dict):
        games = games.values()
    return [game for game in games if isinstance(game, dict)]


def index_games(games: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(game["game_id"]): game
        for game in games
        if game.get("game_id")
