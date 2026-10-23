#!/usr/bin/env bash
set -euo pipefail

commit_message="${1:-Refresh CFB live score pulse}"

stage_scoreboard() {
  git add data/results.json data/live_scores.json
}

commit_scoreboard_if_changed() {
  stage_scoreboard
  if git diff --cached --quiet; then
    return 1
  fi
  git commit -m "$commit_message"
}

if ! commit_scoreboard_if_changed; then
  echo "No scoreboard change to publish."
  exit 0
fi

for attempt in 1 2 3 4 5; do
  git fetch origin main
  if ! git rebase origin/main; then
    echo "Scoreboard data changed upstream; regenerating from current main."
    git rebase --abort || true
    git reset --hard origin/main
    python scripts/fetch_results_no_cfbd.py
    if ! commit_scoreboard_if_changed; then
      echo "The upstream scoreboard already contains this refresh."
      exit 0
    fi
  fi

  if git push origin HEAD:main; then
    exit 0
  fi

  if [[ "$attempt" -lt 5 ]]; then
    sleep 2
  fi
done

echo "Unable to publish the scoreboard after five regenerated attempts." >&2
exit 1
