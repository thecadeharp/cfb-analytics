#!/usr/bin/env python3
"""Regression checks for the dark-mode postgame analytics surfaces."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DarkModePostgameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = (ROOT / "dark-mode.css").read_text(encoding="utf-8")
        cls.index = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_styles_target_the_rendered_postgame_id(self):
        self.assertIn('#hammer-postgame-analysis', self.css)
        self.assertNotIn('#hammer-postgame-analytics', self.css)

    def test_summary_metric_and_audit_values_have_dark_mode_styles(self):
        for selector in (
            '.hammer-pg-card-value',
            '.hammer-pg-panel',
            '.hammer-pg-row',
            '.hammer-pg-heat-card',
            '.pg-metric-value',
            '.final-result-item span:last-child',
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.css)

    def test_dark_mode_stylesheet_cache_key_was_bumped(self):
        self.assertIn(
            'dark-mode.css?v=2026-dark-postgame-v06',
            self.index,
        )


if __name__ == "__main__":
    unittest.main()
