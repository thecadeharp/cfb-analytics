import unittest

from build_cfb_public_rankings import parse


def fixture(count=25):
    return {
        "requestedSeason": {"year": 2026},
        "latestWeek": {"number": 7},
        "rankings": [
            {
                "name": "AP Top 25",
                "ranks": [
                    {
                        "current": rank,
                        "previous": rank + 1,
                        "points": 1000 - rank,
                        "firstPlaceVotes": 1 if rank == 1 else 0,
                        "recordSummary": "6-0",
                        "date": "2026-10-11T07:00Z",
                        "lastUpdated": "2026-10-11T21:07Z",
                        "team": {
                            "location": f"Team {rank}",
                            "abbreviation": f"T{rank}",
                            "groups": {"shortName": "Test"},
                        },
                    }
                    for rank in range(1, count + 1)
                ],
            }
        ],
    }


class PublicRankingsTests(unittest.TestCase):
    def test_parses_complete_poll_and_marks_display_only(self):
        output = parse(fixture())
        self.assertEqual(len(output["teams"]), 25)
        self.assertEqual(output["teams"][0]["team"], "Team 1")
        self.assertEqual(output["meta"]["model_usage"], "display_and_sort_context_only")
        self.assertFalse(output["meta"]["model_a_touched"])

    def test_rejects_incomplete_poll(self):
        with self.assertRaisesRegex(ValueError, "complete AP Top 25"):
            parse(fixture(24))


if __name__ == "__main__":
    unittest.main()
