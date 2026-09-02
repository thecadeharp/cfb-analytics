"""
CFB ANALYTICS
build_historical_training_data.py

Build a frozen, API-key-free historical game-level training table from the
SportsDataverse ESPN CFB play-by-play releases.

Design goals:
- NO CollegeFootballData API calls
- Download public, precompiled Parquet releases once per season
- One canonical row per game
- Preserve market lines only for evaluation/context, never as required model features
- Build team-game efficiency summaries from play-by-play
- Build leakage-safe pregame rolling features using ONLY earlier games in the same season
- Keep 2025 in the output, but do not use 2025 to tune anything before sealed evaluation

Writes:
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


def first_present(columns, *candidates):
    for name in candidates:
        if name in columns:
            return name
    return None


def numeric(series):
    return pd.to_numeric(series, errors="coerce")


def truthy(series):
    if series.dtype == bool:
        return series.fillna(False)
    if pd.api.types.is_numeric_dtype(series):
        return numeric(series).fillna(0).ne(0)
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .isin({"1", "true", "t", "yes", "y"})
    )


def safe_mean(series):
    values = numeric(series).dropna()
    return float(values.mean()) if len(values) else np.nan


def release_assets():
    response = requests.get(RELEASE_API, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    return {asset["name"]: asset for asset in payload.get("assets", [])}


def download_season(year, assets, target_dir):
    name = f"play_by_play_{year}.parquet"
    asset = assets.get(name)
    if not asset:
        raise RuntimeError(f"SportsDataverse release asset missing: {name}")

    target = target_dir / name
    url = asset["browser_download_url"]

    print(f"Downloading {year}: {url}", flush=True)
    with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT) as response:
        response.raise_for_status()
        with target.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    return target, asset


def resolve_columns(df):
    cols = set(df.columns)

    resolved = {
        "game_id": first_present(cols, "game_id", "gameId"),
        "season": first_present(cols, "season", "year"),
        "week": first_present(cols, "week", "wk"),
        "season_type": first_present(cols, "season_type", "seasonType"),
        "game_date": first_present(cols, "game_date", "start_date", "startDate"),
        "neutral_site": first_present(cols, "neutral_site", "neutralSite"),
        "home_team": first_present(cols, "home_team", "homeTeam", "home"),
        "away_team": first_present(cols, "away_team", "awayTeam", "away"),
        "pos_team": first_present(cols, "pos_team", "offense", "offense_play"),
        "def_team": first_present(cols, "def_pos_team", "defense", "defense_play"),
        "epa": first_present(cols, "EPA", "epa"),
        "success": first_present(cols, "success", "epa_success"),
        "rush": first_present(cols, "rush", "rush_play"),
        "pass": first_present(cols, "pass", "pass_play"),
        "yards_gained": first_present(cols, "yards_gained", "yardsGained"),
        "havoc": first_present(cols, "havoc"),
        "turnover": first_present(cols, "turnover"),
        "sack": first_present(cols, "sack"),
        "tfl": first_present(cols, "TFL", "tfl"),
        "drive_id": first_present(cols, "drive_id", "id_drive"),
        "home_score": first_present(cols, "homeScore", "home_score"),
        "away_score": first_present(cols, "awayScore", "away_score"),
        "offense_score": first_present(cols, "offense_score", "pos_team_score"),
        "defense_score": first_present(cols, "defense_score", "def_pos_team_score"),
        "market_home_spread": first_present(
            cols,
            "homeTeamSpread",
            "home_team_spread",
        ),
        "market_total": first_present(cols, "overUnder", "over_under"),
        "provider": first_present(cols, "odds_source", "provider"),
    }

    required = [
        "game_id",
        "season",
        "week",
        "home_team",
        "away_team",
        "pos_team",
        "epa",
    ]
    missing = [key for key in required if resolved[key] is None]
    if missing:
        raise RuntimeError(
            "Required SportsDataverse columns could not be resolved: "
            + ", ".join(missing)
        )

    return resolved


def add_standard_columns(df, c):
    out = pd.DataFrame(index=df.index)

    out["game_id"] = df[c["game_id"]].astype(str)
    out["season"] = numeric(df[c["season"]]).astype("Int64")
    out["week"] = numeric(df[c["week"]]).astype("Int64")
    out["home_team"] = df[c["home_team"]].astype(str)
    out["away_team"] = df[c["away_team"]].astype(str)
    out["pos_team"] = df[c["pos_team"]].astype(str)

    if c["def_team"]:
        out["def_team"] = df[c["def_team"]].astype(str)
    else:
        out["def_team"] = np.where(
            out["pos_team"].eq(out["home_team"]),
            out["away_team"],
            out["home_team"],
        )

    out["epa"] = numeric(df[c["epa"]])

    if c["success"]:
        out["success"] = numeric(df[c["success"]])
    else:
        out["success"] = out["epa"].gt(0).astype(float)

    out["rush"] = truthy(df[c["rush"]]) if c["rush"] else False
    out["pass"] = truthy(df[c["pass"]]) if c["pass"] else False
    out["yards_gained"] = (
        numeric(df[c["yards_gained"]]) if c["yards_gained"] else np.nan
    )

    if c["havoc"]:
        out["havoc"] = truthy(df[c["havoc"]])
    else:
        event = pd.Series(False, index=df.index)
        for key in ("turnover", "sack", "tfl"):
            if c[key]:
                event = event | truthy(df[c[key]])
        out["havoc"] = event

    out["explosive"] = (
        (out["pass"] & out["yards_gained"].ge(15))
        | (out["rush"] & out["yards_gained"].ge(10))
    )

    if c["drive_id"]:
        out["drive_id"] = df[c["drive_id"]].astype(str)
    else:
        out["drive_id"] = np.nan

    for key in (
        "season_type",
        "game_date",
        "neutral_site",
        "home_score",
        "away_score",
        "offense_score",
        "defense_score",
        "market_home_spread",
        "market_total",
        "provider",
    ):
        col = c[key]
        out[key] = df[col] if col else np.nan

    return out


def final_score_from_game(group):
    home_score = numeric(group["home_score"]).dropna()
    away_score = numeric(group["away_score"]).dropna()

    if len(home_score) and len(away_score):
        return float(home_score.iloc[-1]), float(away_score.iloc[-1])

    mapped_home = []
    mapped_away = []

    for _, row in group.iterrows():
        off_score = pd.to_numeric(row["offense_score"], errors="coerce")
        def_score = pd.to_numeric(row["defense_score"], errors="coerce")
        if pd.isna(off_score) or pd.isna(def_score):
            continue

        if row["pos_team"] == row["home_team"]:
            mapped_home.append(float(off_score))
            mapped_away.append(float(def_score))
        elif row["pos_team"] == row["away_team"]:
            mapped_home.append(float(def_score))
            mapped_away.append(float(off_score))

    if mapped_home and mapped_away:
        return max(mapped_home), max(mapped_away)

    return np.nan, np.nan


def first_non_null(series):
    values = series.dropna()
    if not len(values):
        return np.nan
    return values.iloc[0]


def game_metadata(plays):
    rows = []

    for game_id, group in plays.groupby("game_id", sort=False):
        home_score, away_score = final_score_from_game(group)

        row = {
            "game_id": game_id,
            "season": int(group["season"].dropna().iloc[0]),
            "week": int(group["week"].dropna().iloc[0]),
            "home_team": group["home_team"].iloc[0],
            "away_team": group["away_team"].iloc[0],
            "season_type": first_non_null(group["season_type"]),
            "game_date": first_non_null(group["game_date"]),
            "neutral_site": first_non_null(group["neutral_site"]),
            "home_score": home_score,
            "away_score": away_score,
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
            "market_home_spread": safe_mean(group["market_home_spread"]),
            "market_total": safe_mean(group["market_total"]),
            "market_provider": first_non_null(group["provider"]),
        }
        rows.append(row)

    return pd.DataFrame(rows)


def team_game_metrics(plays):
    football = plays.loc[plays["rush"] | plays["pass"]].copy()
    football = football.loc[football["epa"].notna()].copy()

    if football.empty:
        raise RuntimeError("No qualifying rush/pass EPA plays found.")

    rows = []
    grouped = football.groupby(["game_id", "pos_team"], sort=False)

    for (game_id, team), g in grouped:
        rush = g.loc[g["rush"]]
        pas = g.loc[g["pass"]]

        drives = np.nan
        valid_drives = g["drive_id"].replace({"nan": np.nan}).dropna()
        if len(valid_drives):
            drives = float(valid_drives.nunique())

        rows.append(
            {
                "game_id": game_id,
                "team": team,
                "opponent": (
                    g["def_team"].mode().iloc[0]
                    if len(g["def_team"].mode())
                    else first_non_null(g["def_team"])
                ),
                "plays": int(len(g)),
                "epa": safe_mean(g["epa"]),
                "success_rate": safe_mean(g["success"]),
                "explosive_rate": float(g["explosive"].mean()),
                "pass_epa": safe_mean(pas["epa"]),
                "rush_epa": safe_mean(rush["epa"]),
                "havoc_allowed_rate": float(g["havoc"].mean()),
                "drives": drives,
            }
        )

    return pd.DataFrame(rows)


def build_team_perspective(meta, metrics):
    home = meta.merge(
        metrics,
        left_on=["game_id", "home_team"],
        right_on=["game_id", "team"],
        how="left",
    )
    away = meta.merge(
        metrics,
        left_on=["game_id", "away_team"],
        right_on=["game_id", "team"],
        how="left",
    )

    home["side"] = "home"
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

    keep = [
        "game_id",
        "season",
        "week",
        "game_date",
        "team",
        "opponent",
        "side",
        "plays",
        "epa",
        "success_rate",
        "explosive_rate",
        "pass_epa",
        "rush_epa",
        "havoc_allowed_rate",
        "drives",
    ]
    return team_games[keep]


def add_defense_allowed(team_games):
    opponent = team_games[
        [
            "game_id",
            "team",
            "epa",
            "success_rate",
            "explosive_rate",
            "pass_epa",
            "rush_epa",
            "havoc_allowed_rate",
        ]
    ].copy()

    opponent = opponent.rename(
        columns={
            "team": "opponent",
            "epa": "def_epa_allowed",
            "success_rate": "def_success_allowed",
            "explosive_rate": "def_explosive_allowed",
            "pass_epa": "def_pass_epa_allowed",
            "rush_epa": "def_rush_epa_allowed",
            "havoc_allowed_rate": "def_havoc_created_rate",
        }
    )

    return team_games.merge(
        opponent,
        on=["game_id", "opponent"],
        how="left",
    )


def leakage_safe_rolling(team_games):
    metrics = [
        "epa",
        "success_rate",
        "explosive_rate",
        "pass_epa",
        "rush_epa",
        "havoc_allowed_rate",
        "drives",
        "def_epa_allowed",
        "def_success_allowed",
        "def_explosive_allowed",
        "def_pass_epa_allowed",
        "def_rush_epa_allowed",
        "def_havoc_created_rate",
    ]

    out = team_games.copy()
    out["game_date_sort"] = pd.to_datetime(
        out["game_date"], errors="coerce", utc=True
    )
    out = out.sort_values(
        ["season", "team", "week", "game_date_sort", "game_id"],
        na_position="last",
    ).reset_index(drop=True)

    out["prior_games"] = out.groupby(["season", "team"]).cumcount()

    for metric in metrics:
        out[f"pregame_{metric}"] = (
            out.groupby(["season", "team"], sort=False)[metric]
            .transform(lambda s: s.expanding().mean().shift(1))
        )

    return out


def add_previous_season_priors(team_games):
    metrics = [
        "epa",
        "success_rate",
        "explosive_rate",
        "pass_epa",
        "rush_epa",
        "havoc_allowed_rate",
        "drives",
        "def_epa_allowed",
        "def_success_allowed",
        "def_explosive_allowed",
        "def_pass_epa_allowed",
        "def_rush_epa_allowed",
        "def_havoc_created_rate",
    ]

    season_summary = (
        team_games.groupby(["season", "team"], as_index=False)[metrics]
        .mean(numeric_only=True)
    )
    season_summary["season"] = season_summary["season"] + 1
    season_summary = season_summary.rename(
        columns={metric: f"prev_season_{metric}" for metric in metrics}
    )

    return team_games.merge(
        season_summary,
        on=["season", "team"],
        how="left",
    )


def make_game_training_table(meta, team_features):
    feature_cols = [
        c
        for c in team_features.columns
        if c.startswith("pregame_") or c.startswith("prev_season_")
    ]

    base_cols = ["game_id", "team", "prior_games"] + feature_cols

    home = team_features.loc[
        team_features["side"].eq("home"), base_cols
    ].copy()
    away = team_features.loc[
        team_features["side"].eq("away"), base_cols
    ].copy()

    home = home.rename(
        columns={
            "team": "home_feature_team",
            "prior_games": "home_prior_games",
            **{c: f"home_{c}" for c in feature_cols},
        }
    )
    away = away.rename(
        columns={
            "team": "away_feature_team",
            "prior_games": "away_prior_games",
            **{c: f"away_{c}" for c in feature_cols},
        }
    )

    games = meta.merge(home, on="game_id", how="left").merge(
        away, on="game_id", how="left"
    )

    games["sealed_test_season"] = games["season"].eq(SEALED_SEASON)
    games = games.sort_values(["season", "week", "game_date", "game_id"])
    return games.reset_index(drop=True)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    assets = release_assets()
    all_plays = []
    source_manifest = {}
    resolved_schema_by_year = {}

    with tempfile.TemporaryDirectory(prefix="cfb_sdv_") as tmp:
        tmpdir = Path(tmp)

        for year in SEASONS:
            path, asset = download_season(year, assets, tmpdir)
            print(f"Reading {year} parquet...", flush=True)
            raw = pd.read_parquet(path)
            cols = resolve_columns(raw)
            standard = add_standard_columns(raw, cols)

            all_plays.append(standard)
            resolved_schema_by_year[str(year)] = cols
            source_manifest[str(year)] = {
                "asset_name": asset["name"],
                "download_url": asset["browser_download_url"],
                "asset_size_bytes": asset.get("size"),
                "asset_digest": asset.get("digest"),
                "raw_rows": int(len(raw)),
                "standardized_rows": int(len(standard)),
            }

            del raw
            print(
                f"{year}: {len(standard):,} standardized plays",
                flush=True,
            )

    plays = pd.concat(all_plays, ignore_index=True)
    print(f"Total standardized plays: {len(plays):,}", flush=True)

    meta = game_metadata(plays)
    metrics = team_game_metrics(plays)
    team_games = build_team_perspective(meta, metrics)
    team_games = add_defense_allowed(team_games)
    team_games = leakage_safe_rolling(team_games)
    team_games = add_previous_season_priors(team_games)
    games = make_game_training_table(meta, team_games)

    games.to_csv(OUT_CSV, index=False)

    manifest = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "builder_version": "historical_training_v1_sportsdataverse",
        "source": "SportsDataverse espn_cfb_pbp GitHub release",
        "source_release_api": RELEASE_API,
        "seasons": SEASONS,
        "sealed_test_season": SEALED_SEASON,
        "rows_games": int(len(games)),
        "rows_team_games": int(len(team_games)),
        "rows_plays": int(len(plays)),
        "leakage_rule": (
            "pregame_* features use only earlier games in the same season; "
            "prev_season_* features use only the prior season"
        ),
        "market_rule": (
            "market_home_spread and market_total are retained for evaluation; "
            "they are not required predictive features"
        ),
        "explosive_definition": "15+ yard pass or 10+ yard rush",
        "havoc_definition": (
            "native SportsDataverse havoc column when available; otherwise "
            "turnover/sack/TFL proxy"
        ),
        "important_note": (
            "This SportsDataverse training table is a new canonical historical "
            "dataset. It must not be described as numerically identical to CFBD PPA."
        ),
        "source_assets": source_manifest,
        "resolved_schema_by_year": resolved_schema_by_year,
        "columns": list(games.columns),
    }

    with OUT_MANIFEST.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)

    print("=" * 78)
    print("HISTORICAL TRAINING DATA BUILT")
    print("=" * 78)
    print(f"Games:      {len(games):,}")
    print(f"Team-games: {len(team_games):,}")
    print(f"Plays:      {len(plays):,}")
    print(f"Seasons:    {SEASONS[0]}-{SEASONS[-1]}")
    print(f"Sealed:     {SEALED_SEASON}")
    print(f"CSV:        {OUT_CSV.relative_to(ROOT)}")
    print(f"Manifest:   {OUT_MANIFEST.relative_to(ROOT)}")

    season_counts = games.groupby("season").size()
    for year, count in season_counts.items():
        print(f"  {int(year)}: {int(count):,} games")


if __name__ == "__main__":
    main()
