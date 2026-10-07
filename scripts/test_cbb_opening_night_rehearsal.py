import unittest

from scripts.run_cbb_opening_night_rehearsal import run_rehearsal


class CbbOpeningNightRehearsalTests(unittest.TestCase):
    def test_full_lifecycle_passes(self):
        payload = run_rehearsal()
        self.assertEqual(payload["meta"]["status"], "passed")
        self.assertTrue(all(payload["checks"].values()))
        self.assertEqual(payload["evidence"]["market_snapshots"], 2)
        self.assertEqual(payload["evidence"]["model_grade"], "win")


if __name__ == "__main__":
    unittest.main()
