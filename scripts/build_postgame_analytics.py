#!/usr/bin/env python3
"""Build isolated postgame analytics from public cfbfastR data. No CFBD calls."""

from __future__ import annotations
import argparse, json, math, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pandas as pd
from build_advanced_metrics import boolean, download_dataset, normalize_row, row_value

ROOT = Path(__file__).resolve().parents[1]
SETTLED_PATH = ROOT / "data/reports/settled_results.json"
OUTPUT_PATH = ROOT / "data/postgame_analytics.json"

def num(v):
    try:
        v = float(v); return v if math.isfinite(v) else None
    except (TypeError, ValueError): return None

def rnd(v, n=3):
    v = num(v); return round(v, n) if v is not None else None

def canon(v): return re.sub(r"[^a-z0-9]+", "", str(v or "").lower())

def load(path, fallback):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return fallback

def settled_rows(payload):
    out = {}
    for row in payload.get("rows") or []:
        gid = str(row.get("game_key") or "")
        if not gid or not row.get("result_settled"): continue
        old = out.get(gid)
        if old is None or str(row.get("captured_at_utc") or "") < str(old.get("captured_at_utc") or ""):
            out[gid] = row
    return out

def raw_num(row, *names): return num(row_value(row, *names, default=None))

def enrich(row):
    p = normalize_row(row)
    text = f"{p.get('play_type','')} {p.get('play_text','')}".lower()
    p.update({
        "drive_id": str(row_value(row, "drive_id", "drive.id", default="")),
        "play_id": str(row_value(row, "id", "play_id", default="")),
        "start_score": raw_num(row, "start.pos_team_score", "pos_team_score"),
        "end_score": raw_num(row, "end.pos_team_score", "end_pos_team_score"),
        "turnover": boolean(row_value(row, "turnover", "is_turnover", default=False)) or
            any(x in text for x in ("intercepted", "fumble lost", "turnover on downs")),
    })
    return p

def avg(a): return sum(a) / len(a) if a else None

def sd(a):
    if len(a) < 2: return None
    m = avg(a); return math.sqrt(sum((x-m)**2 for x in a) / len(a))

def drives(plays, team):
    groups = {}
    for i, p in enumerate(plays):
        if canon(p.get("offense")) == canon(team):
            groups.setdefault(p.get("drive_id") or f"missing-{i}", []).append(p)
    out = []
    for rows in groups.values():
        starts = [num(p.get("start_score")) for p in rows]; starts = [x for x in starts if x is not None]
        ends = [num(p.get("end_score")) for p in rows]; ends = [x for x in ends if x is not None]
        ytg = [num(p.get("yards_to_goal")) for p in rows]; ytg = [x for x in ytg if x is not None]
        first = num(rows[0].get("yards_to_goal"))
        pts = max(0, max(ends)-min(starts)) if starts and ends else None
        out.append({"pts":pts, "opp":bool(ytg and min(ytg)<=40), "rz":bool(ytg and min(ytg)<=20),
                    "start":100-first if first is not None else None})
    def vals(key, subset=out): return [x[key] for x in subset if x[key] is not None]
    opp = [x for x in out if x["opp"]]; rz = [x for x in out if x["rz"]]
    rzpp = avg(vals("pts", rz))
    return {"drives_tracked":len(out), "points_per_drive":rnd(avg(vals("pts")),2),
            "scoring_opportunities":len(opp), "points_per_opportunity":rnd(avg(vals("pts",opp)),2),
            "red_zone_trips":len(rz), "red_zone_points_per_trip":rnd(rzpp,2),
            "red_zone_overperformance":rnd(rzpp-4.7,2) if rzpp is not None else None,
            "average_drive_start_yardline":rnd(avg(vals("start")),1)}

def team_metrics(plays, team):
    rows = [p for p in plays if canon(p.get("offense")) == canon(team)]
    comp = [p for p in rows if not p.get("garbage_time")]
    ep = [p for p in comp if num(p.get("epa")) is not None]; ev = [num(p["epa"]) for p in ep]
    early = [num(p["epa"]) for p in ep if p.get("down") in (1,2)]
    late = [num(p["epa"]) for p in ep if p.get("down") in (3,4)]
    explosive = [p for p in ep if p.get("explosive")]
    pos = sum(max(x,0) for x in ev); exp_pos = sum(max(num(p["epa"]),0) for p in explosive)
    tos = [p for p in ep if p.get("turnover")]
    result = {"plays":len(rows), "competitive_plays":len(comp), "epa_per_play":rnd(avg(ev)),
              "total_epa":rnd(sum(ev)), "success_rate":rnd(100*sum(bool(p.get("success")) for p in comp)/len(comp),1) if comp else None,
              "early_down_epa":rnd(avg(early)), "late_down_epa":rnd(avg(late)),
              "explosive_play_count":len(explosive), "explosive_epa_dependency_pct":rnd(100*exp_pos/pos,1) if pos else None,
              "turnovers":len(tos), "turnover_epa_cost":rnd(sum(abs(min(num(p["epa"]),0)) for p in tos)),
              "garbage_time_play_share_pct":rnd(100*(len(rows)-len(comp))/len(rows),1) if rows else None,
              "play_epa_volatility":rnd(sd(ev))}
    result.update(drives(plays, team)); return result

