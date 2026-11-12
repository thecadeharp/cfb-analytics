#!/usr/bin/env python3
"""Fail closed when a paid THI build still has unresolved source rights."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "config" / "commercial_sources.json"
ALLOWED = {"allowed_with_conditions", "allowed_build_time_only"}


def load_register(path: Path = REGISTER) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("sources"):
        raise ValueError("Commercial source register is empty")
    return payload


def active_blockers(payload: dict) -> list[dict]:
    return [
        row for row in payload["sources"]
        if row.get("active") is True and row.get("paywall_status") not in ALLOWED
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paywall", action="store_true", help="Enforce paid-launch rights gate")
    args = parser.parse_args()
    paid_build = args.paywall or os.environ.get("THI_PAYWALL_ENABLED", "").lower() in {"1", "true", "yes"}
    payload = load_register()
    blockers = active_blockers(payload)
    if paid_build and blockers:
        print("PAYWALL RIGHTS GATE: BLOCKED")
        for row in blockers:
            print(f"- {row['name']}: {row['paywall_status']} -> {row.get('replacement') or 'resolve source rights'}")
        return 1
    print(f"Commercial source register valid: {len(payload['sources'])} sources; {len(blockers)} paid-launch blockers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
