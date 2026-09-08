#!/usr/bin/env python3
"""Post deduplicated The Hammer Index updates to a Discord webhook.

This is a display/notification layer only. It reads generated artifacts and
never changes Model A, projections, markets, settlements, or postgame data.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "data" / "snapshots" / "latest_snapshot.json"
SETTLED_PATH = ROOT / "data" / "reports" / "settled_results.json"
POSTGAME_PATH = ROOT / "data" / "postgame_analytics.json"
SIGNAL_REPORT_PATH = ROOT / "data" / "reports" / "signal_report.json"
STATE_PATH = ROOT / "data" / "discord_notification_state.json"

SITE_URL = os.environ.get("THI_SITE_URL", "https://thehammerindex.com").rstrip("/")
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

SIGNAL_NAMES = {
    "ALIGNED": "ALIGNED",
    "AGREE W/ MARKET": "ALIGNED",
    "SLIGHT EDGE": "SMALL EDGE",
    "LEAN": "SMALL EDGE",
    "SMALL EDGE": "SMALL EDGE",
    "EDGE": "PLAY",
    "PLAY": "PLAY",
    "STRONG EDGE": "MATERIAL DISAGREEMENT",
    "MATERIAL DISAGREEMENT": "MATERIAL DISAGREEMENT",
    "OUTLIER": "OUTLIER",
}
SIGNAL_RANK = {
    "ALIGNED": 0,
    "SMALL EDGE": 1,
    "PLAY": 2,
    "MATERIAL DISAGREEMENT": 3,
    "OUTLIER": 4,
}
SIGNAL_COLOR = {
    "PLAY": 0x17755B,
    "MATERIAL DISAGREEMENT": 0xC77800,
    "OUTLIER": 0x8D45C7,
}
TOTAL_RANK = {"NONE": 0, "TOTAL LEAN": 1, "TOTAL WATCH": 2}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARNING: could not read {path.relative_to(ROOT)}: {exc}")
        return default


def initial_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "initialized": False,
        "updated_at_utc": None,
        "signals": {},
        "totals": {},
        "finals": {},
        "postgame": {},
    }


def save_state(state: dict[str, Any]) -> None:
    state["updated_at_utc"] = utc_now()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(STATE_PATH)


def number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def signed(value: Any, decimals: int = 1) -> str:
    parsed = number(value)
    if parsed is None:
        return "—"
    if abs(parsed) < 0.05:
        parsed = 0.0
    return f"{parsed:+.{decimals}f}"


def team_line(team: str, home_spread: Any, home_team: str) -> str:
    spread = number(home_spread)
    if spread is None:
        return team
    team_spread = spread if team == home_team else -spread
    return f"{team} {signed(team_spread)}"


def game_key(row: dict[str, Any]) -> str:
    raw = row.get("game_id") or row.get("game_key") or row.get("result_game_id")
    if raw not in (None, ""):
        return str(raw)
    away = str(row.get("away_team") or "").casefold().strip()
    home = str(row.get("home_team") or "").casefold().strip()
    week = str(row.get("week") or "")
    return f"{week}:{away}@{home}"


def translated_signal(value: Any) -> str:
    return SIGNAL_NAMES.get(str(value or "").strip().upper(), "ALIGNED")


def confidence_for(signal: str, report: dict[str, Any]) -> str:
    return str(report.get("signals", {}).get(signal, {}).get("confidence") or "DEVELOPING")


def total_status(snapshot: dict[str, Any]) -> tuple[str, str | None, float | None]:
    model_total = number((snapshot.get("public_projection") or {}).get("total"))
    market_total = number((snapshot.get("market_at_snapshot") or {}).get("total"))
    if model_total is None or market_total is None:
        return "NONE", None, None
    difference = model_total - market_total
    edge = abs(difference)
    direction = "OVER" if difference > 0 else "UNDER" if difference < 0 else None
    if edge >= 7.0:
        return "TOTAL WATCH", direction, edge
    if edge >= 4.0:
        return "TOTAL LEAN", direction, edge
    return "NONE", direction, edge


def embed(title: str, description: str, color: int) -> dict[str, Any]:
    return {
        "title": title[:256],
        "description": description[:4096],
        "url": SITE_URL,
        "color": color,
        "footer": {"text": "The Hammer Index · Experimental, not betting advice"},
        "timestamp": utc_now(),
    }


def signal_events(
    snapshots: list[dict[str, Any]],
    state: dict[str, Any],
    report: dict[str, Any],
) -> list[tuple[dict[str, Any], Callable[[], None]]]:
    events: list[tuple[dict[str, Any], Callable[[], None]]] = []
    signal_state = state.setdefault("signals", {})
    total_state = state.setdefault("totals", {})

    for snapshot in snapshots:
        if not snapshot.get("tracking_eligible", False):
            continue
        key = game_key(snapshot)
        away = str(snapshot.get("away_team") or "Away")
        home = str(snapshot.get("home_team") or "Home")
        comparison = snapshot.get("comparison_at_snapshot") or {}
        market = snapshot.get("market_at_snapshot") or {}
        projection = snapshot.get("public_projection") or {}
        signal = translated_signal(comparison.get("market_disagreement_status"))
        rank = SIGNAL_RANK.get(signal, 0)
        side = str(comparison.get("preferred_side") or "")
        previous = signal_state.get(key, {})
        previous_rank = int(previous.get("rank", 0))
        previous_side = str(previous.get("side") or "")
        was_qualifying = previous_rank >= SIGNAL_RANK["PLAY"]
        is_qualifying = rank >= SIGNAL_RANK["PLAY"] and bool(side)

        should_alert = is_qualifying and (
            not was_qualifying or rank != previous_rank or side != previous_side
        )
        should_withdraw = was_qualifying and not is_qualifying

        if should_alert:
            label = "NEW THI SIGNAL" if not was_qualifying else "THI SIGNAL UPDATE"
            market_side = team_line(side, market.get("home_spread"), home)
            fair_side = team_line(side, projection.get("home_spread"), home)
            description = "\n".join(
                [
                    f"**{away} at {home}**",
                    f"**Model side:** {market_side}",
                    f"**THI fair line:** {fair_side}",
                    f"**Model edge:** {number(comparison.get('disagreement')) or 0:.1f} points",
                    f"**Signal:** {signal}",
                    f"**Confidence:** {confidence_for(signal, report)}",
                    f"**Market source:** {market.get('bookmaker') or 'Available market'}",
                ]
            )
            new_value = {"rank": rank, "signal": signal, "side": side}
            events.append(
                (
                    embed(f"🔨 {label}", description, SIGNAL_COLOR.get(signal, 0x17755B)),
                    lambda k=key, v=new_value: signal_state.__setitem__(k, v),
                )
            )
        elif should_withdraw:
            description = "\n".join(
                [
                    f"**{away} at {home}**",
                    "This matchup no longer meets the PLAY threshold.",
                    f"**Current signal:** {signal}",
                ]
            )
            new_value = {"rank": rank, "signal": signal, "side": side}
            events.append(
                (
                    embed("↘️ THI SIGNAL WITHDRAWN", description, 0x7A8288),
                    lambda k=key, v=new_value: signal_state.__setitem__(k, v),
                )
            )
        elif not previous:
            signal_state[key] = {"rank": rank, "signal": signal, "side": side}

        tier, direction, edge = total_status(snapshot)
        total_rank = TOTAL_RANK[tier]
        prior_total = total_state.get(key, {})
        prior_rank = int(prior_total.get("rank", 0))
        prior_direction = prior_total.get("direction")
        total_changed = total_rank > 0 and (
            prior_rank == 0 or total_rank != prior_rank or direction != prior_direction
        )
        total_withdrawn = prior_rank > 0 and total_rank == 0

        if total_changed:
            description = "\n".join(
                [
                    f"**{away} at {home}**",
                    f"**{direction} {market.get('total')}**",
                    f"**THI projected total:** {projection.get('total')}",
                    f"**Difference:** {edge:.1f} points",
                    f"**Classification:** {tier}",
                ]
            )
            new_value = {"rank": total_rank, "tier": tier, "direction": direction}
            events.append(
                (
                    embed("📊 THI TOTAL SIGNAL", description, 0x1F6FAE),
                    lambda k=key, v=new_value: total_state.__setitem__(k, v),
                )
            )
        elif total_withdrawn:
            description = f"**{away} at {home}**\nThis total no longer meets the 4-point flag threshold."
            new_value = {"rank": 0, "tier": "NONE", "direction": direction}
            events.append(
                (
                    embed("↘️ THI TOTAL SIGNAL WITHDRAWN", description, 0x7A8288),
                    lambda k=key, v=new_value: total_state.__setitem__(k, v),
                )
            )
        elif not prior_total:
            total_state[key] = {"rank": total_rank, "tier": tier, "direction": direction}

    return events


def earliest_settled_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row.get("result_settled") or number(row.get("snapshot_home_spread")) is None:
            continue
        key = game_key(row)
        current = selected.get(key)
        if current is None or str(row.get("captured_at_utc") or "") < str(current.get("captured_at_utc") or ""):
            selected[key] = row
    return selected


def final_events(
    rows: list[dict[str, Any]], state: dict[str, Any]
) -> list[tuple[dict[str, Any], Callable[[], None]]]:
    events: list[tuple[dict[str, Any], Callable[[], None]]] = []
    final_state = state.setdefault("finals", {})
    for key, row in earliest_settled_rows(rows).items():
        if key in final_state:
            continue
        away = str(row.get("away_team") or "Away")
        home = str(row.get("home_team") or "Home")
        away_points = int(number(row.get("away_points")) or 0)
        home_points = int(number(row.get("home_points")) or 0)
        result = {"W": "ATS WIN", "L": "ATS LOSS", "P": "ATS PUSH"}.get(
            str(row.get("ats_result") or "").upper(), "FINAL"
        )
        result_emoji = {"ATS WIN": "✅", "ATS LOSS": "❌", "ATS PUSH": "➖"}.get(result, "🏁")
        preferred = str(row.get("preferred_side") or "Model side")
        side_line = team_line(preferred, row.get("snapshot_home_spread"), home)
        signal = translated_signal(row.get("signal"))
        details = [
            f"**FINAL — {away} {away_points}, {home} {home_points}**",
            f"**Tracked side:** {side_line}",
            f"**Result:** {result}",
            f"**Pregame signal:** {signal}",
        ]
        clv = number(row.get("clv_points"))
        if clv is not None:
            details.append(f"**Closing-line value:** {signed(clv)} points")
        events.append(
            (
                embed(f"{result_emoji} THI RESULT — {result}", "\n".join(details), 0x17755B if result == "ATS WIN" else 0xC5433B if result == "ATS LOSS" else 0xB28A14),
                lambda k=key: final_state.__setitem__(k, {"announced": True}),
            )
        )
    return events


def postgame_events(
    games: dict[str, dict[str, Any]] | list[dict[str, Any]], state: dict[str, Any]
) -> list[tuple[dict[str, Any], Callable[[], None]]]:
    events: list[tuple[dict[str, Any], Callable[[], None]]] = []
    postgame_state = state.setdefault("postgame", {})
    values = list(games.values()) if isinstance(games, dict) else list(games)
    for game in values:
        if game.get("analysis_status") != "available":
            continue
        key = game_key(game)
        if postgame_state.get(key, {}).get("status") == "available":
            continue
        away = str(game.get("away_team") or "Away")
        home = str(game.get("home_team") or "Home")
        headline = game.get("headline") or {}
        win_expectancy = headline.get("postgame_win_expectancy") or {}
        expected_margin = headline.get("expected_margin") or {}
        reality = headline.get("reality_check") or {}
        description = "\n".join(
            [
                f"**{away} at {home}**",
                f"**PGWE:** {away} {win_expectancy.get('away_pct', '—')}% · {home} {win_expectancy.get('home_pct', '—')}%",
                f"**Expected margin:** {expected_margin.get('leader', '—')} by {abs(number(expected_margin.get('home')) or number(expected_margin.get('away')) or 0):.1f}",
                f"**Reality Check:** {reality.get('label', 'AVAILABLE')}",
            ]
        )
        events.append(
            (
                embed("🔨 POSTGAME ANALYSIS AVAILABLE", description, 0x8D45C7),
                lambda k=key: postgame_state.__setitem__(k, {"status": "available"}),
            )
        )
    return events


def baseline(state: dict[str, Any], snapshots: list[dict[str, Any]], rows: list[dict[str, Any]], postgames: Any) -> None:
    signals = state.setdefault("signals", {})
    totals = state.setdefault("totals", {})
    for snapshot in snapshots:
        if not snapshot.get("tracking_eligible", False):
            continue
        key = game_key(snapshot)
        comparison = snapshot.get("comparison_at_snapshot") or {}
        signal = translated_signal(comparison.get("market_disagreement_status"))
        tier, direction, _ = total_status(snapshot)
        signals[key] = {
            "rank": SIGNAL_RANK.get(signal, 0),
            "signal": signal,
            "side": str(comparison.get("preferred_side") or ""),
        }
        totals[key] = {"rank": TOTAL_RANK[tier], "tier": tier, "direction": direction}
    for key in earliest_settled_rows(rows):
        state.setdefault("finals", {})[key] = {"announced": True}
    values = list(postgames.values()) if isinstance(postgames, dict) else list(postgames)
    for game in values:
        if game.get("analysis_status") == "available":
            state.setdefault("postgame", {})[game_key(game)] = {"status": "available"}
    state["initialized"] = True


def post_payload(embeds: list[dict[str, Any]], content: str | None = None) -> None:
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")
    payload: dict[str, Any] = {"username": "The Hammer Index Report"}
    if embeds:
        payload["embeds"] = embeds[:10]
    if content:
        payload["content"] = content[:2000]
    body = json.dumps(payload).encode("utf-8")

    for attempt in range(1, 5):
        request = urllib.request.Request(
            WEBHOOK_URL,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "TheHammerIndex/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status in (200, 204):
                    return
                raise RuntimeError(f"Discord returned HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 4:
                try:
                    retry_after = float(json.loads(exc.read().decode("utf-8")).get("retry_after", 1))
                except Exception:
                    retry_after = 1.0
                time.sleep(max(1.0, retry_after))
                continue
            if 500 <= exc.code < 600 and attempt < 4:
                time.sleep(attempt * 2)
                continue
            raise RuntimeError(f"Discord webhook failed with HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            if attempt < 4:
                time.sleep(attempt * 2)
                continue
            raise RuntimeError(f"Discord webhook connection failed: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", action="store_true", help="Record current events without posting them")
    parser.add_argument("--test", action="store_true", help="Send one connection test and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print new alerts without posting or changing state")
    args = parser.parse_args()

    if args.test:
        post_payload([], "🔨 **The Hammer Index Report is connected.** Automated model updates are ready.")
        print("Discord connection test sent.")
        return 0

    if not WEBHOOK_URL and not args.bootstrap and not args.dry_run:
        print("DISCORD_WEBHOOK_URL is not configured; skipping Discord alerts.")
        return 0

    latest = load_json(SNAPSHOT_PATH, {"snapshots": []})
    settled = load_json(SETTLED_PATH, {"rows": []})
    postgame = load_json(POSTGAME_PATH, {"games": {}})
    signal_report = load_json(SIGNAL_REPORT_PATH, {"signals": {}})
    snapshots = latest.get("snapshots", []) if isinstance(latest, dict) else []
    rows = settled.get("rows", []) if isinstance(settled, dict) else []
    postgames = postgame.get("games", {}) if isinstance(postgame, dict) else {}
    state = load_json(STATE_PATH, initial_state())
    if not isinstance(state, dict):
        state = initial_state()

    if args.bootstrap or not state.get("initialized"):
        baseline(state, snapshots, rows, postgames)
        save_state(state)
        print("Discord alert baseline initialized; existing events were not posted.")
        return 0

    events = []
    events.extend(signal_events(snapshots, state, signal_report))
    events.extend(final_events(rows, state))
    events.extend(postgame_events(postgames, state))

    if not events:
        save_state(state)
        print("No new Discord alerts.")
        return 0

    if args.dry_run:
        print(json.dumps([item[0] for item in events], indent=2))
        print(f"Dry run: {len(events)} alert(s); state not changed.")
        return 0

    for start in range(0, len(events), 10):
        batch = events[start : start + 10]
        post_payload([item[0] for item in batch])
        for _, apply_update in batch:
            apply_update()
        save_state(state)
        print(f"Posted Discord alert batch containing {len(batch)} update(s).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
