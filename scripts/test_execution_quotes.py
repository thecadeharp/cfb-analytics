import unittest

from scripts.snapshot_projections import best_execution_spread, best_execution_total


CAPTURED = "2026-11-13T15:00:00+00:00"


def line(book, spread, home_price=-110, away_price=-110, total=50.5,
         over_price=-110, under_price=-110, updated="2026-11-13T14:55:00Z"):
    return {
        "bookmaker": book,
        "bookmaker_key": book.lower(),
        "spread": {
            "bookmaker": book,
            "bookmaker_key": book.lower(),
            "home_spread": spread,
            "away_spread": -spread,
            "home_price": home_price,
            "away_price": away_price,
            "last_update": updated,
        },
        "total": {
            "bookmaker": book,
            "bookmaker_key": book.lower(),
            "total": total,
            "under_total": total,
            "over_price": over_price,
            "under_price": under_price,
            "last_update": updated,
        },
    }


class ExecutionQuoteTests(unittest.TestCase):
    def setUp(self):
        self.market = {
            "home_spread": -5.5,
            "total": 50.5,
            "book_lines": [
                line("BookA", -5.5),
                line("BookB", -4.5, home_price=-117, total=49.5),
                line("StaleBook", -3.5, total=48.5, updated="2026-11-13T13:00:00Z"),
                line("ExpensiveBook", -4.0, home_price=-130, total=49.0, over_price=-130),
            ],
        }

    def test_home_side_gets_best_fresh_acceptable_spread(self):
        quote = best_execution_spread(self.market, "Home", "Home", CAPTURED)
        self.assertEqual(quote["home_spread"], -4.5)
        self.assertEqual(quote["price"], -117)
        self.assertEqual(quote["bookmaker"], "BookB")

    def test_away_side_gets_most_points(self):
        quote = best_execution_spread(self.market, "Away", "Home", CAPTURED)
        self.assertEqual(quote["team_spread"], 5.5)
        self.assertEqual(quote["home_spread"], -5.5)

    def test_over_gets_lowest_fresh_total_at_acceptable_price(self):
        quote = best_execution_total(self.market, "OVER", CAPTURED)
        self.assertEqual(quote["total"], 49.5)
        self.assertEqual(quote["bookmaker"], "BookB")

    def test_under_gets_highest_total(self):
        quote = best_execution_total(self.market, "UNDER", CAPTURED)
        self.assertEqual(quote["total"], 50.5)
        self.assertEqual(quote["bookmaker"], "BookA")


if __name__ == "__main__":
    unittest.main()
