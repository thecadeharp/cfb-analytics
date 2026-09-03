"""Build verified historical variance cohorts for The Hammer Index.

Data source: CollegeFootballData API.

Verified cohorts produced by this script:
  * full_reset: head coach changed AND primary quarterback changed.
  * qb_swap: head coach stayed AND primary quarterback changed.

CFBD does not provide offensive-coordinator history. The coordinator cohort is
therefore emitted as explicitly unavailable instead of being inferred from head
coach changes. Add a separately verified coordinator-history dataset before
publishing coordinator-only results.
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


BASE_URL = "https://api.collegefootballdata.com"
START_YEAR = 2013
END_YEAR = 2025
YEARS = range(START_YEAR, END_YEAR + 1)
OUTPUT_PATH = Path("data/variance_historical.json")
MIN_COMPLETED_GAMES = 8
MIN_PRIMARY_PASS_YARDS = 200.0
TRANSFER_ATTEMPT_THRESHOLD = 150.0

API_KEY = os.environ.get("CFBD_API_KEY", "").strip()
if not API_KEY:
    raise SystemExit(
        "CFBD_API_KEY is missing. Add it as a GitHub Actions secret; "
        "never put the key in this file."
    )

SESSION = requests.Session()
SESSION.headers.update(
    {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "User-Agent": "TheHammerIndex-VarianceBuilder/1.0",
    }
)


def pick(obj: dict[str, Any], *names: str, default: Any = None) -> Any:
    """Return the first present, non-None spelling of an API field."""
    for name in names:
        if name in obj and obj[name] is not None:
            return obj[name]
    return default


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value: Any, default: int = 0) -> int:
    return int(number(value, default))


def normalized(value: Any) -> str:
    value = str(value or "").casefold().strip()
    return re.sub(r"[^a-z0-9]+", "", value)


def cfbd(endpoint: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Fetch one CFBD endpoint, retrying transient failures but not hiding them."""
    url = f"{BASE_URL}{endpoint}"
    last_error: Exception | None = None

    for attempt in range(1, 6):
        try:
            response = SESSION.get(url, params=params, timeout=(10, 90))

            if response.status_code == 429:
                retry_after = integer(response.headers.get("Retry-After"), 0)
                wait_seconds = retry_after or min(60, 5 * (2 ** (attempt - 1)))
                if attempt == 5:
                    raise RuntimeError(
                        "CFBD returned HTTP 429 after all retries. The API quota or "
                        "rate limit is exhausted; no output was published."
                    )
                print(f"  CFBD rate limited the request; retrying in {wait_seconds}s...")
                time.sleep(wait_seconds)
                continue

            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise RuntimeError(
                    f"Expected a JSON list from {endpoint}, got {type(payload).__name__}."
                )
            return payload
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt == 5:
                break
            wait_seconds = min(30, 2 ** attempt)
            print(f"  Request failed ({exc}); retrying in {wait_seconds}s...")
            time.sleep(wait_seconds)

    raise RuntimeError(f"CFBD request failed: {endpoint} {params}: {last_error}")


def fetch_coaches() -> dict[str, dict[int, str]]:
    print("Fetching head-coach history...")
    raw = cfbd("/coaches")
    candidates: dict[tuple[str, int], list[tuple[int, str]]] = defaultdict(list)

    for coach in raw:
        first = str(pick(coach, "firstName", "first_name", default="")).strip()
        last = str(pick(coach, "lastName", "last_name", default="")).strip()
        name = " ".join(part for part in (first, last) if part).strip()
        if not name:
            name = str(pick(coach, "name", default="")).strip()
        if not name:
            continue

        for season in pick(coach, "seasons", default=[]) or []:
            year = integer(pick(season, "year"), 0)
            school = str(pick(season, "school", "team", default="")).strip()
            if year not in YEARS or not school:
                continue

            # Some CFBD coach-season responses omit `games`. Never turn a missing
            # field into zero and discard the entire coaching history.
            games = integer(pick(season, "games"), -1)
            if games < 0:
                games = (
                    integer(pick(season, "wins"), 0)
                    + integer(pick(season, "losses"), 0)
                    + integer(pick(season, "ties"), 0)
                )
            candidates[(school, year)].append((games, name))

    coaches: dict[str, dict[int, str]] = defaultdict(dict)
    for (school, year), options in candidates.items():
        # For seasons with an interim coach, retain the coach attached to the
        # largest game sample. Stable name ordering makes ties deterministic.
        _, name = max(options, key=lambda item: (item[0], item[1]))
        coaches[school][year] = name

    season_count = sum(len(seasons) for seasons in coaches.values())
    if len(coaches) < 100 or season_count < 1_000:
        raise RuntimeError(
            f"Head-coach history is unexpectedly sparse: {len(coaches)} teams / "
            f"{season_count} team-seasons. Refusing to build cohorts."
        )
    print(f"  {season_count:,} verified team-seasons across {len(coaches)} teams")
    return dict(coaches)


