#!/usr/bin/env python3
"""Compare locked roster-decay schedules for THI Power v0.3 research."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import research_thi_power as v02

RATES = (0.0, 0.15, 0.25, 0.35)


def decay_factor(cutoff_week, rate):
    return 1.0 / (1.0 + rate * np.maximum(np.asarray(cutoff_week, float) - 1.0, 0.0))


def decay_examples(frame, rate):
    result = frame.copy()
    factor = decay_factor(result.week.to_numpy(float), rate)
    for field in v02.ROSTER_PRIOR:
        result['home_' + field] = result['home_' + field] * factor
        result['away_' + field] = result['away_' + field] * factor
    return result


def decay_state(frame, cutoff_week, rate):
    result = frame.copy()
    result[v02.ROSTER_PRIOR] = result[v02.ROSTER_PRIOR] * float(decay_factor(cutoff_week, rate))
    return result


def mean_combined_mae(folds):
    return float(np.mean([fold['mae'] for fold in folds]))


def decayed_matrix(frame, model, rate):
    matrix = v02.matrix(frame, model)
    factor = decay_factor(frame.week.to_numpy(float), rate)
    feature_positions = {name: i for i, name in enumerate(model['features'])}
    for field in v02.ROSTER_PRIOR:
        matrix[:, feature_positions[field]] *= factor
    return matrix


def evaluate_rate(history, rate):
    folds = []
    for year in (2022, 2023, 2024):
        train = history.loc[history.season.lt(year)]
        test = history.loc[history.season.eq(year)]
        model = v02.fit(train, v02.FEATURES)
        prediction = decayed_matrix(test, model, rate) @ np.asarray(model['coefficients'])
        result = v02.metrics(test.margin.to_numpy(float), prediction)
        folds.append({'test_year': year, **result})
    return folds


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input-dir', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--through-week', type=int, required=True)
    args = p.parse_args()
    seasons, audits = {}, []
    for year in v02.YEARS:
        season = v02.read_season(args.input_dir, year)
        seasons[year] = season[:4]; audits.append(season[4])
    elo = {year: v02.result_elo_snapshots(data[1].index, data[2]) for year, data in seasons.items()}
    histories = []
    for year in v02.YEARS:
        if year == 2026: continue
        _, roster, schedule, games = seasons[year]
        sample = v02.examples(roster, schedule, games, elo[year]); sample['season'] = year
        histories.append(sample)
    raw_history = pd.concat(histories, ignore_index=True)
    comparisons = []
    for rate in RATES:
        folds = evaluate_rate(raw_history, rate)
        comparisons.append({'rate': rate, 'mean_combined_mae': mean_combined_mae(folds), 'folds': folds})
    winner = min(comparisons, key=lambda row: (row['mean_combined_mae'], row['rate']))
    rate = winner['rate']; model = v02.fit(raw_history, v02.FEATURES)
    names, roster, schedule, games = seasons[2026]
    latest = v02.state(roster, games, args.through_week + 1, elo=elo[2026][args.through_week])
    x = v02.encode(latest[v02.FEATURES], model)
    factor = float(decay_factor(args.through_week + 1, rate))
    for field in v02.ROSTER_PRIOR:
        x[:, v02.FEATURES.index(field)] *= factor
    contributions = x * np.asarray(model['coefficients'][:-1]); scores = contributions.sum(axis=1)
    center = scores.mean(); scores -= center
    rows = []
    for i, (team_id, data) in enumerate(latest.iterrows()):
        rows.append({'team_id': team_id, 'team': names[team_id], 'rating': round(float(scores[i]), 3),
                     'qualifying_games': int(data.games),
                     'result_elo_contribution': float(contributions[i, 0]),
                     'roster_contribution': float(contributions[i, 1:len(v02.PRIOR)].sum()),
                     'performance_contribution': float(contributions[i, len(v02.PRIOR):len(v02.FEATURES)].sum())})
    rows.sort(key=lambda row: (-row['rating'], row['team']))
    for rank, row in enumerate(rows, 1): row['rank'] = rank
    report = {'meta': {'version': 'thi_power_research_v0.3_comparison', 'status': 'RESEARCH_ONLY',
                       'generated_at': datetime.now(timezone.utc).isoformat(), 'through_week': args.through_week,
                       'model_a_touched': False, 'sealed_2025_used': False,
                       'selected_decay_rate': rate,
                       'decay_formula': 'roster feature multiplier = 1 / (1 + rate * (forecast_week - 1))',
                       'production_ready': False},
              'comparisons': comparisons, 'input_audit': audits, 'model': model, 'teams': rows}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/'thi_power_candidate_v03.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'selected_rate': rate, 'comparisons': [{k:v for k,v in x.items() if k!='folds'} for x in comparisons],
                      'top_25': rows[:25]}, indent=2))


if __name__ == '__main__': main()
