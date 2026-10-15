#!/usr/bin/env python3
"""Build content-addressed versions for THI's static CBB assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-static-cache-manifest-v1.0"

CANDIDATES = [
    "data/cbb/team_profiles.json", "data/cbb/game_board.json", "data/cbb/foundation_status.json",
    "data/cbb/model/model_card.json", "data/cbb/model/current_priors.json", "data/cbb/model/display_power_ratings.json", "data/cbb/model/preseason_index_candidate.json", "data/cbb/frozen/preseason_power_2027.json", "data/cbb/frozen/preseason_sos_2027.json", "data/cbb/home_court_advantage.json",
    "data/cbb/history/manifest.json", "data/cbb/projection_board.json", "data/cbb/play_style.json",
    "data/cbb/matchup_engine.json", "data/cbb/intelligence_suite.json", "data/cbb/model_tracking.json",
    "data/cbb/bracketology.json", "data/cbb/research/model_v02_challenger.json", "data/cbb/game_day_readiness.json",
    "data/cbb/operations_context.json", "data/cbb/platform_health.json", "data/cbb/market_snapshots.json",
    "data/cbb/market_contract.json", "data/cbb/player_ratings.json", "data/trends_lab.json",
    "data/variance/prospective_tracker.json", "data/market/rlm_monitor.json", "data/reports/public_backtest_scorecard.json",
]

HOT_NAMES = {"game_board.json", "projection_board.json", "market_snapshots.json", "market_contract.json", "rlm_monitor.json", "prospective_tracker.json"}


def build_manifest(root: Path = ROOT) -> dict[str, Any]:
    assets: dict[str, Any] = {}
    pairs: list[str] = []
    for relative in CANDIDATES:
        path = root / relative
        if not path.exists():
            continue
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()[:16]
        ttl = 60 if path.name in HOT_NAMES else 3600
        assets[relative] = {"version": digest, "bytes": len(content), "ttl_seconds": ttl, "freshness_class": "live_board" if ttl == 60 else "research"}
        pairs.append(f"{relative}:{digest}")
    build_id = hashlib.sha256("\n".join(pairs).encode()).hexdigest()[:20]
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "build_id": build_id,
            "asset_count": len(assets),
            "policy": "Asset versions change only when file contents change; live boards expire after 60 seconds and research assets after one hour.",
        },
        "assets": assets,
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
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "data/cbb/cache_manifest.json")
    args = parser.parse_args()
    payload = build_manifest(args.root)
    atomic_write(args.output, payload)
    print(f"{VERSION}: {payload['meta']['asset_count']} assets · build {payload['meta']['build_id']}")


if __name__ == "__main__":
    main()
