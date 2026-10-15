#!/usr/bin/env python3
"""Build current-season team ATS splits and join current head coaches.

Published records come from TeamRankings' complete current-season aggregate
tables. THI's settled-results snapshot is retained only as a coverage audit.
The builder joins verified CFBD head-coach assignments and never reads from or
writes to Model A projection inputs.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
SETTLED_PATH = ROOT / "data" / "reports" / "settled_results.json"
PROJECTIONS_PATH = ROOT / "data" / "projections.json"
OUTPUT_PATH = ROOT / "data" / "coach_ats_trends.json"
SEASON = int(os.environ.get("SEASON_YEAR", "2026"))
API_KEY = os.environ.get("CFBD_API_KEY", "").strip()
CFBD_URL = "https://api.collegefootballdata.com/coaches"
TEAMRANKINGS_URL = "https://www.teamrankings.com/ncf/trends/ats_trends/"
TEAMRANKINGS_SITUATIONS = {
    "overall": "all_games",
    "favorite": "is_fav",
    "dog": "is_dog",
    "home": "is_home",
    "road": "is_away",
}


def finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def normalized(value):
    return "".join(char for char in str(value or "").casefold() if char.isalnum())


def canonical_team(value):
    """Normalize TeamRankings display abbreviations to CFBD-style school names."""
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
    aliases = {
        "umass": "massachusetts",
        "mississippi": "ole miss",
        "miami oh": "miami ohio",
        "j madison": "james madison",
        "florida intl": "florida international",
    }
    text = aliases.get(text, text)
    tokens = {
        "app": "appalachian",
        "c": "central",
        "car": "carolina",
        "e": "east",
        "eastern": "east",
        "intl": "international",
        "n": "north",
        "northern": "north",
        "s": "south",
        "so": "south",
        "southern": "south",
        "st": "state",
        "tenn": "tennessee",
        "w": "west",
        "western": "west",
    }
    return "".join(tokens.get(token, token) for token in text.split())


class ATSTableParser(HTMLParser):
    """Extract the public aggregate ATS table without depending on page scripts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_table = False
        self.table_depth = 0
        self.row = None
        self.cell = None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "table" and "tr-table" in attributes.get("class", "").split():
            self.in_table = True
            self.table_depth = 1
            return
        if not self.in_table:
            return
        if tag == "table":
            self.table_depth += 1
        elif tag == "tr":
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.in_table and self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if not self.in_table:
            return
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if len(self.row) >= 2:
                self.rows.append(self.row)
            self.row = None
        elif tag == "table":
            self.table_depth -= 1
            if self.table_depth <= 0:
                self.in_table = False


def parse_teamrankings_table(html):
    parser = ATSTableParser()
    parser.feed(html)
    output = {}
    for row in parser.rows:
        if len(row) < 2 or not re.fullmatch(r"\d+-\d+-\d+", row[1]):
            continue
        wins, losses, pushes = (int(value) for value in row[1].split("-"))
        decisions = wins + losses
        output[canonical_team(row[0])] = {
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "games": wins + losses + pushes,
            "record": f"{wins}-{losses}-{pushes}",
            "cover_pct_ex_pushes": round(100 * wins / decisions, 1) if decisions else None,
            "source": "TeamRankings",
        }
    return output


def teamrankings_splits():
    splits = {}
    headers = {"User-Agent": "TheHammerIndex-CoachATSAudit/2.0"}
    for key, situation in TEAMRANKINGS_SITUATIONS.items():
        response = requests.get(
            TEAMRANKINGS_URL,
            params={"range": f"yearly_{SEASON}", "sc": situation},
            headers=headers,
            timeout=(10, 90),
        )
        response.raise_for_status()
        rows = parse_teamrankings_table(response.text)
        minimum = 130 if key in {"overall", "home", "road"} else 100
        if len(rows) < minimum:
            raise RuntimeError(
                f"TeamRankings {key} table returned only {len(rows)} teams; refusing partial publication"
            )
        splits[key] = rows
    return splits


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


def empty_external_split():
    return {
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "games": 0,
        "record": "0-0-0",
        "cover_pct_ex_pushes": None,
        "source": "TeamRankings",
    }


def main():
    coaches = coach_map()
    benchmark = teamrankings_splits()
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
        internal_by_team[canonical_team(row["team"])] = row

    rows = []
    benchmark_unmatched = []
    comparison_mismatches = []
    seen = set()
    for assignment in coaches.values():
        coach, team = assignment["coach"], assignment["team"]
        team_key = canonical_team(team)
        unique_key = (coach, team_key)
        if unique_key in seen:
            continue
        seen.add(unique_key)
        if team_key not in benchmark["overall"]:
            benchmark_unmatched.append(team)
            continue
        row = {"coach": coach, "team": team}
        for key in TEAMRANKINGS_SITUATIONS:
            row[key] = benchmark[key].get(team_key, empty_external_split())
        internal = internal_by_team.get(team_key)
        row["thi_ledger_audit"] = internal.get("overall") if internal else None
        if internal and any(
            internal["overall"][field] != row["overall"][field]
            for field in ("wins", "losses", "pushes")
        ):
            comparison_mismatches.append({
                "team": team,
                "teamrankings_record": row["overall"]["record"],
                "thi_snapshot_record": internal["overall"]["record"],
            })
        rows.append(row)
    rows.sort(key=lambda row: (-row["overall"]["games"], row["coach"]))
    represented_benchmark_teams = {canonical_team(row["team"]) for row in rows}
    benchmark_teams_without_assignment = sorted(
        set(benchmark["overall"]) - represented_benchmark_teams
    )

    if len(rows) < 130 or benchmark_unmatched:
        raise RuntimeError(
            f"Coach ATS reconciliation incomplete: {len(rows)} coaches, unmatched={benchmark_unmatched}"
        )

    payload = {
        "meta": {
            "schema_version": "2.0",
            "season": SEASON,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "TeamRankings current-season team ATS aggregates joined to CFBD head-coach assignments",
            "source_url": TEAMRANKINGS_URL,
            "methodology": "Overall, favorite, underdog, home and road ATS records use TeamRankings' current-season aggregate tables. Cover percentages exclude pushes. Team records are joined to verified current head-coach assignments; they are descriptive team-season splits, not career coach records.",
            "model_usage": "descriptive_only_not_used_by_model_a",
            "teamrankings_team_count": len(benchmark["overall"]),
            "thi_snapshot_settled_games": len(games),
            "coach_count": len(rows),
            "benchmark_unmatched_teams": sorted(benchmark_unmatched),
            "benchmark_teams_without_assignment": benchmark_teams_without_assignment,
            "thi_snapshot_unmatched_teams": sorted(unmatched),
            "thi_snapshot_mismatch_count": len(comparison_mismatches),
            "thi_snapshot_mismatches": comparison_mismatches,
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
        f"{len(benchmark['overall'])} TeamRankings teams; "
        f"{len(games)} THI snapshot games audited"
    )


if __name__ == "__main__":
    main()
