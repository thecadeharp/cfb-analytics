# THI pregame operations runbook

## Permanent decision records

- [Commercial launch readiness](commercial-launch-readiness.md) records the source-rights, paywall architecture, customer-policy, affiliate, and legal-review gates that must clear before THI accepts payment.
- [CBB model version review](cbb-model-version-review.md) records the v0.6 production selection and the prospective evidence required to compare it fairly with v0.7.

## Weekly CFBD challenger audit

Keep each licensed Model Training Pack in `data/private/cfbd_training_packs/`. The directory is gitignored. Audit the new pack, then build its aggregate scorecard:

```bash
python scripts/audit_cfbd_training_pack.py data/private/cfbd_training_packs/training_data_2026_week06.csv
python scripts/build_cfbd_weekly_challenger_scorecard.py data/private/cfbd_training_packs/training_data_2026_week06.csv
```

The scorecard publishes no raw feature rows. It compares the frozen THI margin, the licensed opening line, and THI's same-snapshot market against the final margin as results arrive. It does not change Model A.

## Verified CBB venue coordinates

Fill a local CSV with this header:

```text
venue_name,city,state,latitude,longitude,source_url,verified_at_utc
```

Import it with `python scripts/import_cbb_verified_venues.py /path/to/venues.csv`. The importer rejects missing provenance, bad timestamps, duplicate venue keys, and invalid coordinates. CBBD's venue endpoint identifies venues but does not provide latitude/longitude, so city-centroid inference is prohibited.

## Verified CBB availability

Fill a local CSV with this header:

```text
game_id,team,player,status,note,verified_source_url,verified_at_utc
```

Import it with `python scripts/import_cbb_verified_availability.py /path/to/availability.csv`. Allowed states are `available`, `probable`, `questionable`, `doubtful`, `out`, `suspended`, and `unknown`. Availability stays display-only until a separately validated adjustment exists.

## Internal health and prediction archive

Run:

```bash
python scripts/build_prediction_archive.py
python scripts/build_operations_readiness.py
```

The scheduled settlement and CBB refresh workflows run both builders automatically. `data/reports/prediction_archive.json` keeps one earliest frozen CFB forecast per game plus CBB frozen decisions. `data/reports/operations_readiness.json` is an internal artifact and is not linked in public navigation.

## Live-score reliability

The public CFB board has two independent refresh paths. `live-score-pulse.yml`
publishes the static scoreboard on an offset five-minute schedule, while the
browser refreshes active scores once per minute. `data-freshness-audit.yml`
runs twice per hour and dispatches a recovery pulse when the static live files
breach their game-window SLO. Once a pulse observes an active game, that run
also retains a five-minute fallback polling loop until every observed game is
final. A changed completed result automatically dispatches the full settlement
workflow. An external scheduler can call the workflow's `live-score-pulse`
repository-dispatch event without changing the workflow.

GitHub scheduled workflows are best-effort and can be delayed. Before a paid
launch, move the authoritative live-score cache to a server scheduler such as a
Supabase scheduled Edge Function or Cloudflare Worker cron. Keep the GitHub
snapshot as the public fallback and release record.

## Market movement and RLM

The free monitor records Pinnacle first and BetOnline only as a fallback. Line movement remains labeled as line movement. True RLM activates only when `THI_SPLITS_FEED_URL` and its optional token supply a licensed public-ticket feed synchronized to the odds feed within five minutes. DraftKings, FanDuel, Caesars, and BetMGM cannot serve as the sharp reference.

## Account library

Authenticated users can save games from CFB/CBB matchup pages, save teams from both dossier views, log plays through `THIAccount.logPlay`, and export their saved library. The library is private local browser storage scoped to the authenticated account ID; the Supabase session remains persistent.