def fetch_records() -> dict[str, dict[int, dict[str, Any]]]:
    print("Fetching team records...")
    records: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)

    for year in YEARS:
        rows = cfbd("/records", {"year": year})
        if len(rows) < 100:
            raise RuntimeError(
                f"Only {len(rows)} record rows returned for {year}; expected FBS coverage."
            )
        for row in rows:
            team = str(pick(row, "team", default="")).strip()
            total = pick(row, "total", default={}) or {}
            if not team or not isinstance(total, dict):
                continue
            wins = integer(pick(total, "wins"), 0)
            losses = integer(pick(total, "losses"), 0)
            ties = integer(pick(total, "ties"), 0)
            records[team][year] = {
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "games": wins + losses + ties,
                "conference": str(
                    pick(row, "conference", default="Independent") or "Independent"
                ),
            }
        print(f"  {year}: {len(rows)} teams")

    return dict(records)


def fetch_quarterbacks() -> tuple[
    dict[str, dict[int, dict[str, Any]]],
    dict[int, dict[str, list[dict[str, Any]]]],
]:
    print("Fetching primary-quarterback history...")
    primary: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    player_history: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for year in YEARS:
        rows = cfbd(
            "/stats/player/season",
            {"year": year, "category": "passing", "seasonType": "regular"},
        )
        by_player_team: dict[tuple[str, str], dict[str, Any]] = {}

        for row in rows:
            team = str(pick(row, "team", default="")).strip()
            player = str(pick(row, "player", default="")).strip()
            stat_type = str(pick(row, "statType", "stat_type", default="")).upper()
            if not team or not player or stat_type not in {"YDS", "ATT"}:
                continue

            key = (team, player)
            entry = by_player_team.setdefault(
                key, {"team": team, "player": player, "yards": 0.0, "attempts": 0.0}
            )
            stat = number(pick(row, "stat"), 0.0)
            if stat_type == "YDS":
                entry["yards"] = stat
            elif stat_type == "ATT":
                entry["attempts"] = stat

        best_by_team: dict[str, dict[str, Any]] = {}
        for entry in by_player_team.values():
            if entry["yards"] < MIN_PRIMARY_PASS_YARDS:
                continue
            team = entry["team"]
            player_key = normalized(entry["player"])
            player_history[year][player_key].append(entry.copy())
            if team not in best_by_team or entry["yards"] > best_by_team[team]["yards"]:
                best_by_team[team] = entry

        for team, entry in best_by_team.items():
            primary[team][year] = entry

        if len(best_by_team) < 100:
            raise RuntimeError(
                f"Only {len(best_by_team)} primary passers found for {year}; "
                "the CFBD response shape may have changed."
            )
        print(f"  {year}: {len(best_by_team)} primary passers")

    return dict(primary), {
        year: dict(players) for year, players in player_history.items()
    }


