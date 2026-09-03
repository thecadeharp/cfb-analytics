name: Settle Results + Live Scores - No CFBD

on:
  workflow_dispatch:

  # Refresh scoreboard state every 10 minutes.
  # This powers LIVE rows and also catches finals quickly.
  schedule:
    - cron: "*/10 * * * *"

permissions:
  contents: write

concurrency:
  group: settle-results-no-cfbd
  cancel-in-progress: false

jobs:
  settle:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests

      - name: Fetch live and completed 2026 scores without CFBD
        env:
          CFB_SEASON: "2026"
        run: |
          python scripts/fetch_results_no_cfbd.py

      - name: Settle prospective projections
        run: |
          python scripts/settle_results.py

      - name: Commit scoreboard and settlement outputs
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

          git add data/results.json
          git add data/live_scores.json
          git add data/reports/settled_results.json
          git add data/reports/settled_snapshot_rows.csv

          if git diff --cached --quiet; then
            echo "No scoreboard or settlement changes to commit."
            exit 0
          fi

          git commit -m "Refresh live scores and settle completed games"
          git pull --rebase origin main
          git push origin main
