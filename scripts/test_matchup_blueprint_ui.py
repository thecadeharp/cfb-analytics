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
        cls.cfb_status = (ROOT / "status-controls.js").read_text(encoding="utf-8")
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
        for grade in ("is-clear", "is-strong", "is-lean", "is-even"):
            self.assertIn(grade, self.cfb)

    def test_cfb_style_matchup_uses_verified_production_metrics(self):
        self.assertIn("function styleMatchupMarkup", self.cfb)
        for metric in (
            '"standard_down_epa"',
            '"passing_down_epa"',
            '"opportunity_rate"',
            '"line_yards_per_rush"',
            '"adjusted_sack_rate"',
            '"havoc_rate"',
            '"explosive_rate"',
        ):
            with self.subTest(metric=metric):
                self.assertIn(metric, self.cfb)
        self.assertIn("does not label run direction", self.cfb)
        self.assertIn('"standard_down_plays"', self.cfb)
        self.assertIn('"passing_down_plays"', self.cfb)
        self.assertIn('"rush_attempts"', self.cfb)
        self.assertIn('"pass_plays"', self.cfb)
        self.assertIn("${styleMatchupMarkup(awayName, homeName)}", self.cfb)

    def test_cbb_blueprint_uses_adjusted_profiles_and_four_factors(self):
        self.assertIn("function cbbMatchupBlueprint", self.cbb)
        self.assertIn("current_efficiency?.adjusted", self.cbb)
        self.assertIn("preseason_prior?.adjusted", self.cbb)
        self.assertIn("factor_advantages", self.cbb)
        self.assertIn("KEY TO WIN OR COVER", self.cbb)
        self.assertIn("${cbbParityHeader(game, date)}\n      ${cbbMatchupBlueprint(game)}", self.cbb)
        self.assertIn('class="is-${escapeHtml(card.grade.toLowerCase())}"', self.cbb)
        self.assertIn("--blueprint-accent", self.cbb_css)

    def test_cbb_style_matchup_surfaces_observed_play_profile(self):
        self.assertIn("function cbbStyleMatchup", self.cbb)
        for metric in ("rim_rate", "midrange_rate", "three_rate", "assisted_rate", "explicit_transition_rate"):
            with self.subTest(metric=metric):
                self.assertIn(metric, self.cbb)
        self.assertIn("${cbbStyleMatchup(game)}", self.cbb)
        self.assertIn("does not by itself imply better efficiency", self.cbb)

    def test_blueprints_are_responsive_and_dark_mode_safe(self):
        self.assertIn(".cbb-matchup-blueprint", self.cbb_css)
        self.assertIn(".cbb-blueprint-grid,.cbb-blueprint-keys{grid-template-columns:1fr}", self.cbb_css)
        self.assertIn(".thi-matchup-blueprint", self.dark)
        self.assertIn(".thi-blueprint-edges", self.dark)
        self.assertIn(".thi-style-matchup", self.dark)
        self.assertIn(".cbb-style-matchup", self.cbb_css)

    def test_standout_cards_use_readable_strength_colors(self):
        for token in ("--standout-bg", "--standout-heading", "--standout-copy", "--standout-badge"):
            with self.subTest(token=token):
                self.assertIn(token, self.cfb)
                self.assertIn(token, self.dark)
        self.assertIn(".thi-standout-card.high", self.dark)
        self.assertIn(".thi-standout-card.notable", self.dark)
        self.assertIn(".thi-standout-card.lean", self.dark)

    def test_cbb_date_divider_matches_cfb_treatment(self):
        self.assertIn('class="cbb-day-divider-box hammer-day-divider-box"', self.cbb)
        for declaration in (
            "min-height:46px",
            "margin:12px 0 8px",
            "padding:0 16px",
            "background:#fff8dc",
            "border:1px solid #e7c967",
            "border-radius:9px",
            "color:#5f4900",
            "font-size:13px",
            "font-weight:700",
            "letter-spacing:.7px",
        ):
            with self.subTest(declaration=declaration):
                self.assertIn(declaration, self.cfb_status)
                self.assertIn(declaration, self.cbb_css)
        for declaration in (
            "background:#322b19 !important",
            "border-color:#68582d !important",
            "color:#e8cf83 !important",
        ):
            with self.subTest(declaration=declaration):
                self.assertIn(declaration, self.dark)
                self.assertIn(declaration, self.cbb_css)

    def test_asset_versions_are_bumped(self):
        self.assertIn("app.js?v=2026-blueprint-grades-v04", self.index)
        self.assertIn("cbb-site.css?v=2027-cbb-date-parity-v04", self.index)
        self.assertIn("cbb-site.js?v=2027-cbb-date-parity-v04", self.index)
        self.assertIn("dark-mode.css?v=2026-standout-contrast-v11", self.index)


if __name__ == "__main__":
    unittest.main()
