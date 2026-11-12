#!/usr/bin/env python3
"""Build current-season team ATS splits from THI's closing-line ledger.

The builder joins verified CFBD head-coach assignments to THI's own immutable
settled-game records. It never scrapes or republishes a third-party trend table
and never reads from or writes to Model A projection inputs.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

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
        if OUTPUT_PATH.exists():
            prior = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
            mapping = {
                normalized(row.get("team")): {"team": row.get("team"), "coach": row.get("coach")}
                for row in prior.get("coaches") or []
                if row.get("team") and row.get("coach")
            }
            if len(mapping) >= 100:
                return mapping
        raise SystemExit("CFBD_API_KEY is required to verify current head coaches")
    import requests

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

    internal_by_team = {}
    for coach, splits in buckets.items():
        row = {"coach": coach, "team": labels[coach]}
        for key in ("overall", "favorite", "dog", "home", "road", "pickem"):
            row[key] = summarize(splits.get(key, []))
        internal_by_team[normalized(row["team"])] = row

    rows = []
    seen = set()
    for assignment in coaches.values():
        coach, team = assignment["coach"], assignment["team"]
        team_key = normalized(team)
        unique_key = (coach, team_key)
        if unique_key in seen:
            continue
        seen.add(unique_key)
        internal = internal_by_team.get(team_key)
        if not internal:
            continue
        row = {"coach": coach, "team": team}
        for key in ("overall", "favorite", "dog", "home", "road", "pickem"):
            row[key] = internal[key]
        rows.append(row)
    rows.sort(key=lambda row: (-row["overall"]["games"], row["coach"]))
    if not rows:
        raise RuntimeError("No THI settled games matched verified coach assignments")

    payload = {
        "meta": {
            "schema_version": "3.0",
            "season": SEASON,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "THI immutable settled-game and closing-line ledger joined to CFBD head-coach assignments",
            "source_url": None,
            "methodology": "Overall, favorite, underdog, home and road ATS records are calculated from THI's immutable closing-line ledger. Cover percentages exclude pushes. Team records are joined to verified current head-coach assignments; they are descriptive team-season splits, not career coach records.",
            "model_usage": "descriptive_only_not_used_by_model_a",
            "thi_snapshot_settled_games": len(games),
            "coach_count": len(rows),
            "thi_snapshot_unmatched_teams": sorted(unmatched),
        },
        "coaches": rows,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=OUTPUT_PATH.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(OUTPUT_PATH)
    print(
        f"Coach ATS trends: {len(rows)} coaches; "
        f"{len(games)} THI settled games"
    )


if __name__ == "__main__":
    main()
