"""
CFB ANALYTICS
build_historical_training_data.py

Build a frozen, API-key-free historical game-level training table from the
SportsDataverse ESPN CFB play-by-play releases.

IMPORTANT DATA RULES
--------------------
1. No CollegeFootballData API calls.
2. 2025 is preserved as the sealed test season.
3. Same-season pregame features use ONLY PRIOR WEEKS, never games from the
   current week. This is intentionally conservative and prevents same-week
   ordering leakage when exact kickoff timestamps are unavailable.
4. Previous-season priors use only the previous completed season.
5. Market lines are retained for evaluation. They are NOT predictive features.
6. SportsDataverse EPA is treated as its own historical source. It is not
   described as numerically identical to CFBD PPA.

Outputs
-------
data/training/historical_games.csv
data/training/historical_training_manifest.json
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


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

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
    if values.empty:
        return np.nan
    return float(values.mean())


def safe_sum(series):
    values = num(series).dropna()
    if values.empty:
        return np.nan
    return float(values.sum())


def first_non_null(series):
    values = series.dropna()
    if values.empty:
        return np.nan
    return values.iloc[0]


def last_non_null(series):
    values = series.dropna()
    if values.empty:
        return np.nan
    return values.iloc[-1]


# ---------------------------------------------------------------------------
# SportsDataverse release access
# ---------------------------------------------------------------------------

def get_release_assets():
    print("Getting SportsDataverse release metadata...", flush=True)

    response = requests.get(RELEASE_API, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    payload = response.json()
    return {
        asset["name"]: asset
        for asset in payload.get("assets", [])
    }


def download_season(year, assets, target_dir):
    asset_name = f"play_by_play_{year}.parquet"

    if asset_name not in assets:
        raise RuntimeError(
            f"SportsDataverse release is missing {asset_name}"
        )

    asset = assets[asset_name]
    url = asset["browser_download_url"]
    target = target_dir / asset_name

    print(f"Downloading {year}: {url}", flush=True)

    with requests.get(
        url,
        stream=True,
        timeout=REQUEST_TIMEOUT,
    ) as response:
        response.raise_for_status()

        with target.open("wb") as handle:
            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):
                if chunk:
                    handle.write(chunk)

    return target, asset


# ---------------------------------------------------------------------------
# Schema validation / normalization
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = [
    "season",
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


OPTIONAL_COLUMNS = [
    "seasonType",
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
    "start.yardsToEndzone",
    "end.homeScore",
    "end.awayScore",
]


def validate_schema(df, year):
    missing = [
        column
        for column in REQUIRED_COLUMNS
        if column not in df.columns
    ]

    if missing:
        raise RuntimeError(
            f"{year} SportsDataverse schema missing required columns: "
            + ", ".join(missing)
        )


def normalize_season(df, year):
    validate_schema(df, year)

    columns = REQUIRED_COLUMNS + [
        column
        for column in OPTIONAL_COLUMNS
        if column in df.columns
    ]

    work = df[columns].copy()

    work["season"] = num(work["season"]).astype("Int64")
    work["week"] = num(work["week"]).astype("Int64")
    work["game_id"] = work["game_id"].astype(str)

    work["home_team"] = work["homeTeamName"].astype(str)
    work["away_team"] = work["awayTeamName"].astype(str)

    # IMPORTANT:
    # SportsDataverse pos_team / def_pos_team are often full display names
    # ("Miami Hurricanes") while homeTeamName / awayTeamName are short
    # canonical names ("Miami"). Joining on those strings silently produced
    # all-null team metrics in V2.
    #
    # Map offense and defense to the canonical home/away names by ESPN team ID
    # instead. This makes the team-game metrics and schedule rows use the same
    # naming system without fuzzy matching.
    pos_id = work["pos_team_id"].astype(str)
    def_id = work["def_pos_team_id"].astype(str)
    home_id = work["homeTeamId"].astype(str)
    away_id = work["awayTeamId"].astype(str)

    work["offense"] = np.select(
        [pos_id.eq(home_id), pos_id.eq(away_id)],
        [work["home_team"], work["away_team"]],
        default=np.nan,
    )
    work["defense"] = np.select(
        [def_id.eq(home_id), def_id.eq(away_id)],
        [work["home_team"], work["away_team"]],
        default=np.nan,
    )

    work["play_order"] = num(work["game_play_number"])

    work["epa"] = num(work["EPA"])
    work["success"] = boolish(work["EPA_success"]).astype(float)
    work["explosive"] = boolish(work["EPA_explosive"]).astype(float)
    work["havoc"] = boolish(work["havoc"]).astype(float)

    work["rush_play"] = boolish(work["rush"])
    work["pass_play"] = boolish(work["pass"])

    if "scrimmage_play" in work.columns:
        work["valid_scrimmage"] = boolish(work["scrimmage_play"])
    else:
        work["valid_scrimmage"] = (
            work["rush_play"] | work["pass_play"]
        )

    if "action_play" in work.columns:
        work["valid_scrimmage"] = (
            work["valid_scrimmage"]
            & boolish(work["action_play"])
        )

    if "kneel_down" in work.columns:
        work["valid_scrimmage"] = (
            work["valid_scrimmage"]
            & ~boolish(work["kneel_down"])
        )

    if "penalty_no_play" in work.columns:
        work["valid_scrimmage"] = (
            work["valid_scrimmage"]
            & ~boolish(work["penalty_no_play"])
        )

    work["home_score_play"] = num(work["homeScore"])
    work["away_score_play"] = num(work["awayScore"])

    work["end_home_score_play"] = (
        num(work["end.homeScore"])
        if "end.homeScore" in work.columns
        else np.nan
    )
    work["end_away_score_play"] = (
        num(work["end.awayScore"])
        if "end.awayScore" in work.columns
        else np.nan
    )

    work["game_spread"] = num(work["gameSpread"])
    work["home_favorite"] = boolish(work["homeFavorite"])
    work["spread_available"] = boolish(
        work["gameSpreadAvailable"]
    )
    work["market_total_play"] = num(work["overUnder"])

    # SportsDataverse's gameSpread is a magnitude in this ESPN dataset.
    # Convert it into our standard HOME-TEAM spread convention:
    # home favorite -> negative home spread
    # away favorite -> positive home spread
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
    work.loc[
        work["drive.id"].isna(),
        "drive_id",
    ] = np.nan

    if "seasonType" in work.columns:
        work["season_type"] = num(work["seasonType"])
    else:
        work["season_type"] = np.nan

    if "status_type_completed" in work.columns:
        work["completed"] = boolish(
            work["status_type_completed"]
        )
    else:
        work["completed"] = True

    if "line_yards" in work.columns:
        work["line_yards"] = num(work["line_yards"])
    else:
        work["line_yards"] = np.nan

    if "scoring_opp" in work.columns:
        work["scoring_opp"] = boolish(
            work["scoring_opp"]
        ).astype(float)
    else:
        work["scoring_opp"] = np.nan

    if "start.yardsToEndzone" in work.columns:
        work["yards_to_endzone"] = num(
            work["start.yardsToEndzone"]
        )
    else:
        work["yards_to_endzone"] = np.nan

    return work


# ---------------------------------------------------------------------------
# Game metadata
# ---------------------------------------------------------------------------

def build_game_metadata(plays):
    rows = []

    for game_id, group in plays.groupby(
        "game_id",
        sort=False,
    ):
        # Put each game's plays in explicit chronological order. The earlier
        # builder used max(homeScore/awayScore), but the ESPN-derived file has
        # occasional malformed intermediate score values. The final observed
        # end-of-play score is the correct game result target.
        ordered = group.sort_values(
            ["play_order"],
            kind="stable",
            na_position="last",
        )

        end_home_scores = ordered["end_home_score_play"].dropna()
        end_away_scores = ordered["end_away_score_play"].dropna()
        home_scores = ordered["home_score_play"].dropna()
        away_scores = ordered["away_score_play"].dropna()

        home_score = (
            float(end_home_scores.iloc[-1])
            if not end_home_scores.empty
            else (
                float(home_scores.iloc[-1])
                if not home_scores.empty
                else np.nan
            )
        )
        away_score = (
            float(end_away_scores.iloc[-1])
            if not end_away_scores.empty
            else (
                float(away_scores.iloc[-1])
                if not away_scores.empty
                else np.nan
            )
        )

        market_home_spread = first_non_null(
            group["market_home_spread_play"]
        )
        market_total = first_non_null(
            group["market_total_play"]
        )

        rows.append(
            {
                "game_id": game_id,
                "season": int(
                    group["season"].dropna().iloc[0]
                ),
                "week": int(
                    group["week"].dropna().iloc[0]
                ),
                "season_type": first_non_null(
                    group["season_type"]
                ),
                "home_team": group["home_team"].iloc[0],
                "away_team": group["away_team"].iloc[0],
                "home_score": home_score,
                "away_score": away_score,
                "actual_home_margin": (
                    home_score - away_score
                    if not pd.isna(home_score)
                    and not pd.isna(away_score)
                    else np.nan
                ),
                "actual_total": (
                    home_score + away_score
                    if not pd.isna(home_score)
                    and not pd.isna(away_score)
                    else np.nan
                ),
                "market_home_spread": market_home_spread,
                "market_total": market_total,
                "completed": bool(
                    group["completed"].fillna(False).any()
                ),
            }
        )

    meta = pd.DataFrame(rows)

    # Keep rows that look like real completed games with both teams.
    meta = meta.loc[
        meta["home_team"].notna()
        & meta["away_team"].notna()
        & meta["home_score"].notna()
        & meta["away_score"].notna()
    ].copy()

    return meta


# ---------------------------------------------------------------------------
# Team-game efficiency
# ---------------------------------------------------------------------------

def build_team_game_metrics(plays):
    football = plays.loc[
        plays["valid_scrimmage"]
        & plays["epa"].notna()
        & (plays["rush_play"] | plays["pass_play"])
    ].copy()

    if football.empty:
        raise RuntimeError(
            "No valid rush/pass EPA plays found."
        )

    rows = []

    for (game_id, team), group in football.groupby(
        ["game_id", "offense"],
        sort=False,
    ):
        rush = group.loc[group["rush_play"]]
        pas = group.loc[group["pass_play"]]

        valid_drives = (
            group["drive_id"]
            .replace({"nan": np.nan})
            .dropna()
        )

        drives = (
            float(valid_drives.nunique())
            if not valid_drives.empty
            else np.nan
        )

        rows.append(
            {
                "game_id": game_id,
                "team": team,
                "opponent": first_non_null(
                    group["defense"]
                ),
                "plays": int(len(group)),
                "off_epa": safe_mean(group["epa"]),
                "off_success_rate": safe_mean(
                    group["success"]
                ),
                "off_explosive_rate": safe_mean(
                    group["explosive"]
                ),
                "off_pass_epa": safe_mean(
                    pas["epa"]
                ),
                "off_rush_epa": safe_mean(
                    rush["epa"]
                ),
                "havoc_allowed_rate": safe_mean(
                    group["havoc"]
                ),
                "line_yards_per_rush": safe_mean(
                    rush["line_yards"]
                ),
                "scoring_opp_rate": safe_mean(
                    group["scoring_opp"]
                ),
                "avg_start_yards_to_endzone": safe_mean(
                    group["yards_to_endzone"]
                ),
                "drives": drives,
                "plays_per_drive": (
                    float(len(group)) / drives
                    if drives
                    and not pd.isna(drives)
                    and drives > 0
                    else np.nan
                ),
            }
        )

    offense = pd.DataFrame(rows)

    # Defense is the opponent offense's output, expressed as "allowed".
    defense = offense[
        [
            "game_id",
            "team",
            "off_epa",
            "off_success_rate",
            "off_explosive_rate",
            "off_pass_epa",
            "off_rush_epa",
            "havoc_allowed_rate",
            "line_yards_per_rush",
            "scoring_opp_rate",
        ]
    ].copy()

    defense = defense.rename(
        columns={
            "team": "opponent",
            "off_epa": "def_epa_allowed",
            "off_success_rate": "def_success_allowed",
            "off_explosive_rate": "def_explosive_allowed",
            "off_pass_epa": "def_pass_epa_allowed",
            "off_rush_epa": "def_rush_epa_allowed",
            "havoc_allowed_rate": "def_havoc_created_rate",
            "line_yards_per_rush": "def_line_yards_allowed",
            "scoring_opp_rate": "def_scoring_opp_allowed",
        }
    )

    return offense.merge(
        defense,
        on=["game_id", "opponent"],
        how="left",
    )


# ---------------------------------------------------------------------------
# Team perspective + leakage-safe pregame features
# ---------------------------------------------------------------------------

TEAM_METRICS = [
    "off_epa",
    "off_success_rate",
    "off_explosive_rate",
    "off_pass_epa",
    "off_rush_epa",
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
    "def_havoc_created_rate",
    "def_line_yards_allowed",
    "def_scoring_opp_allowed",
]


def build_team_games(meta, metrics):
    base = meta[
        [
            "game_id",
            "season",
            "week",
            "home_team",
            "away_team",
        ]
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

    team_games = pd.concat(
        [home, away],
        ignore_index=True,
    )

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
        .groupby(
            ["season", "team"],
            as_index=False,
        )[TEAM_METRICS]
        .mean(numeric_only=True)
    )

    season_summary["season"] = (
        season_summary["season"] + 1
    )

    season_summary = season_summary.rename(
        columns={
            metric: f"prev_season_{metric}"
            for metric in TEAM_METRICS
        }
    )

    return team_games.merge(
        season_summary,
        on=["season", "team"],
        how="left",
    )


def add_prior_week_features(team_games):
    """
    Build SAME-SEASON pregame features using only PRIOR WEEKS.

    We intentionally aggregate to one team-week row first, then shift the
    expanding means by one week. This prevents accidental leakage between
    games played in the same week when exact kickoff timestamps are absent.
    """

    weekly = (
        team_games
        .groupby(
            ["season", "team", "week"],
            as_index=False,
        )[TEAM_METRICS]
        .mean(numeric_only=True)
        .sort_values(
            ["season", "team", "week"]
        )
        .reset_index(drop=True)
    )

    weekly["prior_weeks"] = (
        weekly
        .groupby(["season", "team"])
        .cumcount()
    )

    for metric in TEAM_METRICS:
        weekly[f"pregame_{metric}"] = (
            weekly
            .groupby(
                ["season", "team"],
                sort=False,
            )[metric]
            .transform(
                lambda series:
                series.expanding().mean().shift(1)
            )
        )

    feature_columns = [
        "season",
        "team",
        "week",
        "prior_weeks",
    ] + [
        f"pregame_{metric}"
        for metric in TEAM_METRICS
    ]

    return team_games.merge(
        weekly[feature_columns],
        on=["season", "team", "week"],
        how="left",
    )


# ---------------------------------------------------------------------------
# Canonical one-row-per-game table
# ---------------------------------------------------------------------------

def make_game_table(meta, team_games):
    pregame_columns = [
        column
        for column in team_games.columns
        if column.startswith("pregame_")
        or column.startswith("prev_season_")
    ]

    home = team_games.loc[
        team_games["side"].eq("home"),
        ["game_id", "team", "prior_weeks"]
        + pregame_columns,
    ].copy()

    away = team_games.loc[
        team_games["side"].eq("away"),
        ["game_id", "team", "prior_weeks"]
        + pregame_columns,
    ].copy()

    home = home.rename(
        columns={
            "team": "home_feature_team",
            "prior_weeks": "home_prior_weeks",
            **{
                column: f"home_{column}"
                for column in pregame_columns
            },
        }
    )

    away = away.rename(
        columns={
            "team": "away_feature_team",
            "prior_weeks": "away_prior_weeks",
            **{
                column: f"away_{column}"
                for column in pregame_columns
            },
        }
    )

    games = (
        meta
        .merge(home, on="game_id", how="left")
        .merge(away, on="game_id", how="left")
    )

    games["sealed_test_season"] = (
        games["season"].eq(SEALED_SEASON)
    )

    games["market_favorite"] = np.select(
        [
            games["market_home_spread"].lt(0),
            games["market_home_spread"].gt(0),
        ],
        [
            games["home_team"],
            games["away_team"],
        ],
        default="PICK",
    )

    games["market_favorite_size"] = (
        games["market_home_spread"].abs()
    )

    games = games.sort_values(
        ["season", "week", "game_id"]
    ).reset_index(drop=True)

    return games


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_output(games):
    seasons = set(
        games["season"]
        .dropna()
        .astype(int)
        .unique()
        .tolist()
    )

    expected = set(SEASONS)

    if not expected.issubset(seasons):
        raise RuntimeError(
            "Output is missing seasons: "
            + str(sorted(expected - seasons))
        )

    if games["game_id"].duplicated().any():
        duplicate_count = int(
            games["game_id"].duplicated().sum()
        )
        raise RuntimeError(
            f"Canonical table has {duplicate_count} duplicate game IDs."
        )

    sealed_rows = int(
        games["season"].eq(
            SEALED_SEASON
        ).sum()
    )

    if sealed_rows == 0:
        raise RuntimeError(
            "No sealed 2025 rows found."
        )

    if len(games) < 5000:
        raise RuntimeError(
            f"Historical game table unexpectedly small: {len(games)}"
        )

    print("Output validation passed.", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    OUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    assets = get_release_assets()

    all_plays = []
    source_manifest = {}

    with tempfile.TemporaryDirectory(
        prefix="cfb_sdv_"
    ) as temp_name:
        temp_dir = Path(temp_name)

        for year in SEASONS:
            path, asset = download_season(
                year,
                assets,
                temp_dir,
            )

            print(
                f"Reading {year} parquet...",
                flush=True,
            )

            raw = pd.read_parquet(path)
            standard = normalize_season(
                raw,
                year,
            )

            all_plays.append(standard)

            source_manifest[str(year)] = {
                "asset_name": asset["name"],
                "download_url": asset[
                    "browser_download_url"
                ],
                "asset_size_bytes": asset.get(
                    "size"
                ),
                "asset_digest": asset.get(
                    "digest"
                ),
                "raw_rows": int(len(raw)),
                "standardized_rows": int(
                    len(standard)
                ),
                "raw_columns": int(
                    len(raw.columns)
                ),
            }

            print(
                f"{year}: "
                f"{len(standard):,} standardized plays",
                flush=True,
            )

            del raw

    plays = pd.concat(
        all_plays,
        ignore_index=True,
    )

    print(
        f"Total standardized plays: "
        f"{len(plays):,}",
        flush=True,
    )

    print("Building game metadata...", flush=True)
    meta = build_game_metadata(plays)

    print("Building team-game efficiency...", flush=True)
    metrics = build_team_game_metrics(plays)

    print("Building team perspectives...", flush=True)
    team_games = build_team_games(
        meta,
        metrics,
    )

    # Guard against the exact V2 failure mode: schedule team names existed,
    # but the metrics join silently returned nulls because display-name formats
    # differed. Stop here if canonical mapping ever breaks again.
    populated_team_games = int(
        team_games["off_epa"].notna().sum()
    )
    if populated_team_games == 0:
        raise RuntimeError(
            "Team-game efficiency join produced zero populated off_epa rows."
        )

    print(
        f"Populated team-game EPA rows: {populated_team_games:,}",
        flush=True,
    )

    print("Adding previous-season priors...", flush=True)
    team_games = add_previous_season_features(
        team_games
    )

    print(
        "Adding leakage-safe prior-week features...",
        flush=True,
    )
    team_games = add_prior_week_features(
        team_games
    )

    print("Building canonical game table...", flush=True)
    games = make_game_table(
        meta,
        team_games,
    )

    validate_output(games)

    games.to_csv(
        OUT_CSV,
        index=False,
    )

    manifest = {
        "generated": datetime.now(
            timezone.utc
        ).isoformat(),
        "builder_version": (
            "historical_training_v3_"
            "sportsdataverse_espn"
        ),
        "source": (
            "SportsDataverse "
            "espn_cfb_pbp GitHub release"
        ),
        "source_release_api": RELEASE_API,
        "seasons": SEASONS,
        "sealed_test_season": SEALED_SEASON,
        "rows_games": int(len(games)),
        "rows_team_games": int(
            len(team_games)
        ),
        "rows_plays": int(len(plays)),
        "leakage_rule": (
            "same-season pregame_* features "
            "use only PRIOR WEEKS. Games from "
            "the current week are never used "
            "to predict other games in that week."
        ),
        "previous_season_rule": (
            "prev_season_* features use only "
            "the immediately previous season."
        ),
        "market_rule": (
            "market_home_spread and market_total "
            "are retained for evaluation only. "
            "They are not predictive model inputs."
        ),
        "market_spread_conversion": (
            "SportsDataverse ESPN gameSpread is "
            "treated as a magnitude. homeFavorite "
            "is used to convert it to the standard "
            "home-team spread sign convention."
        ),
        "success_definition": (
            "SportsDataverse EPA_success"
        ),
        "explosive_definition": (
            "SportsDataverse EPA_explosive"
        ),
        "havoc_definition": (
            "SportsDataverse havoc"
        ),
        "neutral_site_status": (
            "Neutral-site metadata is not present "
            "in the inspected ESPN PBP schema and "
            "is therefore not inferred here. "
            "Venue enrichment must be added from a "
            "separate schedule source before venue "
            "effects are used in the new model."
        ),
        "team_name_mapping": (
            "possession and defense teams are mapped to canonical "
            "homeTeamName/awayTeamName values using ESPN team IDs; "
            "no fuzzy team-name matching is used."
        ),
        "final_score_rule": (
            "final scores use the last chronological end.homeScore/"
            "end.awayScore when available, otherwise the last homeScore/"
            "awayScore; max score is never used."
        ),
        "important_note": (
            "SportsDataverse EPA is a new canonical "
            "historical source for this training table "
            "and must not be described as numerically "
            "identical to CFBD PPA."
        ),
        "source_assets": source_manifest,
        "columns": list(games.columns),
    }

    with OUT_MANIFEST.open(
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            manifest,
            handle,
            indent=2,
            default=str,
        )

    print("")
    print("=" * 78)
    print("HISTORICAL TRAINING DATA BUILT")
    print("=" * 78)
    print(f"Games:      {len(games):,}")
    print(f"Team-games: {len(team_games):,}")
    print(f"Plays:      {len(plays):,}")
    print(
        f"Seasons:    "
        f"{SEASONS[0]}-{SEASONS[-1]}"
    )
    print(f"Sealed:     {SEALED_SEASON}")
    print(
        f"CSV:        "
        f"{OUT_CSV.relative_to(ROOT)}"
    )
    print(
        f"Manifest:   "
        f"{OUT_MANIFEST.relative_to(ROOT)}"
    )
    print("")

    for year, count in (
        games.groupby("season").size().items()
    ):
        print(
            f"  {int(year)}: "
            f"{int(count):,} games"
        )


if __name__ == "__main__":
    main()
