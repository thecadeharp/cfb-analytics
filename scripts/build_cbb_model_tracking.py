#!/usr/bin/env python3
"""Grade frozen THI CBB projections without rewriting the original forecast."""
from __future__ import annotations
import argparse, json, math, tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
VERSION="thi-cbb-model-tracking-v0.3"
REQUIRED_BOARD_VERSION="thi-cbb-projection-board-v0.5"
EASTERN=ZoneInfo("America/New_York")

def finite(value:Any)->float|None:
    try:
        number=float(value); return number if math.isfinite(number) else None
    except (TypeError,ValueError): return None

def parse_time(value:Any)->datetime|None:
    try: return datetime.fromisoformat(str(value or "").replace("Z","+00:00"))
    except ValueError: return None

def calendar_fields(value:Any)->dict[str,str|None]:
    started=parse_time(value)
    if not started: return {"game_date_et":None,"calendar_week_start_et":None,"calendar_month_et":None}
    local=started.astimezone(EASTERN); game_date=local.date(); week_start=game_date-timedelta(days=game_date.weekday())
    return {"game_date_et":game_date.isoformat(),"calendar_week_start_et":week_start.isoformat(),"calendar_month_et":game_date.strftime("%Y-%m")}

def is_final(game): return str(game.get("status") or "").lower().replace("_","") in {"final","completed","complete"}
def result_label(value): return "win" if value>.01 else "loss" if value<-.01 else "push"

def summarize(rows):
    wins=sum(r["result"]=="win" for r in rows); losses=sum(r["result"]=="loss" for r in rows); pushes=sum(r["result"]=="push" for r in rows)
    clv=[finite(r.get("clv")) for r in rows]; clv=[v for v in clv if v is not None]; decisions=wins+losses
    return {"games":len(rows),"wins":wins,"losses":losses,"pushes":pushes,"hit_rate":round(100*wins/decisions,2) if decisions else None,"average_clv":round(sum(clv)/len(clv),3) if clv else None,"beat_close_pct":round(100*sum(v>0 for v in clv)/len(clv),2) if clv else None,"closing_line_games":len(clv)}

def summarize_moneylines(rows):
    base=summarize(rows); roi=[finite(r.get("roi_units")) for r in rows]; roi=[v for v in roi if v is not None]
    base.update({"roi_units":round(sum(roi),3) if roi else None,"roi_pct":round(100*sum(roi)/len(roi),2) if roi else None})
    return base

def signal_tier(edge):
    value=abs(edge)
    return "outlier" if value>=10 else "material" if value>=7 else "play" if value>=4 else "small" if value>=2 else "aligned"
def total_tier(edge): return "total_watch" if abs(edge)>=7 else "total_lean" if abs(edge)>=4 else None

def history_rows(history,game_id):
    payload=((history or {}).get("games") or {}).get(str(game_id))
    return payload if isinstance(payload,list) else payload.get("snapshots",[]) if isinstance(payload,dict) else []
def market_points(game,history):
    snapshots=history_rows(history,game.get("game_id")); first=snapshots[0] if snapshots else (game.get("market") or {}); last=snapshots[-1] if snapshots else {}
    def normalized(snapshot):
        row=dict(snapshot or {}); reference=row.get("reference_moneyline") or {}; home=finite(reference.get("home_price")); away=finite(reference.get("away_price")); spread=finite(row.get("consensus_home_spread"))
        if spread is not None and home is not None and away is not None and ((home<0<away and spread>0) or (away<0<home and spread<0)): row["consensus_home_spread"]=-spread
        return row
    return normalized(first), normalized(game.get("closing_market") or last or game.get("market") or {})

def moneyline_market_points(game,history):
    rows=[dict(row) for row in history_rows(history,game.get("game_id")) if isinstance(row,dict)]
    current=dict(game.get("market") or {})
    if current: rows.append(current)
    eligible=[row for row in rows if row.get("moneyline_policy_version")=="relative-market-fit-v1-2026-11-25" and (finite(row.get("moneyline_book_count")) or 0)>=2 and isinstance(row.get("reference_moneyline"),dict)]
    return (eligible[0],eligible[-1]) if eligible else ({},{})

