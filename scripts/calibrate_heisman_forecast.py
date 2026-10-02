#!/usr/bin/env python3
"""Backtest and calibrate the THI Heisman forecast on weekly snapshots.

This is an award-resume research model. It is isolated from Model A and only
publishes coefficients when leave-one-season-out gates pass.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import tempfile
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data/research/heisman_calibration.json"
PBP_URL = "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-cfb-data/main/cfb/pbp/parquet/play_by_play_{year}.parquet"
CHECKPOINTS = (4, 8, 12, 16)
FEATURES = (
    "efficiency_pct", "total_value_pct", "volume_pct", "success_pct",
    "yards_per_game_pct", "touchdowns_per_game_pct", "team_win_pct",
    "qb", "rb", "receiver", "defense",
)
FINALISTS = {
    2019: ("Joe Burrow", "Jalen Hurts", "Justin Fields", "Chase Young"),
    2020: ("DeVonta Smith", "Mac Jones", "Trevor Lawrence", "Kyle Trask"),
    2021: ("Bryce Young", "Aidan Hutchinson", "Kenny Pickett", "C.J. Stroud"),
    2022: ("Caleb Williams", "Max Duggan", "C.J. Stroud", "Stetson Bennett"),
    2023: ("Jayden Daniels", "Michael Penix Jr.", "Bo Nix", "Marvin Harrison Jr."),
    2024: ("Travis Hunter", "Ashton Jeanty", "Dillon Gabriel", "Cam Ward"),
    2025: ("Fernando Mendoza", "Diego Pavia", "Jeremiyah Love", "Julian Sayin"),
}
WINNERS = {
    2019: "Joe Burrow", 2020: "DeVonta Smith", 2021: "Bryce Young",
    2022: "Caleb Williams", 2023: "Jayden Daniels", 2024: "Travis Hunter",
    2025: "Fernando Mendoza",
}


def norm_name(value):
    text = re.sub(r"[^a-z0-9 ]", "", str(value or "").lower())
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", text)
    return re.sub(r"\s+", " ", text).strip()


def pid(value):
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return None


def truth(value):
    return value is True or value == 1 or str(value).lower() == "true"


def num(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else 0.0
    except (TypeError, ValueError):
        return 0.0


def pct(values, target):
    values = np.asarray(values, dtype=float)
    return 50.0 if len(values) < 2 else 100.0 * (np.sum(values < target) + 0.5 * np.sum(values == target)) / len(values)


def load_frame(path):
    wanted = {
        "season", "seasonType", "week", "game_id", "status_type_completed",
        "homeTeamId", "awayTeamId", "homeFinalScore", "awayFinalScore",
        "pos_team_id", "def_pos_team_id", "rush", "pass_attempt", "completion", "target",
        "rush_td", "pass_td", "int", "kneel_down", "yds_rushed", "yds_receiving", "statYardage",
        "EPA", "EPA_pass", "EPA_rush", "passer_player_id", "passer_player_name",
        "rusher_player_id", "rusher_player_name", "receiver_player_id", "receiver_player_name",
        "sack_player_id", "sack_player_name", "sack_player_id2", "sack_player_name2",
        "interception_player_id", "interception_player_name", "pass_breakup_player_id", "pass_breakup_player_name",
        "fumble_forced_player_id", "fumble_forced_player_name",
    }
    available = set(pq.ParquetFile(path).schema.names)
    frame = pd.read_parquet(path, columns=sorted(wanted & available))
    if "status_type_completed" in frame:
        frame = frame.loc[frame.status_type_completed.fillna(False).map(truth)]
    return frame


def snapshot(frame, season, cutoff):
    frame = frame.loc[pd.to_numeric(frame.week, errors="coerce").le(cutoff)]
    records = defaultdict(lambda: defaultdict(float, games=set()))
    names, teams = {}, {}
    team_games = {}
    unique_games = frame.drop_duplicates("game_id")
    for row in unique_games.to_dict("records"):
        home, away = pid(row.get("homeTeamId")), pid(row.get("awayTeamId"))
        if not home or not away: continue
        hs, aws = num(row.get("homeFinalScore")), num(row.get("awayFinalScore"))
        team_games.setdefault(home, [0, 0]); team_games.setdefault(away, [0, 0])
        team_games[home][0] += 1; team_games[away][0] += 1
        team_games[home][1] += int(hs > aws); team_games[away][1] += int(aws > hs)

    for row in frame.to_dict("records"):
        game = str(row.get("game_id")); offense, defense = pid(row.get("pos_team_id")), pid(row.get("def_pos_team_id"))
        epa = num(row.get("EPA"))
        entries = []
        passer = pid(row.get("passer_player_id")); rusher = pid(row.get("rusher_player_id")); receiver = pid(row.get("receiver_player_id"))
        if passer and truth(row.get("pass_attempt")):
            entries.append((passer, row.get("passer_player_name"), offense, "pass", num(row.get("EPA_pass")) or epa, num(row.get("yds_receiving")), int(truth(row.get("pass_td")))))
        if rusher and truth(row.get("rush")) and not truth(row.get("kneel_down")):
            entries.append((rusher, row.get("rusher_player_name"), offense, "rush", num(row.get("EPA_rush")) or epa, num(row.get("yds_rushed")), int(truth(row.get("rush_td")))))
        if receiver and truth(row.get("target")):
            entries.append((receiver, row.get("receiver_player_name"), offense, "target", num(row.get("EPA_pass")) or epa, num(row.get("yds_receiving")), int(truth(row.get("pass_td")))))
        for athlete, name, team, kind, value, yards, td in entries:
            s=records[athlete]; names[athlete]=name; teams[athlete]=team; s["games"].add(game)
            s["opportunities"]+=1; s["epa"]+=value; s["successes"]+=int(value>0); s["yards"]+=yards; s["td"]+=td; s[kind]+=1
        for field, name_field in (("sack_player_id","sack_player_name"),("sack_player_id2","sack_player_name2"),("interception_player_id","interception_player_name"),("pass_breakup_player_id","pass_breakup_player_name"),("fumble_forced_player_id","fumble_forced_player_name")):
            athlete=pid(row.get(field))
            if athlete:
                s=records[athlete]; names[athlete]=row.get(name_field); teams[athlete]=defense; s["games"].add(game); s["defense"]+=1

    raw=[]
    for athlete,s in records.items():
        games=max(1,len(s["games"])); offensive=s["opportunities"]
        role=max((("QB",s["pass"]),("RB",s["rush"]),("REC",s["target"]),("DEF",s["defense"])),key=lambda x:x[1])[0]
        minimum={"QB":8*games,"RB":5*games,"REC":4*games,"DEF":1*games}[role]
        volume=s["opportunities"] if role!="DEF" else s["defense"]
        if volume < minimum: continue
        team=teams.get(athlete); tg,tw=team_games.get(team,(0,0))
        raw.append({"season":season,"week":cutoff,"athlete_id":athlete,"name":names.get(athlete),"name_key":norm_name(names.get(athlete)),"team_id":team,"role":role,"games":games,
                    "efficiency":s["epa"]/offensive if offensive else 0,"total_value":s["epa"]/games if offensive else s["defense"]/games,"volume":volume/games,
                    "success":100*s["successes"]/offensive if offensive else 0,"yards_per_game":s["yards"]/games,"touchdowns_per_game":s["td"]/games,
                    "team_win_pct":100*tw/tg if tg else 0})
    fields=("efficiency","total_value","volume","success","yards_per_game","touchdowns_per_game")
    for row in raw:
        for field in fields: row[field+"_pct"]=pct([r[field] for r in raw if r["role"]==row["role"]],row[field])
        row.update(qb=int(row["role"]=="QB"),rb=int(row["role"]=="RB"),receiver=int(row["role"]=="REC"),defense=int(row["role"]=="DEF"))
        finalists={norm_name(n) for n in FINALISTS[season]}; winner=norm_name(WINNERS[season])
        row["finalist"]=int(row["name_key"] in finalists); row["winner"]=int(row["name_key"]==winner)
    return raw


def fit(rows, label):
    x=np.asarray([[r[f] for f in FEATURES] for r in rows],float); y=np.asarray([r[label] for r in rows],float)
    mean=x.mean(0); std=x.std(0); std[std<1e-8]=1; z=(x-mean)/std; z=np.column_stack([np.ones(len(z)),z])
    w=np.zeros(z.shape[1]); pos=max(1,y.sum()); neg=max(1,len(y)-pos); weights=np.where(y==1,len(y)/(2*pos),len(y)/(2*neg))
    for _ in range(1800):
        p=1/(1+np.exp(-np.clip(z@w,-30,30))); grad=z.T@((p-y)*weights)/len(y); grad[1:]+=0.02*w[1:]; w-=0.08*grad
    return {"mean":mean,"std":std,"coef":w}


def predict(model, rows):
    x=np.asarray([[r[f] for f in FEATURES] for r in rows],float); z=(x-model["mean"])/model["std"]; z=np.column_stack([np.ones(len(z)),z])
    return 1/(1+np.exp(-np.clip(z@model["coef"],-30,30)))


def normalized(probabilities, total):
    p=np.clip(np.asarray(probabilities,float),1e-8,1-1e-8); logits=np.log(p/(1-p))
    lo,hi=-20.0,20.0
    for _ in range(80):
        mid=(lo+hi)/2; s=np.sum(1/(1+np.exp(-(logits+mid))))
        if s>total: hi=mid
        else: lo=mid
    return 1/(1+np.exp(-(logits+(lo+hi)/2)))


def serialize(model):
    return {"features":list(FEATURES),"means":model["mean"].round(8).tolist(),"scales":model["std"].round(8).tolist(),"intercept":round(float(model["coef"][0]),8),"coefficients":model["coef"][1:].round(8).tolist()}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--parquet-dir",type=Path); parser.add_argument("--no-download",action="store_true"); args=parser.parse_args()
    work=args.parquet_dir or Path(tempfile.mkdtemp(prefix="thi-heisman-")); rows=[]; coverage={}
    for year in sorted(FINALISTS):
        candidates=[work/f"play_by_play_{year}.parquet",Path(f"/private/tmp/current-play_by_play_{year}.parquet")]
        path=next((p for p in candidates if p.exists()),None)
        if not path:
            if args.no_download: raise FileNotFoundError(year)
            path=candidates[0]; path.parent.mkdir(parents=True,exist_ok=True); urllib.request.urlretrieve(PBP_URL.format(year=year),path)
        frame=load_frame(path); season_rows=[]
        for week in CHECKPOINTS: season_rows.extend(snapshot(frame,year,week))
        rows.extend(season_rows); coverage[str(year)]={"rows":len(season_rows),"finalist_rows":sum(r["finalist"] for r in season_rows),"winner_rows":sum(r["winner"] for r in season_rows)}

    folds=[]
    for year in sorted(FINALISTS):
        train=[r for r in rows if r["season"]!=year]; test=[r for r in rows if r["season"]==year]
        fm,wm=fit(train,"finalist"),fit(train,"winner")
        recalls=[]; winner_ranks=[]; briers=[]
        for week in CHECKPOINTS:
            group=[r for r in test if r["week"]==week]
            fp=normalized(predict(fm,group),4); wp=normalized(predict(wm,group),1)
            top4=np.argsort(-fp)[:4]; recalls.append(sum(group[i]["finalist"] for i in top4)/4)
            winner_index=next((i for i,r in enumerate(group) if r["winner"]),None)
            if winner_index is not None: winner_ranks.append(int(np.where(np.argsort(-wp)==winner_index)[0][0])+1)
            briers.append(float(np.mean((fp-np.asarray([r["finalist"] for r in group]))**2)))
        folds.append({"season":year,"top4_finalist_recall":round(float(np.mean(recalls)),3),"winner_median_rank":float(np.median(winner_ranks)),"finalist_brier":round(float(np.mean(briers)),4)})
    recall=float(np.mean([f["top4_finalist_recall"] for f in folds])); winner_top5=float(np.mean([f["winner_median_rank"]<=5 for f in folds])); brier=float(np.mean([f["finalist_brier"] for f in folds]))
    passed=recall>=0.45 and winner_top5>=0.70 and brier<=0.08
    finalist_model,winner_model=fit(rows,"finalist"),fit(rows,"winner")
    report={"meta":{"status":"PASSED_FOR_BETA_PROBABILITIES" if passed else "BOARD_ONLY_CALIBRATION_GATE_FAILED","generated_at":datetime.now(timezone.utc).isoformat(),"seasons":sorted(FINALISTS),"checkpoints":list(CHECKPOINTS),"source":"SportsDataverse/cfbfastR PBP and official Heisman finalist labels","labels_url":"https://www.heisman.com/voting-records/","model_usage":"display_only_not_used_by_model_a"},
            "coverage":coverage,"validation":{"leave_one_season_out":folds,"mean_top4_finalist_recall":round(recall,3),"winner_top5_rate":round(winner_top5,3),"mean_finalist_brier":round(brier,4),"gates":{"top4_recall_min":0.45,"winner_top5_min":0.70,"brier_max":0.08},"passed":passed},
            "finalist_model":serialize(finalist_model),"winner_model":serialize(winner_model)}
    REPORT.parent.mkdir(parents=True,exist_ok=True); REPORT.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps(report["validation"],indent=2))


if __name__=="__main__": main()
