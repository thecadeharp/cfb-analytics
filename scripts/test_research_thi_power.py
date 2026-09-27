import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
import pandas as pd
import research_thi_power as m


def roster():
    return pd.DataFrame({'talent_composite': [100., 200.], 'blue_chip_ratio': [.1, .2],
                         'off_returning': [.4, .7], 'def_returning': [.6, np.nan]}, index=['A', 'B'])


def games():
    rows = []
    for week in [1, 2]:
        for team, opponent in [('A', 'B'), ('B', 'A')]:
            rows.append({'game_id': str(week), 'week': week, 'offense': team, 'defense': opponent,
                         'plays': 100, 'dropbacks': 50, 'rushes': 50, 'epa': 20 if team == 'A' else 0,
                         'success': 40, 'ypp': 500, 'explosive': 10, 'sack': 3,
                         'stuff': 8, 'opportunity': 25, 'havoc': 12})
    return pd.DataFrame(rows)


def training():
    rng = np.random.default_rng(30)
    data = {'margin': rng.normal(0, 12, 80), 'venue': np.tile([0., 1.], 40)}
    for f in m.FEATURES:
        data['home_' + f] = rng.normal(size=80)
        data['away_' + f] = rng.normal(size=80)
    return pd.DataFrame(data)


class PowerTests(unittest.TestCase):
    def test_sealed_season_rejected_before_io(self):
        with patch.object(pd, 'read_parquet') as read:
            with self.assertRaises(ValueError):
                m.read_season(Path('/missing'), 2025)
            read.assert_not_called()

    def test_current_week_cannot_change_features(self):
        g = games()
        before = m.state(roster(), g, 2)
        g.loc[g.week.eq(2), list(m.METRICS)] = 999999
        pd.testing.assert_frame_equal(before, m.state(roster(), g, 2))

    def test_future_week_cannot_change_features(self):
        g = games()
        before = m.state(roster(), g, 2)
        future = g.copy(); future.week = 20; future.epa = 999999
        pd.testing.assert_frame_equal(before, m.state(roster(), pd.concat([g, future]), 2))

    def test_no_games_means_prior_only_not_fake_observations(self):
        s = m.state(roster(), games(), 1)
        self.assertTrue(s[m.FEATURES[len(m.PRIOR):]].eq(0).all().all())
        self.assertTrue(s.games.eq(0).all())
        self.assertTrue(pd.isna(s.loc['B', 'def_returning']))

    def test_elo_snapshot_is_joined_by_team_without_zero_fill(self):
        s = m.state(roster(), games(), 1, elo=pd.Series({'A': 1700.}))
        self.assertEqual(s.loc['A', m.ELO_PRIOR], 1700.)
        self.assertTrue(pd.isna(s.loc['B', m.ELO_PRIOR]))

    def test_result_elo_uses_only_completed_prior_weeks(self):
        schedule = pd.DataFrame([
            {'week': 1, 'home_id': 'A', 'away_id': 'B', 'margin': 7},
            {'week': 2, 'home_id': 'A', 'away_id': 'B', 'margin': -7},
        ])
        snapshots = m.result_elo_snapshots(pd.Index(['A', 'B']), schedule)
        self.assertEqual(snapshots[0].loc['A'], 1500.)
        self.assertGreater(snapshots[1].loc['A'], 1500.)
        self.assertLess(snapshots[2].loc['A'], snapshots[1].loc['A'])

    def test_swapping_teams_reverses_neutral_margin(self):
        t = training(); model = m.fit(t, m.FEATURES)
        a = t.iloc[:4].copy(); a.venue = 0
        b = a.copy()
        for f in m.FEATURES:
            b['home_' + f], b['away_' + f] = a['away_' + f], a['home_' + f]
        np.testing.assert_allclose(m.matrix(a, model) @ model['coefficients'],
                                   -(m.matrix(b, model) @ model['coefficients']))

    def test_missing_input_not_zero(self):
        model = {'means': [10.], 'scales': [2.]}
        x = m.encode([[np.nan], [0]], model)
        np.testing.assert_equal(x, [[0, 1], [-5, 0]])

    def test_future_evaluation_does_not_refit_scaling(self):
        model = m.fit(training(), m.FEATURES)
        before = dict(model)
        t = training(); t['home_talent_composite'] = 1e12
        m.matrix(t, model)
        self.assertEqual(before, model)

    def test_all_missing_training_feature_fails(self):
        t = training(); t['home_off_returning'] = np.nan; t['away_off_returning'] = np.nan
        with self.assertRaises(ValueError):
            m.fit(t, m.FEATURES)

    def test_strength_components_match_prediction(self):
        t = training(); model = m.fit(t, m.FEATURES)
        h = m.encode(t[['home_' + f for f in m.FEATURES]], model) @ model['coefficients'][:-1]
        a = m.encode(t[['away_' + f for f in m.FEATURES]], model) @ model['coefficients'][:-1]
        np.testing.assert_allclose(h - a + t.venue * model['coefficients'][-1],
                                   m.matrix(t, model) @ model['coefficients'])

    def test_defense_and_offense_are_symmetric(self):
        s = m.state(roster(), games(), 2)
        self.assertGreater(s.loc['A', 'net_epa'], s.loc['B', 'net_epa'])


if __name__ == '__main__':
    unittest.main()
