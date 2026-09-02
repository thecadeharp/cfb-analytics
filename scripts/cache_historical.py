"""
CFB ANALYTICS
cache_historical.py

Fetch and freeze ONE historical season of CFBD data at a time.

Why:
- Historical seasons are immutable.
- Experimental model runs should read the exact same frozen data every time.
- This prevents repeated CFBD requests and rate-limit failures.

Usage:
    python scripts/cache_historical.py 2019

Run one season per workflow invocation.
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

CFBD_BASE = "https://api.collegefootballdata.com"
CACHE_ROOT = Path("data/historical_cache")
VALID_YEARS = set(range(2019, 2026))


def clean_api_key(raw):
    if raw is None:
        return ""
    key = str(raw).strip()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
        key = key[1:-1].strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key.replace("\r", "").replace("\n", "").replace("\t", "").strip()


CFBD_API_KEY = clean_api_key(os.environ.get("CFBD_API_KEY", ""))


def first_value(data, *keys, default=None):
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)
    return default


def request_json(endpoint, params):
    if not CFBD_API_KEY:
        raise SystemExit("CFBD_API_KEY missing.")

    waits = [0, 8, 20, 45, 90, 150]

    for attempt, wait in enumerate(waits, start=1):
        if wait:
            print(f"   waiting {wait}s before retry...")
            time.sleep(wait)

        try:
            response = requests.get(
                f"{CFBD_BASE}{endpoint}",
                headers={
                    "Authorization": f"Bearer {CFBD_API_KEY}",
                    "Accept": "application/json",
                },
                params=params,
                timeout=120,
            )
        except requests.RequestException as exc:
            print(f"   request error ({attempt}/{len(waits)}): {exc}")
            continue

        if response.status_code in (401, 403):
            raise SystemExit("CFBD authentication failed.")

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            print(
                f"   CFBD 429 ({attempt}/{len(waits)})"
                + (f" | Retry-After={retry_after}" if retry_after else "")
            )
            continue

        if not response.ok:
            print(f"   CFBD HTTP {response.status_code} ({attempt}/{len(waits)})")
            continue

        try:
            return response.json()
        except ValueError:
            print(f"   invalid JSON ({attempt}/{len(waits)})")

    raise SystemExit(f"Unable to cache {endpoint} after retries.")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    tmp.replace(path)


def cache_endpoint(year, label, endpoint, params, path):
    if path.exists() and path.stat().st_size > 10:
        print(f"✅ {label}: already cached")
        return json.loads(path.read_text(encoding="utf-8"))

    print(f"⬇️  {label}")
    data = request_json(endpoint, params)
    write_json(path, data)
    print(f"✅ {label}: {len(data) if isinstance(data, list) else 'saved'}")
    time.sleep(2)
    return data


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/cache_historical.py YEAR")

    try:
        year = int(sys.argv[1])
    except ValueError:
        raise SystemExit("YEAR must be an integer.")

    if year not in VALID_YEARS:
        raise SystemExit("YEAR must be 2019 through 2025.")

    year_dir = CACHE_ROOT / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print(f"CFB HISTORICAL CACHE — {year}")
    print("=" * 72)

    games = cache_endpoint(
        year,
        "games",
        "/games",
        {"year": year, "seasonType": "regular", "classification": "fbs"},
        year_dir / "games.json",
    )

    cache_endpoint(
        year,
        "betting lines",
        "/lines",
        {"year": year, "seasonType": "regular"},
        year_dir / "lines.json",
    )

    weeks = sorted(
        {
            int(first_value(g, "week", default=0))
            for g in games
            if first_value(g, "week") is not None
        }
    )

    if not weeks:
        raise SystemExit("No weeks found in games response.")

    for week in weeks:
        cache_endpoint(
            year,
            f"Week {week} plays",
            "/plays",
            {
                "year": year,
                "week": week,
                "seasonType": "regular",
                "classification": "fbs",
            },
            year_dir / f"plays_week_{week}.json",
        )

    manifest = {
        "year": year,
        "complete": True,
        "weeks": weeks,
        "files": {
            "games": "games.json",
            "lines": "lines.json",
            "plays": [f"plays_week_{week}.json" for week in weeks],
        },
    }
    write_json(year_dir / "manifest.json", manifest)

    print("")
    print(f"🧊 SEALED: {year_dir}")
    print("This season can now be reused without another CFBD request.")
    print("=" * 72)


if __name__ == "__main__":
    main()
