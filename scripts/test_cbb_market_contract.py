import tempfile
import unittest
from pathlib import Path

from scripts.build_cbb_market_contract import ROOT, build_contract
from scripts.build_static_cache_manifest import build_manifest


class CbbMarketContractTests(unittest.TestCase):
    def test_contract_preserves_first_capture_and_separates_model(self):
        board = {"meta": {"version": "board-v1"}, "games": [{
            "game_id": 9, "status": "scheduled", "start_date": "2026-11-03T00:00:00Z", "neutral_site": True,
            "away": {"team": "Ohio State"}, "home": {"team": "BYU"},
            "projection": {"home_margin": -6.2, "total": 154, "away_points": 80.1, "home_points": 73.9, "projected_possessions": 66.1, "home_win_probability": 31.4},
            "market": {"opening_home_spread": 2.5, "consensus_home_spread": 3.5, "opening_total": 151, "consensus_total": 153, "book_count": 4},
        }]}
        history = {"games": {"9": [{"captured_at_utc": "2026-11-01T00:00:00Z", "consensus_home_spread": 2.5, "consensus_total": 151}, {"captured_at_utc": "2026-11-02T00:00:00Z", "consensus_home_spread": 3.5, "consensus_total": 153}]}}
        payload = build_contract(board, history)
        game = payload["games"]["9"]
        self.assertEqual(game["model"]["thi_home_spread"], 6.2)
        self.assertEqual(game["market"]["opening"]["home_spread"], 2.5)
        self.assertEqual(game["market"]["movement"]["home_spread_points"], 1.0)
        self.assertTrue(game["market"]["movement"]["toward_thi"])
        self.assertTrue(game["neutral_site"])

    def test_manifest_versions_change_with_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "data/cbb/projection_board.json"
            path.parent.mkdir(parents=True)
            path.write_text("{}")
            first = build_manifest(root)
            path.write_text('{"changed":true}')
            second = build_manifest(root)
            key = "data/cbb/projection_board.json"
            self.assertNotEqual(first["assets"][key]["version"], second["assets"][key]["version"])
            self.assertEqual(second["assets"][key]["ttl_seconds"], 60)

    def test_frontend_uses_contract_cache_and_isolated_simulator(self):
        source = (ROOT / "cbb-site.js").read_text()
        self.assertIn("CACHE_MANIFEST_PATH", source)
        self.assertIn("state.data?.marketContract?.games", source)
        self.assertIn("data-cbb-possession-simulator", source)
        self.assertIn("normalCdf(margin / residualSd)", source)
        self.assertIn("does not change Model A, signals, tracked plays or the official projection", source)


if __name__ == "__main__":
    unittest.main()
