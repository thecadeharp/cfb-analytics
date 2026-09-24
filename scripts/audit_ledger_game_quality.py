#!/usr/bin/env python3
"""Research-only game-quality segmentation of the 2019-2024 ledger; 2025 sealed."""
from __future__ import annotations
import argparse, json, tempfile
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from audit_historical_ledger_coverage import official_scores, verified_plays
from build_historical_training_data import download_season, get_release_assets
from build_verified_possession_ledger import EXTRA_COLUMNS, build_ledger
from reconstruct_scoring_events import SOURCE_COLUMNS

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data/research/ledger_game_quality_2019_2024.json"
YEARS = list(range(2019, 2025))

def tier(rate):
    if rate == 0: return "clean"
    if rate <= .10: return "isolated"
    if rate <= .25: return "material"
    return "corrupt"

def summarize(ledger):
    observed = ledger.loc[ledger.observed_possession].copy()
    observed["scoring"] = observed.assigned_offensive_points.gt(0)
    game = observed.groupby("game_id").agg(
        possessions=("game_id", "size"), passed=("label_check_passed", "sum"),
        scoring_rate=("scoring", "mean"), mean_core_plays=("core_plays", "mean"),
        q4_share=("start_period", lambda s: float((s == 4).mean())))
    game["unresolved"] = game.possessions - game.passed
    game["unresolved_rate"] = game.unresolved / game.possessions
    game["quality_tier"] = game.unresolved_rate.map(tier)
    by_tier=[]
    for name, g in game.groupby("quality_tier", sort=False):
        by_tier.append({"tier":name,"games":len(g),"possessions":int(g.possessions.sum()),
                        "passed":int(g.passed.sum()),"mean_unresolved_rate":float(g.unresolved_rate.mean()),
                        "mean_scoring_rate":float(g.scoring_rate.mean()),"mean_core_plays":float(g.mean_core_plays.mean()),
                        "mean_q4_share":float(g.q4_share.mean())})
    return {"games":len(game),"tier_counts":game.quality_tier.value_counts().to_dict(),"by_tier":by_tier,
            "clean_game_retention":{"games":int((game.quality_tier=="clean").sum()),"possessions":int(game.loc[game.quality_tier=="clean","possessions"].sum()),"passed":int(game.loc[game.quality_tier=="clean","passed"].sum())}}

def audit_year(year,path,asset):
    raw=pd.read_parquet(path,columns=list(dict.fromkeys(SOURCE_COLUMNS+EXTRA_COLUMNS)))
    official,_=official_scores(year)
    plays,events,ids,rejected=verified_plays(raw,official)
    ledger,_,_,summary=build_ledger(plays,events)
    if summary["verified_games"] != len(ids): raise RuntimeError(f"{year}: coverage mismatch")
    return {"season":year,"source_asset":asset,"verified_games":len(ids),"cross_source_rejections":dict(rejected),"quality":summarize(ledger)}

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--seasons",nargs="+",type=int,default=YEARS); args=parser.parse_args()
    if sorted(set(args.seasons)) != YEARS: parser.error("Exactly 2019-2024 only; 2025 is sealed.")
    results=[]
    with tempfile.TemporaryDirectory() as tmp:
        assets=get_release_assets()
        for year in YEARS:
            path,asset=download_season(year,assets,Path(tmp)); result=audit_year(year,path,asset["browser_download_url"]); results.append(result); print(json.dumps({"season":year,"tiers":result["quality"]["tier_counts"]}),flush=True)
    report={"meta":{"generated_at":datetime.now(timezone.utc).isoformat(),"status":"research_only_historical_ledger_game_quality_audit","scope":"2019-2024 score-verified observed regulation possessions; 2025 excluded and sealed","production_use":"none; no Model A, projections, site, row-repair, or eligibility changes","training_ready":False,"interpretation":"Game tiers quantify feed quality and selection risk; they do not authorize fitting or automatic exclusions."},"seasons":results}
    REPORT.parent.mkdir(parents=True,exist_ok=True); REPORT.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
if __name__ == "__main__": main()
