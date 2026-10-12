# THI Model Validation & Promotion Standard

This standard governs every THI sport, rating, projection, betting signal, and experimental model. A model earns its label from reproducible evidence. Familiar-looking rankings, one profitable slice, or agreement with a public poll cannot promote a model.

## Evidence labels

| Label | Required meaning | Permitted product use |
| --- | --- | --- |
| **Research** | Exploratory work. Inputs, specification, or evaluation may still change. Previously inspected samples may be reported but cannot validate the model. | Research pages and clearly labeled methodology artifacts only. |
| **Provisional** | Code, parameters, eligible-game rules, inputs, and predictions are frozen before the prospective window. Results are accumulating. | Public informational display with an explicit provisional label. No validated or profitable claim. |
| **Validated** | The frozen candidate cleared its predefined data-integrity, predictive, statistical, calibration, stability, and subgroup gates on untouched prospective evidence. | May be described as validated for the exact target and population tested. |
| **Production** | A validated model also cleared operational monitoring, rollback, documentation, and version-governance review. | May power the named production surface. This does not automatically validate betting profitability. |

Betting signals have an additional requirement: actual recorded two-sided prices, per-play no-vig baselines, exact or Poisson-binomial testing, multiplicity correction, outlier-dependency checks, rolling stability, and positive price-aware returns. Hit rate alone never establishes profitability.

## Required frozen model card

Before prospective evaluation begins, THI records:

- candidate identifier and Git commit;
- target outcome and eligible population;
- immutable input files with timestamps and SHA-256 checksums;
- code, feature definitions, parameters, missing-data rules, and output checksum;
- baseline model and comparison metric;
- exclusion, neutral-site, postponement, and cancellation rules;
- checkpoint dates or sample sizes;
- primary and secondary metrics;
- statistical interval and promotion thresholds;
- subgroup and stability gates;
- known limitations and rollback owner.

Changing any frozen element creates a new candidate version and a new prospective clock. The original candidate remains preserved.

## Evaluation rules

1. **Correct target.** A preseason power rating is evaluated against future game-level scoring margins and probabilities, not AP rank or eventual top-25 membership. End-of-season rank overlap may be descriptive only.
2. **Paired comparison.** Candidate and baseline errors are compared on the same eligible games. Report the paired mean difference and a 95% game-level bootstrap interval.
3. **Calibration.** Report performance by projected spread range, probability band, season phase, neutral/campus site, and team-strength tier.
4. **Stability.** Report rolling windows and month-by-month results. A short-lived early edge cannot be generalized to the full season.
5. **Subgroup bias.** Audit conference and ranking-tier residuals where sample size is sufficient. Conference identity may not be added merely to make rankings resemble consensus.
6. **Outlier robustness.** Remove the largest favorable errors and repeat the comparison. A few extreme results cannot carry promotion.
7. **Market context.** Compare with a market baseline only when the timestamp and exact price are known. Market information used for evaluation remains excluded from model features unless the model card explicitly defines otherwise.
8. **No threshold changes.** Promotion gates are frozen before outcomes. Retrospective threshold changes require a new version.

## 2027 CBB preseason candidate protocol

The roster-aware CBB candidate remains **Research** until a reproducible preseason freeze exists. Once frozen, it becomes **Provisional** and follows these checkpoints:

- **Preseason freeze:** preserve inputs, active rosters, code, parameters, baseline ratings, candidate ratings, schedules, checksums, and all initial game predictions.
- **100 eligible games:** descriptive data-quality and performance review only. No parameter changes.
- **Midseason:** descriptive paired-error, calibration, early-season, conference, tier, and neutral-site review. No parameter changes.
- **End of season:** apply the frozen promotion gates.

The primary target is game-level margin prediction on Division I versus Division I games. The primary comparison is paired absolute-error improvement over the frozen production baseline. Early-season games are a predefined secondary cohort because roster information should have its greatest value before current-season observations dominate.

The 2026 retrospective result has already been inspected and cannot be reused as untouched evidence. Historical top-25 overlap is not a promotion criterion. A midseason retune becomes a separately named candidate and does not inherit the original candidate's prospective evidence.

## Governance record

Every decision records **Promote**, **Hold**, or **Reject**, the exact evidence supporting it, the failed gates, and the commit that implements the decision. A hold is the default whenever input timing, licensing, reproducibility, or statistical evidence is uncertain.
