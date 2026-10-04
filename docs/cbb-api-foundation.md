# THI College Basketball API foundation

## Scope

This layer establishes a separate College Basketball data sandbox. It does not read, write, or alter College Football projections, Model A, ratings, or tracking.

CBBD season `2027` represents the 2026–27 season. Completed season `2026` supplies the first preseason benchmark and returning-production context.

## Credentials

Store the CollegeBasketballData key only as the GitHub Actions secret `CBBD_API_KEY`. The key must never appear in repository files, browser JavaScript, generated JSON, workflow logs, or site HTML.

The user's CBBD and CFBD access shares one subscription and one quota pool. The foundation therefore uses compact scheduled batches and commits only transformed THI outputs.

## Access verification

`Verify CBB API Foundation` checks eight API surfaces:

1. Team directory
2. Current-season games
3. Prior-season adjusted ratings
4. Tier 2+ team leaderboard
5. Current rosters
6. Prior-season player statistics
7. Betting-line providers
8. Live scoreboard

The access report stores endpoint status, schema coverage, and row counts only. It never stores response rows.

## Derived build

`Build CBB Data Foundation` makes eight batched requests and writes:

- `data/cbb/team_profiles.json`: THI-transformed team efficiency, Four Factor edges, shot profile, prior adjusted efficiency, and returning-production percentages.
- `data/cbb/game_board.json`: a bounded game window with broadcasts and median market context.
- `data/cbb/foundation_status.json`: coverage and provenance metadata.

Current-season adjusted values become display-ready after three games. Before that threshold, the profile remains marked `preseason_prior`. This foundation does not yet publish a THI predictive rating, spread, total, projected score, or win probability.

Raw responses remain transient in workflow memory. Player rows and complete rosters are used to derive team continuity percentages and are not republished as bulk datasets.

## Model path

The next research sequence is:

1. Historical game and team-efficiency warehouse
2. Possession and Four Factor validation
3. Preseason-prior training and decay
4. Opponent adjustment and home-court estimation
5. Spread, total, score, and win-probability calibration
6. Frozen snapshots, market comparison, and postgame accountability

No CBB projection should be labeled production-ready until walk-forward historical validation clears explicit calibration and error gates.
