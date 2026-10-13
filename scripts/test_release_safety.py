import json
import tempfile
import unittest
from pathlib import Path

from scripts.freeze_cbb_preseason_power import canonical_hash, freeze
from scripts.enforce_cbb_public_roster_gate import enforce
from scripts.validate_cbb_availability import validate
from scripts.verify_public_release import verify


class ReleaseSafetyTests(unittest.TestCase):
    def test_failed_roster_audit_strips_public_player_payload(self):
        players = {"meta": {"version": "test"}, "players": [{"name": "Wrong Player"}], "team_rosters": [{"team": "Test"}]}
        public, changed = enforce(players, {"meta": {"status": "withheld"}, "checks": {"official_spot_check": False}})
        self.assertTrue(changed)
        self.assertEqual(public["players"], [])
        self.assertEqual(public["team_rosters"], [])
        self.assertEqual(public["meta"]["source_player_count_before_gate"], 1)

    def test_availability_requires_null_model_adjustment(self):
        row = {
            "game_id": 1, "team_id": 2, "player_id": 3, "player": "Test Player",
            "status": "questionable", "verified_source_url": "https://example.com/report",
            "verified_at_utc": "2026-11-01T12:00:00Z", "expires_at_utc": "2026-11-02T12:00:00Z",
            "model_adjustment": None,
        }
        self.assertEqual(validate({"reports": [row]}), [])
        row["model_adjustment"] = -2
        self.assertTrue(validate({"reports": [row]}))

    def test_preseason_freeze_is_immutable(self):
        payload = {"meta": {"methodology": "test"}, "teams": [{"team_id": 1, "prior_net": 10}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source.json", root / "frozen.json"
            source.write_text(json.dumps(payload))
            frozen = freeze(source, output)
            self.assertEqual(frozen["meta"]["canonical_sha256"], canonical_hash(payload))
            payload["teams"][0]["prior_net"] = 11
            source.write_text(json.dumps(payload))
            with self.assertRaises(RuntimeError):
                freeze(source, output)

    def test_canary_fails_closed_on_roster_contradiction(self):
        payloads = {
            "cbb_power": {"meta": {"version": "thi-cbb-display-power-v2.0", "model_usage": "display_only"}, "teams": [{}] * 300},
            "cbb_priors": {"teams": [{}] * 300},
            "cbb_health": {"meta": {"status": "healthy"}, "coverage": {"published_roster_players": 10}},
            "cbb_roster_audit": {"meta": {"status": "withheld"}},
            "cbb_players": {"players": [{"name": "Wrong Player"}]},
            "cbb_board": {"games": [{"neutral_site": True, "projection": {"matchup_context": {"home_court": {"points": 0}}}}] * 300},
            "cfb_board": {"games": [{}] * 50},
            "operations": {"meta": {"version": "thi-operations-readiness-v1.0"}},
        }
        with self.assertRaises(RuntimeError):
            verify(payloads)


if __name__ == "__main__":
    unittest.main()