def fetch_final_ap() -> dict[tuple[str, int], int]:
    print("Fetching final AP rankings...")
    rankings: dict[tuple[str, int], int] = {}

    for year in YEARS:
        found: dict[str, int] = {}
        attempts = (
            {"year": year, "seasonType": "postseason", "week": 1},
            {"year": year, "seasonType": "regular", "week": 16},
            {"year": year, "seasonType": "regular", "week": 15},
        )
        for params in attempts:
            payload = cfbd("/rankings", params)
            for week in payload:
                for poll in pick(week, "polls", default=[]) or []:
                    poll_name = str(pick(poll, "poll", default=""))
                    if "AP" not in poll_name.upper():
                        continue
                    for rank_row in pick(poll, "ranks", default=[]) or []:
                        school = str(pick(rank_row, "school", default="")).strip()
                        rank = integer(pick(rank_row, "rank"), 0)
                        if school and rank > 0:
                            found[school] = rank
            if found:
                break

        for school, rank in found.items():
            rankings[(school, year)] = rank
        print(f"  {year}: {len(found)} final AP teams")

    if len(rankings) < 250:
        raise RuntimeError(
            f"Final AP history is unexpectedly sparse ({len(rankings)} rows)."
        )
    return rankings


def is_experienced_transfer(
    player: str,
    current_team: str,
    previous_year: int,
    player_history: dict[int, dict[str, list[dict[str, Any]]]],
) -> bool:
    for entry in player_history.get(previous_year, {}).get(normalized(player), []):
        if (
            normalized(entry.get("team")) != normalized(current_team)
            and number(entry.get("attempts")) >= TRANSFER_ATTEMPT_THRESHOLD
        ):
            return True
    return False


def build_observations(
    coaches: dict[str, dict[int, str]],
    records: dict[str, dict[int, dict[str, Any]]],
    quarterbacks: dict[str, dict[int, dict[str, Any]]],
    player_history: dict[int, dict[str, list[dict[str, Any]]]],
    ap_rankings: dict[tuple[str, int], int],
) -> list[dict[str, Any]]:
    print("Building verified cohorts...")
    observations: list[dict[str, Any]] = []

    teams = sorted(set(records) & set(coaches) & set(quarterbacks))
    for team in teams:
        for year in range(START_YEAR + 1, END_YEAR + 1):
            previous_year = year - 1
            current_record = records[team].get(year)
            previous_record = records[team].get(previous_year)
            current_coach = coaches[team].get(year)
            previous_coach = coaches[team].get(previous_year)
            current_qb = quarterbacks[team].get(year)
            previous_qb = quarterbacks[team].get(previous_year)

            if not all(
                [current_record, previous_record, current_coach, previous_coach,
                 current_qb, previous_qb]
            ):
                continue
            if (
                current_record["games"] < MIN_COMPLETED_GAMES
                or previous_record["games"] < MIN_COMPLETED_GAMES
            ):
                continue

            coach_changed = normalized(current_coach) != normalized(previous_coach)
            qb_changed = normalized(current_qb["player"]) != normalized(previous_qb["player"])
            if not qb_changed:
                continue

            cohort = "full_reset" if coach_changed else "qb_swap"
            experienced_transfer = is_experienced_transfer(
                current_qb["player"], team, previous_year, player_history
            )
            delta = current_record["wins"] - previous_record["wins"]
            ap_rank = ap_rankings.get((team, year))

            observations.append(
                {
                    "team": team,
                    "conference": current_record["conference"],
                    "season": year,
                    "cohort": cohort,
                    "head_coach": current_coach,
                    "prev_head_coach": previous_coach,
                    "hc_changed": coach_changed,
                    "new_qb": current_qb["player"],
                    "prev_qb": previous_qb["player"],
                    "qb_type": (
                        "EXPERIENCED TRANSFER"
                        if experienced_transfer
                        else "1ST-YR STARTER / PROMOTED BACKUP"
                    ),
                    "exp_transfer": experienced_transfer,
                    "prev_wins": previous_record["wins"],
                    "wins": current_record["wins"],
                    "losses": current_record["losses"],
                    "delta": delta,
                    "ap_rank": ap_rank,
                    "result_boom_bust": (
                        "BOOM" if delta >= 3 else "BUST" if delta <= -3 else None
                    ),
                }
            )

    counts = {
        key: sum(row["cohort"] == key for row in observations)
        for key in ("full_reset", "qb_swap")
    }
    if counts["full_reset"] < 25 or counts["qb_swap"] < 100:
        raise RuntimeError(
            "Cohort output is unexpectedly sparse: "
            f"full_reset={counts['full_reset']}, qb_swap={counts['qb_swap']}. "
            "Refusing to publish."
        )
    print(
        f"  full_reset={counts['full_reset']:,}; qb_swap={counts['qb_swap']:,}; "
        "coordinator=unavailable"
    )
    return observations


