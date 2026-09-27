"""Regression tests for conservative stale possession-start score repair."""
import unittest

import pandas as pd

from audit_all_possession_start_scores import audit_game
from test_expected_points_score_margin import play, target


class StartScoreRepairTests(unittest.TestCase):
    def test_repair_requires_next_core_play_corroboration(self):
        raw = pd.DataFrame([
            play(1, "d1", "h", 15, points=True),
            play(2, "d2", "a", 14, start_home=0),
            play(3, "d2", "a", 13, start_home=7),
        ])
        findings = audit_game(raw, pd.DataFrame([
            target("d1", "h", 7), target("d2", "a", 0)
        ]))
        self.assertEqual(findings[1]["status"], "repairable_stale_stamp")
        self.assertEqual(findings[1]["corroborating_play"], "3")

    def test_unconfirmed_stale_score_stays_quarantined(self):
        raw = pd.DataFrame([
            play(1, "d1", "h", 15, points=True),
            play(2, "d2", "a", 14, start_home=0),
            play(3, "d2", "a", 13, start_home=0),
        ])
        findings = audit_game(raw, pd.DataFrame([
            target("d1", "h", 7), target("d2", "a", 0)
        ]))
        self.assertEqual(findings[1]["status"], "unresolved_score_contradiction")

    def test_first_play_score_never_enters_its_start_context(self):
        raw = pd.DataFrame([play(1, "d1", "h", 15, points=True)])
        finding = audit_game(raw, pd.DataFrame([target("d1", "h", 7)]))[0]
        self.assertEqual(finding["status"], "raw_confirmed")
        self.assertEqual(finding["reconstructed_home"], 0)


if __name__ == "__main__":
    unittest.main()
