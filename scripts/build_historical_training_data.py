import requests
import pandas as pd
from pathlib import Path

RELEASE_API = (
    "https://api.github.com/repos/sportsdataverse/"
    "sportsdataverse-data/releases/tags/espn_cfb_pbp"
)

YEAR = 2019


def main():
    print("Getting SportsDataverse release metadata...", flush=True)

    response = requests.get(RELEASE_API, timeout=60)
    response.raise_for_status()

    assets = {
        asset["name"]: asset
        for asset in response.json().get("assets", [])
    }

    name = f"play_by_play_{YEAR}.parquet"
    asset = assets[name]
    url = asset["browser_download_url"]

    target = Path(f"/tmp/{name}")

    print(f"Downloading {YEAR}...", flush=True)

    with requests.get(url, stream=True, timeout=180) as response:
        response.raise_for_status()

        with target.open("wb") as f:
            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):
                if chunk:
                    f.write(chunk)

    print("Reading parquet...", flush=True)

    df = pd.read_parquet(target)

    print("")
    print("=" * 80)
    print("SPORTSDATAVERSE ESPN CFB PBP SCHEMA")
    print("=" * 80)

    print(f"Rows: {len(df):,}")
    print(f"Columns: {len(df.columns):,}")

    print("")
    print("ALL COLUMN NAMES")
    print("-" * 80)

    for i, column in enumerate(df.columns, start=1):
        print(f"{i:03d}: {column}")

    print("")
    print("FIRST ROW — SELECTED IDENTIFIER-LIKE VALUES")
    print("-" * 80)

    keywords = (
        "team",
        "home",
        "away",
        "game",
        "season",
        "week",
        "score",
        "spread",
        "total",
        "epa",
        "rush",
        "pass",
        "drive",
        "success",
    )

    row = df.iloc[0]

    for column in df.columns:
        lower = column.lower()

        if any(keyword in lower for keyword in keywords):
            value = row[column]
            print(f"{column}: {value}")

    print("")
    print("=" * 80)
    print("SCHEMA DIAGNOSTIC COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
