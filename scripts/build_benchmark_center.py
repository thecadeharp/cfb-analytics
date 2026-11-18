#!/usr/bin/env python3
"""Build THI's public benchmark, calibration and market-audit dataset.

This presentation-only build reads frozen forecasts and settled decisions,
computes deterministic uncertainty intervals, and never changes a projection,
grade, signal, model weight or promotion state.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.tracked_decisions import frozen_rows
except ModuleNotFoundError:
    from tracked_decisions import frozen_rows

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "reports" / "benchmark_center.json"
BOOTSTRAP_SEED = 42
BOOTSTRAP_ITERATIONS = 2_000
WILSON_Z = 1.96
MINIMUM_SAMPLE = 100
CFB_MARKET_POLICY = "cfb-executable-quote-and-closing-proxy-v1"

SIGNAL_NAMES = {
    "AGREE W/ MARKET": "ALIGNED", "ALIGNED": "ALIGNED",
    "SLIGHT EDGE": "SMALL EDGE", "LEAN": "SMALL EDGE", "SMALL EDGE": "SMALL EDGE",
    "EDGE": "PLAY", "PLAY": "PLAY", "STRONG EDGE": "MATERIAL DISAGREEMENT",
    "MATERIAL DISAGREEMENT": "MATERIAL DISAGREEMENT", "OUTLIER": "OUTLIER",
}
CBB_SIGNAL_NAMES = {
    "aligned": "ALIGNED", "small": "SMALL EDGE", "play": "PLAY",
    "material": "MATERIAL DISAGREEMENT", "outlier": "OUTLIER",
    "total_lean": "TOTAL LEAN", "total_watch": "TOTAL WATCH",
}


def load(path: str) -> Any:
    return json.loads((ROOT / path).read_text())


def num(value: Any) -> float | None:
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def iso_date(value: Any) -> str | None:
    text = str(value or "")
    return text[:10] if len(text) >= 10 else None


def venue_map() -> dict[str, str]:
    schedule = load("data/schedule_context.json").get("games", {})
    return {str(key): "neutral" if row.get("neutral_site") else "campus" for key, row in schedule.items()}


def source_name(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower().startswith("consensus"):
        return "Consensus fallback"
    aliases = {
        "Draft Kings": "DraftKings", "draftkings": "DraftKings",
        "fanduel": "FanDuel", "betonlineag": "BetOnline",
        "williamhill_us": "Caesars", "betrivers": "BetRivers",
        "betmgm": "BetMGM", "fanatics": "Fanatics",
    }
    return aliases.get(text, aliases.get(text.lower(), text or "Unspecified"))


def cfb_rows() -> tuple[list[dict[str, Any]], str]:
    source = load("data/reports/settled_results.json")
    venues = venue_map()
    clv_rows = load("data/reports/clv_report.json").get("rows", [])
    clv_by_snapshot = {str(row.get("snapshot_id")): row for row in clv_rows if row.get("snapshot_id")}
    output = []
    grading_version = source.get("report_version") or "prospective-settlement-unversioned"
    for key, row in frozen_rows(source.get("rows", [])).items():
        if row.get("tracking_eligible", True) is False or not row.get("result_settled"):
            continue
        spread, actual_margin = num(row.get("model_home_spread")), num(row.get("actual_home_margin"))
        total, actual_total = num(row.get("model_total")), num(row.get("actual_total"))
        probability = num(row.get("model_home_win_probability"))
        predicted_margin = -spread if spread is not None else None
        home_won = actual_margin is not None and actual_margin > 0
        clv_row = clv_by_snapshot.get(str(row.get("snapshot_id") or ""), {})
        clv_points = num(clv_row.get("clv_points") if clv_row.get("clv_points") is not None else row.get("clv_points"))
        freeze_ts = row.get("captured_at_utc")
        line_source = source_name(row.get("snapshot_bookmaker"))
        output.append({
            "season": 2026, "sport": "cfb", "game_id": key, "date": iso_date(row.get("start_date")),
            "venue": venues.get(key, "unknown"), "home_team": row.get("home_team"), "away_team": row.get("away_team"),
            "predicted_margin": predicted_margin, "actual_margin": actual_margin,
            "predicted_total": total, "actual_total": actual_total, "home_win_probability": probability,
            "margin_error": predicted_margin - actual_margin if predicted_margin is not None and actual_margin is not None else None,
            "total_error": total - actual_total if total is not None and actual_total is not None else None,
            "brier": (probability / 100 - (1 if home_won else 0)) ** 2 if probability is not None and actual_margin not in (None, 0) else None,
            "signal": SIGNAL_NAMES.get(str(row.get("signal") or "").upper(), str(row.get("signal") or "").upper()),
            "preferred_side": row.get("preferred_side"), "ats_result": row.get("ats_result"), "clv": clv_points,
            "line_source": line_source, "line_source_raw": row.get("snapshot_bookmaker"), "line_sources": [line_source],
            "model_version": row.get("model_version") or "production-model-a-2026-week1-freeze-v1",
            "freeze_ts": freeze_ts, "freeze_ts_status": "captured" if freeze_ts else "not_archived",
            "market_policy_version": CFB_MARKET_POLICY, "grading_policy_version": grading_version,
            "env_status": "production",
        })
    return output, grading_version


def cbb_sources(game: dict[str, Any]) -> list[str]:
    market = game.get("closing_market") or game.get("market") or {}
    names = [source_name(row.get("provider")) for row in market.get("book_lines") or [] if row.get("provider")]
    if not names and market.get("source"):
        names = [source_name(market.get("source"))]
    return sorted(set(names))


def cbb_rows() -> tuple[list[dict[str, Any]], dict[str, list[str]], dict[str, Any]]:
    board = load("data/cbb/projection_board.json")
    market_contract = load("data/cbb/market_contract.json")
    meta = board.get("meta", {})
    market_version = market_contract.get("meta", {}).get("version") or "thi-cbb-market-contract-unversioned"
    output, sources_by_game = [], {}
    for game in board.get("games", []):
        game_id = str(game.get("game_id"))
        sources_by_game[game_id] = cbb_sources(game)
        if game.get("status") != "final":
            continue
        home, away, projection = game.get("home") or {}, game.get("away") or {}, game.get("projection") or {}
        hp, ap = num(home.get("score")), num(away.get("score"))
        margin, total = num(projection.get("home_margin")), num(projection.get("total"))
        probability = num(projection.get("home_win_probability"))
        if hp is None or ap is None:
            continue
        actual_margin, actual_total = hp - ap, hp + ap
        freeze_ts = projection.get("generated_at_utc")
        output.append({
            "season": meta.get("season"), "sport": "cbb", "game_id": game_id,
            "date": iso_date(game.get("start_date")), "venue": "neutral" if game.get("neutral_site") else "campus",
            "home_team": home.get("team"), "away_team": away.get("team"),
            "predicted_margin": margin, "actual_margin": actual_margin, "predicted_total": total,
            "actual_total": actual_total, "home_win_probability": probability,
            "margin_error": margin - actual_margin if margin is not None else None,
            "total_error": total - actual_total if total is not None else None,
            "brier": (probability / 100 - (1 if actual_margin > 0 else 0)) ** 2 if probability is not None and actual_margin != 0 else None,
            "line_sources": sources_by_game[game_id],
            "model_version": projection.get("model_version") or meta.get("model_version"),
            "freeze_ts": freeze_ts, "freeze_ts_status": "captured" if freeze_ts else "not_archived",
            "market_policy_version": market_version, "grading_policy_version": "thi-cbb-model-tracking-v0.3",
            "env_status": "research",
        })
    return output, sources_by_game, {"board": meta, "market": market_contract.get("meta", {})}


def cbb_decisions(sources_by_game: dict[str, list[str]], meta: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    tracking = load("data/cbb/model_tracking.json")
    tracking_meta = tracking.get("meta", {})
    output = {"spread": [], "total": []}
    for kind, source in (("spread", "spread_decisions"), ("total", "total_decisions")):
        for row in tracking.get(source, []):
            signal = row.get("signal_tier") or row.get("total_tier") or row.get("research_tier")
            result = {"win": "W", "loss": "L", "push": "P"}.get(str(row.get("result") or "").lower())
            game_id = str(row.get("game_id"))
            output[kind].append({
                "season": tracking_meta.get("season"), "sport": "cbb", "decision_type": kind,
                "game_id": game_id, "date": row.get("game_date_et") or iso_date(row.get("start_date")),
                "venue": "neutral" if row.get("neutral_site") else "campus",
                "away_team": row.get("away_team"), "home_team": row.get("home_team"),
                "signal": CBB_SIGNAL_NAMES.get(str(signal or "").lower(), signal), "result": result,
                "clv": num(row.get("clv")), "pregame_line": row.get("pregame_line", row.get("pregame_total")),
                "closing_line": row.get("closing_line", row.get("closing_total")),
                "line_sources": sources_by_game.get(game_id, []),
                "model_version": tracking_meta.get("model_version") or meta["board"].get("model_version"),
                "freeze_ts": None, "freeze_ts_status": "decision_ledger_only",
                "market_policy_version": meta["market"].get("version"),
                "grading_policy_version": tracking_meta.get("version"), "env_status": "research",
            })
    return output


def stable_rng(label: str) -> random.Random:
    digest = hashlib.sha256(f"{BOOTSTRAP_SEED}|{label}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    index = (len(ordered) - 1) * probability
    low, high = math.floor(index), math.ceil(index)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def bootstrap(values: list[float], statistic: Callable[[list[float]], float], label: str) -> dict[str, Any]:
    if not values:
        return {"value": None, "ci_low": None, "ci_high": None, "n": 0, "method": "fixed_seed_bootstrap"}
    point = statistic(values)
    if len(values) == 1:
        low = high = point
    else:
        rng = stable_rng(label)
        estimates = [statistic([values[rng.randrange(len(values))] for _ in values]) for _ in range(BOOTSTRAP_ITERATIONS)]
        low, high = percentile(estimates, .025), percentile(estimates, .975)
    return {"value": point, "ci_low": low, "ci_high": high, "n": len(values), "method": "fixed_seed_bootstrap"}


def wilson(successes: int, trials: int) -> dict[str, Any]:
    if not trials:
        return {"value": None, "ci_low": None, "ci_high": None, "n": 0, "method": "wilson_95"}
    p = successes / trials
    denominator = 1 + WILSON_Z ** 2 / trials
    center = (p + WILSON_Z ** 2 / (2 * trials)) / denominator
    half = WILSON_Z * math.sqrt(p * (1 - p) / trials + WILSON_Z ** 2 / (4 * trials ** 2)) / denominator
    return {"value": 100 * p, "ci_low": 100 * max(0, center - half), "ci_high": 100 * min(1, center + half), "n": trials, "method": "wilson_95"}


def slice_rows(rows: list[dict[str, Any]], sport: str, days: str, venue: str) -> list[dict[str, Any]]:
    selected = [row for row in rows if row.get("sport") == sport and (venue == "all" or row.get("venue") == venue)]
    if days == "all":
        return selected
    dates = [date.fromisoformat(row["date"]) for row in rows if row.get("sport") == sport and row.get("date")]
    if not dates:
        return []
    cutoff = max(dates) - timedelta(days=int(days))
    return [row for row in selected if row.get("date") and date.fromisoformat(row["date"]) >= cutoff]


def source_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    covered = 0
    for row in rows:
        sources = sorted(set(row.get("line_sources") or ([row.get("line_source")] if row.get("line_source") else [])))
        if sources:
            covered += 1
        counts.update(sources)
    return {
        "n_games": len(rows), "n_with_source": covered,
        "counting_rule": "A multi-book CBB game contributes once to each available provider; provider counts can exceed the game total. CFB contributes its frozen execution source or consensus fallback once.",
        "providers": [{"source": key, "games": value, "coverage_pct": 100 * value / len(rows) if rows else None} for key, value in counts.most_common()],
    }


def predictive_metrics(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    margin = [num(row.get("margin_error")) for row in rows]
    margin = [value for value in margin if value is not None]
    total = [num(row.get("total_error")) for row in rows]
    total = [value for value in total if value is not None]
    brier = [num(row.get("brier")) for row in rows]
    brier = [value for value in brier if value is not None]
    winners = [row for row in rows if num(row.get("predicted_margin")) not in (None, 0) and num(row.get("actual_margin")) not in (None, 0)]
    mae = lambda values: sum(abs(value) for value in values) / len(values)
    rmse = lambda values: math.sqrt(sum(value * value for value in values) / len(values))
    mean = lambda values: sum(values) / len(values)
    metrics = {
        "margin_mae": bootstrap(margin, mae, f"{label}|margin-mae"),
        "margin_rmse": bootstrap(margin, rmse, f"{label}|margin-rmse"),
        "margin_bias": bootstrap(margin, mean, f"{label}|margin-bias"),
        "total_mae": bootstrap(total, mae, f"{label}|total-mae"),
        "total_rmse": bootstrap(total, rmse, f"{label}|total-rmse"),
        "total_bias": bootstrap(total, mean, f"{label}|total-bias"),
        "brier": bootstrap(brier, mean, f"{label}|brier"),
        "winner_accuracy": wilson(sum((row["predicted_margin"] > 0) == (row["actual_margin"] > 0) for row in winners), len(winners)),
        "within_7": wilson(sum(abs(value) <= 7 for value in margin), len(margin)),
    }
    usable = [row for row in rows if num(row.get("home_win_probability")) is not None and num(row.get("actual_margin")) not in (None, 0)]
    calibration = []
    for low, high in ((50, 55), (55, 60), (60, 70), (70, 80), (80, 90), (90, 101)):
        sample = []
        for row in usable:
            home = row["home_win_probability"] / 100
            confidence = 100 * max(home, 1 - home)
            if low <= confidence < high:
                sample.append((confidence, (home >= .5) == (row["actual_margin"] > 0)))
        if sample:
            calibration.append({"label": f"{low}–{100 if high == 101 else high}%", "predicted": sum(value for value, _ in sample) / len(sample), "actual": wilson(sum(hit for _, hit in sample), len(sample))})
    return {"n_observations": len(rows), "metrics": metrics, "calibration": calibration}


def market_groups(rows: list[dict[str, Any]], result_key: str, label: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        signal = str(row.get("signal") or "UNCLASSIFIED").replace("_", " ").upper()
        grouped.setdefault(signal, []).append(row)
    output = []
    for signal, sample in grouped.items():
        wins = sum(row.get(result_key) == "W" for row in sample)
        losses = sum(row.get(result_key) == "L" for row in sample)
        pushes = sum(row.get(result_key) == "P" for row in sample)
        clv = [num(row.get("clv")) for row in sample]
        clv = [value for value in clv if value is not None]
        decisive = [value for value in clv if value != 0]
        output.append({
            "signal": signal, "wins": wins, "losses": losses, "pushes": pushes,
            "n_results": wins + losses, "n_clv": len(clv), "hit_rate": wilson(wins, wins + losses),
            "mean_clv": bootstrap(clv, lambda values: sum(values) / len(values), f"{label}|{signal}|clv"),
            "beat_close": wilson(sum(value > 0 for value in decisive), len(decisive)),
        })
    return sorted(output, key=lambda row: row["n_results"], reverse=True)


def build_slices(observations: list[dict[str, Any]], decisions: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    output = {}
    for sport in ("cfb", "cbb"):
        for days in ("all", "30", "7"):
            for venue in ("all", "campus", "neutral"):
                key = f"{sport}|{days}|{venue}"
                rows = slice_rows(observations, sport, days, venue)
                spread_key = "cfb_spread" if sport == "cfb" else "cbb_spread"
                spread = slice_rows(decisions[spread_key], sport, days, venue)
                totals = slice_rows(decisions.get("cbb_total", []), sport, days, venue) if sport == "cbb" else []
                output[key] = {
                    "predictive": predictive_metrics(rows, key),
                    "market": {
                        "spread": market_groups(spread, "ats_result" if sport == "cfb" else "result", f"{key}|spread"),
                        "total": market_groups(totals, "result", f"{key}|total"),
                        "source_coverage": source_coverage(spread),
                    },
                }
    return output


def main() -> None:
    cfb, cfb_grading = cfb_rows()
    cbb, sources_by_game, cbb_meta = cbb_rows()
    cbb_market = cbb_decisions(sources_by_game, cbb_meta)
    decisions = {"cfb_spread": [row for row in cfb if row.get("preferred_side") and row.get("ats_result")], "cbb_spread": cbb_market["spread"], "cbb_total": cbb_market["total"]}
    observations = cfb + cbb
    payload = {
        "meta": {
            "version": "thi-benchmark-center-v2.0", "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "minimum_interpretive_sample": MINIMUM_SAMPLE, "status": "public_prospective_audit",
            "intervals": {"confidence": .95, "binary": "Wilson score interval (z=1.96)", "continuous": "fixed-seed nonparametric bootstrap", "bootstrap_seed": BOOTSTRAP_SEED, "bootstrap_iterations": BOOTSTRAP_ITERATIONS},
            "contracts": {
                "cfb": {"season": 2026, "model_version": "production-model-a-2026-week1-freeze-v1", "market_policy_version": CFB_MARKET_POLICY, "grading_policy_version": cfb_grading, "env_status": "production"},
                "cbb": {"season": cbb_meta["board"].get("season"), "model_version": cbb_meta["board"].get("model_version"), "market_policy_version": cbb_meta["market"].get("version"), "grading_policy_version": "thi-cbb-model-tracking-v0.3", "env_status": "research"},
            },
        },
        "methodology": {
            "cfb_freeze": "CFB freezes the first executable pregame side when one exists; otherwise it retains the earliest pregame Model A forecast. A candidate execution quote must be two-sided, no older than 30 minutes, priced no worse than -125 and within 3 spread points of consensus. If none qualifies, the frozen consensus line is the fallback.",
            "cfb_close": "CFB closing CLV uses the captured price nearest kickoff inside the closing-proxy window from 90 minutes before kickoff through 10 minutes after kickoff. The proxy is disclosed because it is not represented as an official universal close.",
            "cbb_freeze": "CBB freezes the pregame projection retained by the projection board. Starting with this contract release, the projection object carries its actual generated-at timestamp and keeps it after settlement. Earlier finals with no archived projection timestamp are labeled NOT ARCHIVED; THI does not reconstruct one.",
            "cbb_market": "CBB spread and total consensus values are the median across available book lines after orientation validation, rounded to the nearest half-point for the grading contract. Opening is THI's first capture unless a source explicitly supplies an opener. Available providers vary by game.",
            "clv": "CLV compares the tracked side or total at its frozen pregame line with the captured closing line. Positive points mean the frozen number beat the close. Beat-close percentage excludes exact ties; results and CLV display separate sample counts.",
            "intervals": "Binary hit rates and calibration buckets use 95% Wilson score intervals. MAE, RMSE, signed bias, Brier score and mean CLV use 2,000 fixed-seed bootstrap resamples (seed 42). These intervals quantify sampling uncertainty; they do not certify an edge.",
            "sample": "Rows with fewer than 100 graded decisions are labeled SMALL SAMPLE. The warning is interpretive and never changes, hides or promotes a result.",
            "historical": "Historical backtests are research evidence, not prospective validation. They remain separate from every prospective figure on this page.",
        },
        "observations": observations, "decisions": decisions, "slices": build_slices(observations, decisions),
        "active_notes": {
            "cfb": ["Every confidence tier remains DEVELOPING until the complete promotion contract clears.", "Positive CLV in a small tier is not validation without sufficient sample, stability and price coverage."],
            "cbb": ["CBB remains a research environment; spread tiers are not yet clearing THI's performance and CLV standards.", "The middle probability bands require continued calibration monitoring; the dashboard reports the gap instead of smoothing it away.", "Historical CBB finals created before prospective projection timestamps were added are explicitly labeled NOT ARCHIVED rather than backfilled."],
        },
    }
    OUTPUT.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n")
    print({"output": str(OUTPUT), "observations": len(observations), "slices": len(payload["slices"])})


if __name__ == "__main__":
    main()
