"""
CFB ANALYTICS
build_historical_training_data.py

V5 canonical historical training builder using SportsDataverse ESPN CFB PBP.

V4 DATA UPGRADE
---------------
Preserves REALIZED game-level drive/scoring mechanisms for each team:
- actual_drives
- actual_scoring_opportunities
- actual_scoring_opportunity_rate
- actual_points_on_scoring_opportunities
- actual_points_per_scoring_opportunity
- actual_points_per_drive
- actual_scoring_opportunity_conversion_rate

Those realized fields are retained as HOME/AWAY training targets in the final
game table. Their historical averages are also shifted into leakage-safe
prev_season_* and pregame_* predictor features.

IMPORTANT RULES
---------------
1. No CollegeFootballData API calls.
2. 2025 remains the sealed test season.
3. Same-season pregame features use ONLY PRIOR WEEKS.
4. Previous-season priors use only the previous completed season.
5. Market lines are retained for evaluation only.
6. Realized current-game outcomes are targets only; they are NEVER copied into
   the current game's pregame feature columns.
7. Possession/defense team names are mapped with ESPN team IDs, not fuzzy text.
8. Final scores use the last chronological end score, never max(score).
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "training"
OUT_CSV = OUT_DIR / "historical_games.csv"
OUT_MANIFEST = OUT_DIR / "historical_training_manifest.json"

SEASONS = list(range(2019, 2026))
SEALED_SEASON = 2025

RELEASE_API = (
    "https://api.github.com/repos/sportsdataverse/"
    "sportsdataverse-data/releases/tags/espn_cfb_pbp"
)
REQUEST_TIMEOUT = 180


def num(series):
    return pd.to_numeric(series, errors="coerce")


def boolish(series):
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    if pd.api.types.is_numeric_dtype(series):
        return num(series).fillna(0).ne(0)
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .isin({"1", "true", "t", "yes", "y"})
    )


def safe_mean(series):
    values = num(series).dropna()
    return np.nan if values.empty else float(values.mean())


def first_non_null(series):
    values = series.dropna()
    return np.nan if values.empty else values.iloc[0]


def last_non_null(series):
    values = series.dropna()
    return np.nan if values.empty else values.iloc[-1]


def get_release_assets():
    print("Getting SportsDataverse release metadata...", flush=True)
    response = requests.get(RELEASE_API, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    return {asset["name"]: asset for asset in payload.get("assets", [])}


def download_season(year, assets, target_dir):
    asset_name = f"play_by_play_{year}.parquet"
    if asset_name not in assets:
        raise RuntimeError(f"SportsDataverse release is missing {asset_name}")

    asset = assets[asset_name]
    url = asset["browser_download_url"]
    target = target_dir / asset_name

    print(f"Downloading {year}: {url}", flush=True)
    with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT) as response:
        response.raise_for_status()
        with target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)

    return target, asset


REQUIRED_COLUMNS = [
    "season",
    "seasonType",
    "game_id",
    "game_play_number",
    "pos_team_id",
    "def_pos_team_id",
    "pos_team",
    "def_pos_team",
    "EPA",
    "rush",
    "pass",
    "week",
    "homeTeamName",
    "awayTeamName",
    "homeTeamId",
    "awayTeamId",
    "homeScore",
    "awayScore",
    "gameSpread",
    "homeFavorite",
    "gameSpreadAvailable",
    "overUnder",
    "drive.id",
    "EPA_success",
    "EPA_explosive",
    "havoc",
]

# These fields must exist in every downloaded season; missing values on an
# individual play are allowed, but cannot be coerced to zero for a split.
SITUATIONAL_REQUIRED_COLUMNS = [
    "period", "start.down", "start.distance", "start.yardsToEndzone",
    "clock.minutes", "clock.seconds", "start.homeScore", "start.awayScore",
]

OPTIONAL_COLUMNS = [
    "status_type_completed",
    "scrimmage_play",
    "action_play",
    "kneel_down",
    "penalty_no_play",
    "TFL",
    "sack",
    "turnover_vec",
    "is_pos_team_turnover",
    "line_yards",
    "scoring_opp",
    "end.homeScore",
    "end.awayScore",
]


def validate_schema(df, year):
    missing = [c for c in REQUIRED_COLUMNS + SITUATIONAL_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise RuntimeError(
            f"{year} SportsDataverse schema missing required columns: "
            + ", ".join(missing)
        )


def normalize_season(df, year):
    validate_schema(df, year)

    columns = REQUIRED_COLUMNS + SITUATIONAL_REQUIRED_COLUMNS + [
        c for c in OPTIONAL_COLUMNS if c in df.columns
    ]
    work = df[columns].copy()

    work["season"] = num(work["season"]).astype("Int64")
    work["week"] = num(work["week"]).astype("Int64")
    work["game_id"] = work["game_id"].astype(str)

    work["home_team"] = work["homeTeamName"].astype(str)
    work["away_team"] = work["awayTeamName"].astype(str)

    pos_id = work["pos_team_id"].astype(str)
    def_id = work["def_pos_team_id"].astype(str)
    home_id = work["homeTeamId"].astype(str)
    away_id = work["awayTeamId"].astype(str)

    work["offense"] = np.select(
        [pos_id.eq(home_id), pos_id.eq(away_id)],
        [work["home_team"], work["away_team"]],
        default=None,
    )
    work["defense"] = np.select(
        [def_id.eq(home_id), def_id.eq(away_id)],
        [work["home_team"], work["away_team"]],
        default=None,
    )

    work["play_order"] = num(work["game_play_number"])
    work["epa"] = num(work["EPA"])
    work["success"] = boolish(work["EPA_success"]).astype(float)
    work.loc[work["EPA_success"].isna(), "success"] = np.nan
    work["period_number"] = num(work["period"])
    work["down_number"] = num(work["start.down"])
    work["distance_number"] = num(work["start.distance"])
    clock_minutes = num(work["clock.minutes"])
    clock_seconds = num(work["clock.seconds"])
    work["clock_valid"] = (
        clock_minutes.between(0, 15) & clock_seconds.between(0, 59)
        & (~clock_minutes.eq(15) | clock_seconds.eq(0))
    )
    work["explosive"] = boolish(work["EPA_explosive"]).astype(float)
    work["havoc"] = boolish(work["havoc"]).astype(float)

    work["rush_play"] = boolish(work["rush"])
    work["pass_play"] = boolish(work["pass"])

    if "scrimmage_play" in work.columns:
        work["valid_scrimmage"] = boolish(work["scrimmage_play"])
    else:
        work["valid_scrimmage"] = work["rush_play"] | work["pass_play"]

    if "action_play" in work.columns:
        work["valid_scrimmage"] &= boolish(work["action_play"])
    if "kneel_down" in work.columns:
        work["valid_scrimmage"] &= ~boolish(work["kneel_down"])
    if "penalty_no_play" in work.columns:
        work["valid_scrimmage"] &= ~boolish(work["penalty_no_play"])

    work["home_score_play"] = num(work["start.homeScore"])
    work["away_score_play"] = num(work["start.awayScore"])
    work["post_home_score_play"] = num(work["homeScore"])
    work["post_away_score_play"] = num(work["awayScore"])
    work["end_home_score_play"] = (
        num(work["end.homeScore"])
        if "end.homeScore" in work.columns else np.nan
    )
    work["end_away_score_play"] = (
        num(work["end.awayScore"])
        if "end.awayScore" in work.columns else np.nan
    )

    work["game_spread"] = num(work["gameSpread"])
    work["home_favorite"] = boolish(work["homeFavorite"])
    work["spread_available"] = boolish(work["gameSpreadAvailable"])
    work["market_total_play"] = num(work["overUnder"])

    work["market_home_spread_play"] = np.where(
        ~work["spread_available"],
        np.nan,
        np.where(
            work["game_spread"].eq(0),
            0.0,
            np.where(
                work["home_favorite"],
                -work["game_spread"].abs(),
                work["game_spread"].abs(),
            ),
        ),
    )

    work["drive_id"] = work["drive.id"].astype(str)
    work.loc[work["drive.id"].isna(), "drive_id"] = np.nan

    work["season_type"] = num(work["seasonType"])
    work["completed"] = (
        boolish(work["status_type_completed"])
        if "status_type_completed" in work.columns else True
    )
    work["line_yards"] = (
        num(work["line_yards"])
        if "line_yards" in work.columns else np.nan
    )
    work["scoring_opp"] = (
        boolish(work["scoring_opp"]).astype(float)
        if "scoring_opp" in work.columns else np.nan
    )
    work["yards_to_endzone"] = num(work["start.yardsToEndzone"])

    # ESPN homeScore / awayScore are AFTER the play. Only start.homeScore /
    # start.awayScore can classify the game state before this play. Clock stamps
    # have different snap/end semantics by era; we validate them for presence
    # and range, but do not use them for a seconds-remaining cutoff.
    margin = (work["home_score_play"] - work["away_score_play"]).abs()
    threshold = np.select(
        [work["period_number"].le(2), work["period_number"].eq(3), work["period_number"].eq(4)],
        [38, 28, 22], default=0,
    )
    work["competitive_situational"] = (
        work["period_number"].between(1, 4)
        & work["down_number"].between(1, 4)
        & work["distance_number"].notna()
        & work["clock_valid"]
        & work["home_score_play"].notna()
        & work["away_score_play"].notna()
        & margin.lt(threshold)
    )
    work["situational_overtime"] = work["period_number"].ge(5)
    work["situational_garbage"] = (
        work["period_number"].between(1, 4)
        & margin.ge(threshold)
        & work["home_score_play"].notna()
        & work["away_score_play"].notna()
    )

    return work


def build_game_metadata(plays):
    rows = []

    for game_id, group in plays.groupby("game_id", sort=False):
        ordered = group.sort_values(
            ["play_order"], kind="stable", na_position="last"
        )

        end_home = ordered["end_home_score_play"].dropna()
        end_away = ordered["end_away_score_play"].dropna()
        home_scores = ordered["post_home_score_play"].dropna()
        away_scores = ordered["post_away_score_play"].dropna()

        home_score = (
            float(end_home.iloc[-1])
            if not end_home.empty
            else (float(home_scores.iloc[-1]) if not home_scores.empty else np.nan)
        )
        away_score = (
            float(end_away.iloc[-1])
            if not end_away.empty
            else (float(away_scores.iloc[-1]) if not away_scores.empty else np.nan)
        )
        half = ordered.loc[ordered["period_number"].eq(2)]
        half_home = half["end_home_score_play"].dropna()
        half_away = half["end_away_score_play"].dropna()
        half_home_score = (
            float(half_home.iloc[-1]) if not half_home.empty
            else float(half["post_home_score_play"].dropna().iloc[-1])
            if half["post_home_score_play"].notna().any() else np.nan
        )
        half_away_score = (
            float(half_away.iloc[-1]) if not half_away.empty
            else float(half["post_away_score_play"].dropna().iloc[-1])
            if half["post_away_score_play"].notna().any() else np.nan
        )

        rows.append({
            "game_id": game_id,
            "season": int(group["season"].dropna().iloc[0]),
            "week": int(group["week"].dropna().iloc[0]),
            "season_type": first_non_null(group["season_type"]),
            "home_team": group["home_team"].iloc[0],
            "away_team": group["away_team"].iloc[0],
            "home_score": home_score,
            "away_score": away_score,
            "home_first_half_score": half_home_score,
            "away_first_half_score": half_away_score,
            "actual_first_half_margin": (
                half_home_score - half_away_score
                if not pd.isna(half_home_score) and not pd.isna(half_away_score)
                else np.nan
            ),
            "actual_home_margin": (
                home_score - away_score
                if not pd.isna(home_score) and not pd.isna(away_score)
                else np.nan
            ),
            "actual_total": (
                home_score + away_score
                if not pd.isna(home_score) and not pd.isna(away_score)
                else np.nan
            ),
            "market_home_spread": first_non_null(
                group["market_home_spread_play"]
            ),
            "market_total": first_non_null(group["market_total_play"]),
            "completed": bool(group["completed"].fillna(False).any()),
        })

    meta = pd.DataFrame(rows)
    return meta.loc[
        meta["home_team"].notna()
        & meta["away_team"].notna()
        & meta["home_score"].notna()
        & meta["away_score"].notna()
    ].copy()


def build_drive_table(plays):
    """
    One row per actual possession drive.

    A scoring opportunity is counted at the DRIVE level: a drive is a scoring
    opportunity when any play on that drive has SportsDataverse scoring_opp=1.

    Offensive points on the drive are calculated from chronological score
    deltas for the possessing team:
        final end-of-play team score - first observed pre-play team score.

    This prevents multiple plays inside the same scoring opportunity from being
    double counted.
    """
    valid = plays.loc[
        plays["drive_id"].notna()
        & plays["offense"].notna()
    ].copy()

    rows = []

    for (game_id, offense, drive_id), group in valid.groupby(
        ["game_id", "offense", "drive_id"], sort=False
    ):
        ordered = group.sort_values(
            ["play_order"], kind="stable", na_position="last"
        )

        home_team = ordered["home_team"].iloc[0]
        away_team = ordered["away_team"].iloc[0]

        start_home = first_non_null(ordered["home_score_play"])
        start_away = first_non_null(ordered["away_score_play"])

        end_home = last_non_null(ordered["end_home_score_play"])
        end_away = last_non_null(ordered["end_away_score_play"])

        if pd.isna(end_home):
            end_home = last_non_null(ordered["home_score_play"])
        if pd.isna(end_away):
            end_away = last_non_null(ordered["away_score_play"])

        if offense == home_team:
            start_team = start_home
            end_team = end_home
        elif offense == away_team:
            start_team = start_away
            end_team = end_away
        else:
            continue

        offensive_points = (
            max(0.0, float(end_team) - float(start_team))
            if not pd.isna(start_team) and not pd.isna(end_team)
            else np.nan
        )

        scoring_flag_values = num(ordered["scoring_opp"]).dropna()
        scoring_opportunity = (
            bool((scoring_flag_values > 0).any())
            if not scoring_flag_values.empty
            else False
        )

        rows.append({
            "game_id": game_id,
            "team": offense,
            "drive_id": drive_id,
            "drive_start_play": safe_mean(
                pd.Series([ordered["play_order"].dropna().min()])
            ),
            "drive_end_play": safe_mean(
                pd.Series([ordered["play_order"].dropna().max()])
            ),
            "scoring_opportunity": scoring_opportunity,
            "offensive_points": offensive_points,
            "scoring_opportunity_points": (
                offensive_points if scoring_opportunity else 0.0
            ),
            "scoring_opportunity_converted": (
                float(offensive_points > 0)
                if scoring_opportunity and not pd.isna(offensive_points)
                else (0.0 if scoring_opportunity else np.nan)
            ),
        })

    drives = pd.DataFrame(rows)
    if drives.empty:
        raise RuntimeError("No possession drives could be built.")

    return drives


def build_team_drive_metrics(drives):
    rows = []

    for (game_id, team), group in drives.groupby(
        ["game_id", "team"], sort=False
    ):
        actual_drives = float(len(group))
        scoring = group.loc[group["scoring_opportunity"]]

        actual_scoring_opportunities = float(len(scoring))
        points_on_scoring_opps = float(
            num(scoring["scoring_opportunity_points"]).fillna(0).sum()
        )

        rows.append({
            "game_id": game_id,
            "team": team,
            "actual_drives": actual_drives,
            "actual_scoring_opportunities": actual_scoring_opportunities,
            "actual_scoring_opportunity_rate": (
                actual_scoring_opportunities / actual_drives
                if actual_drives > 0 else np.nan
            ),
            "actual_points_on_scoring_opportunities": points_on_scoring_opps,
            "actual_points_per_scoring_opportunity": (
                points_on_scoring_opps / actual_scoring_opportunities
                if actual_scoring_opportunities > 0 else 0.0
            ),
            "actual_scoring_opportunity_conversion_rate": (
                safe_mean(scoring["scoring_opportunity_converted"])
                if actual_scoring_opportunities > 0 else 0.0
            ),
        })

    return pd.DataFrame(rows)


def build_team_game_metrics(plays, drive_metrics):
    football = plays.loc[
        plays["valid_scrimmage"]
        & plays["epa"].notna()
        & (plays["rush_play"] | plays["pass_play"])
        & plays["offense"].notna()
    ].copy()

    if football.empty:
        raise RuntimeError("No valid rush/pass EPA plays found.")

    rows = []

    for (game_id, team), group in football.groupby(
        ["game_id", "offense"], sort=False
    ):
        rush = group.loc[group["rush_play"]]
        pas = group.loc[group["pass_play"]]
        competitive = group.loc[group["competitive_situational"]]
        successful = competitive.loc[competitive["success"].eq(1)]
        script = competitive.loc[
            competitive["period_number"].le(2)
            & competitive["down_number"].isin([1, 2])
        ]
        leverage = competitive.loc[
            competitive["down_number"].isin([3, 4])
            & competitive["distance_number"].ge(3)
        ]
        red_zone = competitive.loc[
            competitive["yards_to_endzone"].between(0, 20)
        ]

        rows.append({
            "game_id": game_id,
            "team": team,
            "opponent": first_non_null(group["defense"]),
            "plays": int(len(group)),
            "off_epa": safe_mean(group["epa"]),
            "off_success_rate": safe_mean(group["success"]),
            "off_explosive_rate": safe_mean(group["explosive"]),
            "off_pass_epa": safe_mean(pas["epa"]),
            "off_rush_epa": safe_mean(rush["epa"]),
            "off_competitive_epa": safe_mean(competitive["epa"]),
            "off_competitive_success_rate": safe_mean(competitive["success"]),
            "off_competitive_plays": int(len(competitive)),
            "off_iso_ppp": safe_mean(successful["epa"]),
            "off_iso_successful_plays": int(len(successful)),
            "off_script_epa": safe_mean(script["epa"]),
            "off_script_success_rate": safe_mean(script["success"]),
            "off_script_plays": int(len(script)),
            "off_leverage_epa": safe_mean(leverage["epa"]),
            "off_leverage_success_rate": safe_mean(leverage["success"]),
            "off_leverage_plays": int(len(leverage)),
            "off_red_zone_epa": safe_mean(red_zone["epa"]),
            "off_red_zone_success_rate": safe_mean(red_zone["success"]),
            "off_red_zone_plays": int(len(red_zone)),
            "havoc_allowed_rate": safe_mean(group["havoc"]),
            "line_yards_per_rush": safe_mean(rush["line_yards"]),
            "scoring_opp_rate": safe_mean(group["scoring_opp"]),
            "avg_start_yards_to_endzone": safe_mean(group["yards_to_endzone"]),
        })

    offense = pd.DataFrame(rows).merge(
        drive_metrics,
        on=["game_id", "team"],
        how="left",
    )

    offense["drives"] = offense["actual_drives"]
    offense["plays_per_drive"] = np.where(
        offense["actual_drives"].gt(0),
        offense["plays"] / offense["actual_drives"],
        np.nan,
    )

    defense = offense[
        [
            "game_id",
            "team",
            "off_epa",
            "off_success_rate",
            "off_explosive_rate",
            "off_pass_epa",
            "off_rush_epa",
            "off_competitive_epa",
            "off_competitive_success_rate",
            "off_competitive_plays",
            "off_iso_ppp",
            "off_iso_successful_plays",
            "off_script_epa",
            "off_script_success_rate",
            "off_script_plays",
            "off_leverage_epa",
            "off_leverage_success_rate",
            "off_leverage_plays",
            "off_red_zone_epa",
            "off_red_zone_success_rate",
            "off_red_zone_plays",
            "havoc_allowed_rate",
            "line_yards_per_rush",
            "scoring_opp_rate",
            "actual_drives",
            "actual_scoring_opportunities",
            "actual_scoring_opportunity_rate",
            "actual_points_on_scoring_opportunities",
            "actual_points_per_scoring_opportunity",
            "actual_scoring_opportunity_conversion_rate",
        ]
    ].copy()

    defense = defense.rename(columns={
        "team": "opponent",
        "off_epa": "def_epa_allowed",
        "off_success_rate": "def_success_allowed",
        "off_explosive_rate": "def_explosive_allowed",
        "off_pass_epa": "def_pass_epa_allowed",
            "off_rush_epa": "def_rush_epa_allowed",
            "off_competitive_epa": "def_competitive_epa_allowed",
            "off_competitive_success_rate": "def_competitive_success_allowed",
            "off_competitive_plays": "def_competitive_plays",
            "off_iso_ppp": "def_iso_ppp_allowed",
            "off_iso_successful_plays": "def_iso_successful_plays",
            "off_script_epa": "def_script_epa_allowed",
            "off_script_success_rate": "def_script_success_allowed",
            "off_script_plays": "def_script_plays",
            "off_leverage_epa": "def_leverage_epa_allowed",
            "off_leverage_success_rate": "def_leverage_success_allowed",
            "off_leverage_plays": "def_leverage_plays",
            "off_red_zone_epa": "def_red_zone_epa_allowed",
            "off_red_zone_success_rate": "def_red_zone_success_allowed",
            "off_red_zone_plays": "def_red_zone_plays",
        "havoc_allowed_rate": "def_havoc_created_rate",
        "line_yards_per_rush": "def_line_yards_allowed",
        "scoring_opp_rate": "def_scoring_opp_allowed",
        "actual_drives": "def_actual_drives_faced",
        "actual_scoring_opportunities": "def_actual_scoring_opportunities_allowed",
        "actual_scoring_opportunity_rate": "def_actual_scoring_opportunity_rate_allowed",
        "actual_points_on_scoring_opportunities": "def_actual_points_on_scoring_opportunities_allowed",
        "actual_points_per_scoring_opportunity": "def_actual_points_per_scoring_opportunity_allowed",
        "actual_scoring_opportunity_conversion_rate": "def_actual_scoring_opportunity_conversion_rate_allowed",
    })

    return offense.merge(
        defense,
        on=["game_id", "opponent"],
        how="left",
    )


REALIZED_TARGET_METRICS = [
    "actual_drives",
    "actual_scoring_opportunities",
    "actual_scoring_opportunity_rate",
    "actual_points_on_scoring_opportunities",
    "actual_points_per_scoring_opportunity",
    "actual_scoring_opportunity_conversion_rate",
]

TEAM_METRICS = [
    "off_epa",
    "off_success_rate",
    "off_explosive_rate",
    "off_pass_epa",
    "off_rush_epa",
    "off_competitive_epa",
    "off_competitive_success_rate",
    "off_competitive_plays",
    "off_iso_ppp",
    "off_iso_successful_plays",
    "off_script_epa",
    "off_script_success_rate",
    "off_script_plays",
    "off_leverage_epa",
    "off_leverage_success_rate",
    "off_leverage_plays",
    "off_red_zone_epa",
    "off_red_zone_success_rate",
    "off_red_zone_plays",
    "havoc_allowed_rate",
    "line_yards_per_rush",
    "scoring_opp_rate",
    "avg_start_yards_to_endzone",
    "drives",
    "plays_per_drive",
    "def_epa_allowed",
    "def_success_allowed",
    "def_explosive_allowed",
    "def_pass_epa_allowed",
    "def_rush_epa_allowed",
    "def_competitive_epa_allowed",
    "def_competitive_success_allowed",
    "def_competitive_plays",
    "def_iso_ppp_allowed",
    "def_iso_successful_plays",
    "def_script_epa_allowed",
    "def_script_success_allowed",
    "def_script_plays",
    "def_leverage_epa_allowed",
    "def_leverage_success_allowed",
    "def_leverage_plays",
    "def_red_zone_epa_allowed",
    "def_red_zone_success_allowed",
    "def_red_zone_plays",
    "def_havoc_created_rate",
    "def_line_yards_allowed",
    "def_scoring_opp_allowed",
    "actual_drives",
    "actual_scoring_opportunities",
    "actual_scoring_opportunity_rate",
    "actual_points_on_scoring_opportunities",
    "actual_points_per_scoring_opportunity",
    "actual_scoring_opportunity_conversion_rate",
    "def_actual_drives_faced",
    "def_actual_scoring_opportunities_allowed",
    "def_actual_scoring_opportunity_rate_allowed",
    "def_actual_points_on_scoring_opportunities_allowed",
    "def_actual_points_per_scoring_opportunity_allowed",
    "def_actual_scoring_opportunity_conversion_rate_allowed",
]

SITUATIONAL_WEIGHTS = {
    f"{side}_{field}{suffix}": f"{side}_{sample}"
    for side, suffix in (("off", ""), ("def", "_allowed"))
    for field, sample in (
        ("competitive_epa", "competitive_plays"),
        ("script_epa", "script_plays"),
        ("leverage_epa", "leverage_plays"),
        ("red_zone_epa", "red_zone_plays"),
    )
}
SITUATIONAL_WEIGHTS.update({
    "off_competitive_success_rate": "off_competitive_plays",
    "off_iso_ppp": "off_iso_successful_plays",
    "off_script_success_rate": "off_script_plays",
    "off_leverage_success_rate": "off_leverage_plays",
    "off_red_zone_success_rate": "off_red_zone_plays",
    "def_competitive_success_allowed": "def_competitive_plays",
    "def_iso_ppp_allowed": "def_iso_successful_plays",
    "def_script_success_allowed": "def_script_plays",
    "def_leverage_success_allowed": "def_leverage_plays",
    "def_red_zone_success_allowed": "def_red_zone_plays",
})
# Defense EPA column spellings use *_epa_allowed, already covered above.
SITUATIONAL_COUNTS = sorted(set(SITUATIONAL_WEIGHTS.values()))


def build_team_games(meta, metrics):
    base = meta[
        ["game_id", "season", "week", "home_team", "away_team"]
    ].copy()

    home = base.merge(
        metrics,
        left_on=["game_id", "home_team"],
        right_on=["game_id", "team"],
        how="left",
    )
    home["side"] = "home"

    away = base.merge(
        metrics,
        left_on=["game_id", "away_team"],
        right_on=["game_id", "team"],
        how="left",
    )
    away["side"] = "away"

    team_games = pd.concat([home, away], ignore_index=True)

    team_games["team"] = np.where(
        team_games["side"].eq("home"),
        team_games["home_team"],
        team_games["away_team"],
    )
    team_games["opponent"] = np.where(
        team_games["side"].eq("home"),
        team_games["away_team"],
        team_games["home_team"],
    )

    return team_games


def add_previous_season_features(team_games):
    season_summary = (
        team_games
        .groupby(["season", "team"], as_index=False)[TEAM_METRICS]
        .mean(numeric_only=True)
    )
    keys = ["season", "team"]
    grouped = team_games.groupby(keys, sort=False)
    idx = season_summary.set_index(keys).index
    for count in SITUATIONAL_COUNTS:
        season_summary[count] = grouped[count].sum().reindex(idx).to_numpy()
    for metric, count in SITUATIONAL_WEIGHTS.items():
        valid = team_games[metric].notna()
        weights = team_games[count].where(valid, 0).fillna(0)
        numerator = (team_games[metric].fillna(0) * weights).groupby(
            [team_games[key] for key in keys]
        ).sum().reindex(idx).fillna(0).to_numpy()
        denominator = weights.groupby(
            [team_games[key] for key in keys]
        ).sum().reindex(idx).fillna(0).to_numpy()
        season_summary[metric] = np.divide(
            numerator, denominator, out=np.full(len(idx), np.nan), where=denominator > 0
        )

    season_summary["season"] = season_summary["season"] + 1
    season_summary = season_summary.rename(columns={
        metric: f"prev_season_{metric}"
        for metric in TEAM_METRICS
    })

    return team_games.merge(
        season_summary,
        on=["season", "team"],
        how="left",
    )


def add_prior_week_features(team_games):
    weekly = (
        team_games
        .groupby(["season", "team", "week"], as_index=False)[TEAM_METRICS]
        .mean(numeric_only=True)
        .sort_values(["season", "team", "week"])
        .reset_index(drop=True)
    )

    weekly["prior_weeks"] = (
        weekly.groupby(["season", "team"]).cumcount()
    )
    keys = ["season", "team", "week"]
    idx = weekly.set_index(keys).index
    for count in SITUATIONAL_COUNTS:
        weekly[count] = team_games.groupby(keys)[count].sum().reindex(idx).to_numpy()

    for metric in TEAM_METRICS:
        weekly[f"pregame_{metric}"] = (
            weekly
            .groupby(["season", "team"], sort=False)[metric]
            .transform(lambda s: s.expanding().mean().shift(1))
        )

    # New splits use pooled-play numerators and exact prior-week counts. An
    # eight-play game cannot have the same weight as a 70-play game, and no
    # row can include a current-week play in its pregame feature.
    for metric, count in SITUATIONAL_WEIGHTS.items():
        valid = team_games[metric].notna()
        weights = team_games[count].where(valid, 0).fillna(0)
        numerator = (team_games[metric].fillna(0) * weights).groupby(
            [team_games[key] for key in keys]
        ).sum().reindex(idx).fillna(0).to_numpy()
        denominator = weights.groupby(
            [team_games[key] for key in keys]
        ).sum().reindex(idx).fillna(0).to_numpy()
        numerator = pd.Series(numerator, index=weekly.index)
        denominator = pd.Series(denominator, index=weekly.index)
        grouping = [weekly["season"], weekly["team"]]
        previous_num = numerator.groupby(grouping).cumsum().groupby(grouping).shift(1)
        previous_den = denominator.groupby(grouping).cumsum().groupby(grouping).shift(1)
        weekly[f"pregame_{metric}"] = previous_num / previous_den.where(previous_den.gt(0))

    for count in SITUATIONAL_COUNTS:
        grouping = [weekly["season"], weekly["team"]]
        weekly[f"pregame_{count}"] = (
            weekly[count].groupby(grouping).cumsum().groupby(grouping).shift(1)
        )

    feature_columns = [
        "season", "team", "week", "prior_weeks"
    ] + [f"pregame_{m}" for m in TEAM_METRICS]

    return team_games.merge(
        weekly[feature_columns],
        on=["season", "team", "week"],
        how="left",
    )


def make_game_table(meta, team_games):
    feature_columns = [
        c for c in team_games.columns
        if c.startswith("pregame_") or c.startswith("prev_season_")
    ]

    current_targets = REALIZED_TARGET_METRICS

    home = team_games.loc[
        team_games["side"].eq("home"),
        ["game_id", "team", "prior_weeks"]
        + current_targets
        + feature_columns,
    ].copy()

    away = team_games.loc[
        team_games["side"].eq("away"),
        ["game_id", "team", "prior_weeks"]
        + current_targets
        + feature_columns,
    ].copy()

    home = home.rename(columns={
        "team": "home_feature_team",
        "prior_weeks": "home_prior_weeks",
        **{m: f"home_{m}" for m in current_targets},
        **{c: f"home_{c}" for c in feature_columns},
    })
    away = away.rename(columns={
        "team": "away_feature_team",
        "prior_weeks": "away_prior_weeks",
        **{m: f"away_{m}" for m in current_targets},
        **{c: f"away_{c}" for c in feature_columns},
    })

    games = (
        meta
        .merge(home, on="game_id", how="left")
        .merge(away, on="game_id", how="left")
    )

    games["sealed_test_season"] = games["season"].eq(SEALED_SEASON)
    games["market_favorite"] = np.select(
        [
            games["market_home_spread"].lt(0),
            games["market_home_spread"].gt(0),
        ],
        [games["home_team"], games["away_team"]],
        default="PICK",
    )
    games["market_favorite_size"] = games["market_home_spread"].abs()

    return games.sort_values(
        ["season", "week", "game_id"]
    ).reset_index(drop=True)


def validate_output(games):
    seasons = set(
        games["season"].dropna().astype(int).unique().tolist()
    )
    expected = set(SEASONS)

    if not expected.issubset(seasons):
        raise RuntimeError(
            "Output is missing seasons: "
            + str(sorted(expected - seasons))
        )

    if games["game_id"].duplicated().any():
        raise RuntimeError(
            f"Canonical table has "
            f"{int(games['game_id'].duplicated().sum())} duplicate game IDs."
        )

    if int(games["season"].eq(SEALED_SEASON).sum()) == 0:
        raise RuntimeError("No sealed 2025 rows found.")

    if len(games) < 5000:
        raise RuntimeError(
            f"Historical game table unexpectedly small: {len(games)}"
        )
    if not games["season_type"].eq(2).all():
        raise RuntimeError("Postseason games entered the regular-season training table")
    if games["actual_first_half_margin"].notna().sum() < 1000:
        raise RuntimeError("First-half scores missing for most training games")
    for metric in ("off_iso_ppp", "off_script_epa", "off_leverage_epa", "off_red_zone_epa"):
        col = f"home_pregame_{metric}"
        if col not in games or games[col].notna().sum() < 1000:
            raise RuntimeError(f"Historical situational feature missing or sparse: {col}")

    target_cols = [
        f"{side}_{metric}"
        for side in ["home", "away"]
        for metric in REALIZED_TARGET_METRICS
    ]
    if any(c not in games.columns for c in target_cols):
        raise RuntimeError("V4 realized drive/scoring target columns missing.")

    if games[target_cols].notna().sum().sum() == 0:
        raise RuntimeError("V4 realized drive/scoring targets are all null.")

    print("Output validation passed.", flush=True)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    assets = get_release_assets()

    all_plays = []
    source_manifest = {}

    with tempfile.TemporaryDirectory(prefix="cfb_sdv_") as temp_name:
        temp_dir = Path(temp_name)

        for year in SEASONS:
            path, asset = download_season(year, assets, temp_dir)

            print(f"Reading {year} parquet...", flush=True)
            raw = pd.read_parquet(path)
            standard = normalize_season(raw, year)
            all_plays.append(standard)

            source_manifest[str(year)] = {
                "asset_name": asset["name"],
                "download_url": asset["browser_download_url"],
                "asset_size_bytes": asset.get("size"),
                "asset_digest": asset.get("digest"),
                "raw_rows": int(len(raw)),
                "standardized_rows": int(len(standard)),
                "raw_columns": int(len(raw.columns)),
                "required_situational_columns": SITUATIONAL_REQUIRED_COLUMNS,
                "situational_competitive_plays": int(standard["competitive_situational"].sum()),
                "situational_missing_down_distance": int(
                    (standard["valid_scrimmage"] & standard["down_number"].notna()
                     & standard["distance_number"].isna()).sum()
                ),
                "situational_missing_or_invalid_clock": int(
                    (standard["valid_scrimmage"] & ~standard["clock_valid"]).sum()
                ),
                "situational_overtime_plays": int(standard["situational_overtime"].sum()),
                "situational_garbage_plays": int(standard["situational_garbage"].sum()),
            }

            print(
                f"{year}: {len(standard):,} standardized plays",
                flush=True,
            )
            del raw

    plays = pd.concat(all_plays, ignore_index=True)
    # ESPN postseason week numbers restart at 1; keep the canonical rolling
    # table regular-season only to prevent postseason data contaminating Week 1.
    excluded_postseason = int((~plays["season_type"].eq(2)).sum())
    plays = plays.loc[plays["season_type"].eq(2)].copy()

    print(f"Total standardized plays: {len(plays):,}", flush=True)

    print("Building game metadata...", flush=True)
    meta = build_game_metadata(plays)

    print("Building actual possession-drive table...", flush=True)
    drives = build_drive_table(plays)

    print("Building actual team drive/scoring targets...", flush=True)
    drive_metrics = build_team_drive_metrics(drives)

    print("Building team-game efficiency...", flush=True)
    metrics = build_team_game_metrics(plays, drive_metrics)

    print("Building team perspectives...", flush=True)
    team_games = build_team_games(meta, metrics)

    populated_team_games = int(team_games["off_epa"].notna().sum())
    if populated_team_games == 0:
        raise RuntimeError(
            "All joined team-game metrics are null. "
            "Canonical ESPN team-ID mapping failed."
        )

    realized_populated = int(
        team_games["actual_drives"].notna().sum()
    )
    if realized_populated == 0:
        raise RuntimeError(
            "All V4 realized drive targets are null."
        )

    print("Adding previous-season priors...", flush=True)
    team_games = add_previous_season_features(team_games)

    print("Adding prior-week features...", flush=True)
    team_games = add_prior_week_features(team_games)

    print("Building canonical game table...", flush=True)
    games = make_game_table(meta, team_games)

    validate_output(games)
    games.to_csv(OUT_CSV, index=False)

    manifest = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "builder_version": "historical_training_v5_situational",
        "excluded_postseason_plays": excluded_postseason,
        "situational_filter": (
            "Regular season; rush/pass with EPA; regulation periods 1-4; "
            "valid start down and distance, clock, and pre-play score; "
            "clock stamp may reflect the end of play in some source years; "
            "garbage excluded at "
            "38+ points in the first half, 28+ in third, 22+ in fourth."
        ),
        "source": "SportsDataverse espn_cfb_pbp GitHub release",
        "source_release_api": RELEASE_API,
        "seasons": SEASONS,
        "sealed_test_season": SEALED_SEASON,
        "rows_games": int(len(games)),
        "rows_team_games": int(len(team_games)),
        "rows_drives": int(len(drives)),
        "rows_plays": int(len(plays)),
        "leakage_rule": (
            "same-season pregame_* features use only PRIOR WEEKS. "
            "Current-week games are never used to predict one another."
        ),
        "previous_season_rule": (
            "prev_season_* features use only the immediately previous season."
        ),
        "realized_target_rule": (
            "home_actual_* and away_actual_* drive/scoring mechanism fields "
            "are realized current-game TRAINING TARGETS. They are not copied "
            "into current-game pregame predictor fields."
        ),
        "drive_definition": (
            "one unique SportsDataverse drive.id for the mapped possession team"
        ),
        "scoring_opportunity_definition": (
            "one unique possession drive where any play has "
            "SportsDataverse scoring_opp=1"
        ),
        "drive_points_definition": (
            "possessing team's nonnegative score delta from first observed "
            "pre-play score to final chronological end-of-play score"
        ),
        "market_rule": (
            "market_home_spread and market_total are evaluation-only and "
            "not predictive model inputs."
        ),
        "market_spread_conversion": (
            "SportsDataverse ESPN gameSpread is treated as magnitude; "
            "homeFavorite determines home-team spread sign."
        ),
        "team_name_mapping": (
            "possession and defense teams map to canonical homeTeamName/"
            "awayTeamName using ESPN team IDs; no fuzzy matching."
        ),
        "final_score_rule": (
            "last chronological end.homeScore/end.awayScore when available, "
            "otherwise last homeScore/awayScore; max score is never used."
        ),
        "important_note": (
            "SportsDataverse EPA is not numerically identical to CFBD PPA."
        ),
        "source_assets": source_manifest,
        "columns": list(games.columns),
    }

    with OUT_MANIFEST.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, default=str)

    print("")
    print("=" * 78)
    print("HISTORICAL TRAINING DATA V4 BUILT")
    print("=" * 78)
    print(f"Games:       {len(games):,}")
    print(f"Team-games:  {len(team_games):,}")
    print(f"Drives:      {len(drives):,}")
    print(f"Plays:       {len(plays):,}")
    print(f"Seasons:     {SEASONS[0]}-{SEASONS[-1]}")
    print(f"Sealed:      {SEALED_SEASON}")
    print(f"CSV:         {OUT_CSV.relative_to(ROOT)}")
    print(f"Manifest:    {OUT_MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
