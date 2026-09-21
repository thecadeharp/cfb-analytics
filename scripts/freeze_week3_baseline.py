#!/usr/bin/env python3
"""Create an immutable Week 1-3 Model A evidence package.

This script never edits projections, results, grading, or postgame analytics. It
only reads the existing ledgers and writes a compact, checksummed checkpoint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SNAPSHOTS = DATA / "snapshots"
FROZEN = DATA / "frozen"
REPORTS = DATA / "reports"

BASELINE_PATH = FROZEN / "2026_week3_modelA_baseline.json"
HASH_PATH = FROZEN / "2026_week3_modelA_baseline.sha256"
MANIFEST_PATH = FROZEN / "2026_week3_modelA_baseline_manifest.txt"
AUDIT_PATH = REPORTS / "week3_integrity_audit.json"


def verify_frozen_baseline() -> None:
    if not BASELINE_PATH.exists() or not HASH_PATH.exists():
        raise SystemExit("Frozen Week 3 baseline or checksum is missing.")
    expected = HASH_PATH.read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(BASELINE_PATH.read_bytes()).hexdigest()
    if expected != actual:
        raise SystemExit(
            "Frozen Week 3 baseline checksum mismatch: "
            f"expected {expected}, received {actual}."
        )
    print(f"Verified immutable Week 3 baseline: {actual}")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if isinstance(value, dict):
            rows.append(value)
    return rows


def game_key(row: dict[str, Any]) -> str:
    value = row.get("game_id") or row.get("game_key") or row.get("result_game_id")
    return str(value or "").strip()


TEAM_ALIASES = {
    "armywestpoint": "army",
    "fiu": "floridainternational",
    "flaintl": "floridainternational",
    "floridainternational": "floridainternational",
    "floridainternationaluniversity": "floridainternational",
    "flaatlantic": "floridaatlantic",
    "floridaatlantic": "floridaatlantic",
    "gasouthern": "georgiasouthern",
    "georgiasouthern": "georgiasouthern",
    "hawaii": "hawaii",
    "miamioh": "miamiohio",
    "miamiohio": "miamiohio",
    "middletenn": "middletennessee",
    "middletennessee": "middletennessee",
    "mississippist": "mississippistate",
    "mississippistate": "mississippistate",
    "ncstate": "northcarolinastate",
    "ncarolinast": "northcarolinastate",
    "olemiss": "mississippi",
    "niu": "northernillinois",
    "northernillinois": "northernillinois",
    "southfla": "southflorida",
    "southflorida": "southflorida",
    "jacksonvillest": "jacksonvillestate",
    "jacksonvillestate": "jacksonvillestate",
    "southernmiss": "southernmississippi",
    "ulmonroe": "ulmonroe",
    "ulm": "ulmonroe",
    "westernky": "westernkentucky",
    "westernkentucky": "westernkentucky",
}


def team_key(value: Any) -> str:
    key = re.sub(r"[^a-z0-9]+", "", str(value or "").lower().replace("university", ""))
    return TEAM_ALIASES.get(key, key)


def matchup_key(row: dict[str, Any]) -> tuple[int, tuple[str, str]]:
    away = row.get("away_team") or (row.get("away") or {}).get("team")
    home = row.get("home_team") or (row.get("home") or {}).get("team")
    return int(row.get("week") or 0), tuple(sorted((team_key(away), team_key(home))))


def iso_key(value: Any) -> str:
    return str(value or "9999-12-31T23:59:59Z")


def unique_counts(rows: list[dict[str, Any]], field: str) -> list[str]:
    counts = Counter(str(row.get(field) or "") for row in rows)
    return sorted(key for key, count in counts.items() if key and count > 1)


def main() -> None:
    projection_data = load_json(DATA / "projections.json", {})
    result_data = load_json(DATA / "results.json", {})
