import unittest
import numpy as np
import pandas as pd
from research_expected_points_score_margin import COLUMNS, game_margins


def play(pid, drive, team, minute, points=False, start_home=0, start_away=0):
    row = dict.fromkeys(COLUMNS, None)
    row.update({'id': str(pid), 'game_id': 'g', 'drive.id': drive,
                'pos_team_id': team, 'def_pos_team_id': 'a' if team == 'h' else 'h',
                'homeTeamId': 'h', 'awayTeamId': 'a', 'period': 1,
                'clock.minutes': minute, 'clock.seconds': 0, 'sequenceNumber': pid,
                'game_play_number': pid, 'penalty_no_play': False,
                'start.yardsToEndzone': 70, 'start.homeScore': start_home,
                'start.awayScore': start_away, 'homeScore': start_home + (7 if points else 0),
                'awayScore': start_away, 'scoringType.name': 'touchdown' if points else None,
                'type.text': 'Rushing Touchdown' if points else 'Rush',
                'offense_score_play': points, 'defense_score_play': False,
                'pointAfterAttempt.value': 1 if points else np.nan})
    return row


def target(drive, team, points):
    return {'drive_id': drive, 'possession_team_id': team, 'start_period': 1,
            'start_yards_to_endzone': 70, 'target_offensive_points': points}


class MarginTests(unittest.TestCase):
    def test_first_play_score_excluded_and_away_sign(self):
        raw = pd.DataFrame([play(1, 'd1', 'h', 15, points=True), play(2, 'd2', 'a', 14, start_home=7)])
        rows = pd.DataFrame([target('d1', 'h', 7), target('d2', 'a', 0)])
        margin, reason = game_margins(raw, rows)
        self.assertIsNone(reason)
        self.assertEqual(margin, {'d1': 0, 'd2': -7})

    def test_uncertain_score_quarantines_whole_game(self):
        raw = pd.DataFrame([play(1, 'd1', 'h', 15, points=True), play(2, 'd2', 'a', 14, start_home=0)])
        margin, reason = game_margins(raw, pd.DataFrame([target('d1', 'h', 7), target('d2', 'a', 0)]))
        self.assertIsNone(margin)
        self.assertEqual(reason, 'start_score_disagreement')

    def test_future_score_cannot_change_earlier_start(self):
        raw = pd.DataFrame([play(1, 'd1', 'h', 15), play(2, 'd2', 'h', 14, points=True)])
        margin, reason = game_margins(raw, pd.DataFrame([target('d1', 'h', 0)]))
        self.assertIsNone(reason)
        self.assertEqual(margin, {'d1': 0})

    def test_frozen_target_must_match(self):
        raw = pd.DataFrame([play(1, 'd1', 'h', 15, points=True)])
        self.assertEqual(game_margins(raw, pd.DataFrame([target('d1', 'h', 0)]))[1], 'frozen_target_changed')

    def test_duplicate_sequence_rejected(self):
        raw = pd.DataFrame([play(1, 'd1', 'h', 15), play(2, 'd2', 'a', 14)])
        raw['sequenceNumber'] = 1
        self.assertEqual(game_margins(raw, pd.DataFrame([target('d1', 'h', 0)]))[1], 'ambiguous_chronology')


if __name__ == '__main__':
    unittest.main()
