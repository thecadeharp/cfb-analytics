#!/usr/bin/env python3
"""Resolve exact CBB arena coordinates from named OpenStreetMap objects.

The resolver is deliberately conservative: it never accepts a city centroid,
street, postcode or unnamed result. Ambiguous responses stay in a review file
and therefore cannot activate mileage.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
PHOTON = "https://photon.komoot.io/api/"
VERSION = "thi-cbb-verified-venues-v1.1"
STATE_NAMES = {
    "AL":"alabama","AK":"alaska","AZ":"arizona","AR":"arkansas","CA":"california","CO":"colorado","CT":"connecticut",
    "DE":"delaware","DC":"district of columbia","FL":"florida","GA":"georgia","HI":"hawaii","ID":"idaho","IL":"illinois",
    "IN":"indiana","IA":"iowa","KS":"kansas","KY":"kentucky","LA":"louisiana","ME":"maine","MD":"maryland",
    "MA":"massachusetts","MI":"michigan","MN":"minnesota","MS":"mississippi","MO":"missouri","MT":"montana",
    "NE":"nebraska","NV":"nevada","NH":"new hampshire","NJ":"new jersey","NM":"new mexico","NY":"new york",
    "NC":"north carolina","ND":"north dakota","OH":"ohio","OK":"oklahoma","OR":"oregon","PA":"pennsylvania",
    "RI":"rhode island","SC":"south carolina","SD":"south dakota","TN":"tennessee","TX":"texas","UT":"utah",
    "VT":"vermont","VA":"virginia","WA":"washington","WV":"west virginia","WI":"wisconsin","WY":"wyoming",
}
GENERIC = {"arena", "center", "centre", "coliseum", "complex", "fieldhouse", "gym", "gymnasium", "pavilion", "s", "stadium", "the"}
VENUE_TAGS = {
    "leisure": {"fitness_centre", "ice_rink", "sports_centre", "stadium"},
    "building": {"civic", "college", "sports_hall", "stadium", "university", "yes"},
    "amenity": {"college", "community_centre", "events_centre", "events_venue", "university"},
    "tourism": {"attraction", "resort"},
}


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def identity(venue: dict) -> str:
    return "|".join(str(venue.get(key) or "").strip() for key in ("name", "city", "state"))


def target_venues(board: dict) -> list[dict]:
    found = {}
    for game in board.get("games") or []:
        venue = game.get("venue") or {}
        if venue.get("name") and venue.get("city") and venue.get("state"):
            found.setdefault(identity(venue), {key: venue.get(key) for key in ("name", "city", "state")})
    return [found[key] for key in sorted(found)]


def name_score(expected: str, actual: str) -> float:
    left, right = norm(expected), norm(actual)
    if not left or not right:
        return 0.0
    sequence = SequenceMatcher(None, left, right).ratio()
    a = set(left.split()) - GENERIC
    b = set(right.split()) - GENERIC
    overlap = len(a & b) / max(1, len(a | b))
    containment = 1.0 if min(len(a), len(b)) >= 2 and (a <= b or b <= a) else 0.0
    return max(sequence, overlap, containment)


def choose(venue: dict, payload: dict) -> tuple[dict | None, list[dict]]:
    accepted = []
    expected_city = norm(venue.get("city"))
    expected_state = STATE_NAMES.get(str(venue.get("state") or "").upper(), norm(venue.get("state")))
    for feature in payload.get("features") or []:
        properties = feature.get("properties") or {}
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        result_name = properties.get("name")
        osm_type = str(properties.get("osm_type") or "").upper()
        osm_id = properties.get("osm_id")
        osm_key = str(properties.get("osm_key") or "").lower()
        osm_value = str(properties.get("osm_value") or "").lower()
        result_city = norm(properties.get("city") or properties.get("town") or properties.get("village"))
        result_state = norm(properties.get("state"))
        score = name_score(str(venue.get("name") or ""), str(result_name or ""))
        if (
            properties.get("countrycode") != "US" or not result_name or len(coordinates) < 2
            or osm_type not in {"N", "W", "R"} or osm_id is None
            or osm_value not in VENUE_TAGS.get(osm_key, set())
            or result_state != expected_state or score < 0.72
            or (result_city != expected_city and score < 0.92)
        ):
            continue
        accepted.append({
            "latitude": float(coordinates[1]), "longitude": float(coordinates[0]),
            "source_url": f"https://www.openstreetmap.org/{ {'N':'node','W':'way','R':'relation'}[osm_type] }/{osm_id}",
            "source_name": result_name, "match_score": round(score, 4),
            "source_object": {"osm_type": osm_type, "osm_key": osm_key, "osm_value": osm_value},
            "verification_method": "named_osm_object_schedule_location_match",
        })
    type_priority = {"W": 0, "R": 1, "N": 2}
    key_priority = {"leisure": 0, "building": 1, "amenity": 2, "tourism": 3, "place": 4}
    accepted.sort(key=lambda row: (
        -row["match_score"],
        key_priority.get(row["source_object"]["osm_key"], 9),
        type_priority.get(row["source_object"]["osm_type"], 9),
        row["source_url"],
    ))
    if not accepted:
        return None, []
    return accepted[0], accepted


def fetch(venue: dict) -> dict:
    query = f"{venue['name']}, {venue['city']}, {venue['state']}, USA"
    url = f"{PHOTON}?{urlencode({'q': query, 'limit': 8})}"
    raw = subprocess.check_output([
        "curl", "-L", "--fail", "--silent", "--show-error", "--connect-timeout", "3", "--max-time", "5",
        "--user-agent", "TheHammerIndex-VenueAudit/1.0", url,
    ], text=True)
    return json.loads(raw)


def build_payloads(venues: dict, reviews: list, status: Counter, targets: list, verified_at: str) -> tuple[dict, dict]:
    registry = {
        "meta": {
            "version": VERSION, "generated_at_utc": verified_at,
            "status": "complete" if targets and len(venues) == len(targets) else "partial" if venues else "source_required",
            "policy": "Only named OpenStreetMap venue objects matching the scheduled state and either the city or an exceptionally strong venue name are accepted. City centroids, streets, postcodes, unnamed results and non-venue object classes are prohibited.",
            "source_attribution": "© OpenStreetMap contributors; Open Database License (ODbL).",
            "target_venues": len(targets), "verified_venues": len(venues),
            "venues_pending_review": max(0, len(targets) - len(venues)),
            "coverage_pct": round(100 * len(venues) / len(targets), 2) if targets else 0.0,
        },
        "venues": venues,
    }
    review = {"meta": {"version": "thi-cbb-venue-geocode-review-v1.0", "generated_at_utc": verified_at, "counts": dict(status)}, "venues": reviews}
    return registry, review


def resolve(board: dict, existing: dict, delay: float = 0.25, checkpoint: Callable | None = None) -> tuple[dict, dict]:
    verified_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    venues = dict((existing or {}).get("venues") or {})
    reviews = []
    status = Counter()
    targets = target_venues(board)
    def save_checkpoint(index: int) -> None:
        if checkpoint and (index + 1) % 10 == 0:
            checkpoint(*build_payloads(venues, reviews, status, targets, verified_at))
    for index, venue in enumerate(targets):
        key = identity(venue)
        if key in venues:
            status["preserved"] += 1
            save_checkpoint(index)
            continue
        try:
            selected, candidates = choose(venue, fetch(venue))
        except Exception as exc:
            reviews.append({"venue": venue, "status": "fetch_error", "error": f"{type(exc).__name__}: {exc}"})
            status["fetch_error"] += 1
            save_checkpoint(index)
            continue
        if selected:
            venues[key] = {**selected, "verified_at_utc": verified_at}
            status["verified"] += 1
        else:
            reviews.append({"venue": venue, "status": "manual_review", "candidates": candidates})
            status["manual_review"] += 1
        if index + 1 < len(targets):
            time.sleep(delay)
        save_checkpoint(index)
    return build_payloads(venues, reviews, status, targets, verified_at)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", type=Path, default=ROOT / "data/cbb/projection_board.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/cbb/verified_venue_geocodes.json")
    parser.add_argument("--review", type=Path, default=ROOT / "data/cbb/venue_geocode_review.json")
    parser.add_argument("--delay", type=float, default=0.25)
    args = parser.parse_args()
    board = json.loads(args.board.read_text())
    existing = json.loads(args.output.read_text()) if args.output.exists() else {"venues": {}}
    def save(registry: dict, review: dict) -> None:
        args.output.write_text(json.dumps(registry, indent=2, allow_nan=False) + "\n")
        args.review.write_text(json.dumps(review, indent=2, allow_nan=False) + "\n")
    registry, review = resolve(board, existing, max(0.0, args.delay), save)
    save(registry, review)
    print(VERSION, registry["meta"]["verified_venues"], "of", registry["meta"]["target_venues"], "venues verified")


if __name__ == "__main__":
    main()
