#!/usr/bin/env python3
"""Audit production data freshness, coverage, and release-state contracts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def nested(payload: dict, path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def first_time(payload: dict, paths: list[str]) -> datetime | None:
    for path in paths:
        parsed = parse_time(nested(payload, path))
        if parsed:
            return parsed
    return None


def within_age(stamp: datetime | None, now: datetime, max_age_hours: float) -> bool:
    if stamp is None:
        return False
    age = (now - stamp).total_seconds() / 3600
    return -0.25 <= age <= max_age_hours


def postgame_covers_results(results: dict, postgame: dict) -> bool:
    """Confirm every published final has a corresponding postgame record.

    Postgame analytics are immutable once built and the builder intentionally
    leaves the file untouched when no new final or retry is due. Coverage is
    therefore the meaningful live-readiness check; a recently rewritten
    timestamp alone is not.
    """
    result_ids = {
        str(game.get("game_id"))
        for game in (results.get("games") or [])
        if isinstance(game, dict) and game.get("game_id") is not None
    }
    postgame_rows = postgame.get("games") or {}
    if isinstance(postgame_rows, dict):
        postgame_ids = {str(game_id) for game_id in postgame_rows}
    else:
        postgame_ids = {
            str(game.get("game_id"))
            for game in postgame_rows
            if isinstance(game, dict) and game.get("game_id") is not None
        }
    return result_ids.issubset(postgame_ids)


def load(root: Path, relative: str) -> dict:
    path = root / relative
    if not path.exists():
        raise RuntimeError(f"Missing production asset: {relative}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Production asset must contain an object: {relative}")
    return payload


def current_cfb_week(projections: dict, now: datetime) -> int | None:
    upcoming = []
    for game in projections.get("games") or []:
        kickoff = parse_time(game.get("start_date"))
        if kickoff and kickoff >= now and str(game.get("status") or "").lower() != "final":
            try:
                upcoming.append(int(game.get("week")))
            except (TypeError, ValueError):
                pass
    return min(upcoming, default=None)


def acceptable_completed_weeks(active_week: int, now: datetime) -> set[int]:
    """Return valid weekly-data cutoffs, including the published delivery window.

    CFBD Tier 3 training inputs normally arrive Sunday evening and no later than
    Monday. When the projection board rolls to the next week early Sunday, the
    prior completed-week metrics are therefore still valid through Monday ET.
    """
    acceptable = {active_week - 1, active_week}
    if now.astimezone(EASTERN).weekday() in {6, 0}:
        acceptable.add(active_week - 2)
    return {week for week in acceptable if week >= 0}


def audit(root: Path, now: datetime) -> dict:
    assets: dict[str, dict] = {}
    findings: list[dict] = []

    def check(
        name: str,
        relative: str,
        timestamp_paths: list[str],
        max_age_hours: float,
        coverage: dict[str, tuple[str, int]],
        severity: str = "critical",
    ) -> dict:
        payload = load(root, relative)
        stamp = first_time(payload, timestamp_paths)
        age = (now - stamp).total_seconds() / 3600 if stamp else None
        checks = {}
        checks["timestamp_present"] = stamp is not None
        checks["fresh"] = within_age(stamp, now, max_age_hours)
        for label, (path, minimum) in coverage.items():
            value = nested(payload, path)
            count = len(value) if isinstance(value, (list, dict)) else int(value or 0)
            checks[label] = count >= minimum
        status = "pass" if all(checks.values()) else "fail"
        row = {
            "status": status,
            "severity": severity,
            "path": relative,
            "generated_at_utc": stamp.isoformat().replace("+00:00", "Z") if stamp else None,
            "age_hours": round(age, 2) if age is not None else None,
            "max_age_hours": max_age_hours,
            "checks": checks,
        }
        assets[name] = row
        if status == "fail":
            findings.append({"severity": severity, "dataset": name, "failed_checks": [key for key, passed in checks.items() if not passed]})
        return payload

    weekend = now.weekday() in {3, 4, 5, 6}
    projections = check("cfb_projections", "data/projections.json", ["meta.generated"], 10 if weekend else 30, {"games": ("games", 800)})
    live_window = any(
        kickoff is not None and -3600 <= (now - kickoff).total_seconds() <= 5 * 3600
        for kickoff in (parse_time(game.get("start_date")) for game in projections.get("games") or [])
    )
    metrics = check("cfb_team_metrics", "data/cfb_metrics.json", ["meta.generated"], 192, {"teams": ("teams", 130)})
    advanced = check("cfb_advanced_metrics", "data/advanced_metrics.json", ["meta.generated"], 192, {"teams": ("teams", 130)})
    check("cfb_external_ratings", "data/external_ratings.json", ["meta.last_updated", "meta.generated_at_utc"], 192, {"teams": ("teams", 130)})
    check("cfb_open_weekly_ratings", "data/open_weekly_ratings.json", ["meta.generated_at", "meta.generated"], 192, {"teams": ("teams", 130)})
    check("cfb_thi_power", "data/thi_power_ratings.json", ["meta.generated_at"], 192, {"teams": ("teams", 130)})
    check("cfb_index", "data/cfb_thi_index.json", ["meta.generated_at"], 192, {"teams": ("teams", 130)})
    check("cfb_observed_ratings", "data/thi_observed_ratings.json", ["meta.generated_at"], 192, {"teams": ("teams", 130)})
    check("cfb_metric_profiles", "data/team_metric_profiles.json", ["meta.generated_at"], 192, {"teams": ("teams", 130)})
    check("cfb_situational_profiles", "data/thi_situational_profiles.json", ["meta.generated_at"], 192, {"teams": ("teams", 130)})
    check("cfb_season_outlook", "data/thi_season_outlook.json", ["meta.generated_at"], 192, {"teams": ("teams", 130)})
    check("cfb_roster_assets", "data/roster_assets.json", ["meta.generated_at"], 192, {"teams": ("teams", 130), "players": ("meta.player_count", 5000)})
    players = check("cfb_player_intelligence", "data/player_intelligence.json", ["meta.generated_at"], 192, {"teams": ("teams", 130), "players": ("players", 3000)})
    player_audit = check("cfb_player_audit", "data/player_intelligence_audit.json", ["meta.generated_at_utc"], 192, {}, severity="critical")
    check("cfb_player_projections", "data/player_projections.json", ["meta.generated_at_utc"], 192, {"projections": ("projections", 500)}, severity="warning")
    check("cfb_schedule_context", "data/schedule_context.json", ["meta.generated_at"], 192, {"games": ("games", 700)})
    check("cfb_coach_ats", "data/coach_ats_trends.json", ["meta.generated_at_utc"], 192, {"coaches": ("coaches", 130)})
    check("cfb_team_market_records", "data/team_market_performance.json", ["meta.generated_at"], 192, {"teams": ("teams", 130)})
    check("cfb_portal", "data/portal_2026.json", ["player_source.generated_at", "generated_at"], 192, {"teams": ("teams", 40), "players": ("players", 1000)})
    score_slo = 0.5 if live_window else 6
    results = check("cfb_scores", "data/results.json", ["meta.generated_at"], score_slo, {"completed_games": ("meta.completed_games", 300)})
    live_scores = check("cfb_live_scores", "data/live_scores.json", ["meta.generated_at"], score_slo, {}, severity="critical")
    actual_live_games = len(live_scores.get("games") or [])
    settlement_slo = 2 if actual_live_games else 8
    postgame = check("cfb_postgame", "data/postgame_analytics.json", ["meta.generated_at"], settlement_slo, {"games": ("games", 300)})
    postgame_aligned = postgame_covers_results(results, postgame)
    assets["cfb_postgame"]["checks"]["finals_aligned"] = postgame_aligned
    if not postgame_aligned:
        assets["cfb_postgame"]["status"] = "fail"
        findings.append({"severity": "critical", "dataset": "cfb_postgame", "failed_checks": ["finals_aligned"]})
    check("cfb_signal_records", "data/reports/signal_report.json", ["generated_at_utc"], settlement_slo, {"signals": ("signals", 1)})
    check("cfb_availability", "data/roster_notes.json", ["meta.generated_at_utc"], 2.5 if weekend else 14, {"source_health": ("meta.source_health", 6)})
    check("cbb_projection_board", "data/cbb/projection_board.json", ["meta.generated_at_utc"], 15, {"games": ("games", 300)})
    check("cbb_team_profiles", "data/cbb/team_profiles.json", ["meta.generated_at_utc"], 15, {"teams": ("teams", 350)})
    check("cbb_platform_health", "data/cbb/platform_health.json", ["meta.generated_at_utc"], 15, {"checks": ("checks", 10)})
    check("cbb_market_contract", "data/cbb/market_contract.json", ["meta.generated_at_utc"], 15, {"games": ("games", 300)})
    cbb_players = check("cbb_player_research", "data/cbb/player_ratings.json", ["meta.generated_at_utc"], 15, {}, severity="warning")
    cbb_roster = check("cbb_roster_audit", "data/cbb/roster_audit.json", ["meta.generated_at_utc"], 15, {}, severity="warning")

    active_week = current_cfb_week(projections, now)
    acceptable_metric_weeks = sorted(acceptable_completed_weeks(active_week, now)) if active_week is not None else []
    week_checks = {
        "active_week": active_week,
        "metrics_through_week": nested(metrics, "meta.through_week"),
        "advanced_through_week": nested(advanced, "meta.through_week"),
        "players_through_week": nested(players, "meta.through_week"),
        "acceptable_metric_weeks": acceptable_metric_weeks,
        "weekly_delivery_grace_active": bool(
            active_week is not None and active_week - 2 in acceptable_metric_weeks
        ),
    }
    if active_week is not None:
        for key in ("metrics_through_week", "advanced_through_week"):
            value = week_checks[key]
            if not isinstance(value, int) or value not in acceptable_metric_weeks:
                findings.append({"severity": "critical", "dataset": key, "failed_checks": ["completed_week_alignment"]})
        player_week = week_checks["players_through_week"]
        if not isinstance(player_week, int) or player_week < active_week - 1 or player_week > active_week:
            findings.append({"severity": "critical", "dataset": "players_through_week", "failed_checks": ["active_week_alignment"]})

    if nested(player_audit, "meta.status") != "passed" or not all((player_audit.get("checks") or {}).values()):
        findings.append({"severity": "critical", "dataset": "cfb_player_audit", "failed_checks": ["integrity_status"]})
    source_health = nested(load(root, "data/roster_notes.json"), "meta.source_health") or {}
    bad_sources = [name for name, row in source_health.items() if row.get("status") not in {"ok", "stale_fallback"}]
    if bad_sources:
        findings.append({"severity": "warning", "dataset": "cfb_availability", "failed_checks": [f"source:{name}" for name in bad_sources]})

    cbb_roster_status = nested(cbb_roster, "meta.status")
    cbb_published = int(nested(cbb_players, "meta.player_count") or 0)
    if cbb_roster_status != "passed" or cbb_published == 0:
        findings.append({
            "severity": "warning", "dataset": "cbb_players",
            "failed_checks": ["withheld_until_independent_roster_audit_passes"],
        })

    critical = [row for row in findings if row["severity"] == "critical"]
    return {
        "meta": {
            "version": "thi-data-freshness-audit-v1.0",
            "generated_at_utc": now.isoformat().replace("+00:00", "Z"),
            "status": "failed" if critical else ("attention_required" if findings else "healthy"),
            "critical_failure_count": len(critical),
            "warning_count": sum(row["severity"] == "warning" for row in findings),
        },
        "week_alignment": week_checks,
        "live_game_window": live_window,
        "actual_live_games": actual_live_games,
        "datasets": assets,
        "findings": findings,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--now")
    args = parser.parse_args()
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        raise RuntimeError("--now must be an ISO-8601 timestamp")
    report = audit(args.root, now)
    text = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    if args.strict and report["meta"]["critical_failure_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
