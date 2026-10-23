import unittest
from datetime import datetime, timezone
from scripts.build_rlm_monitor import analyze,select_authoritative_rows,sharp_line_moves,steam_reversal_alerts,upcoming_circa_moves
from scripts.poll_free_sharp_lines import merge_events
from scripts.poll_owls_rlm import build_capture
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
 def test_cfb_three_point_move_triggers_opposite_side(self):
  moves=[{"sport":"cfb","event_id":"1","away_team":"Away","home_team":"Home","opening_home_spread":-7,"current_home_spread":-10,"line_delta":-3,"sharp_book":"pinnacle"}]
  alert=steam_reversal_alerts(moves)[0]
  self.assertEqual(alert["fade_team"],"Away");self.assertEqual(alert["fade_spread"],10);self.assertEqual(alert["system_id"],"steam-reversal")
 def test_steam_reversal_excludes_cbb_and_sub_three_moves(self):
  moves=[{"sport":"cbb","opening_home_spread":-7,"current_home_spread":-10,"line_delta":-3},{"sport":"cfb","opening_home_spread":-7,"current_home_spread":-9.5,"line_delta":-2.5}]
  self.assertEqual(steam_reversal_alerts(moves),[])
 def test_only_verified_future_circa_rows_reach_official_monitor(self):
  now=datetime(2026,10,22,tzinfo=timezone.utc)
  state={"qualifiers":[
   {"sport":"cfb","sharp_book":"circa","source_verified":True,"start_date":"2026-10-24T00:30:00Z","event_id":"circa"},
   {"sport":"cfb","sharp_book":"pinnacle","source_verified":True,"start_date":"2026-10-24T00:30:00Z","event_id":"pin"},
   {"sport":"cfb","sharp_book":"circa","source_verified":True,"start_date":"2026-10-20T00:30:00Z","event_id":"past"},
  ]}
  self.assertEqual([row["event_id"] for row in upcoming_circa_moves(state,now)], ["circa"])
 def test_steam_reversal_holds_public_label_when_sourced_availability_overlaps(self):
  moves=[{"sport":"cfb","event_id":"1","away_team":"Mississippi State Bulldogs","home_team":"LSU Tigers","opening_home_spread":-10.5,"current_home_spread":-16,"line_delta":-5.5,"sharp_book":"pinnacle"}]
  availability={"teams":{"Mississippi State":[{"player":"Kamario Taylor","position":"QB","status":"Questionable","text":"Quarterback listed questionable.","verified_at_utc":"2026-10-15T20:00:00Z","valid_until_utc":"2026-10-18T20:00:00Z","source_url":"https://example.com/report","market_context_relevant":True,"withhold_public_signal":True}]}}
  alert=steam_reversal_alerts(moves,availability=availability,now=datetime(2026,10,16,tzinfo=timezone.utc))[0]
  self.assertEqual(alert["context_status"],"material_availability_overlap")
  self.assertEqual(alert["action_status"],"context_hold")
  self.assertEqual(alert["context_flags"][0]["position"],"QB")
 def test_owls_capture_joins_dk_splits_to_pinnacle(self):
  odds={"data":{"pinnacle":[{"event_id":"ncaaf:Away@Home-20261010","commence_time":"2026-10-10T23:00:00Z","away_team":"Away","home_team":"Home","bookmakers":[{"key":"pinnacle","last_update":"2026-10-08T12:00:00Z","markets":[{"key":"spreads","outcomes":[{"name":"Away","point":7.0,"price":-110},{"name":"Home","point":-7.0,"price":-110}]}]}]}]}}
  splits={"data":[{"event_id":"ncaaf:Away@Home-20261010","away_team":"Away","home_team":"Home","splits":[{"book":"dk","title":"DraftKings","as_of":"2026-10-08T12:03:00Z","spread":{"away_line":7.0,"home_line":-7.0,"away_bets_pct":72,"home_bets_pct":28,"away_handle_pct":64,"home_handle_pct":36}}]}]}
  state,rows=build_capture({"events":{}},"ncaaf",odds,splits,"2026-10-08T12:04:00Z")
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]["public_side"],"away")
  self.assertEqual(rows[0]["public_ticket_pct"],72);self.assertEqual(rows[0]["sharp_book"],"pinnacle")
  self.assertIn("cfb:ncaaf:Away@Home-20261010",state["events"])
 def test_owls_capture_rejects_stale_pair(self):
  odds={"data":{"pinnacle":[{"event_id":"x","away_team":"Away","home_team":"Home","bookmakers":[{"key":"pinnacle","last_update":"2026-10-08T12:00:00Z","markets":[{"key":"spreads","outcomes":[{"name":"Home","point":-3}]}]}]}]}}
  splits={"data":[{"event_id":"x","away_team":"Away","home_team":"Home","splits":[{"book":"dk","as_of":"2026-10-08T12:10:01Z","spread":{"away_bets_pct":60,"home_bets_pct":40}}]}]}
  _,rows=build_capture({"events":{}},"ncaaf",odds,splits,"2026-10-08T12:11:00Z")
  self.assertEqual(rows,[])
 def test_rank_dates_are_normalized_to_utc(self):
  self.assertEqual(utc_datetime("2025-01-06T12:00:00").tzinfo,timezone.utc)
  self.assertEqual(utc_datetime("2025-01-06T07:00:00-05:00").hour,12)
 def test_prospective_qualifier_freezes_then_settles_against_frozen_line(self):
  now=datetime(2026,10,6,12,tzinfo=timezone.utc)
  game={"game_id":1,"week":6,"start_date":"2026-10-07T23:00:00Z","status":"scheduled","home":{"team":"Home","conference":"American"},"away":{"team":"Away","conference":"ACC"},"market":{"home_spread":3.5,"total":50.5}}
  frozen=build({"frozen":[]},{"games":[game]},{"games":[]},{"games":[]},now)
  self.assertEqual(frozen["meta"]["version"],"thi-variance-prospective-v1.2")
  ids={row["system_id"] for row in frozen["frozen"]}
  self.assertIn("primetime-home-dogs",ids);self.assertIn("p4-at-g5-home-dogs",ids)
  game["market"]["home_spread"]=1.0
  results={"games":[{"game_id":1,"status":"completed","home_team":"Home","away_team":"Away","home_points":24,"away_points":21,"source":"test"}]}
  settled=build(frozen,{"games":[game]},{"games":[]},results,datetime(2026,10,8,12,tzinfo=timezone.utc))
  row=next(row for row in settled["frozen"] if row["system_id"]=="primetime-home-dogs")
  self.assertEqual(row["spread_at_freeze"],3.5);self.assertEqual(row["result"],"W")
  self.assertEqual(settled["summary"]["cfb"]["systems"]["primetime-home-dogs"]["wins"],1)
 def test_steam_reversal_freezes_fade_side_and_grades_it(self):
  now=datetime(2026,10,6,12,tzinfo=timezone.utc)
  game={"game_id":2,"week":6,"start_date":"2026-10-07T23:00:00Z","status":"scheduled","home":{"team":"Home","conference":"SEC"},"away":{"team":"Away","conference":"ACC"},"market":{"home_spread":-10,"total":50}}
  monitor={"steam_reversal_alerts":[{"sport":"cfb","event_id":"market-2","away_team":"Away","home_team":"Home","opening_home_spread":-7,"current_home_spread":-10,"movement_points":3,"fade_side":"away","fade_team":"Away","sharp_book":"circa"}]}
  frozen=build({"frozen":[]},{"games":[game]},{"games":[]},{"games":[]},now,monitor)
  row=next(row for row in frozen["frozen"] if row["system_id"]=="steam-reversal")
  self.assertEqual(row["tracked_team"],"Away");self.assertEqual(row["spread_at_freeze"],-10)
  monitor["steam_reversal_alerts"][0].update({"current_home_spread":-12,"context_status":"material_availability_overlap","action_status":"context_hold","context_flags":[{"team":"Home","player":"Starting QB"}]})
  refreshed=build(frozen,{"games":[game]},{"games":[]},{"games":[]},now,monitor)
  row=next(row for row in refreshed["frozen"] if row["system_id"]=="steam-reversal")
  self.assertEqual(row["spread_at_freeze"],-10)
  self.assertEqual(row["public_action_status"],"context_hold")
  self.assertEqual(row["latest_context_flags"][0]["player"],"Starting QB")
  results={"games":[{"game_id":2,"status":"completed","home_team":"Home","away_team":"Away","home_points":27,"away_points":20,"source":"test"}]}
  settled=build(refreshed,{"games":[game]},{"games":[]},results,datetime(2026,10,8,12,tzinfo=timezone.utc),monitor)
  row=next(row for row in settled["frozen"] if row["system_id"]=="steam-reversal")
  self.assertEqual(row["result"],"W")
 def test_retired_pinnacle_steam_rows_are_removed_from_official_ledger(self):
  old={"frozen":[{"freeze_id":"cfb:2:steam-reversal","sport":"cfb","game_id":"2","system_id":"steam-reversal","sharp_book":"pinnacle","result":"pending"}]}
  rebuilt=build(old,{"games":[]},{"games":[]},{"games":[]},datetime(2026,10,8,12,tzinfo=timezone.utc),{"steam_reversal_alerts":[]})
  self.assertEqual(rebuilt["frozen"],[])
if __name__=="__main__":unittest.main()
