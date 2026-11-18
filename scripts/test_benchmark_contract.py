#!/usr/bin/env python3
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BenchmarkContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "data/reports/benchmark_center.json").read_text())
        cls.changelog = json.loads((ROOT / "data/model_changelog.json").read_text())

    def test_static_interval_contract_is_deterministic_and_complete(self):
        meta = self.data["meta"]
        self.assertEqual(meta["version"], "thi-benchmark-center-v2.0")
        self.assertEqual(meta["intervals"]["bootstrap_seed"], 42)
        self.assertEqual(meta["intervals"]["bootstrap_iterations"], 2000)
        self.assertEqual(len(self.data["slices"]), 18)
        for slice_payload in self.data["slices"].values():
            for metric in slice_payload["predictive"]["metrics"].values():
                self.assertIn(metric["method"], {"wilson_95", "fixed_seed_bootstrap"})
                if metric["value"] is not None:
                    self.assertLessEqual(metric["ci_low"], metric["ci_high"])

    def test_every_observation_has_a_versioned_audit_envelope(self):
        required = {"season", "sport", "model_version", "freeze_ts", "freeze_ts_status", "market_policy_version", "grading_policy_version", "env_status"}
        self.assertTrue(self.data["observations"])
        for row in self.data["observations"]:
            self.assertTrue(required <= set(row))
            self.assertIn(row["env_status"], {"production", "research"})
            if row["freeze_ts_status"] == "captured":
                self.assertTrue(row["freeze_ts"])
            else:
                self.assertIsNone(row["freeze_ts"])

    def test_market_samples_and_source_coverage_are_explicit(self):
        for payload in self.data["slices"].values():
            coverage = payload["market"]["source_coverage"]
            self.assertIn("n_games", coverage)
            self.assertIn("n_with_source", coverage)
            for group in payload["market"]["spread"] + payload["market"]["total"]:
                self.assertIn("n_results", group)
                self.assertIn("n_clv", group)
                self.assertEqual(group["hit_rate"]["n"], group["n_results"])
                self.assertEqual(group["mean_clv"]["n"], group["n_clv"])

    def test_changelog_is_typed_unique_and_chronological(self):
        entries = self.changelog["entries"]
        self.assertEqual(len({row["id"] for row in entries}), len(entries))
        self.assertTrue(all(row["tag"] in {"MODEL", "MARKET CONTRACT", "DATA/PRESENTATION"} for row in entries))
        dates = [row["date"] for row in entries]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertIn("Append-only", self.changelog["meta"]["policy"])


if __name__ == "__main__":
    unittest.main()
