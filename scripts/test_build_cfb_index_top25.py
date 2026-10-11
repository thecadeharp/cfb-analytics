import copy
import unittest

from build_cfb_index_top25 import build_index


def fixture():
    names = [f"Team {index:03d}" for index in range(100)]
    metrics = {
        "meta": {"year": 2026, "through_week": 6},
        "teams": {
            name: {
                "conference": "Test",
                "record": {"wins": index % 7, "losses": 6 - index % 7},
                "power_rating": float(index),
            }
            for index, name in enumerate(names)
        },
    }
    power = {
        "meta": {"through_week": 6},
        "teams": [
            {
                "team": name,
                "result_elo_contribution": float(index),
                "roster_contribution": float(1000 - index),
            }
            for index, name in enumerate(names)
        ],
    }
    observed = {
        "meta": {"through_week": 6},
        "teams": {
            name: {"ratings": {"net": {"value": float(index)}}}
            for index, name in enumerate(names)
        },
    }
    schedule = {"games": []}
    return metrics, power, observed, schedule


class IndexTests(unittest.TestCase):
    def test_roster_contribution_cannot_change_index(self):
        inputs = fixture()
        first = build_index(*inputs)
        changed = copy.deepcopy(inputs)
        for index, row in enumerate(changed[1]["teams"]):
            row["roster_contribution"] = index * 1_000_000
        second = build_index(*changed)
        self.assertEqual(
            [(row["team"], row["score"]) for row in first["teams"]],
            [(row["team"], row["score"]) for row in second["teams"]],
        )
        self.assertFalse(first["meta"]["roster_inputs"])

    def test_week_cutoffs_must_match(self):
        inputs = list(fixture())
        inputs[2]["meta"]["through_week"] = 5
        with self.assertRaisesRegex(ValueError, "share a completed-week cutoff"):
            build_index(*inputs)


if __name__ == "__main__":
    unittest.main()
