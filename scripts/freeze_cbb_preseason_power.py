#!/usr/bin/env python3
"""Create an immutable CBB preseason power baseline for later movement audits."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def canonical_hash(payload: dict) -> str:
    material = {"methodology": payload.get("meta", {}).get("methodology"), "teams": payload.get("teams") or []}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def freeze(source: Path, output: Path) -> dict:
    payload = json.loads(source.read_text(encoding="utf-8"))
    digest = canonical_hash(payload)
    if output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
        if existing.get("meta", {}).get("canonical_sha256") != digest:
            raise RuntimeError(f"immutable baseline already exists with different content: {output}")
        return existing
    frozen = json.loads(json.dumps(payload))
    frozen["meta"] = {
        **frozen.get("meta", {}),
        "frozen_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "canonical_sha256": digest,
        "immutable": True,
        "purpose": "Point-in-time 2027 preseason reference for rating movement and prospective audit.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(frozen, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    return frozen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "data/cbb/model/display_power_ratings.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/cbb/frozen/preseason_power_2027.json")
    args = parser.parse_args()
    payload = freeze(args.source, args.output)
    print(f"Frozen CBB preseason power: {payload['meta']['canonical_sha256'][:16]}")


if __name__ == "__main__":
    main()
