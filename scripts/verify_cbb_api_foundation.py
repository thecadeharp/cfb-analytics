#!/usr/bin/env python3
"""Verify THI's CBBD access without publishing provider responses."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "cbb" / "api_access_report.json"
BASE_URL = "https://api.collegebasketballdata.com"
USER_AGENT = "TheHammerIndex-CBBFoundation/2.0"


def clean_key(value: str | None) -> str:
    return str(value or "").strip().strip('"').strip("'")


def fetch_json(path: str, params: dict[str, Any], api_key: str) -> Any:
    query = urlencode({key: value for key, value in params.items() if value is not None})
    url = f"{BASE_URL}{path}" + (f"?{query}" if query else "")
    request = Request(url, headers={
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    })
    for attempt in range(4):
        try:
            with urlopen(request, timeout=90) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code in {429, 500, 502, 503, 504} and attempt < 3:
                retry_after = error.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                time.sleep(min(delay, 30))
                continue
            if error.code in {401, 403}:
                raise RuntimeError(
                    f"CBBD rejected {path}. Verify CBBD_API_KEY and subscription access."
                ) from error
            raise RuntimeError(f"CBBD {path} returned HTTP {error.code}") from error
        except URLError as error:
            if attempt < 3:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"CBBD {path} could not be reached: {error.reason}") from error
    raise RuntimeError(f"CBBD {path} failed after retries")


def list_probe(name: str, payload: Any, required_fields: set[str]) -> dict[str, Any]:
    if not isinstance(payload, list):
        raise RuntimeError(f"{name} returned {type(payload).__name__}; expected a list")
    observed = set().union(*(row.keys() for row in payload[:50] if isinstance(row, dict)))
    missing = sorted(required_fields - observed) if payload else []
    return {
        "status": "empty" if not payload else ("ok" if not missing else "schema_warning"),
        "record_count": len(payload),
        "required_fields_present": not missing,
        "missing_required_fields": missing,
    }


def build_report(
    season: int,
    benchmark_season: int,
    fetcher: Callable[[str, dict[str, Any]], Any],
) -> dict[str, Any]:
    directory = fetcher("/teams/directory", {"season": season})
    if not isinstance(directory, dict):
        raise RuntimeError("teams/directory did not return an object")
    teams = directory.get("teams")
    conferences = directory.get("conferences")
    if not isinstance(teams, list) or len(teams) < 300:
        raise RuntimeError(f"CBBD team directory returned only {len(teams or [])} teams")
    if not isinstance(conferences, list) or not conferences:
        raise RuntimeError("CBBD team directory did not include conferences")

    responses = {
        "season_games": fetcher("/games", {"season": season}),
        "benchmark_adjusted_ratings": fetcher("/ratings/adjusted", {"season": benchmark_season}),
        "benchmark_team_leaderboard": fetcher("/stats/team/leaderboard", {"season": benchmark_season}),
        "current_rosters": fetcher("/teams/roster", {"season": season}),
        "benchmark_player_stats": fetcher("/stats/player/season", {"season": benchmark_season}),
        "line_providers": fetcher("/lines/providers", {}),
        "live_scoreboard": fetcher("/scoreboard", {}),
    }
    checks = {
        "team_directory": {
            "status": "ok",
            "team_count": len(teams),
            "conference_count": len(conferences),
            "required_fields_present": all(
                isinstance(row, dict) and {"id", "school", "conferenceId"}.issubset(row)
                for row in teams[:25]
            ),
        },
        "season_games": list_probe(
            "games", responses["season_games"],
            {"id", "season", "startDate", "homeTeamId", "awayTeamId", "status"},
        ),
        "benchmark_adjusted_ratings": list_probe(
            "adjusted ratings", responses["benchmark_adjusted_ratings"],
            {"season", "teamId", "team", "offensiveRating", "defensiveRating", "netRating"},
        ),
        "benchmark_team_leaderboard": list_probe(
            "team leaderboard", responses["benchmark_team_leaderboard"],
            {"season", "teamId", "team", "record", "summary", "teamStats", "opponentStats", "adjustedEfficiency"},
        ),
        "current_rosters": list_probe(
            "team rosters", responses["current_rosters"],
            {"teamId", "team", "season", "players"},
        ),
        "benchmark_player_stats": list_probe(
            "player season stats", responses["benchmark_player_stats"],
            {"season", "teamId", "athleteId", "name", "games", "minutes", "points", "usage"},
        ),
        "line_providers": list_probe("line providers", responses["line_providers"], {"id", "name"}),
        "live_scoreboard": list_probe(
            "scoreboard", responses["live_scoreboard"],
            {"id", "startDate", "status", "homeTeam", "awayTeam"},
        ),
    }
    if checks["benchmark_adjusted_ratings"]["record_count"] < 300:
        raise RuntimeError("CBBD adjusted-rating benchmark did not return full Division I coverage")
    if checks["benchmark_team_leaderboard"]["record_count"] < 300:
        raise RuntimeError("CBBD Tier 2+ team leaderboard access was not verified")
    if checks["current_rosters"]["record_count"] < 300:
        raise RuntimeError("CBBD current roster coverage is incomplete")
    if checks["benchmark_player_stats"]["record_count"] < 1000:
        raise RuntimeError("CBBD benchmark player-stat coverage is incomplete")

    return {
        "meta": {
            "schema_version": "2.0",
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "platform": "CollegeBasketballData.com",
            "base_url": BASE_URL,
            "season": season,
            "benchmark_season": benchmark_season,
            "request_count": 8,
            "raw_api_data_stored": False,
            "model_usage": "cbb_foundation_only_no_cfb_or_model_a_access",
            "credential_storage": "github_actions_secret_only",
        },
        "checks": checks,
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=int(os.environ.get("CBB_SEASON", "2027")))
    parser.add_argument("--benchmark-season", type=int, default=int(os.environ.get("CBB_BENCHMARK_SEASON", "2026")))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = clean_key(os.environ.get("CBBD_API_KEY"))
    if not api_key:
        raise SystemExit("CBBD_API_KEY is missing. Add it as a GitHub Actions secret; never commit it.")
    report = build_report(
        args.season,
        args.benchmark_season,
        lambda path, params: fetch_json(path, params, api_key),
    )
    atomic_write(args.output, report)
    print(
        "CBBD foundation verified: "
        f"{report['checks']['team_directory']['team_count']} teams, "
        f"{report['checks']['current_rosters']['record_count']} rosters, "
        f"{report['checks']['benchmark_player_stats']['record_count']} player seasons"
    )


if __name__ == "__main__":
    main()
