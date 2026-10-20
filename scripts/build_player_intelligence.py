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


def distance_rating(values, target, points_per_standard_deviation=12.0):
    """Map observed distance from the position mean onto a 1-99 scale.

    Percentile ranks describe order but hide how far the leaders are ahead.
    This scale is used for WR production so an exceptional top tier does not
    appear tied to the rest of the board merely because all are high-percentile.
    """
    values = [float(value) for value in values if finite(value)]
    if len(values) < 2:
        return 50.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    standard_deviation = math.sqrt(variance)
    if standard_deviation <= 0:
        return 50.0
    return max(1.0, min(99.0, 50.0 + points_per_standard_deviation * ((float(target) - mean) / standard_deviation)))


POSITION_GROUPS = {
    "QB": "QB",
    "RB": "RB", "HB": "RB", "FB": "RB",
    "WR": "WR", "TE": "TE",
    "K": "ST", "P": "ST", "PK": "ST", "LS": "ST",
    "OL": "OL", "OT": "OL", "OG": "OL", "C": "OL", "G": "OL", "T": "OL",
    "DE": "DEF", "DL": "DEF", "DT": "DEF", "NT": "DEF", "EDGE": "DEF",
    "LB": "DEF", "ILB": "DEF", "OLB": "DEF", "CB": "DEF", "DB": "DEF",
    "S": "DEF", "FS": "DEF", "SS": "DEF", "NB": "DEF",
}
RATING_MINIMUMS = {"QB": 35, "RB": 20, "WR": 15, "TE": 12, "DEF": 10}
POSITION_RATING_WEIGHTS = {
    "QB": {
        "adjusted_epa": .18, "success_rate": .12, "yards_per_attempt": .12,
        "completion_rate": .08, "touchdown_rate": .15, "turnover_avoidance": .15,
        "yards_per_game": .10, "touchdowns_per_game": .10,
    },
    "RB": {
        "adjusted_epa": .18, "success_rate": .10, "yards_per_opportunity": .15,
        "yards_per_game": .20, "touchdowns_per_game": .22, "workload_share": .15,
    },
    "WR": {
        "receiving_dominance": .70, "adjusted_epa": .15,
        "yards_per_target": .10, "target_share": .05,
    },
    "TE": {
        "receiving_yards": .20, "receiving_touchdowns": .20, "yards_per_game": .12,
        "touchdowns_per_game": .12, "yards_per_target": .10, "adjusted_epa": .12,
        "receptions": .06, "target_share": .08,
    },
    "DEF": {
        "tackles": .14, "tackles_for_loss": .18, "sacks": .18,
        "passes_defended": .16, "interceptions": .17, "forced_fumbles": .12,
        "fumble_recoveries": .05,
    },
}
DEFENSIVE_POSITION_WEIGHTS = {
    "DB": {"tackles": .10, "tackles_for_loss": .05, "sacks": .03, "passes_defended": .30, "interceptions": .30, "forced_fumbles": .12, "fumble_recoveries": .10},
    "LB": {"tackles": .25, "tackles_for_loss": .25, "sacks": .15, "passes_defended": .10, "interceptions": .10, "forced_fumbles": .10, "fumble_recoveries": .05},
    "DL": {"tackles": .15, "tackles_for_loss": .30, "sacks": .30, "passes_defended": .05, "interceptions": .02, "forced_fumbles": .13, "fumble_recoveries": .05},
}


def defensive_position_group(position):
    position = str(position or "").upper()
    if position in {"CB", "DB", "S", "FS", "SS", "NB"}:
        return "DB"
    if position in {"LB", "ILB", "OLB"}:
        return "LB"
    return "DL"


def divide(numerator, denominator):
    return number(numerator) / max(1.0, number(denominator))


