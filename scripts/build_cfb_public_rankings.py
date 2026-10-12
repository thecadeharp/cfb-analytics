#!/usr/bin/env python3
"""Publish the current sourced AP Top 25 for site ranking context."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


ESPN_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/"
    "college-football/rankings?region=us&lang=en&contentorigin=espn&"
    "isqualified=true&type=ap"
)


def parse(payload: dict) -> dict:
    poll = next(
        (row for row in payload.get("rankings", []) if row.get("name") == "AP Top 25"),
        None,
    )
    if not poll or len(poll.get("ranks", [])) != 25:
        raise ValueError("A complete AP Top 25 was not present in the source payload")

    teams = []
    for row in poll["ranks"]:
        team = row.get("team") or {}
        rank = int(row["current"])
        teams.append(
            {
                "rank": rank,
                "previous_rank": int(row["previous"]) if row.get("previous") else None,
                "team": team.get("location") or team.get("nickname"),
                "abbreviation": team.get("abbreviation"),
                "conference": (team.get("groups") or {}).get("shortName"),
                "record": row.get("recordSummary"),
                "points": int(row.get("points") or 0),
                "first_place_votes": int(row.get("firstPlaceVotes") or 0),
            }
        )
    teams.sort(key=lambda row: row["rank"])
    if [row["rank"] for row in teams] != list(range(1, 26)):
        raise ValueError("AP ranks must be exactly 1 through 25")
    if len({row["team"] for row in teams}) != 25:
        raise ValueError("AP ranking contains duplicate or missing team names")

    return {
        "meta": {
            "version": "thi_cfb_public_rankings_v1.0",
            "status": "SOURCED_CURRENT_POLL",
            "poll": "AP Top 25",
            "season": int(payload.get("requestedSeason", {}).get("year") or payload.get("latestSeason", {}).get("year")),
            "week": int(payload.get("latestWeek", {}).get("number") or 0),
            "poll_date": poll["ranks"][0].get("date"),
            "source_updated_at": poll["ranks"][0].get("lastUpdated"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "Associated Press Top 25 via ESPN public rankings endpoint",
            "source_url": "https://apnews.com/hub/ap-top-25-college-football-poll",
            "model_usage": "display_and_sort_context_only",
            "model_a_touched": False,
            "note": "Public ranking badges are sourced poll context, not a THI model output.",
        },
        "teams": teams,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/cfb_public_rankings.json"))
    args = parser.parse_args()
    if args.input:
        payload = json.loads(args.input.read_text())
    else:
        request = Request(ESPN_URL, headers={"User-Agent": "THI-Rankings/1.0"})
        with urlopen(request, timeout=45) as response:
            payload = json.load(response)
    output = parse(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, separators=(",", ":")) + "\n")
    print(f"Wrote {args.output}: {output['meta']['poll']} Week {output['meta']['week']}")


if __name__ == "__main__":
    main()
