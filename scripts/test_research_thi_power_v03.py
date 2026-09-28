import unittest

import numpy as np
import pandas as pd

import research_thi_power_v03 as m


class DecayTests(unittest.TestCase):
    def test_public_team_contract_retains_existing_columns(self):
        self.assertIn(
            'performance_only_weekly_change',
            m.PUBLIC_TEAM_FIELDS
        )
        self.assertIn(
            'missingness_contribution',
            m.PUBLIC_TEAM_FIELDS
        )
        self.assertIn(
            'centering_offset',
            m.PUBLIC_TEAM_FIELDS
        )

    def test_decay_is_one_before_week_one_and_declines(self):
        values = m.decay_factor(np.array([1, 2, 5]), .25)
        np.testing.assert_allclose(values, [1, .8, .5])

    def test_only_roster_fields_decay(self):
        row = {'week': 5}

        for field in m.v02.FEATURES:
            row['home_' + field] = 2.
            row['away_' + field] = 1.

        result = m.decay_examples(pd.DataFrame([row]), .25)

        for field in m.v02.ROSTER_PRIOR:
            self.assertEqual(
                result.loc[0, 'home_' + field],
                1.
            )

        self.assertEqual(
            result.loc[0, 'home_result_elo'],
            2.
        )
        self.assertEqual(
            result.loc[0, 'home_net_epa'],
            2.
        )


if __name__ == '__main__':
    unittest.main()
