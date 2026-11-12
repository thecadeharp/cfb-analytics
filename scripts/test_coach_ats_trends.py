import unittest

from scripts.build_coach_ats_trends import normalized, summarize


class CoachATSTrendsTests(unittest.TestCase):
    def test_team_name_normalization(self):
        self.assertEqual(normalized("Ohio State"), "ohiostate")
        self.assertEqual(normalized("Miami (OH)"), "miamioh")

    def test_ledger_summary_preserves_pushes_and_cover_rate(self):
        row = summarize(["W", "W", "L", "P"])
        self.assertEqual(row["record"], "2-1-1")
        self.assertEqual(row["games"], 4)
        self.assertEqual(row["cover_pct_ex_pushes"], 66.7)


if __name__ == "__main__":
    unittest.main()
