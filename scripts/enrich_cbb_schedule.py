#!/usr/bin/env python3
"""Reconcile the rolling CBB board with confirmed ESPN schedule metadata.

CBBD remains the schedule authority and supplies the game identifiers. ESPN's
team schedule feed fills confirmed tip times and broadcast designations. When
CBBD omits a game entirely, a verified ESPN event may also supply a fallback
board row if both participants map unambiguously to THI team ids. Raw ESPN
responses are never stored.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
BOARD_PATH = ROOT / "data" / "cbb" / "game_board.json"
PROFILES_PATH = ROOT / "data" / "cbb" / "team_profiles.json"
ESPN_SCHEDULE_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/"
    "mens-college-basketball/teams/{team_id}/schedule"
)


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def iso_millis(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def extract_events(payload: dict[str, Any], espn_to_cbb: dict[str, int]) -> list[dict[str, Any]]:
    rows = []
    for event in payload.get("events") or []:
        competitions = event.get("competitions") or []
        competition = competitions[0] if competitions else {}
        competitors = competition.get("competitors") or []
        mapped = []
        for competitor in competitors:
            espn_id = str((competitor.get("team") or {}).get("id") or "")
            if espn_id in espn_to_cbb:
                mapped.append({
                    "team_id": espn_to_cbb[espn_id],
                    "home_away": str(competitor.get("homeAway") or "").lower(),
                    "score": competitor.get("score"),
                })
        if len(mapped) != 2 or mapped[0]["team_id"] == mapped[1]["team_id"]:
            continue
        home = next((row for row in mapped if row["home_away"] == "home"), None)
        away = next((row for row in mapped if row["home_away"] == "away"), None)
        start = parse_time(event.get("date") or competition.get("date"))
        if start is None:
            continue
        broadcasts = sorted({
            str(((item.get("media") or {}).get("shortName") or "")).strip()
            for item in competition.get("broadcasts") or []
            if str(((item.get("media") or {}).get("shortName") or "")).strip()
        })
        status_type = ((event.get("status") or {}).get("type") or (competition.get("status") or {}).get("type") or {})
        state = str(status_type.get("state") or "pre").lower()
        completed = bool(status_type.get("completed"))
        status = "final" if completed or state == "post" else "live" if state == "in" else "scheduled"
        venue = competition.get("venue") or {}
        address = venue.get("address") or {}
        rows.append({
            "event_id": str(event.get("id") or ""),
            "pair": tuple(sorted(row["team_id"] for row in mapped)),
            "home_id": home["team_id"] if home else None,
            "away_id": away["team_id"] if away else None,
            "start": start,
            "time_valid": bool(competition.get("timeValid")),
            "broadcasts": broadcasts,
            "status": status,
            "home_score": home.get("score") if home else None,
            "away_score": away.get("score") if away else None,
            "neutral_site": bool(competition.get("neutralSite")),
            "conference_game": bool(competition.get("conferenceCompetition")),
            "venue": {
                "name": venue.get("fullName"),
                "city": address.get("city"),
                "state": address.get("state"),
            },
        })
    return rows


def enrich(
    board: dict[str, Any],
    profiles: dict[str, Any],
    fetcher: Callable[[str], dict[str, Any] | None],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    espn_to_cbb = {
        str(row.get("espn_id")): int(row["team_id"])
        for row in profiles.get("teams") or []
        if row.get("espn_id") is not None and row.get("team_id") is not None
    }
    events: dict[str, dict[str, Any]] = {}
    requests_made = 0
    fetch_errors = 0
    for espn_id in sorted(espn_to_cbb, key=lambda value: int(value)):
        requests_made += 1
        payload = fetcher(espn_id)
        if not isinstance(payload, dict):
            fetch_errors += 1
            continue
        for event in extract_events(payload, espn_to_cbb):
            key = event["event_id"] or f"{event['pair']}:{event['start'].isoformat()}"
            events[key] = event

    by_pair: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for event in events.values():
        by_pair.setdefault(event["pair"], []).append(event)

    times_updated = 0
    broadcasts_updated = 0
    matched_games = 0
    board_games = board.get("games") or []
    for game in board_games:
        try:
            pair = tuple(sorted((int(game["home"]["team_id"]), int(game["away"]["team_id"]))))
        except (KeyError, TypeError, ValueError):
            continue
        current = parse_time(game.get("start_date"))
        if current is None:
            continue
        candidates = by_pair.get(pair) or []
        if not candidates:
            continue
        event = min(candidates, key=lambda row: abs((row["start"] - current).total_seconds()))
        if abs((event["start"] - current).total_seconds()) > 3 * 86400:
            continue
        matched_games += 1
        if event["time_valid"] and (
            bool(game.get("start_time_tbd"))
            or abs((event["start"] - current).total_seconds()) >= 60
        ):
            game["start_date"] = iso_millis(event["start"])
            game["start_time_tbd"] = False
            times_updated += 1
        merged_broadcasts = sorted(set(game.get("broadcasts") or []) | set(event["broadcasts"]))
        if merged_broadcasts != (game.get("broadcasts") or []):
            game["broadcasts"] = merged_broadcasts
            broadcasts_updated += 1

    profiles_by_id = {
        int(row["team_id"]): row
        for row in profiles.get("teams") or []
        if row.get("team_id") is not None
    }
    board_pairs: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for game in board_games:
        try:
            pair = tuple(sorted((int(game["home"]["team_id"]), int(game["away"]["team_id"]))))
        except (KeyError, TypeError, ValueError):
            continue
        board_pairs.setdefault(pair, []).append(game)

    meta = board.setdefault("meta", {})
    range_start = parse_time(meta.get("start_date"))
    range_end = parse_time(meta.get("end_date"))
    added_game_ids: list[str] = []
    conflicts_quarantined = 0
    espn_mapped_team_ids = set(espn_to_cbb.values())

    def score_value(value: Any) -> int | float:
        try:
            parsed = float(value)
            return int(parsed) if parsed.is_integer() else parsed
        except (TypeError, ValueError):
            return 0

    def conference_label(profile: dict[str, Any]) -> str | None:
        conference = profile.get("conference") or {}
        return conference.get("abbreviation") or conference.get("name")

    for event in sorted(events.values(), key=lambda row: (row["start"], row["event_id"])):
        if (
            not event["event_id"]
            or event["home_id"] is None
            or event["away_id"] is None
            or not event["time_valid"]
            or (event["status"] == "scheduled" and event["start"] < now - timedelta(hours=2))
            or (range_start is not None and event["start"] < range_start)
            or (range_end is not None and event["start"] > range_end)
        ):
            continue
        existing = board_pairs.get(event["pair"]) or []
        if any(
            (current := parse_time(game.get("start_date"))) is not None
            and abs((event["start"] - current).total_seconds()) <= 3 * 86400
            for game in existing
        ):
            continue

        home_profile = profiles_by_id.get(event["home_id"])
        away_profile = profiles_by_id.get(event["away_id"])
        if home_profile is None or away_profile is None:
            continue

        # Quarantine a conflicting provider placeholder instead of deleting it.
        # This preserves the source row for audit while keeping it out of the
        # projection board. A row is quarantined only when its tip time is TBD,
        # it shares a team with this verified ESPN event inside 36 hours, and
        # ESPN has no corresponding event for the provider's participant pair.
        event_team_ids = set(event["pair"])
        for game in board_games:
            if str(game.get("status") or "").lower() != "scheduled" or not game.get("start_time_tbd"):
                continue
            try:
                game_pair = tuple(sorted((int(game["home"]["team_id"]), int(game["away"]["team_id"]))))
            except (KeyError, TypeError, ValueError):
                continue
            current = parse_time(game.get("start_date"))
            if (
                not event_team_ids.intersection(game_pair)
                or game_pair == event["pair"]
                or current is None
                or abs((event["start"] - current).total_seconds()) > 36 * 3600
                or by_pair.get(game_pair)
                or all(team_id in espn_mapped_team_ids for team_id in game_pair)
            ):
                continue
            game["status"] = "schedule_conflict"
            game["schedule_reconciliation"] = {
                "state": "quarantined_provider_placeholder",
                "conflicts_with_espn_event_id": event["event_id"],
                "verified_at_utc": now.isoformat().replace("+00:00", "Z"),
            }
            conflicts_quarantined += 1

        game_id: int | str = int(event["event_id"]) if event["event_id"].isdigit() else f"espn:{event['event_id']}"
        fallback_game = {
            "game_id": game_id,
            "start_date": iso_millis(event["start"]),
            "status": event["status"],
            "start_time_tbd": False,
            "neutral_site": event["neutral_site"],
            "conference_game": event["conference_game"],
            "home": {
                "team_id": event["home_id"],
                "team": home_profile.get("team"),
                "conference": conference_label(home_profile),
                "score": score_value(event["home_score"]),
            },
            "away": {
                "team_id": event["away_id"],
                "team": away_profile.get("team"),
                "conference": conference_label(away_profile),
                "score": score_value(event["away_score"]),
            },
            "venue": event["venue"],
            "broadcasts": event["broadcasts"],
            "market": None,
            "schedule_source": "ESPN verified fallback",
            "external_ids": {"espn": event["event_id"], "cbbd": None},
        }
        board_games.append(fallback_game)
        board_pairs.setdefault(event["pair"], []).append(fallback_game)
        added_game_ids.append(str(game_id))

    board_games.sort(key=lambda row: (str(row.get("start_date") or ""), str(row.get("game_id") or "")))
    board["games"] = board_games

    meta["schedule_enrichment"] = {
        "source": "ESPN public team schedule metadata",
        "policy": "CBBD remains primary. Confirmed ESPN events enrich known games and may add a missing game only when both participants map unambiguously; conflicting TBD provider placeholders are quarantined.",
        "generated_at_utc": now.isoformat().replace("+00:00", "Z"),
        "team_requests": requests_made,
        "fetch_errors": fetch_errors,
        "unique_events": len(events),
        "matched_games": matched_games,
        "times_updated": times_updated,
        "broadcasts_updated": broadcasts_updated,
        "games_added": len(added_game_ids),
        "added_game_ids": added_game_ids,
        "conflicts_quarantined": conflicts_quarantined,
        "raw_api_data_stored": False,
    }
    meta["game_count"] = len(board_games)
    meta["games_with_broadcasts"] = sum(bool(row.get("broadcasts")) for row in board_games)
    meta["games_with_confirmed_time"] = sum(not row.get("start_time_tbd") for row in board_games)
    return board


def fetch_schedule(team_id: str) -> dict[str, Any] | None:
    url = ESPN_SCHEDULE_URL.format(team_id=team_id) + "?" + urlencode({"season": 2027, "seasontype": 2})
    try:
        request = Request(url, headers={"User-Agent": "The Hammer Index schedule enrichment/1.0"})
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", type=Path, default=BOARD_PATH)
    parser.add_argument("--profiles", type=Path, default=PROFILES_PATH)
    args = parser.parse_args()
    board = json.loads(args.board.read_text())
    profiles = json.loads(args.profiles.read_text())
    output = enrich(board, profiles, fetch_schedule)
    atomic_write(args.board, output)
    status = output["meta"]["schedule_enrichment"]
    print(
        "CBB schedule enrichment: "
        f"{status['matched_games']} matched, {status['times_updated']} times, "
        f"{status['broadcasts_updated']} broadcasts, {status['fetch_errors']} fetch errors"
    )


if __name__ == "__main__":
    main()
