#!/usr/bin/env python3
"""Build current-season head-coach ATS splits from settled closing lines.

This is a descriptive research table. It reads published game results and
closing spreads, joins the season's verified CFBD head-coach assignments, and
never reads from or writes to Model A projection inputs.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
SETTLED_PATH = ROOT / "data" / "reports" / "settled_results.json"
PROJECTIONS_PATH = ROOT / "data" / "projections.json"
OUTPUT_PATH = ROOT / "data" / "coach_ats_trends.json"
SEASON = int(os.environ.get("SEASON_YEAR", "2026"))
API_KEY = os.environ.get("CFBD_API_KEY", "").strip()
CFBD_URL = "https://api.collegefootballdata.com/coaches"


def finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def normalized(value):
    return "".join(char for char in str(value or "").casefold() if char.isalnum())


def coach_map():
    if not API_KEY:
        raise SystemExit("CFBD_API_KEY is required to verify current head coaches")
    response = requests.get(
        CFBD_URL,
        params={"year": SEASON},
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Accept": "application/json",
            "User-Agent": "TheHammerIndex-CoachATSTrends/1.0",
        },
        timeout=(10, 90),
    )
    response.raise_for_status()
    rows = response.json()
    mapping = {}
    for coach in rows:
        name = " ".join(
            part for part in [coach.get("firstName"), coach.get("lastName")] if part
        ).strip() or str(coach.get("name") or "").strip()
        for season in coach.get("seasons") or []:
            if int(season.get("year") or 0) != SEASON:
                continue
            school = str(season.get("school") or "").strip()
            if school and name:
                mapping[normalized(school)] = {"team": school, "coach": name}
    if len(mapping) < 100:
        raise RuntimeError(f"CFBD returned only {len(mapping)} verified {SEASON} coach assignments")
    return mapping


def record_label(wins, losses, pushes):
    return f"{wins}-{losses}" + (f"-{pushes}" if pushes else "")


def summarize(results):
    wins = results.count("W")
    losses = results.count("L")
    pushes = results.count("P")
    decisions = wins + losses
    return {
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "games": len(results),
        "record": record_label(wins, losses, pushes),
        "cover_pct_ex_pushes": round(100 * wins / decisions, 1) if decisions else None,
    }


def main():
    coaches = coach_map()
    settled = json.loads(SETTLED_PATH.read_text(encoding="utf-8"))
    projection_payload = json.loads(PROJECTIONS_PATH.read_text(encoding="utf-8"))
    projection_rows = projection_payload.get("games", projection_payload)
    neutral = {
        str(row.get("game_id")): bool(row.get("neutral_site"))
        for row in projection_rows
    }

    # One game, one closing-line result. Snapshot rows repeat the same final.
    games = {}
    for row in sorted(settled.get("rows") or [], key=lambda item: str(item.get("captured_at_utc") or "")):
        game_id = str(row.get("game_key") or "")
        if not game_id or not row.get("result_settled"):
            continue
        if finite(row.get("actual_home_margin")) is None or finite(row.get("closing_home_spread")) is None:
            continue
        games.setdefault(game_id, row)

    buckets = defaultdict(lambda: defaultdict(list))
    labels = {}
    unmatched = set()
    for game_id, row in games.items():
        margin = finite(row.get("actual_home_margin"))
        spread = finite(row.get("closing_home_spread"))
        cover = margin + spread
        home_result = "W" if cover > 0 else "L" if cover < 0 else "P"
        away_result = "L" if home_result == "W" else "W" if home_result == "L" else "P"
        for side, team, result in (
            ("home", row.get("home_team"), home_result),
            ("away", row.get("away_team"), away_result),
        ):
            assignment = coaches.get(normalized(team))
            if not assignment:
                unmatched.add(str(team))
                continue
            coach = assignment["coach"]
            labels[coach] = assignment["team"]
            buckets[coach]["overall"].append(result)
            if spread < 0:
                buckets[coach]["favorite" if side == "home" else "dog"].append(result)
            elif spread > 0:
                buckets[coach]["dog" if side == "home" else "favorite"].append(result)
            else:
                buckets[coach]["pickem"].append(result)
            if not neutral.get(game_id, False):
                buckets[coach]["home" if side == "home" else "road"].append(result)

    rows = []
    for coach, splits in buckets.items():
        row = {"coach": coach, "team": labels[coach]}
        for key in ("overall", "favorite", "dog", "home", "road", "pickem"):
            row[key] = summarize(splits.get(key, []))
        rows.append(row)
    rows.sort(key=lambda row: (-row["overall"]["games"], row["coach"]))

    payload = {
        "meta": {
            "schema_version": "1.0",
            "season": SEASON,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "CFBD head-coach assignments + THI settled closing-line results",
            "methodology": "ATS is graded against the recorded closing home spread. Cover percentages exclude pushes. Neutral-site games are excluded from home/road splits.",
            "model_usage": "descriptive_only_not_used_by_model_a",
            "settled_games": len(games),
            "coach_count": len(rows),
            "unmatched_teams": sorted(unmatched),
        },
        "coaches": rows,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=OUTPUT_PATH.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(OUTPUT_PATH)
    print(f"Coach ATS trends: {len(rows)} coaches across {len(games)} settled games")


if __name__ == "__main__":
    main()
