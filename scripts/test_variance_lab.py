import unittest
from datetime import datetime, timezone
from scripts.build_rlm_monitor import analyze,select_authoritative_rows,sharp_line_moves
from scripts.poll_free_sharp_lines import merge_events
from scripts.build_trends_lab import evidence_state
from scripts.build_variance_context import utc_datetime
from scripts.build_variance_prospective_tracker import build
class VarianceLabTests(unittest.TestCase):
 def test_large_positive_sample_remains_developing_without_full_gate(self):self.assertEqual(evidence_state(300,170,3.0),"developing")
 def test_verified_requires_full_validation_gate(self):self.assertEqual(evidence_state(300,170,3.0,{"passed":True}),"verified")
 def test_losing_large_sample_is_failed(self):self.assertEqual(evidence_state(300,145,-7.0),"failed_hypothesis")
 def test_rlm_home_public_moves_to_away(self):
  row={"sharp_book":"pinnacle","public_side":"home","public_ticket_pct":78,"opening_home_spread":-7.5,"current_home_spread":-6,"home_team":"A","away_team":"B"};alert=analyze(row);self.assertEqual(alert["sharp_team"],"B");self.assertEqual(alert["severity"],"max")
 def test_no_rlm_when_line_follows_public(self):self.assertIsNone(analyze({"sharp_book":"pinnacle","public_side":"home","public_ticket_pct":80,"opening_home_spread":-7,"current_home_spread":-8}))
 def test_recreational_book_cannot_trigger_sharp_alert(self):self.assertIsNone(analyze({"sharp_book":"draftkings","public_side":"home","public_ticket_pct":80,"opening_home_spread":-7,"current_home_spread":-6}))
 def test_pinnacle_wins_over_betonline_for_same_event(self):
  rows=[{"sport":"cfb","event_id":"1","sharp_book":"betonline","captured_at_utc":"2026-01-01T12:05:00Z"},{"sport":"cfb","event_id":"1","sharp_book":"pinnacle","captured_at_utc":"2026-01-01T12:00:00Z"}]
  self.assertEqual(select_authoritative_rows(rows)[0]["sharp_book"],"pinnacle")
 def test_free_pinnacle_capture_preserves_open_and_updates_current(self):
  payload=[{"id":"game-1","commence_time":"2026-10-08T23:00:00Z","away_team":"Away","home_team":"Home","bookmakers":[{"key":"pinnacle","last_update":"2026-10-07T12:00:00Z","markets":[{"key":"spreads","outcomes":[{"name":"Away","point":3.5},{"name":"Home","point":-3.5}]}]}]}]
  state,changes=merge_events({"events":{}},"cfb",payload,"2026-10-07T12:00:00Z")
  self.assertEqual(len(changes),1)
  payload[0]["bookmakers"][0]["markets"][0]["outcomes"][1]["point"]=-2.5
  state,changes=merge_events(state,"cfb",payload,"2026-10-07T16:00:00Z")
  row=state["events"]["cfb:game-1"]
  self.assertEqual(row["opening_home_spread"],-3.5);self.assertEqual(row["current_home_spread"],-2.5)
  self.assertEqual(len(changes),1)
 def test_free_line_move_is_not_labeled_rlm(self):
  state={"events":{"cfb:1":{"sport":"cfb","event_id":"1","away_team":"Away","home_team":"Home","opening_home_spread":-3.5,"current_home_spread":-2.5}}}
  move=sharp_line_moves(state)[0]
  self.assertEqual(move["movement_toward_team"],"Away")
  self.assertNotIn("public_ticket_pct",move)
  self.assertIn("not an RLM",move["definition"])
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
