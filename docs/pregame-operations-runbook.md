# THI pregame operations runbook

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

## Market movement and RLM

The free monitor records Pinnacle first and BetOnline only as a fallback. Line movement remains labeled as line movement. True RLM activates only when `THI_SPLITS_FEED_URL` and its optional token supply a licensed public-ticket feed synchronized to the odds feed within five minutes. DraftKings, FanDuel, Caesars, and BetMGM cannot serve as the sharp reference.

## Account library

Authenticated users can save games from CFB/CBB matchup pages, save teams from both dossier views, log plays through `THIAccount.logPlay`, and export their saved library. The library is private local browser storage scoped to the authenticated account ID; the Supabase session remains persistent.
