import unittest

from scripts.market_provider_contract import novig_quote, quote


class MarketProviderContractTests(unittest.TestCase):
    def test_novig_order_book_fields_normalize_without_credentials(self):
        row = novig_quote(
            {"id": "abc", "sport": "cbb"}, {"type": "spread"},
            {"selection": "Duke", "point": -4.5, "best_price": -105, "quantity": 250, "last_trade_price": -107, "deeplink": "https://novig.com/market/abc"},
            "2026-10-09T12:00:00Z", "thi",
        )
        self.assertEqual(row["provider"], "novig")
        self.assertEqual(row["line"], -4.5)
        self.assertEqual(row["available_quantity"], 250.0)
        self.assertIn("partner_id=thi", row["deeplink"])

    def test_public_splits_are_not_part_of_quote_contract(self):
        row = quote(provider="book", event_id="1", sport="cfb", market="moneyline", selection="A", price=-110, observed_at_utc="2026-10-09T12:00:00Z")
        self.assertNotIn("ticket_pct", row)
        self.assertNotIn("handle_pct", row)

    def test_invalid_market_is_rejected(self):
        with self.assertRaises(ValueError):
            quote(provider="x", event_id="1", sport="cbb", market="splits", selection="A", price=-110, observed_at_utc="2026-10-09T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
