# CBB model version review

Decision recorded: 2026-10-09

## Why this record exists

A user requested restoration of the earlier CBB backtest after observing that it outperformed the current public study. This document preserves that request, identifies the exact versions, and prevents an exposed historical result from being used as an unacknowledged model-selection criterion.

## Reconstructed comparison

Both versions are strict chronological walk-forward research models trained on 2019–2024. The reported comparison combines the already-exposed 2025 validation season and 2026 out-of-time test season for selections with an absolute model-market spread disagreement greater than five points.

| Model | Historical role | Record | Hit rate | Hypothetical flat -110 return | Exact p vs. 52.381% |
| --- | --- | ---: | ---: | ---: | ---: |
| v0.6 | Previous published research model | 1158–1020–2 | 53.168% | +1.501% | 0.237657 |
| v0.7 | Current published research model | 1231–1144–3 | 51.832% | -1.047% | 0.711177 |

The v0.6 95% Wilson interval is 51.069%–55.256%. Its positive hypothetical return is descriptive and did not establish corrected statistical significance or realized ROI. Historical two-sided prices are unavailable.

## What changed

Version 0.7 introduced chronological opponent-adjusted Four Factor states, carried those states into preseason priors with regression, and expanded the qualifying sample. It is a methodological change rather than a recalculation of the same predictions.

## Decision

Do not replace the current public v0.7 result with the v0.6 result while continuing to run v0.7 projections. That would attribute one model's historical performance to another model.

Do not select v0.6 for production solely because it performed better on 2025–2026. Those outcomes are now exposed to the selection process, so choosing between versions on that basis would create model-selection leakage.

Preserve v0.6 as the official rollback challenger. Generate v0.6 and v0.7 projections in parallel against identical frozen 2027 markets without changing the published model. Reconsider production only after a predeclared prospective sample compares:

- exact selection and closing prices from the same named book;
- ATS return and no-vig probability per play;
- margin MAE and calibration;
- corrected significance across every tested threshold;
- rolling stability and outlier dependency; and
- performance by month, market range, venue type, and team-quality cohort.

A rollback may occur earlier only if an implementation or data-integrity defect is independently found in v0.7. Better exposed historical returns alone are not sufficient.
