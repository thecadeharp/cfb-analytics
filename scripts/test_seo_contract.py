#!/usr/bin/env python3

import json
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE_URL = "https://thehammerindex.com/"


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

    def test_robots_and_sitemap_are_valid_and_consistent(self):
        robots = (ROOT / "robots.txt").read_text(encoding="utf-8")
        self.assertIn("User-agent: *", robots)
        self.assertIn("Allow: /", robots)
        self.assertIn(f"Sitemap: {SITE_URL}sitemap.xml", robots)
        self.assertNotIn("Disallow: /data/", robots)

        tree = ET.parse(ROOT / "sitemap.xml")
        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = [node.text for node in tree.findall("sm:url/sm:loc", namespace)]
        self.assertEqual(urls, [SITE_URL])
        self.assertFalse(any("#" in url for url in urls))

    def test_existing_analytics_remain_present_once(self):
        self.assertEqual(self.index.count("static.cloudflareinsights.com/beacon.min.js"), 1)
        self.assertEqual(self.index.count('src="engagement-analytics.js?v=2026-engagement-v01"'), 1)
        self.assertEqual(self.index.count('src="analytics-config.js?v=2026-engagement-v01"'), 1)


if __name__ == "__main__":
    unittest.main()