def moneyline_decision(game,first,close,actual):
    projection=game.get("projection") or {}; raw=finite(projection.get("home_win_probability"))
    if raw is None: return None
    home_probability=raw/100 if raw>1 else raw; side="home" if home_probability>=.5 else "away"; probability=home_probability if side=="home" else 1-home_probability
    reference=first.get("reference_moneyline") or {}; price=finite(reference.get(f"{side}_price")); market_probability=finite((reference.get("no_vig_probability") or {}).get(side)); margin=finite(projection.get("home_margin")); team_margin=margin if side=="home" else -margin if margin is not None else None
    edge=probability-market_probability if market_probability is not None else None
    favorite=price is not None and -185<=price<=-100; dog=price is not None and 100<=price<=250 and probability>=.5 and team_margin is not None and team_margin>=0
    if not (favorite or dog) or edge is None or edge<.03: return None
    won=actual>0 if side=="home" else actual<0; result="win" if won else "loss" if actual!=0 else "push"; roi=(price/100 if price>0 else 100/abs(price)) if won else -1 if actual!=0 else 0
    closing=close.get("reference_moneyline") or {}; closing_price=finite(closing.get(f"{side}_price")); closing_probability=finite((closing.get("no_vig_probability") or {}).get(side)); clv=100*(closing_probability-market_probability) if closing_probability is not None else None
    team=(game.get(side) or {}).get("team")
    return {"pick_team":team,"side":side,"price":int(price),"model_probability":round(probability,5),"market_probability":round(market_probability,5),"probability_edge":round(edge,5),"closing_price":int(closing_price) if closing_price is not None else None,"closing_probability":round(closing_probability,5) if closing_probability is not None else None,"clv":round(clv,3) if clv is not None else None,"beat_close":clv>0 if clv is not None else None,"result":result,"roi_units":round(roi,4),"policy_version":"relative-market-fit-v1-2026-11-25"}

def projection_accuracy(games):
    margins=[]; totals=[]; winners=[]
    for game in games:
        hs=finite((game.get("home") or {}).get("score")); aw=finite((game.get("away") or {}).get("score")); p=game.get("projection") or {}; pm=finite(p.get("home_margin")); pt=finite(p.get("total"))
        if hs is None or aw is None: continue
        actual=hs-aw
        if pm is not None: margins.append(abs(actual-pm)); winners.append((actual>=0)==(pm>=0))
        if pt is not None: totals.append(abs(hs+aw-pt))
    return {"margin_mae":round(sum(margins)/len(margins),3) if margins else None,"total_mae":round(sum(totals)/len(totals),3) if totals else None,"winner_accuracy":round(100*sum(winners)/len(winners),2) if winners else None,"games":len(margins)}

