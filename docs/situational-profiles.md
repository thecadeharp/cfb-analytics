# 2026 Situational Profiles

Situational Profiles are a research-only, postgame view of possession value.
They do not feed Model A, THI Power Ratings, projections, wagers or live scores.

Run **Build 2026 Situational Profiles** manually after a week is complete. Enter
the last completed week as an integer from 1 through 15. The workflow downloads
the current SportsDataverse 2026 play-by-play snapshot, checks completed game
finals against the NCAA scoreboard and commits only
`data/research/situational_profiles_2026.json`.

## Admission rules

A game is admitted only when:

- it is a completed 2026 regular-season game at or before the selected week;
- one unique NCAA matchup has the same home and away final score;
- tagged scoring events reproduce that final score;
- the possession ledger finds no game-level or drive-level ownership problem;
- every admitted possession has an observed start field position and period;
- every possession start score exactly matches reconstructed prior scoring.

Any failure quarantines the whole game from the profile sample. No score, team,
drive or possession is imputed. The output records source hashes, coverage and
exclusion counts on every run.

## Metrics

The frozen expected-points candidate uses only possession-start field position,
period and possession-team score margin. For each admitted possession, the
profile compares actual offensive points with those expected start points.

- **Points over expected per possession:** offense actual points minus expected
  start points.
- **Points prevented over expected per possession:** expected start points minus
  the opponent's actual points.
- **Net possession value:** offensive points over expected plus defensive points
  prevented over expected.
- **Scoring, touchdown and empty-possession rates:** shares of admitted drives.
- **Average starting field position:** `100 - yards to end zone`.
- **Short-field production:** possessions starting no more than 40 yards from
  the end zone and their actual points per possession.
- **Score-state and half splits:** the same value comparison while leading, tied
  or trailing and in each half.

Reliability is based on the smaller of a team's admitted offensive and defensive
samples: `limited` below 25 possessions, `developing` from 25–49 and
`established` at 50 or more. Values are deliberately not ranked. Early-season
and quarantined-game coverage can make comparisons unstable.

All admitted participants are retained, including FCS opponents, so an FBS
team's FBS-vs-FCS possessions remain visible. The eventual site component can
filter which team dossiers are displayed without discarding opponent context.
