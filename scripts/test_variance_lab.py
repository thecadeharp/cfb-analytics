import unittest
from datetime import timezone
from scripts.build_rlm_monitor import analyze
from scripts.build_trends_lab import evidence_state
from scripts.build_variance_context import utc_datetime
class VarianceLabTests(unittest.TestCase):
 def test_verified_requires_positive_significant_sample(self):self.assertEqual(evidence_state(300,170,3.0),"verified")
 def test_losing_large_sample_is_failed(self):self.assertEqual(evidence_state(300,145,-7.0),"failed_hypothesis")
 def test_rlm_home_public_moves_to_away(self):
  row={"public_side":"home","public_ticket_pct":78,"opening_home_spread":-7.5,"current_home_spread":-6,"home_team":"A","away_team":"B"};alert=analyze(row);self.assertEqual(alert["sharp_team"],"B");self.assertEqual(alert["severity"],"max")
 def test_no_rlm_when_line_follows_public(self):self.assertIsNone(analyze({"public_side":"home","public_ticket_pct":80,"opening_home_spread":-7,"current_home_spread":-8}))
 def test_rank_dates_are_normalized_to_utc(self):
  self.assertEqual(utc_datetime("2025-01-06T12:00:00").tzinfo,timezone.utc)
  self.assertEqual(utc_datetime("2025-01-06T07:00:00-05:00").hour,12)
if __name__=="__main__":unittest.main()
