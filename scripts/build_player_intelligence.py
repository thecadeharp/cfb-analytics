#!/usr/bin/env python3
"""Build THI display-only player production, rankings and award board.

The builder joins cfbfastR play-by-play athlete IDs to the ESPN roster IDs in
``roster_assets.json``. Outputs never feed Model A.
"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "player_intelligence.json"
PBP_URL = "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-cfb-data/main/cfb/pbp/parquet/play_by_play_{year}.parquet"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def number(value, default=0.0):
    return float(value) if finite(value) else default


def truthy(value):
    return value is True or value == 1 or str(value).lower() == "true"


def player_id(value):
    if not finite(value):
        return None
    return str(int(float(value)))


def percentile(values, target):
    values = [float(v) for v in values if finite(v)]
    if len(values) < 2:
        return 50.0
    less = sum(v < target for v in values)
    equal = sum(v == target for v in values)
    return 100.0 * (less + 0.5 * equal) / len(values)


def position_group(position, stats):
    pos = str(position or "").upper()
    if pos == "QB" or stats["pass_attempts"]:
        return "QB"
    if pos in {"RB", "HB", "FB"} or stats["rush_attempts"]:
        return "RB"
    if pos in {"WR", "TE"} or stats["targets"]:
        return "TE" if pos == "TE" else "WR"
    if pos in {"K", "P", "PK", "LS"}:
        return "ST"
    if pos in {"OL", "OT", "OG", "C", "G", "T"}:
        return "OL"
    if stats["defensive_disruptions"] or pos in {"DE", "DL", "DT", "NT", "EDGE", "LB", "ILB", "OLB", "CB", "DB", "S", "FS", "SS", "NB"}:
        return "DEF"
    return "OTHER"


def empty_stats():
    return defaultdict(float, {
        "games": set(), "weeks": set(),
        "pass_attempts": 0, "completions": 0, "pass_yards": 0, "pass_tds": 0, "interceptions": 0, "sacks_taken": 0,
        "rush_attempts": 0, "rush_yards": 0, "rush_tds": 0,
        "targets": 0, "receptions": 0, "receiving_yards": 0, "receiving_tds": 0,
        "sacks": 0, "interceptions_def": 0, "pass_breakups": 0, "forced_fumbles": 0, "fumble_recoveries": 0,
        "epa_total": 0.0, "successes": 0, "opportunities": 0, "opponent_baseline_total": 0.0,
        "defensive_disruptions": 0,
    })


def add_opportunity(stats, row, epa):
    stats["games"].add(str(row.get("game_id")))
    stats["weeks"].add(int(number(row.get("week"))))
    stats["opportunities"] += 1
    stats["epa_total"] += number(epa)
    stats["successes"] += int(number(epa) > 0)
    stats["opponent_baseline_total"] += number(row.get("opponent_defense_epa"))


def add_defense(stats, row, amount=1.0):
    stats["games"].add(str(row.get("game_id")))
    stats["weeks"].add(int(number(row.get("week"))))
    stats["defensive_disruptions"] += amount


def get_frame(path):
    requested = {
        "season", "seasonType", "week", "game_id", "pos_team_id", "def_pos_team_id", "pos_team", "def_pos_team",
        "status_type_completed", "garbage_time", "rush", "pass", "pass_attempt", "completion", "target", "touchdown",
        "rush_td", "pass_td", "interception", "int", "sack", "kneel_down", "yards_gained", "statYardage", "yds_rushed", "yds_receiving", "EPA", "EPA_pass", "EPA_rush",
        "passer_player_id", "passer_player_name", "rusher_player_id", "rusher_player_name", "receiver_player_id", "receiver_player_name",
        "sack_player_id", "sack_player_id2", "interception_player_id", "pass_breakup_player_id", "fumble_forced_player_id", "fumble_recovered_player_id",
    }
    import pyarrow.parquet as pq
    available = set(pq.ParquetFile(path).schema.names)
    return pd.read_parquet(path, columns=sorted(requested & available))


def roster_contract():
    roster = load(DATA / "roster_assets.json")
    players = {}
    team_by_id = {}
    teams = defaultdict(list)
    for team, payload in (roster.get("teams") or {}).items():
        tid = str(payload.get("espn_team_id") or "")
        if tid:
            team_by_id[tid] = team
        for row in payload.get("players") or []:
            pid = str(row.get("athlete_id") or "")
            if not pid:
                continue
            players[pid] = {**row, "team": team, "team_id": tid}
            teams[team].append(pid)
    return roster, players, team_by_id, teams


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--local-parquet", type=Path)
    parser.add_argument("--through-week", type=int, default=0)
    args = parser.parse_args()

    temporary = None
    path = args.local_parquet
    if not path:
        temporary = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
        temporary.close()
        path = Path(temporary.name)
        urllib.request.urlretrieve(PBP_URL.format(year=args.year), path)

    roster, roster_players, team_by_id, roster_teams = roster_contract()
    calibration_path = DATA / "research" / "heisman_calibration.json"
    calibration = load(calibration_path) if calibration_path.exists() else None
    calibration_status = ((calibration or {}).get("meta") or {}).get("status", "NOT_RUN")
    calibration_validation = (calibration or {}).get("validation") or {}
    model_teams = load(DATA / "cfb_metrics.json").get("teams") or {}
    advanced = load(DATA / "advanced_metrics.json")
    defense_epa = {
        team: number((((payload.get("non_garbage") or {}).get("defense") or {}).get("epa_play")))
        for team, payload in (advanced.get("teams") or {}).items()
    }
    frame = get_frame(path)
    frame = frame.loc[frame.get("season", args.year).fillna(args.year).astype(int).eq(args.year)].copy()
    if "seasonType" in frame:
        season_type = frame.seasonType.astype(str).str.lower()
        frame = frame.loc[season_type.isin({"regular", "2"})]
    if "status_type_completed" in frame:
        frame = frame.loc[frame.status_type_completed.fillna(False).map(truthy)]
    if "garbage_time" in frame:
        frame = frame.loc[~frame.garbage_time.fillna(False).map(truthy)]
    if args.through_week > 0:
        frame = frame.loc[pd.to_numeric(frame.week, errors="coerce").le(args.through_week)]
    through_week = int(pd.to_numeric(frame.week, errors="coerce").max()) if len(frame) else 0
    frame["def_team_key"] = frame.get("def_pos_team_id", pd.Series(index=frame.index, dtype=object)).map(player_id)
    frame["opponent_defense_epa"] = frame.def_team_key.map(lambda key: defense_epa.get(team_by_id.get(key, ""), 0.0))

    stats = defaultdict(empty_stats)
    names = {}
    for row in frame.to_dict("records"):
        epa = number(row.get("EPA"))
        passer = player_id(row.get("passer_player_id"))
        rusher = player_id(row.get("rusher_player_id"))
        receiver = player_id(row.get("receiver_player_id"))
        if passer and truthy(row.get("pass_attempt")):
            s = stats[passer]; names[passer] = row.get("passer_player_name")
            add_opportunity(s, row, row.get("EPA_pass", epa))
            s["pass_attempts"] += 1; s["completions"] += int(truthy(row.get("completion")))
            s["pass_yards"] += number(row.get("yds_receiving", row.get("statYardage", row.get("yards_gained")))) if truthy(row.get("completion")) else 0
            s["pass_tds"] += int(truthy(row.get("pass_td"))); s["interceptions"] += int(truthy(row.get("interception")) or truthy(row.get("int")))
            s["sacks_taken"] += int(truthy(row.get("sack")))
        if rusher and truthy(row.get("rush")) and not truthy(row.get("kneel_down")):
            s = stats[rusher]; names[rusher] = row.get("rusher_player_name")
            add_opportunity(s, row, row.get("EPA_rush", epa))
            s["rush_attempts"] += 1; s["rush_yards"] += number(row.get("yds_rushed", row.get("yards_gained")))
            s["rush_tds"] += int(truthy(row.get("rush_td")))
        if receiver and truthy(row.get("target")):
            s = stats[receiver]; names[receiver] = row.get("receiver_player_name")
            add_opportunity(s, row, row.get("EPA_pass", epa))
            s["targets"] += 1; s["receptions"] += int(truthy(row.get("completion")))
            s["receiving_yards"] += number(row.get("yds_receiving", row.get("statYardage", row.get("yards_gained")))) if truthy(row.get("completion")) else 0
            s["receiving_tds"] += int(truthy(row.get("pass_td")))
        for field, stat_name, amount in (
            ("sack_player_id", "sacks", 1.0), ("sack_player_id2", "sacks", 0.5),
            ("interception_player_id", "interceptions_def", 1.0), ("pass_breakup_player_id", "pass_breakups", 1.0),
            ("fumble_forced_player_id", "forced_fumbles", 1.0), ("fumble_recovered_player_id", "fumble_recoveries", 1.0),
        ):
            pid = player_id(row.get(field))
            if pid:
                add_defense(stats[pid], row, amount); stats[pid][stat_name] += amount

    # The public product is a current-roster view. Historical/FCS athletes that
    # appear in the PBP but are absent from the current ESPN roster contract are
    # intentionally excluded instead of being attached by fuzzy name matching.
    all_ids = sorted(roster_players)
    players = {}
    for pid in all_ids:
        meta = roster_players.get(pid, {})
        s = stats[pid]
        games = len(s["games"])
        opportunities = int(s["opportunities"])
        group = position_group(meta.get("position"), s)
        team = meta.get("team")
        epa_per = s["epa_total"] / opportunities if opportunities else None
        opponent_adjusted = (
            (s["epa_total"] - s["opponent_baseline_total"]) / opportunities
            if opportunities else None
        )
        primary_volume = s["pass_attempts"] or s["rush_attempts"] or s["targets"] or s["defensive_disruptions"]
        players[pid] = {
            "athlete_id": pid,
            "name": meta.get("name") or names.get(pid) or f"Player {pid}",
            "team": team,
            "conference": (model_teams.get(team) or {}).get("conference"),
            "team_id": meta.get("team_id"),
            "position": meta.get("position"), "position_name": meta.get("position_name"), "position_group": group,
            "class": meta.get("class"), "class_name": meta.get("class_name"), "jersey": meta.get("jersey"),
            "height": meta.get("height"), "weight": meta.get("weight"), "status": meta.get("status"),
            "headshot": meta.get("headshot"), "profile_url": meta.get("profile_url"),
            "games": games, "weeks": sorted(w for w in s["weeks"] if w), "opportunities": opportunities,
            "traditional": {key: int(value) if float(value).is_integer() else round(value, 1) for key, value in s.items() if key in {
                "pass_attempts", "completions", "pass_yards", "pass_tds", "interceptions", "sacks_taken",
                "rush_attempts", "rush_yards", "rush_tds", "targets", "receptions", "receiving_yards", "receiving_tds",
                "sacks", "interceptions_def", "pass_breakups", "forced_fumbles", "fumble_recoveries", "defensive_disruptions"
            } and value},
            "advanced": {
                "epa_total": round(s["epa_total"], 2) if opportunities else None,
                "epa_per_opportunity": round(epa_per, 3) if epa_per is not None else None,
                "opponent_adjusted_epa_per_opportunity": round(opponent_adjusted, 3) if opponent_adjusted is not None else None,
                "success_rate": round(100 * s["successes"] / opportunities, 1) if opportunities else None,
            },
            "primary_volume": primary_volume,
            "rating": None, "national_position_rank": None, "conference_position_rank": None,
        }

    team_totals = defaultdict(lambda: defaultdict(float))
    for row in players.values():
        if row.get("team"):
            for key in ("pass_attempts", "rush_attempts", "targets"):
                team_totals[row["team"]][key] += number(row["traditional"].get(key))
    for row in players.values():
        shares = {}
        for key, out in (("pass_attempts", "pass_attempt_share"), ("rush_attempts", "rush_attempt_share"), ("targets", "target_share")):
            total = team_totals[row.get("team")][key]
            value = number(row["traditional"].get(key))
            if total and value:
                shares[out] = round(100 * value / total, 1)
        row["workload"] = shares

    minimums = {"QB": 35, "RB": 20, "WR": 15, "TE": 12, "DEF": 3}
    for group in ("QB", "RB", "WR", "TE", "DEF"):
        pool = [row for row in players.values() if row["position_group"] == group and number(row["primary_volume"]) >= minimums[group]]
        effs = [row["advanced"]["opponent_adjusted_epa_per_opportunity"] for row in pool if finite(row["advanced"]["opponent_adjusted_epa_per_opportunity"])]
        totals = [row["advanced"]["epa_total"] for row in pool if finite(row["advanced"]["epa_total"])]
        volumes = [row["primary_volume"] for row in pool]
        successes = [row["advanced"]["success_rate"] for row in pool if finite(row["advanced"]["success_rate"])]
        for row in pool:
            if group == "DEF":
                rating = percentile(volumes, row["primary_volume"])
            else:
                rating = (
                    0.45 * percentile(effs, row["advanced"]["opponent_adjusted_epa_per_opportunity"])
                    + 0.30 * percentile(totals, row["advanced"]["epa_total"])
                    + 0.15 * percentile(volumes, row["primary_volume"])
                    + 0.10 * percentile(successes, row["advanced"]["success_rate"])
                )
            reliability = min(1.0, number(row["primary_volume"]) / (minimums[group] * 2))
            row["rating"] = round(50 + (rating - 50) * reliability, 1)
            row["reliability"] = round(100 * reliability, 0)
        ordered = sorted(pool, key=lambda row: (-(row["rating"] or -999), row["name"]))
        for rank, row in enumerate(ordered, 1):
            row["national_position_rank"] = rank
        for conference in sorted({row.get("team") for row in []}):
            pass
        conf_groups = defaultdict(list)
        for row in ordered:
            conf_groups[row.get("conference")].append(row)
        for conf_rows in conf_groups.values():
            for rank, row in enumerate(conf_rows, 1):
                row["conference_position_rank"] = rank

    projections = load(DATA / "projections.json").get("season_projections") or {}
    power = {row.get("team"): row for row in load(DATA / "thi_power_ratings.json").get("teams", [])}
    eligible = [row for row in players.values() if row["position_group"] in {"QB", "RB", "WR", "TE"} and finite(row.get("rating"))]
    ratings = [row["rating"] for row in eligible]
    values = [row["advanced"]["epa_total"] for row in eligible]
    heisman = []
    for row in eligible:
        team = row.get("team")
        expected_wins = number((projections.get(team) or {}).get("expected_wins"), 6)
        team_rating = number((power.get(team) or {}).get("rating"), 0)
        score = (
            0.52 * percentile(ratings, row["rating"])
            + 0.23 * percentile(values, row["advanced"]["epa_total"])
            + 0.15 * min(100, 100 * expected_wins / 12)
            + 0.10 * min(100, max(0, 50 + 3 * team_rating))
        )
        heisman.append({
            "athlete_id": row["athlete_id"], "name": row["name"], "team": team, "position": row.get("position"),
            "heisman_score": round(score, 1), "win_probability": None, "finalist_probability": None,
            "team_expected_wins": round(expected_wins, 1), "player_rating": row["rating"],
        })
    heisman.sort(key=lambda row: (-row["heisman_score"], row["name"]))
    for rank, row in enumerate(heisman, 1): row["rank"] = rank

    published_players = {
        pid: row for pid, row in players.items()
        if row["opportunities"] or number(row["traditional"].get("defensive_disruptions"))
    }
    team_payload = {}
    for team, ids in sorted(roster_teams.items()):
        ordered = sorted((pid for pid in ids if pid in published_players), key=lambda pid: (
            {"QB": 0, "RB": 1, "WR": 2, "TE": 3, "OL": 4, "DEF": 5, "ST": 6, "OTHER": 7}.get(players[pid]["position_group"], 9),
            -(players[pid].get("rating") or -1), players[pid]["name"],
        ))
        team_payload[team] = ordered

    output = {
        "meta": {
            "season": args.year, "through_week": through_week, "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "SportsDataverse/cfbfastR play-by-play joined to ESPN roster athlete IDs",
            "model_usage": "display_only_not_used_by_model_a",
            "rating_status": "research_beta",
            "heisman_status": calibration_status,
            "heisman_validation": {
                "passed": bool(calibration_validation.get("passed")),
                "mean_top4_finalist_recall": calibration_validation.get("mean_top4_finalist_recall"),
                "winner_top5_rate": calibration_validation.get("winner_top5_rate"),
                "seasons": ((calibration or {}).get("meta") or {}).get("seasons", []),
            },
            "notes": [
                "Observed role is based on recorded workload and is not an official depth chart.",
                "THI player ratings are position-specific and should not be compared across positions as equivalent scouting grades.",
                "Award probabilities are withheld unless the leave-one-season-out historical calibration clears every publication gate.",
            ],
        },
        "players": published_players, "teams": team_payload,
        "leaderboards": {
            group: [row["athlete_id"] for row in sorted(
                [p for p in published_players.values() if p["position_group"] == group and finite(p.get("rating"))],
                key=lambda p: (-(p["rating"] or -1), p["name"]),
            )]
            for group in ("QB", "RB", "WR", "TE", "DEF")
        },
        "heisman_board": heisman[:50],
    }
    OUTPUT.write_text(json.dumps(output, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT}: {len(published_players)} players with recorded production, {sum(finite(p.get('rating')) for p in published_players.values())} rated")


if __name__ == "__main__":
    main()
