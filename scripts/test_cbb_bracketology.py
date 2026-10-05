#!/usr/bin/env python3

import unittest

from scripts.build_cbb_bracketology import build_bracketology


def priors(conferences: int = 32, teams_each: int = 3) -> dict:
    teams = []
    team_id = 1
    for conference in range(conferences):
        for member in range(teams_each):
            teams.append({
                "team_id": team_id,
                "team": f"Team {team_id}",
                "conference": {"id": conference + 1, "name": f"Conference {conference + 1}", "abbreviation": f"C{conference + 1}"},
                "prior_net": 50 - member * 20 - conference / 10,
            })
            team_id += 1
    return {"meta": {"model_version": "thi-cbb-walk-forward-v0.6-research", "season": 2027}, "teams": teams}


class CbbBracketologyTests(unittest.TestCase):
    def test_builds_complete_field_first_four_and_bubble(self):
        payload = build_bracketology(priors())
        self.assertEqual(payload["meta"]["version"], "thi-cbb-bracketology-v0.1")
        self.assertEqual(len(payload["field"]), 68)
        self.assertEqual(sum(row["bid_type"] == "automatic" for row in payload["field"]), 32)
        self.assertEqual(sum(row["bid_type"] == "at_large" for row in payload["field"]), 36)
        self.assertEqual(len(payload["first_four"]), 4)
        self.assertEqual(sum(len(row["teams"]) for row in payload["first_four"]), 8)
        self.assertEqual(sum(row["first_four"] for row in payload["field"]), 8)
        self.assertEqual(len(payload["bubble"]["first_four_out"]), 4)
        self.assertEqual(len(payload["bubble"]["next_four_out"]), 4)
        self.assertEqual(set(payload["regions"]), {"East", "South", "Midwest", "West"})
        self.assertTrue(all(len(rows) == 16 for rows in payload["regions"].values()))
        self.assertTrue(all({row["seed"] for row in rows} == set(range(1, 17)) for rows in payload["regions"].values()))

    def test_requires_current_model_and_32_conferences(self):
        bad_model = priors()
        bad_model["meta"]["model_version"] = "old"
        with self.assertRaisesRegex(RuntimeError, "v0.6"):
            build_bracketology(bad_model)
        with self.assertRaisesRegex(RuntimeError, "32 conferences"):
            build_bracketology(priors(conferences=31))


if __name__ == "__main__":
    unittest.main()
