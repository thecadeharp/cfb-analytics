import sys
import json
import tempfile
import types
import unittest
from pathlib import Path

# The projection builder imports the HTTP client used only by live refreshes.
# Unit tests exercise pure market parsing and do not make network calls.
if "requests" not in sys.modules:
    sys.modules["requests"] = types.SimpleNamespace(
        RequestException=Exception,
        get=lambda *args, **kwargs: None,
    )

from scripts.build_cbb_data_foundation import market_summary
from scripts.build_commercial_readiness import build
from scripts.build_projections import (
    ODDS_SCREEN_BOOKMAKERS,
    extract_market,
    freeze_started_markets,
    market_for_schedule_game,
)
from scripts.capture_closing_lines import load_existing_game_keys


class PriceContractTest(unittest.TestCase):
    def test_same_team_rematches_do_not_share_market_or_frozen_result(self):
        earlier = {
            "game_id": "earlier",
            "home_team": "Colorado State",
            "away_team": "Boise State",
            "start_date": "2026-11-07T23:00:00Z",
        }
        rematch = {
            "game_id": "rematch",
            "home_team": "Colorado State",
            "away_team": "Boise State",
            "start_date": "2026-11-28T23:00:00Z",
        }
        rematch_market = {
            "id": "provider-rematch",
            "home_team": "Colorado State",
            "away_team": "Boise State",
            "commence_time": "2026-11-28T23:00:00Z",
            "spread_home": 4.5,
        }
        odds = {"meta": {}, "games": [rematch_market]}
        frozen = {
            ("id", "earlier"): {
                "id": "frozen:earlier",
                "home_team": "Colorado State",
                "away_team": "Boise State",
                "commence_time": earlier["start_date"],
                "spread_home": 17.0,
            }
        }

        refreshed = freeze_started_markets(
            odds,
            {"games": [earlier, rematch]},
            frozen,
            now=__import__("datetime").datetime.fromisoformat("2026-11-24T12:00:00+00:00"),
        )
        self.assertEqual(len(refreshed["games"]), 2)
        lookup = {("Colorado State", "Boise State"): refreshed["games"]}
        self.assertEqual(market_for_schedule_game(lookup, earlier)["spread_home"], 17.0)
        self.assertEqual(market_for_schedule_game(lookup, rematch)["spread_home"], 4.5)

    def test_odds_screen_uses_requested_exchange_books_at_one_region_cost(self):
        books = ODDS_SCREEN_BOOKMAKERS.split(",")
        self.assertEqual(len(books), 10)
        self.assertIn("novig", books)
        self.assertIn("prophetx", books)
        self.assertIn("espnbet", books)
        self.assertNotIn("lowvig", books)
        self.assertNotIn("mybookieag", books)
        self.assertNotIn("bovada", books)

    def test_cfb_reference_quote_is_two_sided_and_prefers_sharp_book(self):
        raw = {
            "home_team": "Home",
            "bookmakers": [
                {"key": "draftkings", "title": "DraftKings", "markets": [{"key": "spreads", "outcomes": [{"name": "Home", "point": -3.5, "price": -110}, {"name": "Away", "point": 3.5, "price": -110}]}, {"key": "h2h", "outcomes": [{"name": "Home", "price": -170}, {"name": "Away", "price": 145}]}]},
                {"key": "pinnacle", "title": "Pinnacle", "markets": [{"key": "spreads", "outcomes": [{"name": "Home", "point": -3, "price": -105}, {"name": "Away", "point": 3, "price": -115}]}, {"key": "h2h", "outcomes": [{"name": "Home", "price": -165}, {"name": "Away", "price": 148}]}]},
            ],
        }
        market = extract_market(raw)
        self.assertEqual(market["reference_spread"]["bookmaker_key"], "pinnacle")
        self.assertEqual(market["reference_spread"]["home_price"], -105)
        self.assertEqual(market["reference_spread"]["away_price"], -115)
        self.assertAlmostEqual(sum(market["reference_spread"]["no_vig_probability"].values()), 1.0)
        self.assertEqual(market["reference_moneyline"]["bookmaker_key"], "pinnacle")
        self.assertEqual(market["reference_moneyline"]["home_price"], -165)
        self.assertAlmostEqual(sum(market["reference_moneyline"]["no_vig_probability"].values()), 1.0)
        self.assertEqual(len(market["book_lines"]), 2)
        pinnacle = next(row for row in market["book_lines"] if row["bookmaker_key"] == "pinnacle")
        self.assertEqual(pinnacle["spread"]["home_spread"], -3)
        self.assertEqual(pinnacle["spread"]["away_price"], -115)
        self.assertEqual(pinnacle["moneyline"]["away_price"], 148)

    def test_incomplete_cfb_quote_is_not_used_for_validation(self):
        raw = {"home_team": "Home", "bookmakers": [{"key": "pinnacle", "markets": [{"key": "spreads", "outcomes": [{"name": "Home", "point": -3, "price": -105}]}]}]}
        self.assertIsNone(extract_market(raw)["reference_spread"])

    def test_cbb_contract_keeps_moneyline_prices_and_marks_spread_gap(self):
        market = market_summary([
            {"provider": "DraftKings", "spread": -4, "overUnder": 145, "homeMoneyline": -180, "awayMoneyline": 155},
            {"provider": "Pinnacle", "spread": -3.5, "overUnder": 144.5, "homeMoneyline": -172, "awayMoneyline": 151},
        ])
        self.assertEqual(market["reference_moneyline"]["provider"], "Pinnacle")
        self.assertEqual(market["reference_moneyline"]["validation_scope"], "moneyline_only")
        self.assertAlmostEqual(sum(market["reference_moneyline"]["no_vig_probability"].values()), 1.0)
        self.assertEqual(market["spread_price_status"], "unavailable_from_provider_contract")
        self.assertEqual(len(market["book_lines"]), 2)
        self.assertEqual(market["book_lines"][1]["provider"], "Pinnacle")
        self.assertEqual(market["book_lines"][1]["spread"], -3.5)

    def test_cbb_odds_api_prices_support_two_sided_spread_validation(self):
        market = market_summary([
            {"provider": "DraftKings", "spread": -4, "homeSpreadPrice": -110, "awaySpreadPrice": -110, "homeMoneyline": -180, "awayMoneyline": 155},
            {"provider": "Pinnacle", "spread": -3.5, "homeSpreadPrice": -105, "awaySpreadPrice": -115, "homeMoneyline": -172, "awayMoneyline": 151},
        ])
        self.assertEqual(market["reference_spread"]["provider"], "Pinnacle")
        self.assertEqual(market["reference_spread"]["home_price"], -105)
        self.assertEqual(market["reference_spread"]["away_price"], -115)
        self.assertAlmostEqual(sum(market["reference_spread"]["no_vig_probability"].values()), 1.0)
        self.assertEqual(market["spread_price_status"], "available")

    def test_legacy_closing_is_eligible_for_one_price_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "closings.jsonl"
            rows = [
                {"game_key": "old", "closing_market": {"home_spread": -3}},
                {"game_key": "priced", "closing_market": {"reference_spread": {"home_price": -105, "away_price": -115}}},
            ]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            existing, complete = load_existing_game_keys(path)
            self.assertEqual(existing, {"old", "priced"})
            self.assertEqual(complete, {"priced"})


class ReadinessTest(unittest.TestCase):
    def test_readiness_separates_research_from_betting_claim(self):
        report = build()
        self.assertEqual(report["verdict"]["research_subscription"], "ready_with_guardrails")
        self.assertEqual(report["verdict"]["betting_edge_product"], "not_ready")
        self.assertEqual(len(report["pillars"]), 5)
        self.assertEqual({row["id"] for row in report["pillars"]}, {"prospective_validation", "real_prices", "predeclared_rules", "operational_proof", "data_rights"})


if __name__ == "__main__":
    unittest.main()
