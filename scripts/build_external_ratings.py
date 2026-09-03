"""Build display-only external ratings from SportsDataverse datasets."""

import json
import math
import os
import tempfile
from datetime import datetime

import pandas as pd
import requests


YEAR = 2026
OUTPUT_PATH = "data/external_ratings.json"
METRICS_PATH = "data/cfb_metrics.json"
BASE = "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-cfb-data/main/cfb"
FPI_URL = f"{BASE}/fpi_weekly/parquet/cfb_fpi_weekly_{YEAR}.parquet"
TEAMS_URL = f"{BASE}/cfb_teams/parquet/cfb_teams_{YEAR}.parquet"

TEAM_NAME_ALIASES = {
    "Sam José State": "San Jose State",
    "Sam Jose State": "San Jose State",
    "San José State": "San Jose State",
    "Appalachian State": "App State",
    "Connecticut": "UConn",
    "Louisiana Monroe": "UL Monroe",
    "Southern Mississippi": "Southern Miss",
    "UT San Antonio": "UTSA",
}


def normalize_team(value):
    name = str(value or "").strip()
    return TEAM_NAME_ALIASES.get(name, name)


def value(raw, digits=None, positive=False):
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    if digits is None:
        return int(number) if number.is_integer() else number
    return round(number, digits)


def download_parquet(url):
    response = requests.get(url, timeout=90)
    response.raise_for_status()
    if len(response.content) < 1_000:
        raise RuntimeError(f"Dataset is unexpectedly small: {url}")
    temp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
    try:
        temp.write(response.content)
        temp.close()
        return pd.read_parquet(temp.name)
    finally:
        if not temp.closed:
            temp.close()
        if os.path.exists(temp.name):
            os.remove(temp.name)


def select_snapshot(frame):
    frame = frame[pd.to_numeric(frame["season"], errors="coerce") == YEAR].copy()
    if "snapshot_is_contemporaneous" in frame.columns:
        contemporary = frame[frame["snapshot_is_contemporaneous"].fillna(False).astype(bool)]
        if not contemporary.empty:
            frame = contemporary

    counts = frame.groupby("week")["team_id"].nunique().sort_index()
    eligible = counts[counts >= 100]
    if eligible.empty:
        raise RuntimeError("No complete 2026 FPI snapshot contains at least 100 teams")
    latest_week = int(eligible.index.max())
    snapshot = frame[pd.to_numeric(frame["week"], errors="coerce") == latest_week].copy()
    snapshot = snapshot.sort_values(["team_id", "run_date_time_key"]).drop_duplicates(
        "team_id", keep="last"
    )
    return latest_week, snapshot


def main():
    with open(METRICS_PATH, "r", encoding="utf-8") as file:
        model_teams = set((json.load(file).get("teams") or {}).keys())
    if len(model_teams) < 100:
        raise RuntimeError("Existing model team list contains fewer than 100 teams")

    print("Downloading SportsDataverse weekly FPI snapshot...")
    fpi = download_parquet(FPI_URL)
    team_reference = download_parquet(TEAMS_URL)
    latest_week, snapshot = select_snapshot(fpi)

    names = (
        team_reference[team_reference["is_fbs"].fillna(False).astype(bool)]
        [["team_id", "school"]]
        .drop_duplicates("team_id", keep="last")
    )
    snapshot = snapshot.merge(names, on="team_id", how="left")

    output = {
        "meta": {
            "year": YEAR,
            "week": latest_week,
            "generated": datetime.now().isoformat(),
            "last_updated": str(snapshot["last_updated"].dropna().max()),
            "source": "SportsDataverse cfbfastR ESPN FPI weekly snapshot",
            "model_usage": "display_only_not_used_by_model_a",
            "definitions": {
                "fpi": "ESPN Football Power Index; points above or below average",
                "sor_rank": "ESPN accomplishment/Strength of Record rank",
                "sos_rank": "ESPN average schedule strength rank",
                "remaining_sos_rank": "ESPN remaining schedule strength rank",
            },
        },
        "teams": {},
    }

    for _, row in snapshot.iterrows():
        team = normalize_team(row.get("school"))
        if team not in model_teams:
            continue
        output["teams"][team] = {
            "fpi": value(row.get("fpi"), 3),
            "fpi_rank": value(row.get("fpirank"), positive=True),
            "sor_rank": value(row.get("accomplishmentrank"), positive=True),
            "sos_rank": value(row.get("avgsosrank"), positive=True),
            "remaining_sos_rank": value(row.get("sosremainingrank"), positive=True),
            "game_control_rank": value(row.get("gamecontrolrank"), positive=True),
            "projected_wins": value(row.get("projectedw"), 2),
            "projected_losses": value(row.get("projectedl"), 2),
            "win_out_pct": value(row.get("probwinout"), 1),
            "win_conference_pct": value(row.get("probwinconf"), 1),
            "make_playoff_pct": value(row.get("probmakeplayoffs"), 1),
            "make_title_game_pct": value(row.get("probmaketitlegame"), 1),
            "win_title_pct": value(row.get("probwintitle"), 1),
            "fpi_offense": value(row.get("epaoffense"), 3),
            "fpi_defense": value(row.get("epadefense"), 3),
            "fpi_special_teams": value(row.get("epaspecialteams"), 3),
        }

    if len(output["teams"]) < 130:
        raise RuntimeError(
            f"External ratings safety check failed: only {len(output['teams'])} teams mapped"
        )

    temp_path = OUTPUT_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(output, file, indent=2, ensure_ascii=False, allow_nan=False)
    os.replace(temp_path, OUTPUT_PATH)
    print(f"✅ External ratings written for {len(output['teams'])} teams")
    print(f"✅ FPI snapshot week: {latest_week}")
    print("✅ Model A files were not changed")


if __name__ == "__main__":
    main()

