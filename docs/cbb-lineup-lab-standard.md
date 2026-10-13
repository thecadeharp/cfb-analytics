# THI CBB Lineup Lab Build Standard

## Purpose

The Lineup Lab may publish projected five-player combinations before observed lineup data exists, but it must never present a projection as an observed stint. It remains isolated from Model A until it clears THI's model-promotion standard.

## Current status

Publication is withheld. `data/cbb/roster_audit.json` currently fails three gates:

- recognized position normalization;
- plausible roster sizes;
- official roster spot checks.

THI also lacks a verified, possession-level substitution feed capable of reconstructing observed five-player stints.

## Required input contract

Every player row must include a stable provider ID, normalized team ID, verified current team, normalized position family, active/inactive status, class, height, and source timestamp. Projection features must be frozen before the game or season being evaluated.

The player feature layer must include, where applicable:

- expected minute share and rotation role;
- usage and shot volume;
- 2-point, 3-point, and free-throw efficiency;
- offensive and defensive rebounding;
- assists and playmaking;
- turnover rate;
- steals, blocks, and foul rate;
- opponent-adjusted prior production;
- transfer, freshman, injury, and role-change uncertainty.

Missing values must remain missing or use an explicitly documented prior. Zero is never a silent missing-value substitute.

## Projected lineup engine

1. Estimate a probability distribution for each player's minutes, rather than assigning a single fixed rotation.
2. Generate legal five-player combinations subject to team membership, active status, plausible ball-handling, wing, and interior roles, and a 200-minute team constraint.
3. Estimate lineup offense and defense from player priors, role balance, spacing, rim pressure, rebounding, creation, turnover risk, and defensive event rates.
4. Apply hierarchical Bayesian shrinkage toward player-role, team, and national priors. Uncertainty must increase for freshmen, transfers, role changes, and sparse histories.
5. Produce posterior means and credible intervals. The public grade uses the posterior mean; uncertainty is displayed separately.
6. Calculate percentiles against the complete eligible projected-lineup population from the same frozen build.

## Grade contract

Each projected lineup may display:

- overall efficiency margin;
- offensive efficiency;
- defensive efficiency;
- shooting;
- usage and creation;
- rebounding;
- playmaking;
- turnover security;
- steals and disruption;
- blocks and rim protection;
- foul pressure and foul risk.

Grades must be derived from versioned percentile cutoffs. They cannot be hand-assigned or changed after results are known.

## Observed lineup gate

Observed possessions, efficiency, or on-court labels stay hidden until THI has a possession feed with complete substitution events and validates stint reconstruction against official box-score minutes. A game fails the observed-lineup gate when any of these checks fail:

- exactly five active players per team for every scored possession;
- reconstructed player minutes reconcile to the official box score within the published tolerance;
- team points and possessions reconcile to the official game totals;
- substitution ordering is complete and deterministic;
- overtime and technical-foul possessions are handled explicitly.

Observed lineup estimates use possession-dependent shrinkage:

`posterior = w_observed * observed_stint + w_player * projected_lineup + w_team * team_prior`

The observed weight increases with possessions and data quality. Tiny samples remain dominated by the projected and team priors.

## Publication labels

- **Projected lineup**: model-generated combination with no claim that the five players shared the floor.
- **Likely rotation combination**: projected lineup with meaningful estimated minutes.
- **Observed lineup**: reconstructed from a verified possession and substitution feed.
- **Withheld**: roster, identity, minutes, or stint-reconstruction gate failed.

## Promotion gates

Before public release, the build must pass:

1. all current-roster integrity checks for every Division I team;
2. official spot checks across high-major, mid-major, and low-major programs;
3. frozen historical inputs and reproducible output checksums;
4. out-of-sample lineup or team-efficiency validation;
5. calibration by conference, roster-turnover tier, and projected minute tier;
6. stability and outlier-dependency review;
7. a prospective shadow period with no in-period retuning.

Projected Lineup Lab can launch after gates 1–6. Observed lineup possessions require the separate observed-lineup gate. Model A integration requires the full THI validation and promotion process.
