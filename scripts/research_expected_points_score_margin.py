#!/usr/bin/env python3
"""One locked score-margin challenger on 2019–2024; no production or 2025 access.

Reconstruct scores before first observed core play, cross-check raw start scores,
and quarantine a whole game if any required possession is uncertain. The frozen
target table and existing baseline reports are never modified.
"""
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlretrieve

import numpy as np
import pandas as pd

from build_verified_possession_ledger import CORE_TYPES, identifier
from build_historical_training_data import boolish
from reconstruct_scoring_events import SOURCE_COLUMNS, reconstructed_events
from validate_clean_game_expected_points_rolling import design, score, FOLDS

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / 'data/research/expected_points_clean_games_2019_2024.csv.gz'
REPORT = ROOT / 'data/research/expected_points_score_margin_challenger.json'
EXPECTED_SHA = '983f967620d63173e2c105defc9e537d6c32789bf23c56f9d608cb289598c141'
YEARS = tuple(range(2019, 2025))
KEYS = ['season', 'game_id', 'drive_id']
ORDER = ['period', 'clock.minutes', 'clock.seconds', 'sequenceNumber', 'game_play_number']
COLUMNS = list(dict.fromkeys(SOURCE_COLUMNS + ['id', 'sequenceNumber', 'penalty_no_play', 'start.yardsToEndzone']))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def game_margins(raw, frozen):
    """Return margins keyed by drive, or a reason for whole-game quarantine."""
    if raw.empty:
        return None, 'missing_source_game'
    raw = raw.copy()
    for name in ['game_id', 'drive.id', 'id', 'pos_team_id', 'def_pos_team_id', 'homeTeamId', 'awayTeamId']:
        raw[name] = raw[name].map(identifier)
    for name in ORDER + ['start.homeScore', 'start.awayScore', 'start.yardsToEndzone']:
        raw[name] = pd.to_numeric(raw[name], errors='coerce')
    if raw.period.isna().any():
        return None, 'missing_period'
    raw = raw.loc[raw.period.between(1, 4)].copy()
    core = raw['type.text'].isin(CORE_TYPES) & ~boolish(raw.penalty_no_play)
    events = reconstructed_events(raw)
    relevant = raw.loc[core | raw.index.isin(events.index)]
    if not np.isfinite(relevant[ORDER].to_numpy(float)).all():
        return None, 'missing_chronology'
    if relevant.id.isna().any() or relevant.id.duplicated().any() or relevant.sequenceNumber.duplicated().any():
        return None, 'ambiguous_chronology'
    elapsed = (relevant.period - 1) * 900 + 900 - relevant['clock.minutes'] * 60 - relevant['clock.seconds']
    if elapsed.loc[relevant.sort_values('sequenceNumber').index].diff().lt(0).any():
        return None, 'chronology_reversal'
    if (events.points.isna().any() or not events.points.between(1, 8).all()
            or not events.scoring_side.isin(['home', 'away']).all()):
        return None, 'uncertain_scoring_event'
    ordered = raw.sort_values(ORDER, ascending=[True, False, False, True, True], kind='stable')
    first = ordered.loc[core.reindex(ordered.index)].drop_duplicates('drive.id')
    if first['drive.id'].isna().any():
        return None, 'missing_drive_identity'
    first = first.set_index('drive.id', drop=False)
    event_map = {idx: e for idx, e in events.iterrows()}
    starts = {}
    home_score = away_score = 0.0
    # Record the score BEFORE this play; a first-play TD cannot enter its input.
    for idx, row in ordered.iterrows():
        if row['drive.id'] in first.index and row.id == first.loc[row['drive.id']].id:
            starts[row['drive.id']] = (home_score, away_score)
        if idx in event_map:
            event = event_map[idx]
            if event.scoring_side == 'home':
                home_score += event.points
            else:
                away_score += event.points
    margins = {}
    for row in frozen.itertuples():
        drive = str(row.drive_id)
        if drive not in first.index or drive not in starts:
            return None, 'missing_possession_start'
        p = first.loc[drive]
        if p.pos_team_id != str(row.possession_team_id):
            return None, 'possession_team_changed'
        if p.period != row.start_period or not np.isclose(p['start.yardsToEndzone'], row.start_yards_to_endzone):
            return None, 'frozen_context_changed'
        hs, aws = starts[drive]
        if p['start.homeScore'] != hs or p['start.awayScore'] != aws:
            return None, 'start_score_disagreement'
        is_home = p.pos_team_id == p.homeTeamId
        if not is_home and p.pos_team_id != p.awayTeamId:
            return None, 'unknown_possession_side'
        side = 'home' if is_home else 'away'
        credited = events.loc[events['drive.id'].eq(drive) & events.scoring_side.eq(side)
                              & events.channel.isin(['offense', 'field_goal']), 'points'].sum()
        if credited != row.target_offensive_points:
            return None, 'frozen_target_changed'
        margins[drive] = hs - aws if is_home else aws - hs
    return margins, None


def fit_predict(train, test, margin=False):
    x, xt = design(train), design(test)
    if margin:
        x = np.column_stack([x, train.start_score_margin.to_numpy(float) / 28.0])
        xt = np.column_stack([xt, test.start_score_margin.to_numpy(float) / 28.0])
    penalty = np.eye(x.shape[1]); penalty[0, 0] = 0
    coefficients = np.linalg.solve(x.T @ x + 10.0 * penalty, x.T @ train.target_offensive_points.to_numpy(float))
    return np.clip(xt @ coefficients, 0, 8)


