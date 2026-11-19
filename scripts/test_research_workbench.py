#!/usr/bin/env python3
import csv
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ResearchWorkbenchTests(unittest.TestCase):
    def test_public_page_preserves_analytics_and_contract_language(self):
        source = (ROOT / "research-workbench.html").read_text()
        self.assertEqual(source.count("static.cloudflareinsights.com/beacon.min.js"), 1)
        self.assertEqual(source.count('src="engagement-analytics.js?v=2026-engagement-v01"'), 1)
        self.assertIn('href="https://thehammerindex.com/research-workbench.html"', source)
        for section_id in ("archive", "compare", "simulations", "coverage", "verification"):
            self.assertIn(f'id="{section_id}"', source)
        self.assertIn("Ready” does not mean a third party has accepted", source)

    def test_packet_matches_the_full_public_benchmark(self):
        benchmark = json.loads((ROOT / "data/reports/benchmark_center.json").read_text())
        packet = json.loads((ROOT / "data/reports/independent_benchmark_packet.json").read_text())
        self.assertEqual(packet["meta"]["version"], "thi-independent-benchmark-packet-v1.0")
        self.assertEqual(packet["meta"]["row_count"], len(benchmark["observations"]))
        self.assertEqual(len(packet["rows"]), len(benchmark["observations"]))
        with (ROOT / "data/reports/independent_benchmark_packet.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), len(packet["rows"]))
        self.assertEqual(list(rows[0]), packet["fields"])

    def test_research_registry_is_explicit_and_non_promotional(self):
        registry = json.loads((ROOT / "data/research_registry.json").read_text())
        self.assertEqual(registry["meta"]["version"], "thi-public-research-registry-v1.0")
        self.assertIn("falsifiable", registry["meta"]["cadence"])
        self.assertTrue(registry["notes"])
        for note in registry["notes"]:
            self.assertIn(note["status"], {"published", "planned"})
            self.assertIn("production_effect", note)

    def test_client_exposes_real_filters_compare_and_export(self):
        source = (ROOT / "research-workbench.js").read_text()
        for token in ("archive-sport", "archive-team", "archive-from", "archive-to", "archive-venue", "archive-env", "exportFiltered", "renderCompare"):
            self.assertIn(token, source)
        self.assertIn("#matchup=", source)
        self.assertIn("?sport=cbb&game=", source)


if __name__ == "__main__":
    unittest.main()
