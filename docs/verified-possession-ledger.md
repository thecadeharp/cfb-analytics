# Verified-game possession ledger: research v1

Run **Build Verified Possession Ledger** manually on `main` after committing:

- `scripts/build_verified_possession_ledger.py`
- `scripts/test_verified_possession_ledger.py`
- `.github/workflows/build-verified-possession-ledger.yml`
- this document

The existing scoring reconstruction, NCAA verification and possession-point audit scripts remain dependencies. No model is fitted. The site, Model A and published postgame estimates do not consume this output.

## What is retained

The builder rechecks the 2025 eligible game IDs against NCAA finals using the existing verification function. It then retains every observed regulation drive ID, including IDs without enough evidence to represent a possession. Kickoffs and timeouts do not establish ownership. Rushes, passes, sacks, field goals, punts, turnovers and other possession-ending events do establish ownership evidence. Penalty-only IDs are unresolved. Drives are keyed by game plus drive ID, never by drive ID alone.

Artifacts available on the Actions run for 30 days:

- `possessions.csv`: one row per observed regulation drive key, including scoreless and unresolved cases, field position, team, first/last play, source result and diagnostic EPA.
- `scoring_events.csv`: every scoring event retained once with assigned, unassigned, overtime or nonoffensive status. This preserves the prior reconstruction's channel labels; some return scores remain labeled defense rather than special teams and require a separate classification review.
- `review_queue.csv`: complete game, drive and play identifiers for review issues.
- `verified_game_ids.csv`: the actual independently admitted games, rather than only their count.
- `report.json`: counts, sample issues, source/script hashes and CSV hashes.

Only the aggregate `data/research/verified_possession_ledger_2025.json` is committed. A green run means the build, tests and accounting checks passed. It does not mean all drives are resolved or the data is ready for training.

## Labels and chronology

`assigned_offensive_points` is a diagnostic sum of attributable tagged events; it is not necessarily an approved label. `offensive_points` remains blank unless both drive-level and game-level checks pass. A zero therefore means a checked observed possession without an assigned offensive score, never missing points filled with zero. A game with any unassigned offensive scoring event cannot receive accepted zero labels.

The builder checks duplicate play IDs, conflicting versions, duplicate scoring fingerprints, missing core IDs/sequences/clocks, sequence/clock reversals, repeated drive blocks, mixed possession teams and drive IDs crossing halftime. It also flags a first observed down other than one, absent terminal evidence, and missing start field position. Sorting uses period, descending clock and source sequence as a tie breaker. Sorting does not repair or waive chronology conflicts. Duplicate rows are retained for inspection and block labels rather than silently deleted.

Terminal evidence is conservative. A kneeldown at a nonzero clock with no final marker can remain unresolved even if the game likely ended there. Drive result and reported offensive play count are retained for review, not treated as independent ground truth.

Raw score stamps are diagnostic only; they never supply possession points or verified garbage-time flags. EPA and success summaries remain source-provided diagnostics and are not approved model inputs while their score-state dependence is unresolved.

## Local full-data validation, September 24, 2026

Source parquet SHA-256: `740566c0d034fa767008a40797dd491acb91dee47934cefb4225494f71c42853`.

- 654 NCAA-verified games; 5,781 scoring events preserved.
- 15,209 observed regulation drive keys: 15,165 with possession evidence and 44 without it.
- 10,408 possessions pass the current label checks, including 6,511 scoreless possessions.
- 4,757 observed possessions remain unresolved; 184 games have game-level review flags.
- 5,473 offensive scoring events provisionally assigned, totaling 32,124 points.
- 8 offensive scoring events / 39 points remain unassigned; 263 nonoffensive events and 37 overtime scoring events remain separate.

The earlier scoring-only audit assigned 5,475 events and left 6 events / 33 points unassigned. The two additional exclusions are field goals in games `401760414` (drive `40176041429`) and `401754610` (drive `4017546104`). Both drive IDs include an earlier fumble row belonging to the other team. The broader ownership check detects this conflicting evidence and withholds the field goals rather than assuming the drive boundary is correct. The original six unresolved events remain unresolved.

## Next gate

All rows explicitly have `training_eligible=false`. Passing these checks does not prove that entirely absent possessions do not exist, that source EPA is usable, or that a sample is representative.

The 2019–2024 repair stage subsequently audited every possession in the 291 score-context rejections. It admitted 111 fully corroborated games, quarantined 180 games and froze a research-only expected-points candidate after that candidate improved MAE and RMSE in every 2022–2024 rolling fold. The candidate remains separate from Model A and is not production-ready.

The next gate is the manual **Evaluate Sealed Expected Points 2025** workflow. It checksum-locks the candidate, historical repair evidence, independent 2025 score audit and every annual source file before opening the holdout. It reconstructs the score before each admitted possession, permits only independently corroborated stale-stamp repairs, quarantines unresolved games and compares the frozen candidate with its matched field-position baseline. The workflow may run only once: after its report is committed, repeat evaluation is refused. A pass does not authorize Model A integration; a failure must be reported without tuning this candidate against 2025.
