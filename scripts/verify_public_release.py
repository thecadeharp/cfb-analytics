#!/usr/bin/env python3
"""Fail-closed local and post-deployment verification for THI's public contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

PATHS = {
    "manifest": "data/cbb/cache_manifest.json",
    "cbb_power": "data/cbb/model/display_power_ratings.json",
    "cbb_priors": "data/cbb/model/current_priors.json",
    "cbb_model": "data/cbb/model/model_card.json",
    "cbb_candidate": "data/cbb/model/preseason_index_candidate.json",
    "cbb_sos": "data/cbb/frozen/preseason_sos_2027.json",
    "cbb_tracking": "data/cbb/model_tracking.json",
    "cbb_health": "data/cbb/platform_health.json",
    "cbb_roster_audit": "data/cbb/roster_audit.json",
    "cbb_players": "data/cbb/player_ratings.json",
    "cbb_board": "data/cbb/projection_board.json",
    "cfb_board": "data/projections.json",
    "cfb_player_projections": "data/player_projections.json",
    "operations": "data/reports/operations_readiness.json",
}


def fetch_asset(base_url: str, relative: str) -> tuple[dict, bytes]:
    url = f"{base_url.rstrip('/')}/{relative}?canary=1"
    request = Request(url, headers={"User-Agent": "THI public-release-canary/2.0", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"{relative} returned HTTP {response.status}")
        raw = response.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"{relative} is not parseable JSON: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"{relative} must contain a JSON object")
    return payload, raw


def load_local(root: Path, relative: str) -> tuple[dict, bytes]:
    raw = (root / relative).read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{relative} must contain a JSON object")
    return payload, raw


def unique_non_null(rows: list[dict], key: str) -> bool:
    values = [row.get(key) for row in rows]
    return bool(values) and all(value is not None for value in values) and len(values) == len(set(values))


def verify(payloads: dict[str, dict], raw_assets: dict[str, bytes] | None = None) -> list[str]:
    checks: list[tuple[bool, str]] = []
    required = set(PATHS)
    if not required <= set(payloads):
        raise RuntimeError("Public release canary failed: missing payloads " + ", ".join(sorted(required - set(payloads))))
    checks.append((True, "Every required release asset is present and parseable"))

    manifest = payloads["manifest"]
    power = payloads["cbb_power"]
    priors = payloads["cbb_priors"]
    model = payloads["cbb_model"]
    candidate = payloads["cbb_candidate"]
    sos = payloads["cbb_sos"]
    tracking = payloads["cbb_tracking"]
    health = payloads["cbb_health"]
    roster = payloads["cbb_roster_audit"]
    players = payloads["cbb_players"]
    cbb_board = payloads["cbb_board"]
    cfb_board = payloads["cfb_board"]
    cfb_player_projections = payloads["cfb_player_projections"]
    operations = payloads["operations"]
    power_teams = power.get("teams") or []
    prior_teams = priors.get("teams") or []
    sos_teams = sos.get("teams") or []
    sos_game_ids = {opponent.get("game_id") for row in sos_teams for opponent in (row.get("opponents") or []) if opponent.get("game_id") is not None}
    cbb_games = cbb_board.get("games") or []
    cfb_games = cfb_board.get("games") or []
    projected_players = cfb_player_projections.get("projections") or []

    checks.extend([
        (manifest.get("meta", {}).get("version") == "thi-static-cache-manifest-v1.0", "Cache manifest is current schema"),
        (manifest.get("meta", {}).get("asset_count") == len(manifest.get("assets") or {}), "Manifest asset count matches contents"),
        (power.get("meta", {}).get("version") == "thi-cbb-roster-power-v3.0", "CBB Roster-Era Power v3 is published"),
        (len(power_teams) >= 300 and all(isinstance(row, dict) for row in power_teams), "CBB power board has typed national coverage"),
        (unique_non_null(power_teams, "team_id"), "CBB power team identifiers are unique"),
        (power.get("meta", {}).get("team_count") == len(power_teams), "CBB power record count matches metadata"),
        (str(power.get("meta", {}).get("model_usage", "")).startswith("display_only"), "CBB power remains isolated from Model A"),
        (len(prior_teams) >= 300 and unique_non_null(prior_teams, "team_id"), "CBB production priors have unique national coverage"),
        (len(cbb_games) >= 300 and unique_non_null(cbb_games, "game_id"), "CBB projection board is populated with unique games"),
        (cbb_board.get("meta", {}).get("game_count") == len(cbb_games), "CBB game count matches metadata"),
        (len(cfb_games) >= 50 and unique_non_null(cfb_games, "game_id"), "CFB projection board is populated with unique games"),
        (cfb_player_projections.get("meta", {}).get("version") == "thi-cfb-player-projections-v0.1-research", "CFB player projections use the research schema"),
        (cfb_player_projections.get("meta", {}).get("status") == "research_only", "CFB player projections remain research-only"),
        (cfb_player_projections.get("meta", {}).get("model_usage") == "display_only_not_used_by_model_a", "CFB player projections remain isolated from Model A"),
        (len(projected_players) >= 500 and unique_non_null(projected_players, "athlete_id"), "CFB player projection board has unique national coverage"),
        (cfb_player_projections.get("meta", {}).get("projection_count") == len(projected_players), "CFB player projection count matches metadata"),
        (health.get("meta", {}).get("status") in {"healthy", "attention_required"}, "CBB health contract is readable"),
        (operations.get("meta", {}).get("version") == "thi-operations-readiness-v1.0", "Operations report is current schema"),
        (model.get("meta", {}).get("model_version") == cbb_board.get("meta", {}).get("model_version"), "CBB board and model-card versions match"),
        (tracking.get("meta", {}).get("projection_board_version") == cbb_board.get("meta", {}).get("version"), "Tracking ledger matches the projection board"),
        (candidate.get("evaluation", {}).get("promotion_eligible") is False, "Roster-aware challenger remains ineligible for promotion"),
        (candidate.get("prospective_protocol", {}).get("candidate_state") in {"research_awaiting_preseason_freeze", "research_blocked_roster_audit"}, "Roster-aware challenger remains research-only"),
        ("does not feed Model A" in str(candidate.get("meta", {}).get("model_usage", "")), "Challenger remains isolated from production"),
        (sos.get("meta", {}).get("version") == "thi-cbb-preseason-sos-snapshot-v1.0", "Projected SOS snapshot is current schema"),
        (sos.get("meta", {}).get("immutable") is True and sos.get("meta", {}).get("status") == "immutable_preseason_snapshot", "Projected SOS snapshot is immutable"),
        (sos.get("meta", {}).get("game_count") == len(sos_game_ids), "Projected SOS game count is internally consistent"),
        (len(sos_teams) >= 300 and unique_non_null(sos_teams, "team_id"), "Projected SOS has unique national coverage"),
        (sos.get("meta", {}).get("team_count") == len(sos_teams), "Projected SOS team count matches metadata"),
        (sos.get("meta", {}).get("power_version") in {power.get("meta", {}).get("version"), "thi-cbb-display-power-v2.0"}, "Projected SOS retains a declared power-version reference"),
    ])

    neutral_ok = all(float(((((game.get("projection") or {}).get("matchup_context") or {}).get("home_court") or {}).get("points") or 0)) == 0 for game in cbb_games if game.get("neutral_site"))
    checks.append((neutral_ok, "All CBB neutral-site games have zero home-court input"))
    audit_status = roster.get("meta", {}).get("status")
    published = int((health.get("coverage") or {}).get("published_roster_players") or 0)
    checks.append((audit_status == "passed" or published == 0, "Failed roster audit cannot publish player data"))
    checks.append((audit_status == "passed" or len(players.get("players") or []) == 0, "Failed roster audit strips the public player payload"))
    if audit_status != "passed":
        checks.extend([
            (candidate.get("meta", {}).get("roster_audit_status") == audit_status, "Challenger reports the independent roster-audit status"),
            (candidate.get("meta", {}).get("roster_verification_status") == "withheld_by_thi_audit", "Challenger cannot claim verified rosters after a failed audit"),
            (candidate.get("prospective_protocol", {}).get("candidate_state") == "research_blocked_roster_audit", "Failed roster audit blocks the challenger research clock"),
            (not any(row.get("roster_verified") is True for row in candidate.get("teams") or []), "Failed roster audit clears challenger team verification flags"),
        ])

    if raw_assets is not None:
        manifest_assets = manifest.get("assets") or {}
        for key, relative in PATHS.items():
            if key == "manifest" or relative not in manifest_assets:
                continue
            raw = raw_assets.get(key, b"")
            record = manifest_assets[relative]
            checks.append((record.get("bytes") == len(raw), f"Manifest byte count matches {relative}"))
            checks.append((record.get("version") == hashlib.sha256(raw).hexdigest()[:16], f"Manifest content version matches {relative}"))

    failures = [label for passed, label in checks if not passed]
    if failures:
        raise RuntimeError("Public release canary failed: " + "; ".join(failures))
    return [label for passed, label in checks if passed]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://thehammerindex.com")
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    loaded = {key: load_local(args.root, relative) if args.root else fetch_asset(args.base_url, relative) for key, relative in PATHS.items()}
    checks = verify({key: item[0] for key, item in loaded.items()}, {key: item[1] for key, item in loaded.items()})
    print(f"THI public release canary passed: {len(checks)} checks")
    print("Software/data release verified. This result does not authorize or imply model promotion.")


if __name__ == "__main__":
    main()
