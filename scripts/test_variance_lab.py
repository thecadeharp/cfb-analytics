import unittest
from datetime import datetime, timezone
from scripts.build_rlm_monitor import analyze
from scripts.build_trends_lab import evidence_state
from scripts.build_variance_context import utc_datetime
from scripts.build_variance_prospective_tracker import build
class VarianceLabTests(unittest.TestCase):
 def test_verified_requires_positive_significant_sample(self):self.assertEqual(evidence_state(300,170,3.0),"verified")
 def test_losing_large_sample_is_failed(self):self.assertEqual(evidence_state(300,145,-7.0),"failed_hypothesis")
 def test_rlm_home_public_moves_to_away(self):
  row={"public_side":"home","public_ticket_pct":78,"opening_home_spread":-7.5,"current_home_spread":-6,"home_team":"A","away_team":"B"};alert=analyze(row);self.assertEqual(alert["sharp_team"],"B");self.assertEqual(alert["severity"],"max")
 def test_no_rlm_when_line_follows_public(self):self.assertIsNone(analyze({"public_side":"home","public_ticket_pct":80,"opening_home_spread":-7,"current_home_spread":-8}))
 def test_rank_dates_are_normalized_to_utc(self):
  self.assertEqual(utc_datetime("2025-01-06T12:00:00").tzinfo,timezone.utc)
  self.assertEqual(utc_datetime("2025-01-06T07:00:00-05:00").hour,12)
 def test_prospective_qualifier_freezes_then_settles_against_frozen_line(self):
  now=datetime(2026,10,6,12,tzinfo=timezone.utc)
  game={"game_id":1,"week":6,"start_date":"2026-10-07T23:00:00Z","status":"scheduled","home":{"team":"Home","conference":"American"},"away":{"team":"Away","conference":"ACC"},"market":{"home_spread":3.5,"total":50.5}}
  frozen=build({"frozen":[]},{"games":[game]},{"games":[]},{"games":[]},now)
  self.assertEqual(frozen["meta"]["version"],"thi-variance-prospective-v1.1")
  ids={row["system_id"] for row in frozen["frozen"]}
  self.assertIn("primetime-home-dogs",ids);self.assertIn("p4-at-g5-home-dogs",ids)
  game["market"]["home_spread"]=1.0
  results={"games":[{"game_id":1,"status":"completed","home_team":"Home","away_team":"Away","home_points":24,"away_points":21,"source":"test"}]}
  settled=build(frozen,{"games":[game]},{"games":[]},results,datetime(2026,10,8,12,tzinfo=timezone.utc))
  row=next(row for row in settled["frozen"] if row["system_id"]=="primetime-home-dogs")
  self.assertEqual(row["spread_at_freeze"],3.5);self.assertEqual(row["result"],"W")
  self.assertEqual(settled["summary"]["cfb"]["systems"]["primetime-home-dogs"]["wins"],1)
if __name__=="__main__":unittest.main()
