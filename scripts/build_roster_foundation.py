"""Build display-only roster foundation metrics from SportsDataverse datasets."""

import json
import math
import os
import tempfile
from datetime import datetime, timezone

import pandas as pd
import requests


YEAR = 2026
OUTPUT_PATH = "data/roster_foundation.json"
METRICS_PATH = "data/cfb_metrics.json"
BASE = "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-cfb-data/main/cfb"
RETURNING_URL = (
    f"{BASE}/cfb_returning_production/parquet/"
    f"cfb_returning_production_{YEAR}.parquet"
)
TALENT_URL = f"{BASE}/cfb_team_talent/parquet/cfb_team_talent_{YEAR}.parquet"
TEAMS_URL = f"{BASE}/cfb_teams/parquet/cfb_teams_{YEAR}.parquet"

TEAM_NAME_ALIASES = {
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


def number(raw, digits=None):
    try:
        result = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    if digits is None:
        return int(result) if result.is_integer() else result
    return round(result, digits)


def percentage(raw):
    value = number(raw)
    if value is None or value < 0 or value > 1:
        return None
    return round(value * 100, 1)


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


def normalize_ids(frame):
    copy = frame.copy()
    copy["team_id"] = pd.to_numeric(copy["team_id"], errors="coerce").astype("Int64")
    return copy


def rank_values(rows, field, rank_field):
    valid = [row for row in rows if row.get(field) is not None]
    valid.sort(key=lambda row: (-row[field], row["team"]))
    previous = None
    previous_rank = 0
    for position, row in enumerate(valid, start=1):
        if row[field] != previous:
            previous_rank = position
            previous = row[field]
        row[rank_field] = previous_rank


def main():
    with open(METRICS_PATH, "r", encoding="utf-8") as file:
        model_teams = set((json.load(file).get("teams") or {}).keys())
    if len(model_teams) < 100:
        raise RuntimeError("Existing model team list contains fewer than 100 teams")

    print("Downloading SportsDataverse roster foundation datasets...")
    returning = normalize_ids(download_parquet(RETURNING_URL))
    talent = normalize_ids(download_parquet(TALENT_URL))
    reference = normalize_ids(download_parquet(TEAMS_URL))

    reference = (
        reference[reference["is_fbs"].fillna(False).astype(bool)]
        [["team_id", "school"]]
        .dropna(subset=["team_id", "school"])
        .drop_duplicates("team_id", keep="last")
    )
    returning = returning[pd.to_numeric(returning["season"], errors="coerce") == YEAR]
    talent = talent[pd.to_numeric(talent["season"], errors="coerce") == YEAR]
    returning = returning.merge(reference, on="team_id", how="inner")
    talent = talent.merge(reference, on="team_id", how="inner")

    returning_by_id = returning.set_index("team_id").to_dict("index")
    talent_by_id = talent.set_index("team_id").to_dict("index")
    rows = []

    for _, team_ref in reference.iterrows():
        team = normalize_team(team_ref["school"])
        if team not in model_teams:
            continue

        team_id = team_ref["team_id"]
        rp = returning_by_id.get(team_id, {})
        tt = talent_by_id.get(team_id, {})
        offense = percentage(rp.get("off_returning"))
        defense = percentage(rp.get("def_returning"))
        combined = (
            round((offense + defense) / 2, 1)
            if offense is not None and defense is not None
            else None
        )

        rows.append({
            "team": team,
            "returning_production_pct": combined,
            "returning_offense_pct": offense,
            "returning_defense_pct": defense,
            "returning_players": number(rp.get("n_returning")),
            "talent_composite": number(tt.get("talent_composite"), 2),
            "talent_rank": None,
            "blue_chip_ratio_pct": percentage(tt.get("blue_chip_ratio")),
            "rated_recruits": number(tt.get("n_recruits")),
        })

    rank_values(rows, "returning_production_pct", "returning_production_rank")
    rank_values(rows, "returning_offense_pct", "returning_offense_rank")
    rank_values(rows, "returning_defense_pct", "returning_defense_rank")
    rank_values(rows, "talent_composite", "talent_rank")

    teams = {}
    for row in sorted(rows, key=lambda item: item["team"]):
        team = row.pop("team")
        teams[team] = row

    if len(teams) < 130:
        raise RuntimeError(f"Roster foundation safety check failed: only {len(teams)} teams mapped")

    output = {
        "meta": {
            "year": YEAR,
            "generated": datetime.now(timezone.utc).isoformat(),
            "source": "SportsDataverse cfbfastR roster datasets",
            "model_usage": "display_only_not_used_by_model_a",
            "portal_data_included": False,
            "definitions": {
                "returning_production_pct": (
                    "Simple average of the source offensive and defensive returning-production shares"
                ),
                "returning_offense_pct": "Source offensive returning-production share",
                "returning_defense_pct": "Source defensive returning-production share",
                "talent_composite": "SportsDataverse team-talent composite",
                "blue_chip_ratio_pct": "Share of rated recruits classified as blue-chip players",
            },
        },
        "teams": teams,
    }

    temp_path = OUTPUT_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(output, file, indent=2, ensure_ascii=False, allow_nan=False)
    os.replace(temp_path, OUTPUT_PATH)
    talent_count = sum(team["talent_composite"] is not None for team in teams.values())
    print(f"✅ Roster foundation written for {len(teams)} teams")
    print(f"✅ Team talent available for {talent_count} teams")
    print("✅ Transfer Portal data was not added")
    print("✅ Model A files were not changed")


if __name__ == "__main__":
    main()
