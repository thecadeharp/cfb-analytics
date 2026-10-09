# CBB model version review

Decision recorded: 2026-10-09; production selection updated 2026-10-09

## Why this record exists

A user requested restoration of the earlier CBB backtest after observing that it outperformed the current public study. This document preserves that request, identifies the exact versions, and prevents an exposed historical result from being used as an unacknowledged model-selection criterion.

## Reconstructed comparison

Both versions are strict chronological walk-forward research models trained on 2019–2024. The reported comparison combines the already-exposed 2025 validation season and 2026 out-of-time test season for selections with an absolute model-market spread disagreement greater than five points.

| Model | Historical role | Record | Hit rate | Hypothetical flat -110 return | Exact p vs. 52.381% |
| --- | --- | ---: | ---: | ---: | ---: |
| v0.6 | Selected production research model | 1158–1020–2 | 53.168% | +1.501% | 0.237657 |
| v0.7 | Archived challenger | 1231–1144–3 | 51.832% | -1.047% | 0.711177 |

The v0.6 95% Wilson interval is 51.069%–55.256%. Its positive hypothetical return is descriptive and did not establish corrected statistical significance or realized ROI. Historical two-sided prices are unavailable.

## What changed

Version 0.7 introduced chronological opponent-adjusted Four Factor states, carried those states into preseason priors with regression, and expanded the qualifying sample. It is a methodological change rather than a recalculation of the same predictions.

## Production decision

THI now uses and displays v0.6 as the selected CBB research model. The projection engine, generated model card, current priors, bracketology input, and public historical audit must carry the same v0.6 version identifier.

This selection was made after observing the 2025–2026 comparison and therefore carries model-selection risk. The public result remains labeled historical research and not validated; it cannot be presented as independent proof of future profitability.

Preserve v0.7 as the challenger. Generate v0.6 and v0.7 projections in parallel against identical frozen 2027 markets. Reconsider production only after a predeclared prospective sample compares:

- exact selection and closing prices from the same named book;
- ATS return and no-vig probability per play;
- margin MAE and calibration;
- corrected significance across every tested threshold;
- rolling stability and outlier dependency; and
- performance by month, market range, venue type, and team-quality cohort.

The selected model can change earlier if an implementation or data-integrity defect is independently confirmed. Historical return comparisons remain descriptive rather than an independent validation sample.
