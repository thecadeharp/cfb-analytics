#!/usr/bin/env python3

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicDataStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "data-status.js").read_text(encoding="utf-8")

    def test_status_panel_and_versioned_script_are_published(self):
        self.assertIn('id="data-health-panel"', self.index)
        self.assertIn('data-status.js?v=2026-public-status-v01', self.index)

    def test_status_monitor_covers_core_public_feeds(self):
        for path in (
            "data/projections.json",
            "data/live_scores.json",
            "data/roster_notes.json",
            "data/cbb/projection_board.json",
            "data/cbb/platform_health.json",
            "data/market/rlm_monitor.json",
        ):
            self.assertIn(path, self.script)
            self.assertTrue((ROOT / path).exists(), path)

    def test_mobile_layout_uses_single_column_without_fixed_width(self):
        mobile = re.search(r"@media \(max-width: 600px\) \{(?P<body>.*?)\n    \}", self.index, re.S)
        self.assertIsNotNone(mobile)
        body = mobile.group("body")
        self.assertIn(".data-health-grid { grid-template-columns: 1fr; }", body)
        self.assertNotIn("min-width:", body.split(".data-health-grid", 1)[1].split(".page", 1)[0])

    def test_status_copy_does_not_claim_model_validation(self):
        self.assertIn("does not certify model performance", self.index)
        self.assertIn('panel.dataset.state = overall', self.script)

    def test_naive_generated_timestamps_are_treated_as_utc(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        updated = (ROOT / "last-updated-timestamp.js").read_text(encoding="utf-8")
        self.assertIn("function parseDataTimestamp(value)", app)
        self.assertIn("`${text}Z`", app)
        self.assertIn("`${text}Z`", updated)
        self.assertNotIn("new Date(generated)", app)


if __name__ == "__main__":
    unittest.main()