def rating_metrics(group, row):
    """Return position-relevant observed metrics used by the ratings board."""
    stats = row.get("traditional") or {}
    advanced = row.get("advanced") or {}
    workload = row.get("workload") or {}
    games = max(1.0, number(row.get("games")))
    if group == "QB":
        attempts = number(stats.get("pass_attempts"))
        total_plays = attempts + number(stats.get("rush_attempts"))
        total_yards = number(stats.get("pass_yards")) + number(stats.get("rush_yards"))
        total_touchdowns = number(stats.get("pass_tds")) + number(stats.get("rush_tds"))
        return {
            "adjusted_epa": number(advanced.get("opponent_adjusted_epa_per_opportunity")),
            "success_rate": number(advanced.get("success_rate")),
            "yards_per_attempt": divide(stats.get("pass_yards"), attempts),
            "completion_rate": 100 * divide(stats.get("completions"), attempts),
            "touchdown_rate": 100 * divide(total_touchdowns, total_plays),
            "turnover_avoidance": -100 * divide(stats.get("interceptions"), attempts),
            "yards_per_game": total_yards / games,
            "touchdowns_per_game": total_touchdowns / games,
        }
    if group == "RB":
        opportunities = number(stats.get("rush_attempts")) + number(stats.get("targets"))
        total_yards = number(stats.get("rush_yards")) + number(stats.get("receiving_yards"))
        total_touchdowns = number(stats.get("rush_tds")) + number(stats.get("receiving_tds"))
        return {
            "adjusted_epa": number(advanced.get("opponent_adjusted_epa_per_opportunity")),
            "success_rate": number(advanced.get("success_rate")),
            "yards_per_opportunity": divide(total_yards, opportunities),
            "yards_per_game": total_yards / games,
            "touchdowns_per_game": total_touchdowns / games,
            "workload_share": number(workload.get("rush_attempt_share")),
        }
    if group in {"WR", "TE"}:
        targets = number(stats.get("targets"))
        receiving_yards = number(stats.get("receiving_yards"))
        receiving_touchdowns = number(stats.get("receiving_tds"))
        return {
            "receiving_dominance": receiving_yards + 30 * receiving_touchdowns,
            "yards_per_target": divide(receiving_yards, targets),
            "adjusted_epa": number(advanced.get("opponent_adjusted_epa_per_opportunity")),
            "target_share": number(workload.get("target_share")),
        } if group == "WR" else {
            "receiving_yards": receiving_yards,
            "receiving_touchdowns": receiving_touchdowns,
            "yards_per_game": receiving_yards / games,
            "touchdowns_per_game": receiving_touchdowns / games,
            "yards_per_target": divide(receiving_yards, targets),
            "adjusted_epa": number(advanced.get("opponent_adjusted_epa_per_opportunity")),
            "receptions": number(stats.get("receptions")),
            "target_share": number(workload.get("target_share")),
        }
    if group == "DEF":
        return {
            "tackles": number(stats.get("total_tackles")),
            "tackles_for_loss": number(stats.get("tackles_for_loss")),
            "sacks": number(stats.get("sacks")),
            "passes_defended": number(stats.get("passes_defended", stats.get("pass_breakups"))),
            "interceptions": number(stats.get("interceptions_def")),
            "forced_fumbles": number(stats.get("forced_fumbles")),
            "fumble_recoveries": number(stats.get("fumble_recoveries")),
        }
    return {}


def position_group(position, stats):
    pos = str(position or "").upper()
    # The roster position is authoritative. Incidental carries, targets or
    # trick-play passes must not move a player into another rating cohort.
    if pos in POSITION_GROUPS:
        return POSITION_GROUPS[pos]
    if stats["pass_attempts"]:
        return "QB"
    if stats["rush_attempts"]:
        return "RB"
    if stats["targets"]:
        return "WR"
    if stats["defensive_disruptions"]:
        return "DEF"
    return "OTHER"


def usage_volume(group, stats):
    """Return the opportunity count appropriate to a player's roster role."""
    if group == "QB":
        return number(stats.get("pass_attempts")) + number(stats.get("rush_attempts"))
    if group == "RB":
        return number(stats.get("rush_attempts")) + number(stats.get("targets"))
    if group in {"WR", "TE"}:
        return number(stats.get("targets")) + number(stats.get("rush_attempts"))
    if group == "DEF":
        if number(stats.get("total_tackles")):
            return number(stats.get("total_tackles"))
        return number(stats.get("defensive_disruptions"))
    return 0.0


