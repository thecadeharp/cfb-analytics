import unittest

from scripts.build_coach_ats_trends import canonical_team, parse_teamrankings_table


class CoachATSTrendsTests(unittest.TestCase):
    def test_team_name_normalization_matches_public_abbreviations(self):
        pairs = [
            ("Ohio St", "Ohio State"),
            ("S Florida", "South Florida"),
            ("C Michigan", "Central Michigan"),
            ("J Madison", "James Madison"),
            ("Florida Intl", "Florida International"),
            ("UMass", "Massachusetts"),
            ("Mississippi", "Ole Miss"),
        ]
        for public_name, internal_name in pairs:
            self.assertEqual(canonical_team(public_name), canonical_team(internal_name))

    def test_public_table_parser_preserves_pushes_and_cover_rate(self):
        html = """
        <table class="tr-table datatable"><tbody><tr>
          <td><a href="/team">Louisiana</a></td><td>4-1-1</td>
          <td>80.0%</td><td>8.0</td><td>+6.6</td>
        </tr></tbody></table>
        """
        row = parse_teamrankings_table(html)[canonical_team("Louisiana")]
        self.assertEqual(row["record"], "4-1-1")
        self.assertEqual(row["games"], 6)
        self.assertEqual(row["cover_pct_ex_pushes"], 80.0)


if __name__ == "__main__":
    unittest.main()
