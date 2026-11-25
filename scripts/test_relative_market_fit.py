import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RelativeMarketFitContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfb = (ROOT / "app.js").read_text()
        cls.cbb = (ROOT / "cbb-site.js").read_text()
        cls.builder = (ROOT / "scripts" / "build_projections.py").read_text()
        cls.snapshot = (ROOT / "scripts" / "snapshot_projections.py").read_text()
        cls.closing = (ROOT / "scripts" / "capture_closing_lines.py").read_text()
        cls.index = (ROOT / "index.html").read_text()

    def test_both_sports_publish_descriptive_relative_market_fit(self):
        for source in (self.cfb, self.cbb):
            self.assertIn("Relative Market Fit", source)
            self.assertIn("Moneyline offers stronger modeled fit", source)
            self.assertIn("Spread offers stronger modeled fit", source)
            self.assertIn("No qualifying market advantage", source)
            self.assertIn("not a recommendation, play tier or tracked ATS result", source)

    def test_declared_price_and_edge_guardrails_are_present(self):
        self.assertIn("favoriteFloor: -185", self.cfb)
        self.assertIn("underdogCeiling: 250", self.cfb)
        self.assertIn("minProbabilityEdge: 0.03", self.cfb)
        self.assertIn("minEdge:.03", self.cbb)
        self.assertIn("favoriteFloor:-185", self.cbb)
        self.assertIn("underdogCeiling:250", self.cbb)

    def test_cfb_capture_contract_freezes_moneylines(self):
        self.assertIn('"markets": "h2h,spreads,totals"', self.builder)
        self.assertIn('"reference_moneyline"', self.snapshot)
        self.assertIn('"reference_moneyline"', self.closing)

    def test_new_asset_keys_are_published(self):
        self.assertIn("app.js?v=2026-relative-market-fit-v01", self.index)
        self.assertIn("cbb-site.js?v=2027-relative-market-fit-v01", self.index)
        self.assertIn("postgame-analytics.js?v=2026-relative-market-fit-v01", self.index)


if __name__ == "__main__":
    unittest.main()
