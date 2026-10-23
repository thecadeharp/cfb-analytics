import unittest

from scripts.import_circa_line_sheet import build_state, parse_current, parse_opening


def board():
    return {"games": [
        {"game_id": 1, "week": 8, "start_date": "2026-10-24T00:30:00Z", "away": {"team": "Army"}, "home": {"team": "Tulsa"}},
        {"game_id": 2, "week": 8, "start_date": "2026-10-24T01:00:00Z", "away": {"team": "Air Force"}, "home": {"team": "Wyoming"}},
    ]}


class CircaSheetImportTests(unittest.TestCase):
    def test_line_flip_is_interpreted_from_named_team(self):
        opening, issue = parse_opening("ARMY -1.5 V TULSA (53.5) (FRI)")
        self.assertIsNone(issue)
        current, source = parse_current(["", "TULSA -1.5 LINE FLIP", ""], opening, 1, 2)
        self.assertEqual(current, 1.5)
        self.assertEqual(source, "TULSA -1.5 LINE FLIP")

    def test_total_is_not_mistaken_for_spread(self):
        opening, _ = parse_opening("ECU -4.5 v UAB (THURS) 52")
        current, _ = parse_current(["", "48.5", ""], opening, 1, 2)
        self.assertIsNone(current)

    def test_sub_three_point_move_does_not_qualify(self):
        empty = [["Team & Opening Number (circa)", "Change (3+ pts)", "Friday/Saturday Number"]]
        tabs = {week: list(empty) for week in range(13)}
        tabs[8].append(["AF -7.5 V WYO (43.5)", "-5.5 45.5", ""])
        state = build_state(board(), tabs, observed_at="2026-10-22T12:00:00Z")
        self.assertEqual(state["qualifiers"], [])

    def test_only_exact_three_point_circa_move_qualifies(self):
        empty = [["Team & Opening Number (circa)", "Change (3+ pts)", "Friday/Saturday Number"]]
        tabs = {week: list(empty) for week in range(13)}
        tabs[8].append(["ARMY -1.5 V TULSA (53.5)", "TULSA -1.5 LINE FLIP", ""])
        state = build_state(board(), tabs, observed_at="2026-10-22T12:00:00Z")
        row = state["qualifiers"][0]
        self.assertEqual(row["opening_home_spread"], 1.5)
        self.assertEqual(row["current_home_spread"], -1.5)
        self.assertEqual(row["sharp_book"], "circa")
        self.assertTrue(row["source_verified"])
        self.assertFalse(state["meta"]["write_access_used"])

    def test_first_seen_time_is_immutable(self):
        empty = [["Team & Opening Number (circa)", "Change (3+ pts)", "Friday/Saturday Number"]]
        tabs = {week: list(empty) for week in range(13)}
        tabs[8].append(["ARMY -1.5 V TULSA (53.5)", "TULSA -1.5 LINE FLIP", ""])
        initial = build_state(board(), tabs, observed_at="2026-10-22T12:00:00Z")
        refreshed = build_state(board(), tabs, old=initial, observed_at="2026-10-22T13:00:00Z")
        self.assertEqual(refreshed["qualifiers"][0]["first_seen_at_utc"], "2026-10-22T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
