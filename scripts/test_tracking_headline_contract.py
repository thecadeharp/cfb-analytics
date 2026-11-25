import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TrackingHeadlineContractTests(unittest.TestCase):
    def test_cfb_headline_uses_overall_clv_not_featured_tiers(self):
        source = (ROOT / "postgame-analytics.js").read_text()
        self.assertNotIn('perfStat("Notable Tier ATS"', source)
        self.assertNotIn('perfStat("Play Tier YTD"', source)
        self.assertIn('perfStat("ATS CLV YTD"', source)
        self.assertIn('perfStat("ATS Beat Close YTD"', source)
        self.assertNotIn("Season-to-Date · Every Signal and Testing Key", source)
        self.assertIn("Prospective Moneyline Ledger · Separate from ATS", source)

    def test_cbb_headline_uses_overall_clv_not_featured_tiers(self):
        source = (ROOT / "cbb-site.js").read_text()
        self.assertNotIn('performanceCard("Notable tier ATS"', source)
        self.assertNotIn('performanceCard("Play tier YTD"', source)
        self.assertIn('performanceCard("ATS CLV YTD"', source)
        self.assertIn('performanceCard("ATS beat close YTD"', source)
        self.assertNotIn("Season-to-Date · Every Signal and Testing Key", source)
        self.assertIn("Prospective Moneyline Ledger · Separate from ATS", source)


if __name__ == "__main__":
    unittest.main()
