#!/usr/bin/env python3

import json
import struct
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE_URL = "https://thehammerindex.com/"
BENCHMARK_URL = f"{SITE_URL}benchmark.html"
PHILOSOPHY_URL = f"{SITE_URL}philosophy.html"
CHANGELOG_URL = f"{SITE_URL}changelog.html"


class HeadParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.in_title = False
        self.in_json_ld = False
        self.title = ""
        self.meta = []
        self.links = []
        self.json_ld = []
        self._json_chunks = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "head":
            self.in_head = True
        if not self.in_head:
            return
        if tag == "title":
            self.in_title = True
        elif tag == "meta":
            self.meta.append(attributes)
        elif tag == "link":
            self.links.append(attributes)
        elif tag == "script" and attributes.get("type") == "application/ld+json":
            self.in_json_ld = True
            self._json_chunks = []

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag == "script" and self.in_json_ld:
            self.in_json_ld = False
            self.json_ld.append(json.loads("".join(self._json_chunks)))
            self._json_chunks = []
        elif tag == "head":
            self.in_head = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.in_json_ld:
            self._json_chunks.append(data)


class SeoContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.parser = HeadParser()
        cls.parser.feed(cls.index)

    def meta_content(self, key, value):
        return next((item.get("content") for item in self.parser.meta if item.get(key) == value), None)

    def test_homepage_metadata_targets_real_site_content(self):
        self.assertEqual(
            self.parser.title.strip(),
            "The Hammer Index | College Football & Basketball Analytics",
        )
        description = self.meta_content("name", "description")
        self.assertIsNotNone(description)
        self.assertIn("football and basketball power ratings", description)
        self.assertIn("matchup projections", description)
        self.assertLessEqual(len(description), 160)
        self.assertIn("index, follow", self.meta_content("name", "robots"))

    def test_canonical_and_social_urls_use_the_primary_origin(self):
        canonical = next(
            (item.get("href") for item in self.parser.links if item.get("rel") == "canonical"),
            None,
        )
        self.assertEqual(canonical, SITE_URL)
        self.assertEqual(self.meta_content("property", "og:url"), SITE_URL)
        self.assertEqual(self.meta_content("property", "og:type"), "website")

    def test_structured_data_is_parseable_and_truthful(self):
        self.assertEqual(len(self.parser.json_ld), 1)
        graph = self.parser.json_ld[0].get("@graph") or []
        by_type = {item.get("@type"): item for item in graph}
        self.assertIn("Organization", by_type)
        self.assertIn("WebSite", by_type)
        self.assertIn("WebPage", by_type)
        self.assertEqual(by_type["Organization"].get("url"), SITE_URL)
        self.assertEqual(by_type["WebSite"].get("url"), SITE_URL)
        self.assertNotIn("AggregateRating", json.dumps(graph))
        self.assertNotIn("Review", json.dumps(graph))

    def test_google_favicon_is_declared_and_square(self):
        favicon = next(
            (
                item
                for item in self.parser.links
                if item.get("rel") == "icon" and item.get("sizes") == "48x48"
            ),
            None,
        )
        self.assertIsNotNone(favicon)
        self.assertEqual(favicon.get("href"), "/favicon-48.png")
        icon_path = ROOT / favicon["href"].lstrip("/")
        self.assertTrue(icon_path.is_file())
        with icon_path.open("rb") as handle:
            self.assertEqual(handle.read(8), b"\x89PNG\r\n\x1a\n")
            handle.read(8)
            width, height = struct.unpack(">II", handle.read(8))
        self.assertEqual((width, height), (48, 48))

    def test_robots_and_sitemap_are_valid_and_consistent(self):
        robots = (ROOT / "robots.txt").read_text(encoding="utf-8")
        self.assertIn("User-agent: *", robots)
        self.assertIn("Allow: /", robots)
        self.assertIn(f"Sitemap: {SITE_URL}sitemap.xml", robots)
        self.assertNotIn("Disallow: /data/", robots)

        tree = ET.parse(ROOT / "sitemap.xml")
        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = [node.text for node in tree.findall("sm:url/sm:loc", namespace)]
        self.assertEqual(urls, [SITE_URL, BENCHMARK_URL, PHILOSOPHY_URL, CHANGELOG_URL])
        self.assertFalse(any("#" in url for url in urls))

    def test_benchmark_page_is_indexable_and_uses_primary_origin(self):
        source = (ROOT / "benchmark.html").read_text(encoding="utf-8")
        parser = HeadParser()
        parser.feed(source)
        canonical = next(
            (item.get("href") for item in parser.links if item.get("rel") == "canonical"),
            None,
        )
        self.assertEqual(canonical, BENCHMARK_URL)
        self.assertEqual(
            next((item.get("content") for item in parser.meta if item.get("property") == "og:url"), None),
            BENCHMARK_URL,
        )
        self.assertIn("Benchmark & Calibration Center", parser.title)
        self.assertEqual(source.count("static.cloudflareinsights.com/beacon.min.js"), 1)

    def test_public_governance_pages_are_indexable_and_analytics_preserved(self):
        for filename, expected, title_fragment in (
            ("philosophy.html", PHILOSOPHY_URL, "What The Hammer Index Is"),
            ("changelog.html", CHANGELOG_URL, "Public Model Changelog"),
        ):
            source = (ROOT / filename).read_text(encoding="utf-8")
            parser = HeadParser()
            parser.feed(source)
            canonical = next((item.get("href") for item in parser.links if item.get("rel") == "canonical"), None)
            self.assertEqual(canonical, expected)
            self.assertIn(title_fragment, parser.title)
            self.assertEqual(source.count("static.cloudflareinsights.com/beacon.min.js"), 1)
            self.assertEqual(source.count('src="engagement-analytics.js?v=2026-engagement-v01"'), 1)

    def test_existing_analytics_remain_present_once(self):
        self.assertEqual(self.index.count("static.cloudflareinsights.com/beacon.min.js"), 1)
        self.assertEqual(self.index.count('src="engagement-analytics.js?v=2026-engagement-v01"'), 1)
        self.assertEqual(self.index.count('src="analytics-config.js?v=2026-engagement-v01"'), 1)


if __name__ == "__main__":
    unittest.main()