def build_tracking(board,market_history=None):
    version=board.get("meta",{}).get("version")
    if version!=REQUIRED_BOARD_VERSION: raise RuntimeError(f"tracking requires {REQUIRED_BOARD_VERSION}")
    finals=[g for g in board.get("games") or [] if is_final(g) and g.get("projection")]
    dates=[parse_time(g.get("start_date")) for g in finals]; dates=[d for d in dates if d]; season_start=min(dates) if dates else None
    spreads=[]; totals=[]; moneylines=[]; su=[]
    for game in finals:
        hs=finite((game.get("home") or {}).get("score")); aw=finite((game.get("away") or {}).get("score"))
        if hs is None or aw is None: continue
        p=game.get("projection") or {}; pm=finite(p.get("home_margin")); pt=finite(p.get("total")); actual=hs-aw; actual_total=hs+aw; started=parse_time(game.get("start_date")); week=1+max(0,(started.date()-season_start.date()).days//7) if started and season_start else 1
        common={"game_id":game.get("game_id"),"start_date":game.get("start_date"),**calendar_fields(game.get("start_date")),"week":week,"away_team":(game.get("away") or {}).get("team"),"home_team":(game.get("home") or {}).get("team"),"neutral_site":bool(game.get("neutral_site")),"final_score":f"{int(aw)}-{int(hs)}"}
        if pm is not None: su.append({**common,"result":"win" if ((pm>=0)==(actual>=0)) else "loss","margin_error":round(abs(actual-pm),3),"total_error":round(abs(actual_total-pt),3) if pt is not None else None})
        first,close=market_points(game,market_history); opening=finite(first.get("consensus_home_spread")); closing=finite(close.get("consensus_home_spread"))
        ml_first,ml_close=moneyline_market_points(game,market_history); ml=moneyline_decision(game,ml_first,ml_close,actual)
        if ml: moneylines.append({**common,**ml})
        if opening is not None and pm is not None:
            edge=pm+opening; pick_home=edge>=0; line=opening if pick_home else -opening; close_line=(closing if pick_home else -closing) if closing is not None else None; grade=(actual if pick_home else -actual)+line
            spreads.append({**common,"pick_team":((game.get("home") if pick_home else game.get("away")) or {}).get("team"),"pregame_line":round(line,2),"closing_line":round(close_line,2) if close_line is not None else None,"clv":round(line-close_line,2) if close_line is not None else None,"result":result_label(grade),"result_margin":round(grade,2),"signal_tier":signal_tier(edge),"confidence":p.get("signal_confidence"),"model_edge":round(abs(edge),2),"qualified_signal":bool(p.get("spread_signal_eligible"))})
        opening_total=finite(first.get("consensus_total")); closing_total=finite(close.get("consensus_total"))
        if opening_total is not None and pt is not None:
            edge=pt-opening_total; tier=total_tier(edge)
            if tier:
                over=edge>=0; grade=actual_total-opening_total; total_clv=((closing_total-opening_total) if over else (opening_total-closing_total)) if closing_total is not None else None
                totals.append({**common,"pick":"over" if over else "under","pregame_total":round(opening_total,2),"closing_total":round(closing_total,2) if closing_total is not None else None,"clv":round(total_clv,2) if total_clv is not None else None,"result":result_label(grade if over else -grade),"result_margin":round(grade if over else -grade,2),"signal_tier":tier,"model_edge":round(abs(edge),2),"final_total":round(actual_total,2),"qualified_signal":bool(p.get("totals_signal_eligible"))})
    spreads.sort(key=lambda r:str(r.get("start_date") or ""),reverse=True); totals.sort(key=lambda r:str(r.get("start_date") or ""),reverse=True); moneylines.sort(key=lambda r:str(r.get("start_date") or ""),reverse=True)
    weeks=defaultdict(lambda:{"su":[],"spread":[],"totals":[]})
    for name,rows in (("su",su),("spread",spreads),("totals",totals)):
        for row in rows: weeks[row["week"]][name].append(row)
    weekly=[]
    for week,rows in sorted(weeks.items()):
        week_games=[g for g in finals if (1+max(0,((parse_time(g.get("start_date")) or season_start).date()-season_start.date()).days//7) if season_start else 1)==week]
        weekly.append({"week":week,"finals":len(week_games),"straight_up":summarize(rows["su"]),"spread":summarize(rows["spread"]),"totals":summarize(rows["totals"]),"projection_accuracy":projection_accuracy(week_games)})
    spread_groups=defaultdict(list); total_groups=defaultdict(list)
    for row in spreads: spread_groups[row["signal_tier"]].append(row)
    for row in totals: total_groups[row["signal_tier"]].append(row)
    return {"meta":{"version":VERSION,"projection_board_version":version,"model_version":board.get("meta",{}).get("model_version"),"season":board.get("meta",{}).get("season"),"generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"reporting_timezone":"America/New_York","calendar_week_definition":"Monday through Sunday by scheduled game date in Eastern Time","grading_policy":"Every frozen projection with a valid pregame market is graded for accountability. Disagreement labels are descriptive and are not promoted recommendation tiers.","moneyline_policy":"Prospective only from relative-market-fit-v1-2026-11-25: at least two complete books, 3 percentage-point no-vig edge, favorites -100 through -185, or model-favored underdogs +100 through +250.","totals_policy":"Total disagreements of 4+ points are tracked as testing keys; promotion eligibility remains separate."},"summary":{"final_games_with_frozen_projection":len(finals),"projection_accuracy":projection_accuracy(finals),"straight_up":summarize(su),"spread":summarize(spreads),"totals":summarize(totals),"moneyline":summarize_moneylines(moneylines)},"by_week":weekly,"spread_by_signal":{k:summarize(v) for k,v in sorted(spread_groups.items())},"totals_by_signal":{k:summarize(v) for k,v in sorted(total_groups.items())},"game_results":su,"spread_decisions":spreads,"total_decisions":totals,"moneyline_decisions":moneylines}

def atomic_write(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile("w",dir=path.parent,delete=False,encoding="utf-8") as handle:
        json.dump(payload,handle,separators=(",",":"),allow_nan=False); handle.write("\n"); temporary=Path(handle.name)
    temporary.replace(path)
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--projection-board",type=Path,default=ROOT/"data"/"cbb"/"projection_board.json"); parser.add_argument("--market-history",type=Path,default=ROOT/"data"/"cbb"/"market_snapshots.json"); parser.add_argument("--output",type=Path,default=ROOT/"data"/"cbb"/"model_tracking.json"); args=parser.parse_args()
    board=json.loads(args.projection_board.read_text()); history=json.loads(args.market_history.read_text()) if args.market_history.exists() else None; payload=build_tracking(board,history); atomic_write(args.output,payload); spread=payload["summary"]["spread"]; print(f"{VERSION}: {spread['wins']}-{spread['losses']}-{spread['pushes']} across {spread['games']} ATS grades")
if __name__=="__main__": main()
