#!/usr/bin/env python3
"""Independent THI power candidate. Never reads/writes Model A or sealed 2025.

Historical replay uses prior weeks only. All outputs are research artifacts;
retrospective roster sources are not point-in-time certified for deployment.
"""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import urlopen

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

YEARS = (2019, 2020, 2021, 2022, 2023, 2024, 2026)
BASE = 'https://raw.githubusercontent.com/sportsdataverse/cfbfastR-cfb-data/main/cfb'
METRICS = {'epa': 'plays', 'success': 'plays', 'ypp': 'plays',
           'explosive': 'plays', 'sack': 'dropbacks', 'stuff': 'rushes',
           'opportunity': 'rushes', 'havoc': 'plays'}
ROSTER_PRIOR = ['talent_composite', 'blue_chip_ratio', 'off_returning', 'def_returning']
ELO_PRIOR = 'result_elo'
PRIOR = [ELO_PRIOR] + ROSTER_PRIOR
FEATURES = PRIOR + ['net_' + m for m in METRICS]
ALIASES = {'San José State': 'San Jose State', 'Appalachian State': 'App State',
           'Connecticut': 'UConn', 'Louisiana Monroe': 'UL Monroe',
           'Southern Mississippi': 'Southern Miss', 'UT San Antonio': 'UTSA'}


def flag(s):
    return s.astype(str).str.lower().isin(['true', '1', '1.0'])


def ids(s):
    return pd.to_numeric(s, errors='raise').astype('int64').astype(str)


def result_elo_snapshots(team_ids, schedule, k_factor=20.0):
    """Result Elo updated after each completed week, with no same-week leak.

    Each season starts at 1500 because 2025 is sealed. This is therefore a
    current-season result feature, not a prior-season or external CFBD rating.
    """
    ratings = pd.Series(1500.0, index=team_ids, dtype=float)
    snapshots = {0: ratings.copy()}
    for week in sorted(schedule.week.unique()):
        changes = pd.Series(0.0, index=ratings.index)
        for game in schedule.loc[schedule.week.eq(week)].itertuples():
            expected_home = 1.0 / (1.0 + 10.0 ** (-(ratings[game.home_id] - ratings[game.away_id]) / 400.0))
            actual_home = 1.0 if game.margin > 0 else 0.0 if game.margin < 0 else 0.5
            delta = k_factor * (actual_home - expected_home)
            changes[game.home_id] += delta
            changes[game.away_id] -= delta
        ratings = ratings + changes
        snapshots[int(week)] = ratings.copy()
    return snapshots


