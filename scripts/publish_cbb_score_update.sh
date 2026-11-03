#!/usr/bin/env bash
set -euo pipefail

commit_message="${1:-Refresh CBB live scores and finals}"

stage_scoreboard() {
  git add data/cbb/game_board.json data/cbb/projection_board.json data/cbb/model_tracking.json data/cbb/postgame.json data/cbb/cache_manifest.json
}

commit_scoreboard_if_changed() {
  stage_scoreboard
  if git diff --cached --quiet; then
    return 1
  fi
  git commit -m "$commit_message"
}

if ! commit_scoreboard_if_changed; then
  echo "No CBB score change to publish."
  exit 0
fi

for attempt in 1 2 3 4 5; do
  git fetch origin main
  if ! git rebase origin/main; then
    echo "CBB data changed upstream; regenerating the pulse from current main."
    git rebase --abort || true
    git reset --hard origin/main
    rm -f /tmp/thi-cbb-score-changed /tmp/thi-cbb-recent-final /tmp/thi-cbb-newly-final
    python scripts/refresh_cbb_scores.py \
      --changed-flag /tmp/thi-cbb-score-changed \
      --recent-final-flag /tmp/thi-cbb-recent-final \
      --newly-final-flag /tmp/thi-cbb-newly-final
    if [[ -s /tmp/thi-cbb-recent-final ]]; then
      python scripts/build_cbb_postgame.py
    fi
    if [[ -s /tmp/thi-cbb-newly-final ]]; then
      python scripts/build_cbb_model_tracking.py
    fi
    python scripts/build_static_cache_manifest.py
    if ! commit_scoreboard_if_changed; then
      echo "The upstream CBB board already contains this refresh."
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

echo "Unable to publish the CBB score pulse after five attempts." >&2
exit 1
