#!/usr/bin/env python3

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.audit_data_freshness import audit


class DataFreshnessAuditTests(unittest.TestCase):
    def test_current_repository_contract_is_not_critically_stale(self):
        root = Path(__file__).resolve().parents[1]
        report = audit(root, datetime(2026, 10, 17, 0, 45, tzinfo=timezone.utc))
        self.assertEqual(report["meta"]["critical_failure_count"], 0, report["findings"])
        self.assertEqual(report["week_alignment"]["active_week"], 7)
        self.assertTrue(any(row["dataset"] == "cbb_players" for row in report["findings"]))


if __name__ == "__main__":
    unittest.main()