def frozen_total(row):
    a=num(row.get("public_total")); return a if a is not None else num(row.get("model_total"))

def reality(row, margin):
    h=num(row.get("home_points")); a=num(row.get("away_points"))
    if h is None or a is None or margin is None: return "INSUFFICIENT DATA"
    actual=h-a
    if actual*margin < 0: return "MISLEADING FINAL"
    gap=abs(actual-margin)
    if gap>=14: return "CLOSER THAN THE SCORE" if abs(actual)>abs(margin) else "MORE DECISIVE THAN THE SCORE"
    if gap>=7: return "SCORE OVERSTATED THE GAP" if abs(actual)>abs(margin) else "SCORE UNDERSTATED THE GAP"
    return "FINAL MATCHED THE PERFORMANCE"

def build(row, plays, stamp):
    away=str(row.get("away_team") or ""); home=str(row.get("home_team") or "")
    am=team_metrics(plays,away); hm=team_metrics(plays,home)
    if not am["competitive_plays"] or not hm["competitive_plays"]: return None
    margin=rnd(num(hm["total_epa"])-num(am["total_epa"]))
    hp=100/(1+math.exp(-margin/7)) if margin is not None else None
    total=frozen_total(row); score=None
    if total is not None and margin is not None:
        m=max(-35,min(35,margin)); score={"away_points":rnd(max(0,(total-m)/2),1),"home_points":rnd(max(0,(total+m)/2),1)}
    hc=num(hm.get("turnover_epa_cost")); ac=num(am.get("turnover_epa_cost"))
    return {"game_id":str(row.get("game_key")),"week":row.get("week"),"away_team":away,"home_team":home,
            "availability":"available","source":"SportsDataverse cfbfastR ESPN-derived play-by-play","generated_at_utc":stamp,
            "headline":{"home_win_expectancy_pct":rnd(hp,1),"away_win_expectancy_pct":rnd(100-hp,1) if hp is not None else None,
                        "adjusted_score":score,"reality_check":reality(row,margin)},
            "teams":{"away":am,"home":hm},
            "comparisons":{"epa_margin_home":margin,"turnover_epa_swing_home":rnd(ac-hc) if hc is not None and ac is not None else None},
            "methodology":{"win_expectancy":"Logistic transform of non-garbage-time total EPA margin.",
                           "adjusted_score":"Frozen pregame THI total split by postgame EPA margin."}}

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--refresh",action="store_true"); args=parser.parse_args()
    eligible=settled_rows(load(SETTLED_PATH,{}))
    if not eligible: raise RuntimeError("No settled games are eligible")
    existing=load(OUTPUT_PATH,{"games":{}}); games={} if args.refresh else dict(existing.get("games") or {})
    wanted=set(eligible) if args.refresh else set(eligible)-set(games)
    if wanted:
        frame=download_dataset()
        if "status_type_completed" in frame.columns: frame=frame[frame["status_type_completed"].map(boolean)]
        frame=frame[frame["game_id"].astype(str).isin(wanted)]
        grouped={}
        for _,raw in frame.iterrows():
            p=enrich(raw)
            if p.get("epa") is not None: grouped.setdefault(str(p.get("game_id")),[]).append(p)
        stamp=datetime.now(timezone.utc).isoformat()
        for gid in sorted(wanted):
            game=build(eligible[gid],grouped.get(gid,[]),stamp)
            if game: games[gid]=game; print(f"Built {gid}: {game['away_team']} at {game['home_team']}")
            else: print(f"WARNING: public play-by-play is not available yet for {gid}")
    output={"meta":{"version":"postgame-analytics-v2-no-cfbd","uses_cfbd":False,"model_a_affected":False,
                    "source":"SportsDataverse cfbfastR ESPN-derived play-by-play","generated_at_utc":datetime.now(timezone.utc).isoformat(),
                    "eligible_games":len(eligible),"games_available":len(games)},"games":games}
    OUTPUT_PATH.write_text(json.dumps(output,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} with {len(games)} game(s). No CFBD calls were made.")

if __name__ == "__main__": main()
