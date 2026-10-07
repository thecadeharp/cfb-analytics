#!/usr/bin/env python3
"""Exercise the CBB market-to-grade lifecycle without live sportsbook data."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.build_cbb_model_tracking import build_tracking
    from scripts.build_variance_prospective_tracker import build as build_variance
    from scripts.refresh_cbb_markets import refresh
except ModuleNotFoundError:
    from build_cbb_model_tracking import build_tracking
    from build_variance_prospective_tracker import build as build_variance
    from refresh_cbb_markets import refresh

ROOT = Path(__file__).resolve().parents[1]
VERSION = "thi-cbb-opening-night-rehearsal-v1.0"


def run_rehearsal() -> dict[str, Any]:
    game = {
        "game_id": 9900001,
        "start_date": "2026-11-03T01:00:00Z",
        "status": "scheduled",
        "neutral_site": True,
        "conference_game": False,
        "venue": {"name": "THI Test Arena", "city": "Test City", "state": "US"},
        "away": {"team_id": 901, "team": "THI Away"},
        "home": {"team_id": 902, "team": "THI Listed"},
        "projection": {
            "home_margin": 4.0,
            "total": 134.0,
            "spread_edge": 6.0,
            "spread_signal_eligible": True,
            "spread_signal_tier": "play",
            "signal_confidence": "developing",
            "totals_signal_eligible": False,
            "matchup_context": {
                "home_court": {"points": 0.0, "source": "neutral_site"},
                "margin_drivers": [{"feature": "efg_edge", "margin_points": 2.1}],
            },
        },
    }
    board = {"meta": {"version": "thi-cbb-projection-board-v0.5", "season": 2027, "model_version": "rehearsal"}, "games": [game]}
    active_ids = {str(game["game_id"])}
    open_time = datetime(2026, 11, 2, 14, tzinfo=timezone.utc)
    open_lines = [{"gameId": game["game_id"], "lines": [{"spread": -2.0, "spreadOpen": -2.0, "overUnder": 128.0, "overUnderOpen": 128.0}]}]
    board, history, _ = refresh(board, None, open_lines, open_time, active_ids)
    opening_spread = board["games"][0]["market"]["opening_home_spread"]
    published_board = deepcopy(board)

    moved_time = datetime(2026, 11, 2, 18, tzinfo=timezone.utc)
    moved_lines = [{"gameId": game["game_id"], "lines": [{"spread": -3.0, "spreadOpen": -2.5, "overUnder": 127.0, "overUnderOpen": 127.5}]}]
    board, history, _ = refresh(board, history, moved_lines, moved_time, active_ids)
    current_market = deepcopy(board["games"][0]["market"])
    frozen = build_variance({"frozen": []}, {"games": []}, board, {"games": []}, moved_time)

    # The published projection keeps its first qualifying market. The later
    # observation is attached separately as the close so CLV cannot rewrite
    # the original decision.
    final_board = deepcopy(published_board)
    final_game = final_board["games"][0]
    final_game["status"] = "final"
    final_game["away"]["score"] = 65
    final_game["home"]["score"] = 72
    final_game["closing_market"] = deepcopy(current_market)
    tracking = build_tracking(final_board)
    settled = build_variance(frozen, {"games": []}, final_board, {"games": []}, datetime(2026, 11, 3, 4, tzinfo=timezone.utc))

    home_context_features = {str(row.get("feature")) for row in final_game["projection"]["matchup_context"]["margin_drivers"]}
    settled_rows = [row for row in settled["frozen"] if row.get("result") in {"W", "L", "P"}]
    checks = {
        "neutral_context_zero": final_game["projection"]["matchup_context"]["home_court"]["points"] == 0.0 and not {"home_court", "early_home", "nonconference_home", "team_home_court_adjustment"}.intersection(home_context_features),
        "opening_line_frozen": opening_spread == -2.0 and current_market["opening_home_spread"] == -2.0,
        "market_move_captured": current_market["consensus_home_spread"] == -3.0 and current_market["spread_move"] == -1.0 and len(history["games"][str(game["game_id"])]) == 2,
        "variance_qualifier_frozen": len(frozen["frozen"]) >= 2 and all(row.get("neutral_site") is True for row in frozen["frozen"]),
        "variance_final_settled": bool(settled_rows) and all(row["result"] in {"W", "L", "P"} for row in settled_rows),
        "model_signal_graded": tracking["summary"]["spread"]["games"] == 1 and tracking["spread_decisions"][0]["result"] == "win",
        "closing_line_value_calculated": tracking["spread_decisions"][0]["clv"] == 1.0,
    }
    return {
        "meta": {
            "version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "passed" if all(checks.values()) else "failed",
            "scope": "Synthetic neutral-site open, market move, prospective freeze, final score, Variance Lab settlement, official model grading and CLV.",
        },
        "checks": checks,
        "evidence": {
            "opening_home_spread": opening_spread,
            "current_home_spread": current_market["consensus_home_spread"],
            "spread_move": current_market["spread_move"],
            "market_snapshots": len(history["games"][str(game["game_id"])]),
            "variance_qualifiers": len(frozen["frozen"]),
            "settled_qualifiers": len(settled_rows),
            "model_grade": tracking["spread_decisions"][0]["result"],
            "clv": tracking["spread_decisions"][0]["clv"],
        },
    }


def main() -> None:
    output = ROOT / "data/cbb/opening_night_rehearsal.json"
    payload = run_rehearsal()
    output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(VERSION, payload["meta"]["status"])
    if payload["meta"]["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