def rounded_mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 1)


def sample_std(values: list[float]) -> float:
    return round(statistics.stdev(values), 1) if len(values) > 1 else 0.0


def percent(count: int, total: int) -> float:
    return round(100.0 * count / total, 1) if total else 0.0


def subgroup(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    deltas = [row["delta"] for row in rows]
    return {
        "n": len(rows),
        "avg_delta": rounded_mean(deltas),
        "boom_rate": percent(sum(value >= 3 for value in deltas), len(rows)),
        "bust_rate": percent(sum(value <= -3 for value in deltas), len(rows)),
        "won_10_plus": percent(sum(row["wins"] >= 10 for row in rows), len(rows)),
    }


def build_cohort(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    n = len(rows)
    deltas = [row["delta"] for row in rows]

    buckets = (
        ("-4 or worse", lambda value: value <= -4),
        ("-3 to -1", lambda value: -3 <= value <= -1),
        ("0 to +2", lambda value: 0 <= value <= 2),
        ("+3 to +5", lambda value: 3 <= value <= 5),
        ("+6 or more", lambda value: value >= 6),
    )
    distribution = []
    for label, predicate in buckets:
        count = sum(predicate(value) for value in deltas)
        distribution.append({"bucket": label, "count": count, "pct": percent(count, n)})

    experienced = [row for row in rows if row["exp_transfer"]]
    first_year = [row for row in rows if not row["exp_transfer"]]

    swing_source = sorted(
        rows,
        key=lambda row: (abs(row["delta"]), row["delta"], row["season"]),
        reverse=True,
    )[:20]
    swings = []
    for row in swing_source:
        sign = "+" if row["delta"] >= 0 else ""
        swings.append(
            {
                "season": row["season"],
                "team": row["team"],
                "conference": row["conference"],
                "head_coach": row["head_coach"],
                "new_qb": row["new_qb"],
                "qb_type": row["qb_type"],
                "change_type": row["qb_type"],
                "prev_wins": row["prev_wins"],
                "wins": row["wins"],
                "delta": row["delta"],
                "result_boom_bust": row["result_boom_bust"],
                "result_ap": row["ap_rank"],
                "what_happened": (
                    f"{row['new_qb']} — {row['wins']} wins "
                    f"({sign}{row['delta']} from {row['prev_wins']})"
                ),
            }
        )

    avg = rounded_mean(deltas)
    std = sample_std(deltas)
    boom = percent(sum(value >= 3 for value in deltas), n)
    bust = percent(sum(value <= -3 for value in deltas), n)
    label = "head-coach and primary-quarterback changes" if key == "full_reset" else (
        "primary-quarterback changes with the same head coach"
    )
    analysis = (
        f"Across {n} verified team-seasons from {START_YEAR + 1}–{END_YEAR}, "
        f"{label} produced an average win change of {avg:+.1f} with a "
        f"{std:.1f}-win sample standard deviation. {boom:.1f}% improved by at "
        f"least three wins and {bust:.1f}% declined by at least three wins. "
        "This is descriptive history, not a causal estimate or betting signal."
    )

    return {
        "data_status": "verified",
        "definition": label,
        "aggregate": {
            "n": n,
            "avg_win_change": avg,
            "std_dev": std,
            "best_swing": f"+{max(deltas)}" if max(deltas) >= 0 else str(max(deltas)),
            "worst_swing": str(min(deltas)),
            "boom_rate": boom,
            "bust_rate": bust,
            "won_10_plus": percent(sum(row["wins"] >= 10 for row in rows), n),
            "finished_ap_25": percent(sum(row["ap_rank"] is not None for row in rows), n),
            "ap_top_10": percent(
                sum(row["ap_rank"] is not None and row["ap_rank"] <= 10 for row in rows),
                n,
            ),
        },
        "distribution": distribution,
        "qb_split": {
            "experienced_transfer": subgroup(experienced),
            "first_year_starter": subgroup(first_year),
        },
        "analysis": analysis,
        "qualifying_2026": [],
        "biggest_swings": swings,
    }


def unavailable_coordinator_cohort() -> dict[str, Any]:
    return {
        "data_status": "unavailable",
        "definition": "New offensive coordinator, same head coach and primary quarterback",
        "unavailable_reason": (
            "CFBD coaching history identifies head coaches but does not provide the "
            "verified offensive-coordinator history required for this cohort."
        ),
        "aggregate": {"n": 0},
        "distribution": [],
        "qb_split": {},
        "analysis": (
            "Coordinator-only results are not published yet. A verified OC-history "
            "dataset is required; head-coach changes are not used as a proxy."
        ),
        "qualifying_2026": [],
        "biggest_swings": [],
    }


def validate_output(payload: dict[str, Any]) -> None:
    cohorts = payload.get("cohorts", {})
    for key in ("full_reset", "qb_swap", "coordinator"):
        if key not in cohorts:
            raise RuntimeError(f"Output is missing cohort: {key}")

    for key in ("full_reset", "qb_swap"):
        cohort = cohorts[key]
        n = integer(cohort.get("aggregate", {}).get("n"), 0)
        distribution_n = sum(integer(row.get("count"), 0) for row in cohort["distribution"])
        if n <= 0 or distribution_n != n:
            raise RuntimeError(
                f"{key} failed validation: n={n}, distribution total={distribution_n}."
            )
        for field in ("avg_win_change", "std_dev", "boom_rate", "bust_rate"):
            value = cohort["aggregate"].get(field)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise RuntimeError(f"{key}.{field} is not a finite number.")

    if cohorts["coordinator"].get("data_status") != "unavailable":
        raise RuntimeError("Coordinator cohort must remain unavailable without verified OC data.")


def main() -> None:
    coaches = fetch_coaches()
    records = fetch_records()
    quarterbacks, player_history = fetch_quarterbacks()
    ap_rankings = fetch_final_ap()
    observations = build_observations(
        coaches, records, quarterbacks, player_history, ap_rankings
    )

    by_cohort = {
        key: [row for row in observations if row["cohort"] == key]
        for key in ("full_reset", "qb_swap")
    }
    payload = {
        "meta": {
            "schema_version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "CollegeFootballData API",
            "years": f"{START_YEAR}-{END_YEAR}",
            "observation_years": f"{START_YEAR + 1}-{END_YEAR}",
            "total_observations": len(observations),
            "methodology": {
                "primary_qb": "Team leader in regular-season passing yards (minimum 200)",
                "experienced_transfer": (
                    "Current primary QB had at least 150 pass attempts for a different "
                    "FBS team in the immediately preceding season"
                ),
                "full_reset": "Verified head-coach change plus primary-QB change",
                "qb_swap": "Same verified head coach plus primary-QB change",
                "coordinator": "Unavailable until verified OC history is supplied",
                "win_change": "Current total wins minus prior-season total wins",
                "minimum_games": MIN_COMPLETED_GAMES,
            },
        },
        "cohorts": {
            "full_reset": build_cohort(by_cohort["full_reset"], "full_reset"),
            "qb_swap": build_cohort(by_cohort["qb_swap"], "qb_swap"),
            "coordinator": unavailable_coordinator_cohort(),
        },
    }
    validate_output(payload)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = OUTPUT_PATH.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(OUTPUT_PATH)

    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"Wrote {OUTPUT_PATH} ({size_kb:.1f} KB)")
    for key in ("full_reset", "qb_swap", "coordinator"):
        cohort = payload["cohorts"][key]
        print(
            f"  {key}: status={cohort['data_status']}, "
            f"n={cohort['aggregate'].get('n', 0)}"
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
