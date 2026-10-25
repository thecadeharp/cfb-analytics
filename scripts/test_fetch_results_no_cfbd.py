import sys
import unittest
from unittest.mock import MagicMock

try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    sys.modules["requests"] = MagicMock()

from scripts.fetch_results_no_cfbd import (
    align_to_projection_names,
    combine_provider_rows,
    espn_team_name,
)


class FetchResultsNoCfbdTests(unittest.TestCase):
    def test_espn_prefers_school_location_over_mascot_display_name(self):
        competitor = {
            "team": {
                "location": "Baylor",
                "displayName": "Baylor Bears",
                "shortDisplayName": "Baylor",
            }
        }
        self.assertEqual(espn_team_name(competitor), "Baylor")

    def test_old_mascot_row_aligns_and_deduplicates_with_ncaa_final(self):
        known = {"baylor@kansas": ("Baylor", "Kansas")}
        espn = align_to_projection_names(
            {"away_team": "Baylor Bears", "home_team": "Kansas Jayhawks", "source": "ESPN fallback"},
            known,
        )
        ncaa = {"away_team": "Baylor", "home_team": "Kansas", "source": "NCAA"}
        merged = combine_provider_rows([ncaa], [espn])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source"], "NCAA")


if __name__ == "__main__":
    unittest.main()