def evaluate(table):
    folds = []
    for end, test_year in FOLDS:
        train = table.loc[table.season.le(end)]
        test = table.loc[table.season.eq(test_year)]
        if train.empty or test.empty:
            raise ValueError('Missing eligible train/test fold; no challenger result')
        actual = test.target_offensive_points.to_numpy(float)
        base, challenger = fit_predict(train, test), fit_predict(train, test, margin=True)
        b, c = score(actual, base), score(actual, challenger)
        # Resample games, not dependent possessions; fixed seed and 2,000 draws.
        errors = pd.DataFrame({'game': test.game_id.to_numpy(), 'delta': np.abs(base-actual)-np.abs(challenger-actual)})
        groups = errors.groupby('game').delta.agg(['sum', 'count']).to_numpy()
        rng = np.random.default_rng(20260927 + test_year)
        draws = rng.integers(len(groups), size=(2000, len(groups)))
        improvements = groups[draws, 0].sum(axis=1) / groups[draws, 1].sum(axis=1)
        folds.append({'train_through': end, 'test_year': test_year, 'train_rows': len(train),
                      'test_rows': len(test), 'test_games': int(test.game_id.nunique()),
                      'matched_baseline': b, 'score_margin_challenger': c,
                      'mae_improvement': b['mae']-c['mae'], 'rmse_improvement': b['rmse']-c['rmse'],
                      'mae_improvement_game_bootstrap_95_interval': np.quantile(improvements, [.025,.975]).tolist(),
                      'improves_both': c['mae'] < b['mae'] and c['rmse'] < b['rmse']})
    return folds


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-dir', type=Path, required=True, help='Cache with thi-pbp-2019.parquet through thi-pbp-2024.parquet')
    parser.add_argument('--download', action='store_true', help='Download missing 2019–2024 source files only')
    args = parser.parse_args()
    if digest(TABLE) != EXPECTED_SHA:
        raise ValueError('Frozen target-table checksum changed; review required')
    frozen = pd.read_csv(TABLE, dtype={'game_id': str, 'drive_id': str, 'possession_team_id': str})
    if set(frozen.season) != set(YEARS) or frozen.duplicated(KEYS).any():
        raise ValueError('Locked seasons or unique-key violation')
    expected_partition = np.where(frozen.season <= 2022, 'development', 'validation')
    if not (frozen.partition == expected_partition).all():
        raise ValueError('Locked partitions changed')
    frames, coverage, hashes, exclusions = [], [], {}, []
    args.source_dir.mkdir(parents=True, exist_ok=True)
    for year in YEARS:
        path = args.source_dir / f'thi-pbp-{year}.parquet'
        url = f'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_pbp/play_by_play_{year}.parquet'
        if not path.exists() and args.download:
            temp = path.with_suffix('.download')
            urlretrieve(url, temp)
            temp.replace(path)
        hashes[str(year)] = {'url': url, 'sha256': digest(path)}
        season = frozen.loc[frozen.season.eq(year)]
        raw = pd.read_parquet(path, columns=COLUMNS)
        raw['game_id'] = raw.game_id.map(identifier)
        groups = {game: frame for game, frame in raw.loc[raw.game_id.isin(season.game_id)].groupby('game_id')}
        reasons, accepted = Counter(), []
        for game, rows in season.groupby('game_id'):
            margins, reason = game_margins(groups.get(game, raw.iloc[:0]), rows)
            if reason:
                reasons[reason] += 1
                exclusions.append({'season': year, 'game_id': game, 'rows': len(rows), 'reason': reason})
                continue
            enriched = rows.copy()
            enriched['start_score_margin'] = enriched.drive_id.map(margins)
            accepted.append(enriched)
        frame = pd.concat(accepted, ignore_index=True) if accepted else season.iloc[:0]
        frames.append(frame)
        coverage.append({'season': year, 'original_games': int(season.game_id.nunique()),
                         'eligible_games': int(frame.game_id.nunique()), 'original_rows': len(season),
                         'eligible_rows': len(frame), 'excluded_game_reasons': dict(reasons)})
        print(json.dumps(coverage[-1]), flush=True)
    enriched = pd.concat(frames, ignore_index=True)
    folds = evaluate(enriched)
    report = {'meta': {'generated_at': datetime.now(timezone.utc).isoformat(),
              'status': 'research_only_score_margin_challenger', 'training_ready': False,
              'production_use': 'none; no Model A, projections, site, or sealed 2025 access',
              'target_table_sha256': EXPECTED_SHA,
              'specification': 'Existing field-position quadratic + period ridge baseline; add ONE signed start-score-margin / 28 feature; penalty=10; clip predictions 0..8; original rolling folds; no tuning.',
              'margin_definition': 'Possession-team score minus opponent score before first core play; prior reconstructed scoring events must agree with raw start scores.',
              'comparison': 'Both models fit and evaluated on identical eligible rows. Whole-game quarantine; no drive repair or imputation.',
              'limits': 'Previously inspected validation years are reused for exploratory research. Selection bias remains; bootstrap intervals do not resolve source or selection bias.'},
              'source_hashes': hashes, 'coverage': coverage, 'excluded_games': exclusions,
              'folds': folds, 'all_folds_improve_both': all(f['improves_both'] for f in folds)}
    REPORT.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'folds': folds, 'all_folds_improve_both': report['all_folds_improve_both']}), flush=True)


if __name__ == '__main__':
    main()
