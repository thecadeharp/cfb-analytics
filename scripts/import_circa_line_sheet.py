#!/usr/bin/env python3
"""Import the owner's read-only Circa line-movement Google Sheet.

The workbook intentionally remains human-oriented.  This adapter converts only
rows that can be resolved without guessing.  It never writes to Google Sheets.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHEET_ID = "1Kp565JoyCyQq1ddSs_Ri5daSC85Ss9KgldyTDdbHceg"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
TABS = {
    0: ("Week 0", 0),
    1: ("Week 1", 803881640),
    2: ("Week 2", 854079292),
    3: ("WEEK 3", 2079476727),
    4: ("WEEK 4", 1596141846),
    5: ("WEEK 5", 529371322),
    6: ("WEEK 6", 1934759966),
    7: ("WEEK 7", 602427907),
    8: ("WEEK 8", 2094482329),
    9: ("WEEK 9", 257008375),
    10: ("WEEK 10", 700026445),
    11: ("WEEK 11", 2103443628),
    12: ("WEEK 12", 687871402),
}

ALIASES = {
    "af": "airforce", "airforce": "airforce", "appst": "appstate",
    "arkst": "arkansasstate", "arizonast": "arizonastate", "zonast": "arizonastate",
    "bama": "alabama", "boise": "boisestate", "bostoncoll": "bostoncollege", "bowlinggrn": "bowlinggreen", "cal": "california",
    "cenmich": "centralmichigan", "charlotte": "charlotte", "cincy": "cincinnati",
    "coastcar": "coastalcarolina", "colst": "coloradostate", "coloradost": "coloradostate", "cuse": "syracuse",
    "eamer": "eastcarolina", "ecar": "eastcarolina", "ecu": "eastcarolina",
    "emu": "easternmichigan", "fau": "floridaatlantic", "fla": "florida", "fresnost": "fresnostate", "fsu": "floridastate",
    "ga": "georgia", "gaso": "georgiasouthern", "gast": "georgiastate", "gasouthern": "georgiasouthern",
    "gatech": "georgiatech", "iu": "indiana", "iast": "iowastate", "jmu": "jamesmadison",
    "jaxst": "jacksonvillestate", "kennstate": "kennesawstate", "kennst": "kennesawstate",
    "kst": "kansasstate", "latech": "louisianatech", "louisianna": "louisiana",
    "lousiville": "louisville", "miami": "miamifl", "miamifl": "miamifl",
    "miamioh": "miamioh", "mioh": "miamioh", "mich": "michigan", "michst": "michiganstate",
    "midtennst": "middletennessee", "minne": "minnesota", "missst": "mississippistate", "mizzst": "missouristate",
    "nbama": "alabama", "nd": "notredame", "ndakotast": "northdakotastate",
    "nds": "northdakotastate", "ndsu": "northdakotastate", "neb": "nebraska",
    "newmexico": "newmexico", "nm": "newmexico", "nmst": "newmexicostate",
    "nill": "northernillinois", "ntex": "northtexas", "okst": "oklahomastate",
    "odu": "olddominion", "orgst": "oregonstate", "osu": "ohiostate", "ou": "oklahoma", "psu": "pennstate",
    "sabama": "southalabama", "sbama": "southalabama", "samhouston": "samhouston", "shsu": "samhouston",
    "sds": "sandiegostate", "sdstate": "sandiegostate", "sflorida": "southflorida",
    "sanjosest": "sanjosestate", "sc": "southcarolina", "sjsu": "sanjosestate", "socar": "southcarolina", "southcar": "southcarolina",
    "somiss": "southernmiss", "so miss": "southernmiss", "syeracuse": "syracuse", "syracuse": "syracuse",
    "tamu": "texasam", "texam": "texasam", "texst": "texasstate", "textech": "texastech",
    "ulmon": "ulmonroe", "ulmonroe": "ulmonroe", "umass": "massachusetts",
    "unc": "northcarolina", "uconn": "uconn", "uva": "virginia", "va": "virginia",
    "vatech": "virginiatech", "washst": "washingtonstate", "wisky": "wisconsin",
    "wku": "westernkentucky", "wkentucky": "westernkentucky", "wmu": "westernmichigan",
    "wvu": "westvirginia", "wyo": "wyoming", "zon": "arizona", "zona": "arizona",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def key(value: str) -> str:
    raw = "".join(ch for ch in str(value or "").lower() if ch.isalnum())
    return ALIASES.get(raw, raw)


def normalize_fractions(value: str) -> str:
    return re.sub(r"([+-]?\d+)\s+1/2\b", lambda m: str(float(m.group(1)) + (-0.5 if m.group(1).startswith("-") else 0.5)), value)


def strip_notes(value: str) -> str:
    return re.sub(r"\([^)]*\)", " ", value or " ")


def parse_opening(cell: str):
    cleaned = normalize_fractions(strip_notes(cell)).replace("½", ".5")
    parts = re.split(r"\s+V(?:S)?\s+", cleaned, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        return None, "matchup separator was not recognized"
    left, right = (re.sub(r"\s+", " ", part).strip() for part in parts)
    pick_left, pick_right = bool(re.search(r"\bPK\b", left, re.I)), bool(re.search(r"\bPK\b", right, re.I))
    number_pattern = r"(?<![A-Za-z])([+-]?\d+(?:\.\d+)?)"
    left_matches = [match for match in re.finditer(number_pattern, left) if abs(float(match.group(1))) <= 40]
    right_matches = [match for match in re.finditer(number_pattern, right) if abs(float(match.group(1))) <= 40]
    left_match = left_matches[-1] if len(left_matches) == 1 else None
    right_match = right_matches[-1] if len(right_matches) == 1 else None
    if pick_left or pick_right:
        spread = 0.0
        left = re.sub(r"\bPK\b", "", left, flags=re.I).strip()
        right = re.sub(r"\bPK\b", "", right, flags=re.I).strip()
        favorite = None
    elif bool(left_match) == bool(right_match):
        return None, "opening favorite and spread were ambiguous"
    elif left_match:
        spread = -abs(float(left_match.group(1)))
        left = (left[: left_match.start()] + left[left_match.end():]).strip(" .")
        favorite = "left"
    else:
        spread = abs(float(right_match.group(1)))
        right = (right[: right_match.start()] + right[right_match.end():]).strip(" .")
        favorite = "right"
    if not key(left) or not key(right):
        return None, "one or both team names were empty"
    return {"left_team_raw": left, "right_team_raw": right, "left_key": key(left), "right_key": key(right), "opening_left_spread": spread, "opening_favorite": favorite}, None


def numeric_candidates(value: str) -> list[float]:
    text = normalize_fractions(value or "").replace("½", ".5")
    return [float(item) for item in re.findall(r"(?<![A-Za-z])([+-]?\d+(?:\.\d+)?)", text)]


def explicit_team_side(value: str, opening: dict) -> str | None:
    before_number = re.split(r"[+-]?\d", value or "", maxsplit=1)[0]
    candidate = key(before_number)
    if candidate and (candidate == opening["left_key"] or candidate in opening["left_key"] or opening["left_key"] in candidate):
        return "left"
    if candidate and (candidate == opening["right_key"] or candidate in opening["right_key"] or opening["right_key"] in candidate):
        return "right"
    return None


def line_from_cell(value: str, opening: dict):
    text = str(value or "").strip()
    if not text or re.search(r"\bSAME\b", text, re.I):
        return None
    values = numeric_candidates(text)
    if not values:
        return None
    opening_abs = abs(opening["opening_left_spread"])
    plausible = [number for number in values if abs(number) <= 40 and abs(abs(number) - opening_abs) <= 15]
    if not plausible:
        return None
    chosen = min(plausible, key=lambda number: abs(abs(number) - opening_abs))
    explicit = explicit_team_side(text, opening)
    if explicit:
        team_spread = chosen if chosen < 0 or "+" in text else -abs(chosen)
        return team_spread if explicit == "left" else -team_spread
    favorite = opening.get("opening_favorite")
    if favorite == "left":
        return -abs(chosen)
    if favorite == "right":
        return abs(chosen)
    return chosen


def source_columns(headers: list[str]):
    normalized = [str(header or "").strip().lower() for header in headers]
    movement = next((index for index, header in enumerate(normalized) if "change" in header or "weds line" in header), None)
    later = next((index for index, header in enumerate(normalized) if "friday/saturday" in header), None)
    movement_header = normalized[movement] if movement is not None else ""
    return movement, later, movement_header


def parse_current(row: list[str], opening: dict, movement_index: int | None, later_index: int | None, movement_header: str = ""):
    movement_cell = row[movement_index] if movement_index is not None and movement_index < len(row) else ""
    later_cell = row[later_index] if later_index is not None and later_index < len(row) else ""
    movement_is_line = (
        "line" in movement_header
        or explicit_team_side(movement_cell, opening) is not None
        or bool(re.search(r"(?<![A-Za-z])[+-]\d", movement_cell))
        or not str(later_cell or "").strip()
    )
    order = (movement_index, later_index) if movement_is_line else (later_index, movement_index)
    parsed = []
    for index in order:
        if index is not None and index < len(row):
            cell = row[index]
            current = line_from_cell(cell, opening)
            if current is not None:
                parsed.append((current, cell))
    for current, cell in parsed:
        if abs(current - opening["opening_left_spread"]) >= 3:
            return current, cell
    for current, cell in parsed:
        return current, cell
    return None, None


def projection_index(board: dict):
    by_week = {}
    for game in board.get("games") or []:
        week = int(game.get("week") or -1)
        away = (game.get("away") or {}).get("team") or game.get("away_team")
        home = (game.get("home") or {}).get("team") or game.get("home_team")
        if away and home:
            by_week.setdefault(week, []).append((game, key(away), key(home)))
    return by_week


def resolve_game(opening: dict, week: int, index: dict):
    wanted = {opening["left_key"], opening["right_key"]}
    candidate_weeks = [week, 1] if week == 0 else [week]
    matches = [(game, away, home) for candidate_week in candidate_weeks for game, away, home in index.get(candidate_week, []) if {away, home} == wanted]
    if len(matches) != 1:
        return None
    game, away_key, home_key = matches[0]
    left_is_home = opening["left_key"] == home_key
    return game, left_is_home


def parse_rows(week: int, tab: str, rows: list[list[str]], board: dict, observed_at: str):
    qualifiers, issues = [], []
    index = projection_index(board)
    movement_index, later_index, movement_header = source_columns(rows[0] if rows else [])
    for row_number, row in enumerate(rows[1:], start=2):
        first = row[0].strip() if row else ""
        if not first:
            continue
        source_cells = [row[index] for index in (movement_index, later_index) if index is not None and index < len(row)]
        if not any(str(cell or "").strip() and not re.search(r"\bSAME\b", str(cell), re.I) for cell in source_cells):
            continue
        opening, reason = parse_opening(first)
        if not opening:
            issues.append({"week": week, "tab": tab, "row": row_number, "status": "unparsed_opening", "reason": reason, "source": first})
            continue
        current_left, current_source = parse_current(row, opening, movement_index, later_index, movement_header)
        if current_left is None:
            if any(str(cell or "").strip() for cell in source_cells):
                issues.append({"week": week, "tab": tab, "row": row_number, "status": "no_verified_spread_change", "reason": "The populated movement cells did not contain an unambiguous spread", "source": first})
            continue
        movement = round(current_left - opening["opening_left_spread"], 2)
        if abs(movement) < 3:
            continue
        resolved = resolve_game(opening, week, index)
        if not resolved:
            issues.append({"week": week, "tab": tab, "row": row_number, "status": "unmatched_game", "reason": "The teams did not resolve to exactly one THI game in this week", "source": first})
            continue
        game, left_is_home = resolved
        opening_home = opening["opening_left_spread"] if left_is_home else -opening["opening_left_spread"]
        current_home = current_left if left_is_home else -current_left
        delta = round(current_home - opening_home, 2)
        away = (game.get("away") or {}).get("team") or game.get("away_team")
        home = (game.get("home") or {}).get("team") or game.get("home_team")
        source_id = f"week-{week}:row-{row_number}:{game.get('game_id')}"
        qualifiers.append({
            "sport": "cfb", "event_id": str(game.get("game_id")), "game_id": str(game.get("game_id")),
            "week": week, "start_date": game.get("start_date"), "away_team": away, "home_team": home,
            "opening_home_spread": round(opening_home, 2), "current_home_spread": round(current_home, 2),
            "line_delta": delta, "movement_points": round(abs(delta), 2), "sharp_book": "circa",
            "source_verified": True, "source_id": source_id, "source_sheet": tab, "source_row": row_number,
            "source_opening_text": first, "source_movement_text": current_source,
            "source_observed_at_utc": observed_at,
            "definition": "Circa opening-to-later spread movement recorded in the system owner's authoritative read-only Google Sheet.",
        })
    return qualifiers, issues


def export_url(gid: int) -> str:
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"


def fetch_rows(gid: int, timeout: int = 20) -> list[list[str]]:
    completed = subprocess.run(
        ["curl", "-L", "--fail", "--silent", "--show-error", "--max-time", str(timeout), export_url(gid)],
        check=True, capture_output=True,
    )
    data = completed.stdout.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(data)))


def build_state(board: dict, tab_rows: dict[int, list[list[str]]], old: dict | None = None, observed_at: str | None = None):
    observed_at = observed_at or utc_now()
    all_qualifiers, issues, tabs = [], [], []
    for week, (tab, gid) in TABS.items():
        rows = tab_rows[week]
        qualifiers, tab_issues = parse_rows(week, tab, rows, board, observed_at)
        all_qualifiers.extend(qualifiers); issues.extend(tab_issues)
        tabs.append({"week": week, "title": tab, "gid": gid, "row_count": max(0, len(rows) - 1), "qualifier_count": len(qualifiers)})
    old_by_id = {row.get("source_id"): row for row in (old or {}).get("qualifiers") or []}
    first_seen = {source_id: row.get("first_seen_at_utc") for source_id, row in old_by_id.items()}
    for row in all_qualifiers:
        row["first_seen_at_utc"] = first_seen.get(row["source_id"]) or observed_at
        previous = old_by_id.get(row["source_id"])
        if previous:
            comparable = lambda value: {key: item for key, item in value.items() if key not in {"source_observed_at_utc", "first_seen_at_utc"}}
            if comparable(previous) == comparable(row):
                row["source_observed_at_utc"] = previous.get("source_observed_at_utc") or observed_at
    all_qualifiers.sort(key=lambda row: (row["week"], row["source_row"]))
    return {
        "meta": {"version": "thi-circa-sheet-v1.0", "status": "verified_read_only", "generated_at_utc": observed_at,
                 "source": "Google Sheets", "book": "Circa", "spreadsheet_id": SHEET_ID, "spreadsheet_url": SHEET_URL,
                 "write_access_used": False, "tabs_read": len(tabs), "qualifier_count": len(all_qualifiers),
                 "issue_count": len(issues), "policy": "Only unambiguous CFB moves of at least 3.0 points are published. The Sheet is never modified."},
        "tabs": tabs, "qualifiers": all_qualifiers, "issues": issues,
    }


def stable_content(state: dict):
    copy = json.loads(json.dumps(state))
    (copy.get("meta") or {}).pop("generated_at_utc", None)
    return copy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--projections", type=Path, default=ROOT / "data/projections.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/market/circa_sheet_state.json")
    parser.add_argument("--fixture-dir", type=Path)
    args = parser.parse_args()
    board = json.loads(args.projections.read_text())
    old = json.loads(args.output.read_text()) if args.output.exists() else {}
    try:
        tab_rows = {}
        for week, (tab, gid) in TABS.items():
            if args.fixture_dir:
                tab_rows[week] = list(csv.reader(io.StringIO((args.fixture_dir / f"week-{week}.csv").read_text())))
            else:
                tab_rows[week] = fetch_rows(gid)
        state = build_state(board, tab_rows, old=old)
    except (subprocess.CalledProcessError, TimeoutError, OSError, UnicodeError, csv.Error, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Circa Sheet import failed; last verified state preserved: {exc}") from exc
    if old and stable_content(old) == stable_content(state):
        print(f"Circa Sheet unchanged: {len(state['qualifiers'])} verified qualifiers; {len(state['issues'])} review notes")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(state, indent=2, allow_nan=False) + "\n")
    print(f"Circa Sheet: {len(state['qualifiers'])} verified qualifiers; {len(state['issues'])} review notes")


if __name__ == "__main__":
    main()
