#!/usr/bin/env python3
"""Regression checks for the CFB and CBB matchup blueprint surfaces."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MatchupBlueprintUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfb = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.cbb = (ROOT / "cbb-site.js").read_text(encoding="utf-8")
        cls.cbb_css = (ROOT / "cbb-site.css").read_text(encoding="utf-8")
        cls.dark = (ROOT / "dark-mode.css").read_text(encoding="utf-8")
        cls.index = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_cfb_blueprint_follows_what_stands_out(self):
        self.assertIn("function matchupBlueprintMarkup", self.cfb)
        self.assertIn("Who does what better", self.cfb)
        self.assertIn("Expected game script", self.cfb)
        self.assertIn("key to win or cover", self.cfb)
        self.assertIn(
            "${matchupStandoutsMarkup(awayName, homeName)}\n      ${matchupBlueprintMarkup(awayName, homeName, game)}",
            self.cfb,
        )

    def test_cfb_blueprint_uses_direction_aware_profile_metrics(self):
        for metric in (
            '"epa_play"',
            '"success_rate"',
            '"iso_ppp"',
            '"opportunity_rate"',
            '"havoc_rate"',
            '"points_per_opportunity"',
        ):
            with self.subTest(metric=metric):
                self.assertIn(metric, self.cfb)
        self.assertIn("Model A remains the published line", self.cfb)

    def test_cbb_blueprint_uses_adjusted_profiles_and_four_factors(self):
        self.assertIn("function cbbMatchupBlueprint", self.cbb)
        self.assertIn("current_efficiency?.adjusted", self.cbb)
        self.assertIn("preseason_prior?.adjusted", self.cbb)
        self.assertIn("factor_advantages", self.cbb)
        self.assertIn("KEY TO WIN OR COVER", self.cbb)
        self.assertIn("${cbbParityHeader(game, date)}\n      ${cbbMatchupBlueprint(game)}", self.cbb)

    def test_blueprints_are_responsive_and_dark_mode_safe(self):
        self.assertIn(".cbb-matchup-blueprint", self.cbb_css)
        self.assertIn(".cbb-blueprint-grid,.cbb-blueprint-keys{grid-template-columns:1fr}", self.cbb_css)
        self.assertIn(".thi-matchup-blueprint", self.dark)
        self.assertIn(".thi-blueprint-edges", self.dark)

    def test_asset_versions_are_bumped(self):
        self.assertIn("app.js?v=2026-matchup-blueprint-v01", self.index)
        self.assertIn("cbb-site.css?v=2027-cbb-matchup-blueprint-v01", self.index)
        self.assertIn("cbb-site.js?v=2027-cbb-matchup-blueprint-v01", self.index)
        self.assertIn("dark-mode.css?v=2026-matchup-blueprint-v09", self.index)


if __name__ == "__main__":
    unittest.main()
