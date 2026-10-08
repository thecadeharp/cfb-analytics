#!/usr/bin/env python3
"""Publish a factual five-pillar readiness audit for THI's paid research product."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load(path: str, fallback: Any = None) -> Any:
    target = ROOT / path
    return json.loads(target.read_text()) if target.exists() else fallback


def jsonl(path: str) -> list[dict[str, Any]]:
    target = ROOT / path
    if not target.exists():
        return []
    return [json.loads(line) for line in target.read_text().splitlines() if line.strip()]


def nested(row: dict[str, Any], *keys: str) -> Any:
    value: Any = row
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def build() -> dict[str, Any]:
    snapshots = jsonl("data/snapshots/projection_market_snapshots.jsonl")
    closings = jsonl("data/snapshots/closing_lines.jsonl")
    cfb_scorecard = load("data/reports/weekly_model_scorecard.json", {}) or {}
    cfb_signals = load("data/reports/signal_report.json", {}) or {}
    cbb_tracking = load("data/cbb/model_tracking.json", {}) or {}
    cbb_health = load("data/cbb/platform_health.json", {}) or {}
    cbb_market_history = load("data/cbb/market_snapshots.json", {}) or {}
    cbb_snapshot_count = sum(len(rows) for rows in (cbb_market_history.get("games") or {}).values())

    priced_snapshots = sum(bool(nested(row, "market_at_snapshot", "reference_spread")) for row in snapshots)
    priced_closings = sum(bool(nested(row, "closing_market", "reference_spread")) for row in closings)
    settled_cfb = int(nested(cfb_scorecard, "season", "settled_games") or 0)
    cbb_decisions = int(nested(cbb_tracking, "summary", "spread", "games") or 0)
    signal_rules = nested(cfb_signals, "confidence_system", "meaning") or ""

    return {
        "meta": {
            "version": "thi-commercial-readiness-v1.0",
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "scope": "Operational and evidence readiness for a paid THI research product; this is not a claim that a betting edge has validated.",
        },
        "verdict": {
            "research_subscription": "ready_with_guardrails",
            "betting_edge_product": "not_ready",
            "recommended_positioning": "Paid college-sports research, model transparency, team intelligence and decision support.",
            "prohibited_positioning": "Do not market THI as a proven profitable picks service unless the prospective price-aware validation gate clears.",
        },
        "pillars": [
            {
                "id": "prospective_validation",
                "label": "Prospective validation",
                "status": "in_progress",
                "summary": f"CFB has {len(snapshots):,} immutable observations across {int(nested(cfb_scorecard, 'season', 'frozen_snapshot_games') or 0):,} frozen games and {settled_cfb:,} settled games. CBB automation is ready but has {cbb_decisions:,} settled 2027 spread decisions.",
                "pass_condition": "A full predeclared sample settles with complete price records, stability checks and corrected significance tests.",
            },
            {
                "id": "real_prices",
                "label": "Exact market prices",
                "status": "collector_upgraded_history_incomplete",
                "summary": f"Existing CFB history has {priced_snapshots:,}/{len(snapshots):,} opening snapshots and {priced_closings:,}/{len(closings):,} near-kickoff captures with paired single-book prices. New CFB captures preserve them. CBBD exposes paired moneyline prices but not spread juice, so CBB ATS price validation still needs a two-sided sportsbook feed.",
                "pass_condition": "Every evaluated play stores one named book, exact line, both prices and timestamp at selection and close.",
            },
            {
                "id": "predeclared_rules",
                "label": "Predeclared validation rules",
                "status": "ready",
                "summary": "The production validator requires a per-play no-vig baseline, exact or Poisson-binomial testing, Holm correction, outlier dependency checks and rolling stability. " + str(signal_rules),
                "pass_condition": "Rules remain frozen before outcomes are observed and every tested bucket stays in the correction family.",
            },
            {
                "id": "operational_proof",
                "label": "Operational proof",
                "status": "in_progress",
                "summary": f"CFB collection, closing capture and settlement are active. CBB platform health is {nested(cbb_health, 'meta', 'status') or 'unknown'} with {int(nested(cbb_health, 'coverage', 'games') or 0):,} scheduled games and {cbb_snapshot_count:,} market observations; live CBB proof begins when books post lines.",
                "pass_condition": "Complete a season with scheduled jobs healthy, no silent gaps, reconciled finals and published incident notes for material failures.",
            },
            {
                "id": "data_rights",
                "label": "Paid-data rights",
                "status": "ready_with_open_items",
                "summary": "CFBD/CBBD and The Odds API permit commercial analytical products under their current terms while restricting raw redistribution. SportsDataverse code is MIT licensed. Source-level rights for third-party underlying data, team marks and any ESPN/NCAA-derived fields remain open items before scaling paid access.",
                "pass_condition": "Maintain a source register, comply with attribution/redistribution limits and resolve every source-pending asset or field.",
            },
        ],
        "rights_register": [
            {
                "source": "CollegeFootballData.com / CollegeBasketballData.com",
                "status": "commercial_use_permitted_with_limits",
                "url": "https://collegebasketballdata.com/terms",
                "conditions": "Derived models, paid sites, dashboards and reasonable factual display are allowed; do not redistribute a raw bulk mirror or competing API.",
            },
            {
                "source": "The Odds API",
                "status": "commercial_use_permitted_with_limits",
                "url": "https://the-odds-api.com/terms-and-conditions.html",
                "conditions": "Integrated display, research and derived analytics are allowed; do not resell or repackage the feed as a standalone data product.",
            },
            {
                "source": "cfbfastR / SportsDataverse code",
                "status": "code_license_verified_source_data_pending",
                "url": "https://cfbfastr.sportsdataverse.org/",
                "conditions": "Package code is MIT licensed; that license does not itself grant rights to every upstream dataset loaded by the package.",
            },
            {
                "source": "Team names, logos and third-party endpoint-derived fields",
                "status": "source_pending",
                "url": None,
                "conditions": "Inventory marks and upstream fields, then document a license, permission, fair-use rationale or replacement for each paid-product dependency.",
            },
        ],
    }


def main() -> None:
    output = ROOT / "data/reports/commercial_readiness.json"
    payload = build()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    main()