def empty_stats():
    return defaultdict(float, {
        "games": set(), "weeks": set(),
        "pass_attempts": 0, "completions": 0, "pass_yards": 0, "pass_tds": 0, "interceptions": 0, "sacks_taken": 0,
        "rush_attempts": 0, "rush_yards": 0, "rush_tds": 0,
        "targets": 0, "receptions": 0, "receiving_yards": 0, "receiving_tds": 0,
        "sacks": 0, "interceptions_def": 0, "pass_breakups": 0, "forced_fumbles": 0, "fumble_recoveries": 0,
        "epa_total": 0.0, "successes": 0, "opportunities": 0, "opponent_baseline_total": 0.0,
        "total_tackles": 0, "solo_tackles": 0, "tackles_for_loss": 0, "passes_defended": 0, "qb_hurries": 0,
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
        usage = meta.get("usage") or {}
        # CFBD game box scores carry the complete defensive counting-stat line.
        # Prefer those season aggregates over the smaller subset of disruptive
        # events identified in play-by-play descriptions.
        for key in (
            "total_tackles", "solo_tackles", "tackles_for_loss", "sacks", "passes_defended",
            "interceptions_def", "forced_fumbles", "fumble_recoveries", "qb_hurries",
        ):
            if finite(usage.get(key)):
                s[key] = number(usage[key])
        if any(number(s.get(key)) for key in ("tackles_for_loss", "sacks", "passes_defended", "interceptions_def", "forced_fumbles")):
            s["defensive_disruptions"] = sum(number(s.get(key)) for key in (
                "tackles_for_loss", "passes_defended", "interceptions_def", "forced_fumbles", "fumble_recoveries"
            ))
        games = len(s["games"])
        opportunities = int(s["opportunities"])
        group = position_group(meta.get("position"), s)
        team = meta.get("team")
        epa_per = s["epa_total"] / opportunities if opportunities else None
        opponent_adjusted = (
            (s["epa_total"] - s["opponent_baseline_total"]) / opportunities
            if opportunities else None
        )
        primary_volume = usage_volume(group, s)
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
                "total_tackles", "solo_tackles", "tackles_for_loss", "sacks", "interceptions_def", "pass_breakups",
                "passes_defended", "forced_fumbles", "fumble_recoveries", "qb_hurries", "defensive_disruptions"
            } and value},
            "advanced": {
                "epa_total": round(s["epa_total"], 2) if opportunities else None,
                "epa_per_opportunity": round(epa_per, 3) if epa_per is not None else None,
                "opponent_adjusted_epa_per_opportunity": round(opponent_adjusted, 3) if opponent_adjusted is not None else None,
                "success_rate": round(100 * s["successes"] / opportunities, 1) if opportunities else None,
            },
            "primary_volume": primary_volume,
            "rating": None, "rating_components": None,
            "national_position_rank": None, "conference_position_rank": None,
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

    minimums = RATING_MINIMUMS
    for group in ("QB", "RB", "WR", "TE", "DEF"):
        pool = [row for row in players.values() if row["position_group"] == group and number(row["primary_volume"]) >= minimums[group]]
        metrics_by_id = {row["athlete_id"]: rating_metrics(group, row) for row in pool}
        defensive_cohorts = {row["athlete_id"]: defensive_position_group(row.get("position")) for row in pool}
        for row in pool:
            observed = metrics_by_id[row["athlete_id"]]
            cohort = defensive_cohorts[row["athlete_id"]] if group == "DEF" else group
            weights = DEFENSIVE_POSITION_WEIGHTS[cohort] if group == "DEF" else POSITION_RATING_WEIGHTS[group]
            comparison_ids = [
                candidate["athlete_id"] for candidate in pool
                if group != "DEF" or defensive_cohorts[candidate["athlete_id"]] == cohort
            ]
            metric_pools = {
                key: [metrics_by_id[athlete_id][key] for athlete_id in comparison_ids if finite(metrics_by_id[athlete_id].get(key))]
                for key in weights
            }
            component_values = {
                key: percentile(metric_pools[key], observed[key])
                for key in weights
            }
            rating = sum(weights[key] * component_values[key] for key in weights)
            formula = f"{cohort.lower()}_position_specific_production_v2"
            if group == "WR":
                # Preserve real production separation at the top of the WR
                # board. A percentile-only composite compressed the historic
                # output of the leaders into the same one-point band.
                rating = distance_rating(metric_pools["receiving_dominance"], observed["receiving_dominance"])
                formula = "wr_distance_scaled_receiving_production_v2_1"
            reliability = min(1.0, number(row["primary_volume"]) / (minimums[group] * 2))
            row["rating"] = round(max(1.0, min(99.0, 50 + (rating - 50) * reliability)), 1)
            row["reliability"] = round(100 * reliability, 0)
            row["rating_components"] = {
                **{key: round(value, 1) if value is not None else None for key, value in component_values.items()},
                "raw_composite": round(rating, 1),
                "reliability_percent": round(100 * reliability, 0),
                "final_rating": row["rating"],
                "formula": formula,
                "weights": weights,
                "observed_metrics": {key: round(value, 3) for key, value in observed.items()},
            }
        ordered = sorted(pool, key=lambda row: (
            -(row["rating"] or -999),
            -number(metrics_by_id[row["athlete_id"]].get("receiving_dominance")) if group == "WR" else 0,
            row["name"],
        ))
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
    position_rating_pools = defaultdict(list)
    production_pools = defaultdict(list)
    production_values = {}
    for row in eligible:
        group = row["position_group"]
        stats_row = row.get("traditional") or {}
        if group == "QB":
            production = (
                number(stats_row.get("pass_yards")) + number(stats_row.get("rush_yards"))
                + 20 * (number(stats_row.get("pass_tds")) + number(stats_row.get("rush_tds")))
                - 50 * number(stats_row.get("interceptions"))
            )
        elif group == "RB":
            production = (
                number(stats_row.get("rush_yards")) + number(stats_row.get("receiving_yards"))
                + 25 * (number(stats_row.get("rush_tds")) + number(stats_row.get("receiving_tds")))
            )
        else:
            production = number(stats_row.get("receiving_yards")) + 30 * number(stats_row.get("receiving_tds"))
        production_values[row["athlete_id"]] = production
        position_rating_pools[group].append(row["rating"])
        production_pools[group].append(production)

    availability_path = DATA / "research" / "cfb_player_availability_overrides_2026.json"
    availability_payload = load(availability_path) if availability_path.exists() else {"players": []}
    now = datetime.now(timezone.utc)
    heisman_ineligible = {}
    for status_row in availability_payload.get("players") or []:
        try:
            starts = datetime.fromisoformat(str(status_row.get("effective_from_utc")).replace("Z", "+00:00"))
            expires = datetime.fromisoformat(str(status_row.get("expires_at_utc")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if starts <= now <= expires and status_row.get("heisman_eligible") is False:
            heisman_ineligible[(status_row.get("team"), status_row.get("name"))] = status_row

    heisman = []
    for row in eligible:
        team = row.get("team")
        status_row = heisman_ineligible.get((team, row.get("name")))
        if status_row:
            continue
        expected_wins = number((projections.get(team) or {}).get("expected_wins"), 6)
        team_rating = number((power.get(team) or {}).get("rating"), 0)
        group = row["position_group"]
        position_rating = percentile(position_rating_pools[group], row["rating"])
        position_production = percentile(production_pools[group], production_values[row["athlete_id"]])
        score = (
            0.45 * position_rating
            + 0.25 * position_production
            + 0.10 * percentile(ratings, row["rating"])
            + 0.10 * min(100, 100 * expected_wins / 12)
            + 0.10 * min(100, max(0, 50 + 3 * team_rating))
        )
        heisman.append({
            "athlete_id": row["athlete_id"], "name": row["name"], "team": team, "position": row.get("position"),
            "heisman_score": round(score, 1), "win_probability": None, "finalist_probability": None,
            "team_expected_wins": round(expected_wins, 1), "player_rating": row["rating"],
            "position_production_percentile": round(position_production, 1),
        })
    watch_path = DATA / "research" / "cfb_heisman_watch_2026.json"
    watch_payload = load(watch_path) if watch_path.exists() else {"top_tier": []}
    editorial_order = {
        (row.get("team"), row.get("name")): index
        for index, row in enumerate(watch_payload.get("top_tier") or [], 1)
    }
    for row in heisman:
        editorial_rank = editorial_order.get((row.get("team"), row.get("name")))
        row["editorial_watch_rank"] = editorial_rank
        row["board_basis"] = "editorial_top_tier" if editorial_rank else "production_score"
    heisman.sort(key=lambda row: (
        0 if row.get("editorial_watch_rank") else 1,
        row.get("editorial_watch_rank") or 999,
        -row["heisman_score"], row["name"],
    ))
    for rank, row in enumerate(heisman, 1): row["rank"] = rank

    published_players = {
        pid: row for pid, row in players.items()
        if row["opportunities"] or number(row["traditional"].get("total_tackles")) or number(row["traditional"].get("defensive_disruptions"))
    }
    team_payload = {}
    for team, ids in sorted(roster_teams.items()):
        ordered = sorted((pid for pid in ids if pid in published_players), key=lambda pid: (
            {"QB": 0, "RB": 1, "WR": 2, "TE": 3, "OL": 4, "DEF": 5, "ST": 6, "OTHER": 7}.get(players[pid]["position_group"], 9),
            -(players[pid].get("rating") or -1), players[pid]["name"],
        ))
        team_payload[team] = ordered

    def published_leaderboard_sort_key(row, group):
        components = row.get("rating_components") or {}
        observed = components.get("observed_metrics") or {}
        receiving_dominance = number(observed.get("receiving_dominance")) if group == "WR" else 0.0
        return (-(row.get("rating") or -1), -receiving_dominance, row["name"])

    output = {
        "meta": {
            "season": args.year, "through_week": through_week, "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "SportsDataverse/cfbfastR play-by-play joined to ESPN roster athlete IDs",
            "model_usage": "display_only_not_used_by_model_a",
            "rating_status": "research_beta",
            "rating_version": "thi-cfb-player-production-v2.1",
            "rating_method": {
                "label": "position-specific production rating",
                "position_weights": POSITION_RATING_WEIGHTS,
                "defensive_position_weights": DEFENSIVE_POSITION_WEIGHTS,
                "defensive_formula": "position-balanced box-score production using tackles, tackles for loss, sacks, passes defended, interceptions and takeaways",
                "reliability_rule": "regress the raw composite toward 50 until twice the position minimum is reached",
                "not_a_measure_of": ["scouting talent", "draft grade", "award probability"],
            },
            "heisman_status": calibration_status,
            "heisman_validation": {
                "passed": bool(calibration_validation.get("passed")),
                "mean_top4_finalist_recall": calibration_validation.get("mean_top4_finalist_recall"),
                "winner_top5_rate": calibration_validation.get("winner_top5_rate"),
                "seasons": ((calibration or {}).get("meta") or {}).get("seasons", []),
            },
            "heisman_board_method": "Source-linked availability gate, editorial top tier, then position-adjusted production score. No award probabilities.",
            "notes": [
                "Observed role is based on recorded workload and is not an official depth chart.",
                "Official roster positions define rating cohorts; incidental trick-play usage does not reclassify players.",
                "Primary volume is position-specific usage: QB dropbacks/carries, RB carries/targets, receiver targets/carries and defensive tackles.",
                "Each offensive position uses its own production formula; quarterback turnover avoidance and receiver touchdown/yardage dominance are evaluated explicitly.",
                "Defensive ratings require the complete CFBD box-score layer and are withheld when only partial play-by-play disruption data is available.",
                "THI player ratings are position-specific and should not be compared across positions as equivalent scouting grades.",
                "The rating describes observed current-season production within position; it is not a talent grade or Heisman probability.",
                "Award probabilities are withheld unless the leave-one-season-out historical calibration clears every publication gate.",
            ],
        },
        "players": published_players, "teams": team_payload,
        "leaderboards": {
            group: [row["athlete_id"] for row in sorted(
                [p for p in published_players.values() if p["position_group"] == group and finite(p.get("rating"))],
                key=lambda p: published_leaderboard_sort_key(p, group),
            )]
            for group in ("QB", "RB", "WR", "TE", "DEF")
        },
        "heisman_board": heisman[:50],
    }
    OUTPUT.write_text(json.dumps(output, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT}: {len(published_players)} players with recorded production, {sum(finite(p.get('rating')) for p in published_players.values())} rated")


if __name__ == "__main__":
    main()
