"""
CFB ANALYTICS
build_projections.py

Production projection engine.

Builds:
    data/schedule.json
    data/odds.json
    data/projections.json

Production rules:
- Strict FBS school matching for CFBD schedules
- Team-specific 2026 HFA; neutral-site HFA = 0.0
- Historical leakage-safe rating-to-points production scale
- Current SP+ regression retained as diagnostic only
- Live matchup adjustments require comparable samples on both FBS teams
- Multi-book median market consensus with outlier rejection
- Odds participants are resolved against the actual FBS + scheduled FCS universe
- FBS-v-FCS games receive a transparent generic FCS fallback spread/win probability
- FCS fallback does not invent an opponent-specific model total
- Full schedules include FCS opponents for season-win distributions
"""

import json
import math
import os
import statistics
import sys
import time
import unicodedata
from datetime import datetime

import requests


# =============================================================================
# CONFIG
# =============================================================================

YEAR = 2026

CFBD_BASE = "https://api.collegefootballdata.com"
ODDS_BASE = "https://api.the-odds-api.com/v4"

METRICS_PATH = "data/cfb_metrics.json"
HFA_PATH = "data/hfa_2026.json"
SCHEDULE_PATH = "data/schedule.json"
ODDS_PATH = "data/odds.json"
PROJECTIONS_PATH = "data/projections.json"

MAX_MATCHUP_ADJUSTMENT = 3.0
BASE_TOTAL = 52.5

MIN_LIVE_PLAYS = 35
MIN_LIVE_PASS_PLAYS = 15
MIN_LIVE_RUSH_PLAYS = 15

WIN_PROB_STD_DEV = 16.0

MARKET_SPREAD_OUTLIER_DISTANCE = 3.0
MARKET_TOTAL_OUTLIER_DISTANCE = 4.0
MARKET_MIN_BOOKS_FOR_FILTERING = 3

HISTORICAL_SCALE_BY_YEAR = {
    "2022": 11.194,
    "2023": 10.392,
    "2024": 10.162,
    "2025": 9.950,
}
HISTORICAL_RATING_SCALE = (
    sum(HISTORICAL_SCALE_BY_YEAR.values())
    / len(HISTORICAL_SCALE_BY_YEAR)
)

# Generic FCS fallback.
# This is NOT an opponent-specific FCS rating.
FCS_BASE_MARGIN = 24.0
FCS_POWER_MULTIPLIER = 0.60
FCS_MIN_WIN_PROB = 0.65
FCS_MAX_WIN_PROB = 0.995


# =============================================================================
# KEYS + GENERAL HELPERS
# =============================================================================

def clean_api_key(raw):
    if raw is None:
        return ""

    key = str(raw).strip()

    if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
        key = key[1:-1].strip()