def fetch_inputs(root, download=False):
    records = []
    for year in YEARS:
        assets = {f'{kind}_{year}.parquet': f'{BASE}/{kind}/parquet/{kind}_{year}.parquet'
                  for kind in ['cfb_teams', 'cfb_team_talent', 'cfb_returning_production']}
        assets[f'cfb_schedule_{year}.parquet'] = f'{BASE}/schedules/parquet/cfb_schedule_{year}.parquet'
        assets[f'play_by_play_{year}.parquet'] = (
            f'{BASE}/pbp/parquet/play_by_play_{year}.parquet' if year == 2026 else
            f'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_pbp/play_by_play_{year}.parquet')
        for name, url in assets.items():
            path = root / name
            if not path.exists() or (download and year == 2026):
                if not download:
                    raise FileNotFoundError(path)
                with urlopen(url, timeout=180) as response:
                    payload = response.read()
                temporary = path.with_suffix('.partial')
                temporary.write_bytes(payload)
                temporary.replace(path)
            records.append({'name': name, 'url': url,
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return records


def read_season(root, year):
    if year not in YEARS:
        raise ValueError('Season not allowed; 2025 is sealed')
    teams = pd.read_parquet(root / f'cfb_teams_{year}.parquet')
    teams = teams.loc[flag(teams.is_fbs) & teams.school.notna(), ['team_id', 'school']].copy()
    teams.team_id = ids(teams.team_id)
    if teams.team_id.duplicated().any() or teams.school.duplicated().any():
        raise ValueError('Ambiguous team reference')
    names = {r.team_id: ALIASES.get(r.school, r.school) for r in teams.itertuples()}
    roster = teams.set_index('team_id').drop(columns='school')
    for kind, fields in [('cfb_team_talent', ROSTER_PRIOR[:2]),
                         ('cfb_returning_production', ROSTER_PRIOR[2:])]:
        frame = pd.read_parquet(root / f'{kind}_{year}.parquet')
        frame = frame.loc[frame.season.eq(year)].copy()
        frame.team_id = ids(frame.team_id)
        if frame.team_id.duplicated().any():
            raise ValueError('Duplicate roster record')
        roster = roster.join(frame.set_index('team_id')[fields].apply(pd.to_numeric, errors='coerce'))
    for field in ROSTER_PRIOR[1:]:
        roster.loc[~roster[field].between(0, 1), field] = np.nan
    roster.loc[roster.talent_composite.le(0), 'talent_composite'] = np.nan

    schedule = pd.read_parquet(root / f'cfb_schedule_{year}.parquet')
    for col in ['game_id', 'home_id', 'away_id']:
        schedule[col] = ids(schedule[col])
    schedule = schedule.loc[schedule.season.eq(year) & schedule.season_type.eq(2)
                            & schedule.home_id.isin(names) & schedule.away_id.isin(names)
                            & schedule.status.eq('STATUS_FINAL')].copy()
    if schedule.game_id.duplicated().any() or schedule.week.isna().any():
        raise ValueError('Invalid game identity/week')
    schedule['margin'] = schedule.home_score - schedule.away_score
    if not np.isfinite(schedule.margin).all():
        raise ValueError('Missing final scores')
    if schedule.neutral_site.isna().any():
        raise ValueError('Unknown neutral venue')
    schedule['venue'] = (~flag(schedule.neutral_site)).astype(float)

    path = root / f'play_by_play_{year}.parquet'
    fields = ['game_id', 'season', 'week', 'pos_team_id', 'def_pos_team_id', 'EPA',
              'rush', 'pass', 'sack', 'statYardage', 'start.down', 'start.distance',
              'penalty_no_play', 'kneel_down', 'type.text', 'havoc', 'game_play_number',
              'homeScore', 'awayScore', 'homeTeamId', 'awayTeamId', 'seasonType']
    schema = pq.read_schema(path).names
    if set(fields) - set(schema):
        raise ValueError('Play schema missing required fields')
    raw = pd.read_parquet(path, columns=fields)
    raw = raw.loc[raw.season.eq(year) & raw.seasonType.eq(2)].copy()
    raw.game_id = ids(raw.game_id)
    raw = raw.loc[raw.game_id.isin(schedule.game_id)].copy()
    if raw.game_play_number.isna().any() or raw.duplicated(['game_id', 'game_play_number']).any():
        raise ValueError('Ambiguous play sequence')
    # Require the provider's terminal scoreboard to agree with the schedule.
    last = raw.sort_values('game_play_number').groupby('game_id').tail(1).set_index('game_id')
    checked = schedule.set_index('game_id').join(last[['homeScore', 'awayScore']])
    good = checked.home_score.eq(checked.homeScore) & checked.away_score.eq(checked.awayScore)
    rejected = int((~good).sum())
    schedule = schedule.loc[schedule.game_id.isin(checked.index[good])].copy()
    raw = raw.loc[raw.game_id.isin(schedule.game_id)].copy()
    raw['offense'] = ids(raw.pos_team_id)
    raw['defense'] = ids(raw.def_pos_team_id)
    reference = schedule.set_index('game_id')
    if (ids(raw.homeTeamId).ne(raw.game_id.map(reference.home_id)).any()
            or ids(raw.awayTeamId).ne(raw.game_id.map(reference.away_id)).any()):
        raise ValueError('Play teams disagree with schedule')
    raw = raw.loc[raw.offense.isin(names) & raw.defense.isin(names)
                  & ~flag(raw.penalty_no_play) & ~flag(raw.kneel_down)].copy()
    passing = flag(raw['pass']) | flag(raw.sack)
    rushing = flag(raw.rush) & ~passing
    raw = raw.loc[(passing | rushing) & ~raw['type.text'].str.contains('spike', case=False, na=False)].copy()
    passing, rushing = passing.loc[raw.index], rushing.loc[raw.index]
    yards = pd.to_numeric(raw.statYardage, errors='coerce')
    distance = pd.to_numeric(raw['start.distance'], errors='coerce')
    down = pd.to_numeric(raw['start.down'], errors='coerce')
    epa = pd.to_numeric(raw.EPA, errors='coerce')
    valid = np.isfinite(epa) & np.isfinite(yards) & down.between(1, 4) & distance.gt(0)
    raw = raw.loc[valid].copy()
    yards, distance, down, epa = [x.loc[raw.index] for x in (yards, distance, down, epa)]
    passing, rushing = passing.loc[raw.index], rushing.loc[raw.index]
    raw['plays'] = 1
    raw['dropbacks'] = passing.astype(int)
    raw['rushes'] = rushing.astype(int)
    raw['epa'] = epa
    raw['success'] = (yards >= distance * np.select([down.eq(1), down.eq(2)], [.5, .7], default=1)).astype(int)
    raw['ypp'] = yards
    raw['explosive'] = ((passing & yards.ge(15)) | (rushing & yards.ge(10))).astype(int)
    raw['sack'] = (flag(raw.sack) & passing).astype(int)
    raw['stuff'] = (rushing & yards.le(0)).astype(int)
    raw['opportunity'] = (rushing & yards.ge(4)).astype(int)
    raw['havoc'] = flag(raw.havoc).astype(int)
    group = raw.groupby(['game_id', 'offense', 'defense'])
    games = group[list(METRICS) + ['plays', 'dropbacks', 'rushes']].sum().reset_index()
    games = games.merge(schedule[['game_id', 'week']], on='game_id', validate='many_to_one')
    # A game is usable only if both offenses have an observed sample.
    two_sides = games.groupby('game_id').offense.nunique()
    usable = two_sides.index[two_sides.eq(2)]
    schedule = schedule.loc[schedule.game_id.isin(usable)].copy()
    games = games.loc[games.game_id.isin(usable)].copy()
    audit = {'season': year, 'teams': len(names), 'games': len(schedule),
             'score_or_missing_pbp_rejections': rejected,
             'rejected_game_ids': checked.index[~good].tolist(),
             'missing_roster_by_field': roster.isna().sum().astype(int).to_dict()}
    return names, roster, schedule, games, audit


def state(roster, games, before_week, elo=None, shrinkage=200.0):
    """Only weeks strictly before forecast cutoff; retain exact denominators."""
    prior = games.loc[games.week.lt(before_week)]
    result = roster.copy()
    for metric, denominator in METRICS.items():
        off_num = prior.groupby('offense')[metric].sum().reindex(result.index, fill_value=0)
        def_num = prior.groupby('defense')[metric].sum().reindex(result.index, fill_value=0)
        off_n = prior.groupby('offense')[denominator].sum().reindex(result.index, fill_value=0)
        def_n = prior.groupby('defense')[denominator].sum().reindex(result.index, fill_value=0)
        total = prior[denominator].sum()
        baseline = float(prior[metric].sum() / total) if total else 0.0
        # Solve additive offensive/defensive opponent effects with exposure weights.
        off = pd.Series(0., index=result.index)
        defense = off.copy()
        for _ in range(20):
            against = prior.defense.map(defense).fillna(0) * prior[denominator]
            faced = prior.offense.map(off).fillna(0) * prior[denominator]
            off_adj = against.groupby(prior.offense).sum().reindex(result.index, fill_value=0)
            def_adj = faced.groupby(prior.defense).sum().reindex(result.index, fill_value=0)
            target_off = (off_num - baseline * off_n - off_adj) / (off_n + shrinkage)
            target_def = (def_num - baseline * def_n - def_adj) / (def_n + shrinkage)
            off = .5 * off + .5 * target_off
            defense = .5 * defense + .5 * target_def
        result['net_' + metric] = off - defense
    result['games'] = prior.groupby('offense').game_id.nunique().reindex(result.index, fill_value=0)
    if elo is None:
        result[ELO_PRIOR] = np.nan
    else:
        result[ELO_PRIOR] = pd.Series(result.index, index=result.index).map(elo)
    return result


def examples(roster, schedule, games, elo_by_cutoff):
    frames = []
    for week in sorted(schedule.week.unique()):
        s = state(roster, games, week, elo=elo_by_cutoff[week - 1])
        sample = schedule.loc[schedule.week.eq(week)]
        left = s.loc[sample.home_id, FEATURES].reset_index(drop=True)
        right = s.loc[sample.away_id, FEATURES].reset_index(drop=True)
        frame = sample[['game_id', 'week', 'margin', 'venue']].reset_index(drop=True)
        for name in FEATURES:
            frame['home_' + name] = left[name]
            frame['away_' + name] = right[name]
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def fit(train, features, penalty=100.):
    # Fit imputation and scaling on training seasons ONLY. Missing indicators are
    # separate features; absent returning production is never treated as zero.
    all_teams = np.vstack([train[['home_' + f for f in features]].to_numpy(float),
                           train[['away_' + f for f in features]].to_numpy(float)])
    if (~np.isfinite(all_teams)).all(axis=0).any():
        raise ValueError('Entire training feature missing')
    means = np.nanmean(all_teams, axis=0)
    if not np.isfinite(means).all():
        raise ValueError('Entire training feature missing')
    scales = np.nanstd(all_teams, axis=0)
    scales[scales < 1e-8] = 1
    model = {'features': features, 'means': means.tolist(), 'scales': scales.tolist(), 'penalty': penalty}
    x = matrix(train, model)
    regularizer = np.eye(x.shape[1]) * penalty
    regularizer[-1, -1] = 0  # Venue effect fitted separately from team strength.
    model['coefficients'] = np.linalg.solve(x.T @ x + regularizer,
                                             x.T @ train.margin.to_numpy(float)).tolist()
    return model


def encode(values, model):
    values = np.asarray(values, float)
    missing = ~np.isfinite(values)
    z = (np.where(missing, model['means'], values) - model['means']) / model['scales']
    return np.column_stack([z, missing.astype(float)])


def matrix(frame, model):
    h = encode(frame[['home_' + f for f in model['features']]], model)
    a = encode(frame[['away_' + f for f in model['features']]], model)
    return np.column_stack([h - a, frame.venue.to_numpy(float)])


def metrics(y, pred):
    e = pred - y
    return {'games': len(y), 'mae': float(np.mean(np.abs(e))), 'rmse': float(np.sqrt(np.mean(e * e)))}


def evaluate(table):
    folds = []
    for year in (2022, 2023, 2024):
        train, test = table.loc[table.season.lt(year)], table.loc[table.season.eq(year)]
        row = {'test_year': year, 'train_games': len(train)}
        predictions = {}
        for name, features in [('roster_only', PRIOR), ('epa_only', ['net_epa']),
                               ('rates_only', FEATURES[4:]), ('combined', FEATURES)]:
            model = fit(train, features)
            pred = matrix(test, model) @ model['coefficients']
            predictions[name] = pred
            row[name] = metrics(test.margin.to_numpy(float), pred)
            early = test.week.le(5).to_numpy()
            row[name]['early_season'] = metrics(test.margin.to_numpy(float)[early], pred[early])
        y = test.margin.to_numpy(float)
        rng = np.random.default_rng(817 + year)
        draws = rng.integers(len(test), size=(2000, len(test)))
        for baseline in ['roster_only', 'epa_only', 'rates_only']:
            delta = np.abs(predictions[baseline] - y) - np.abs(predictions['combined'] - y)
            row['mae_improvement_vs_' + baseline] = {
                'points': float(delta.mean()),
                'game_bootstrap_95_interval': np.quantile(delta[draws].mean(axis=1), [.025, .975]).tolist(),
                'note': 'Exploratory game resampling; does not account for repeated-team/season dependencies or source revisions.'}
        folds.append(row)
    return folds


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input-dir', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--download', action='store_true')
    p.add_argument('--through-week', type=int, default=0,
                   help='0 selects latest covered source week; report remains research-only')
    args = p.parse_args()
    if not 0 <= args.through_week <= 16:
        raise ValueError('Explicit completed-week cutoff required')
    args.input_dir.mkdir(parents=True, exist_ok=True)
    provenance = fetch_inputs(args.input_dir, args.download)
    seasons, audits = {}, []
    for year in YEARS:
        names, roster, schedule, games, audit = read_season(args.input_dir, year)
        audits.append(audit)
        seasons[year] = (names, roster, schedule, games)
        print(f'{year}: {audit["games"]} usable FBS games', flush=True)
    current = seasons[2026]
    _, _, current_schedule, _ = current
    if args.through_week == 0:
        args.through_week = int(current_schedule.week.max())
    expected = current_schedule.loc[current_schedule.week.eq(args.through_week)]
    if expected.empty:
        raise ValueError('Requested current week unavailable; refusing stale relabel')
    elo_by_season = {}
    for year, (_, _, schedule, _) in seasons.items():
        team_ids = seasons[year][1].index
        elo_by_season[year] = result_elo_snapshots(team_ids, schedule)
    histories = []
    for year in YEARS:
        if year == 2026:
            continue
        _, roster, schedule, games = seasons[year]
        sample = examples(roster, schedule, games, elo_by_season[year])
        sample['season'] = year
        histories.append(sample)
    history = pd.concat(histories, ignore_index=True)
    folds = evaluate(history)
    model = fit(history, FEATURES)
    names, roster, schedule, games = current
    latest = state(roster, games, args.through_week + 1, elo=elo_by_season[2026][args.through_week])
    x = encode(latest[FEATURES], model)
    contributions = x * np.array(model['coefficients'][:-1])
    scores = contributions.sum(axis=1)
    center = scores.mean()
    scores -= center
    previous_state = state(roster, games, args.through_week,
                           elo=elo_by_season[2026][max(args.through_week - 1, 0)])
    previous_scores = encode(previous_state[FEATURES], model) @ model['coefficients'][:-1]
    previous_scores -= previous_scores.mean()
    rows = []
    for i, (team_id, data) in enumerate(latest.iterrows()):
        missing = [f for f in PRIOR if pd.isna(data[f])]
        rows.append({'team_id': team_id, 'team': names[team_id], 'rating': float(scores[i]),
                     'previous_week_same_model_rating': float(previous_scores[i]),
                     'performance_only_weekly_change': float(scores[i] - previous_scores[i]),
                     'qualifying_games': int(data.games), 'missing_prior_fields': missing,
                     'prior_contribution': float(contributions[i, :len(PRIOR)].sum()),
                     'performance_contribution': float(contributions[i, len(PRIOR):len(FEATURES)].sum()),
                     'missingness_contribution': float(contributions[i, len(FEATURES):].sum()),
                     'centering_offset': float(center)})
    rows.sort(key=lambda r: (-r['rating'], r['team']))
    for rank, row in enumerate(rows, 1):
        row['rank'] = rank
        row['rating'] = round(row['rating'], 3)
    report = {'meta': {'version': 'thi_power_research_v0.2', 'status': 'RESEARCH_ONLY',
                       'generated_at': datetime.now(timezone.utc).isoformat(), 'season': 2026,
                       'through_week': args.through_week, 'model_a_touched': False,
                       'weekly_change_definition': 'Recomputed the prior cutoff with the same model, roster file, and result-Elo snapshot; not a frozen historical rating',
                       'production_ready': False, 'sealed_2025_used': False,
                       'scale': 'Fitted scoring-margin points relative to candidate FBS mean; unvalidated current-season forecasts',
                       'prior': 'Current-season result Elo through the completed week, plus talent/blue-chip and returning-production proxies. Result Elo starts each season at 1500 because 2025 remains sealed.',
                       'limitations': ['Historical roster files lack verified pregame publication timestamps; retrospective results are exploratory.',
                                       'No previous-season performance prior is present. Result Elo begins at 1500 each season and uses only completed same-season FBS results.',
                                       'No verified TARP, coaching/injury/news, verified drive finishing, or special-teams features.',
                                       'All eligible scrimmage situations, including garbage time; no fragile start-score filtering.',
                                       'Overtime is included in training final-margin targets.',
                                       'Fixed 200-exposure shrinkage and ridge 100 are design choices, not tuned optimal values.',
                                       'Public file coverage is not proof of complete weekly coverage; no automatic production promotion.'],
                       'definitions': {'success': '50% of yards needed on first down, 70% on second, 100% on third/fourth',
                                       'explosive': '15+ yard pass or 10+ yard rush per eligible play',
                                       'sack': 'Sacks per pass/dropback including sacks, excluding spikes',
                                       'opportunity': 'Rushes gaining at least four yards per eligible rush',
                                       'stuff': 'Rushes gaining zero or fewer yards per eligible rush',
                                       'havoc': 'Source havoc flag per eligible scrimmage play',
                                       'opponent_adjustment': 'Regularized additive offense/defense effects, weighted by each rate denominator; prior weeks only'}},
              'validation': folds, 'input_audit': audits, 'provenance': provenance,
              'model': model, 'teams': rows}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / 'thi_power_candidate.json'
    target.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'validation': folds, 'top_15': rows[:15]}, indent=2))


if __name__ == '__main__':
    main()
