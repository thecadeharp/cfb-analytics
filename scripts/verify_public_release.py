#!/usr/bin/env python3
"""Fail-fast public deployment canary for THI's core CFB/CBB contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen


PATHS = {
    "cbb_power": "data/cbb/model/display_power_ratings.json",
    "cbb_priors": "data/cbb/model/current_priors.json",
    "cbb_health": "data/cbb/platform_health.json",
    "cbb_roster_audit": "data/cbb/roster_audit.json",
    "cbb_players": "data/cbb/player_ratings.json",
    "cbb_board": "data/cbb/projection_board.json",
    "cfb_board": "data/projections.json",
    "operations": "data/reports/operations_readiness.json",
}


def fetch_json(base_url: str, relative: str) -> dict:
    url = f"{base_url.rstrip('/')}/{relative}"
    request = Request(url, headers={"User-Agent": "THI public-release-canary/1.0", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"{relative} returned HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def load_local(root: Path, relative: str) -> dict:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def verify(payloads: dict[str, dict]) -> list[str]:
    checks: list[tuple[bool, str]] = []
    power = payloads["cbb_power"]
    priors = payloads["cbb_priors"]
    health = payloads["cbb_health"]
    roster = payloads["cbb_roster_audit"]
    players = payloads["cbb_players"]
    cbb_games = payloads["cbb_board"].get("games") or []
    cfb_games = payloads["cfb_board"].get("games") or []
    operations = payloads["operations"]
    checks.extend([
        (power.get("meta", {}).get("version") == "thi-cbb-display-power-v2.0", "CBB Power v2 is published"),
        (len(power.get("teams") or []) >= 300, "CBB power board has national coverage"),
        (str(power.get("meta", {}).get("model_usage", "")).startswith("display_only"), "CBB power remains isolated from Model A"),
        (len(priors.get("teams") or []) >= 300, "CBB production priors remain available"),
        (len(cbb_games) >= 300, "CBB projection board is populated"),
        (len(cfb_games) >= 50, "CFB projection board is populated"),
        (health.get("meta", {}).get("status") in {"healthy", "attention_required"}, "CBB health contract is readable"),
        (operations.get("meta", {}).get("version") == "thi-operations-readiness-v1.0", "Operations report is current schema"),
    ])
    neutral_ok = all(
        float(((((game.get("projection") or {}).get("matchup_context") or {}).get("home_court") or {}).get("points") or 0)) == 0
        for game in cbb_games if game.get("neutral_site")
    )
    checks.append((neutral_ok, "All CBB neutral-site games have zero home-court input"))
    audit_status = roster.get("meta", {}).get("status")
    published = int((health.get("coverage") or {}).get("published_roster_players") or 0)
    checks.append((audit_status == "passed" or published == 0, "Failed roster audit cannot publish player data"))
    checks.append((audit_status == "passed" or len(players.get("players") or []) == 0, "Failed roster audit strips the public player payload"))
    failures = [label for passed, label in checks if not passed]
    if failures:
        raise RuntimeError("Public release canary failed: " + "; ".join(failures))
    return [label for passed, label in checks if passed]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://thehammerindex.com")
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    payloads = {
        key: load_local(args.root, relative) if args.root else fetch_json(args.base_url, relative)
        for key, relative in PATHS.items()
    }
    checks = verify(payloads)
    print(f"THI public release canary passed: {len(checks)} checks")


if __name__ == "__main__":
    main()
