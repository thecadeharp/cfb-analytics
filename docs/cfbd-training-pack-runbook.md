# CFBD weekly training-pack runbook

The CFBD Model Training Pack is a licensed, point-in-time pregame snapshot.
Raw weekly CSVs stay local under `data/private/cfbd_training_packs/` and are
never committed to the public repository.

## Weekly intake

1. Save the untouched download as
   `data/private/cfbd_training_packs/training_data_YYYY_weekNN.csv`.
2. Run the identity, timing, and integrity audit:

   ```bash
   python scripts/audit_cfbd_training_pack.py \
     data/private/cfbd_training_packs/training_data_YYYY_weekNN.csv
   ```

3. Require every critical check in
   `data/research/cfbd_training_pack_audit.json` to pass. Kickoff changes are
   advisory when the stable game id and both participants still match.
4. Keep `spread` evaluation-only. It may benchmark the frozen THI projection
   or measure opening-to-current/closing movement, but it must never enter a
   predictive feature matrix.
5. After games settle, join final scores and closing prices by game id in a
   separate derived evaluation table. Never overwrite the pregame snapshot.

## Model governance

- A single weekly drop is a prediction cohort, not enough training history to
  replace Model A.
- Accumulate the weekly snapshots unchanged and evaluate a challenger with
  expanding-window or sealed-season validation.
- Compare the challenger against the no-vig market baseline and Model A using
  MAE, calibration, ATS ROI at recorded prices, CLV, exact/Poisson-binomial
  tests, multiple-comparison correction, outlier sensitivity, and rolling
  stability.
- Promotion requires prospective evidence. Never refit a published week's
  frozen projection after its games begin.
