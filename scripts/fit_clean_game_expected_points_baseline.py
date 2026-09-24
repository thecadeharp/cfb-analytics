#!/usr/bin/env python3
"""Private ridge baseline for clean-game expected points; never production."""
from __future__ import annotations
import gzip, json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
TABLE=ROOT/'data/research/expected_points_clean_games_2019_2024.csv.gz'
REPORT=ROOT/'data/research/expected_points_baseline_validation.json'

def design(frame):
    yte=frame.start_yards_to_endzone.to_numpy(dtype=float)/100
    period=frame.start_period.to_numpy(dtype=int)
    return np.column_stack([np.ones(len(frame)),yte,yte*yte,period==2,period==3,period==4]).astype(float)

def metrics(actual,pred):
    error=pred-actual
    return {'mae':float(np.abs(error).mean()),'rmse':float(np.sqrt(np.mean(error**2))),'bias':float(error.mean())}

def main():
    table=pd.read_csv(gzip.open(TABLE,'rt'))
    development=table.loc[table.partition.eq('development')].copy()
    validation=table.loc[table.partition.eq('validation')].copy()
    if set(development.season)!={2019,2020,2021,2022} or set(validation.season)!={2023,2024} or 2025 in set(table.season):
        raise RuntimeError('Locked partition or sealed-holdout violation')
    x,y=design(development),development.target_offensive_points.to_numpy(float)
    ridge=10.0
    penalty=np.eye(x.shape[1]); penalty[0,0]=0
    coefficients=np.linalg.solve(x.T@x+ridge*penalty,x.T@y)
    prediction=np.clip(design(validation)@coefficients,0,8)
    league_mean=float(y.mean())
    baseline=np.full(len(validation),league_mean)
    buckets=pd.cut(validation.start_yards_to_endzone,[0,20,40,60,80,100],include_lowest=True)
    calibration=[]
    for name,group in validation.assign(prediction=prediction).groupby(buckets,observed=False):
        calibration.append({'field_position_bucket':str(name),'rows':len(group),'actual_mean':float(group.target_offensive_points.mean()),'predicted_mean':float(group.prediction.mean()),'bias':float((group.prediction-group.target_offensive_points).mean())})
    report={'meta':{'generated_at':datetime.now(timezone.utc).isoformat(),'status':'research_only_clean_game_expected_points_ridge_baseline','production_use':'none; does not modify Model A, projections, site, postgame, or table','training_ready':False,'scope':'development=2019-2022; validation=2023-2024; 2025 sealed and excluded','features':'start yards-to-endzone quadratic plus period indicators; no EPA, drive outcome context, market, or team strength','ridge_penalty':ridge},'development_rows':len(development),'validation_rows':len(validation),'league_mean_baseline':league_mean,'coefficients':coefficients.tolist(),'validation_metrics':{'ridge':metrics(validation.target_offensive_points.to_numpy(float),prediction),'league_mean':metrics(validation.target_offensive_points.to_numpy(float),baseline)},'field_position_calibration':calibration}
    REPORT.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
if __name__=='__main__': main()
