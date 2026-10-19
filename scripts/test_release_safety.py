import json
import tempfile
import unittest
from pathlib import Path

from scripts.freeze_cbb_preseason_power import canonical_hash, freeze
from scripts.freeze_cbb_preseason_sos import freeze as freeze_sos
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

    def test_preseason_sos_freeze_is_immutable(self):
        intelligence = {"team_dossiers": [{"team_id": 1, "team": "Test", "conference": {"abbreviation": "T"}, "schedule_strength": {"scheduled_games": 1, "average_opponent_thi_net": 4.2, "nonconference_average_opponent_thi_net": 4.2}, "schedule_window": [{"game_id": 10, "opponent_id": 2, "opponent": "Other", "site": "away"}]}]}
        board = {"meta": {"season": 2027, "version": "board-v1"}, "games": [{"game_id": 10}]}
        power = {"meta": {"version": "power-v1"}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            intelligence_path, board_path, power_path, output = (root / name for name in ["intelligence.json", "board.json", "power.json", "frozen.json"])
            intelligence_path.write_text(json.dumps(intelligence))
            board_path.write_text(json.dumps(board))
            power_path.write_text(json.dumps(power))
            frozen = freeze_sos(intelligence_path, board_path, power_path, output)
            self.assertTrue(frozen["meta"]["immutable"])
            intelligence["team_dossiers"][0]["schedule_strength"]["average_opponent_thi_net"] = 5.2
            intelligence_path.write_text(json.dumps(intelligence))
            with self.assertRaises(RuntimeError):
                freeze_sos(intelligence_path, board_path, power_path, output)

    def test_canary_fails_closed_on_roster_contradiction(self):
        power_teams = [{"team_id": index} for index in range(300)]
        prior_teams = [{"team_id": index} for index in range(300)]
        cbb_games = [{"game_id": index, "neutral_site": index == 0, "projection": {"matchup_context": {"home_court": {"points": 0}}}} for index in range(300)]
        cfb_games = [{"game_id": index} for index in range(50)]
        sos_teams = [{"team_id": index, "opponents": [{"game_id": index}]} for index in range(300)]
        payloads = {
            "manifest": {"meta": {"version": "thi-static-cache-manifest-v1.0", "asset_count": 0}, "assets": {}},
            "cbb_power": {"meta": {"version": "thi-cbb-roster-power-v3.0", "model_usage": "display_only", "team_count": 300}, "teams": power_teams},
            "cbb_priors": {"teams": prior_teams},
            "cbb_model": {"meta": {"model_version": "model-v1"}},
            "cbb_candidate": {"meta": {"model_usage": "display_only; does not feed Model A", "roster_audit_status": "withheld", "roster_verification_status": "withheld_by_thi_audit"}, "evaluation": {"promotion_eligible": False}, "prospective_protocol": {"candidate_state": "research_blocked_roster_audit"}, "teams": []},
            "cbb_sos": {"meta": {"version": "thi-cbb-preseason-sos-snapshot-v1.0", "immutable": True, "status": "immutable_preseason_snapshot", "game_count": 300, "team_count": 300, "power_version": "thi-cbb-display-power-v2.0"}, "teams": sos_teams},
            "cbb_tracking": {"meta": {"projection_board_version": "board-v1"}},
            "cbb_health": {"meta": {"status": "healthy"}, "coverage": {"published_roster_players": 10}},
            "cbb_roster_audit": {"meta": {"status": "withheld"}},
            "cbb_players": {"players": [{"name": "Wrong Player"}]},
            "cbb_board": {"meta": {"version": "board-v1", "model_version": "model-v1", "game_count": 300}, "games": cbb_games},
            "cfb_board": {"games": cfb_games},
            "cfb_player_projections": {
                "meta": {
                    "version": "thi-cfb-player-projections-v0.1-research",
                    "status": "research_only",
                    "model_usage": "display_only_not_used_by_model_a",
                    "market_data_usage": "none_ingested_retained_or_displayed",
                    "projection_count": 500,
                },
                "projections": [{"athlete_id": str(index)} for index in range(500)],
            },
            "operations": {"meta": {"version": "thi-operations-readiness-v1.0"}},
        }
        with self.assertRaises(RuntimeError):
            verify(payloads)

        # Once the public payload is stripped, a stale candidate verification
        # claim must still fail independently of the public-player guard.
        payloads["cbb_health"]["coverage"]["published_roster_players"] = 0
        payloads["cbb_players"]["players"] = []
        payloads["cbb_candidate"]["meta"]["roster_verification_status"] = "provider_verified"
        payloads["cbb_candidate"]["prospective_protocol"]["candidate_state"] = "research_awaiting_preseason_freeze"
        with self.assertRaises(RuntimeError):
            verify(payloads)


if __name__ == "__main__":
    unittest.main()
