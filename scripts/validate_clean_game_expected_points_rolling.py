#!/usr/bin/env python3
"""Locked rolling OOS checks for the private clean-game expected-points baseline."""
from __future__ import annotations
import gzip,json
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
TABLE=ROOT/'data/research/expected_points_clean_games_2019_2024.csv.gz'
REPORT=ROOT/'data/research/expected_points_rolling_validation.json'
FOLDS=[(2021,2022),(2022,2023),(2023,2024)]
def design(f):
 y=f.start_yards_to_endzone.to_numpy(float)/100;p=f.start_period.to_numpy(int)
 return np.column_stack([np.ones(len(f)),y,y*y,p==2,p==3,p==4]).astype(float)
def score(a,p):
 e=p-a;return {'mae':float(np.abs(e).mean()),'rmse':float(np.sqrt(np.mean(e*e))),'bias':float(e.mean())}
def main():
 t=pd.read_csv(gzip.open(TABLE,'rt'))
 if 2025 in set(t.season):raise RuntimeError('sealed-holdout violation')
 rows=[]
 for end,test_year in FOLDS:
  train=t.loc[t.season.le(end)];test=t.loc[t.season.eq(test_year)]
  x,y=design(train),train.target_offensive_points.to_numpy(float);pen=np.eye(x.shape[1]);pen[0,0]=0
  c=np.linalg.solve(x.T@x+10*pen,x.T@y);pred=np.clip(design(test)@c,0,8);base=np.full(len(test),y.mean());a=test.target_offensive_points.to_numpy(float)
  ridge,mean=score(a,pred),score(a,base)
  rows.append({'train_through':end,'test_year':test_year,'train_rows':len(train),'test_rows':len(test),'ridge':ridge,'league_mean':mean,'mae_improvement':mean['mae']-ridge['mae'],'rmse_improvement':mean['rmse']-ridge['rmse'],'passed':ridge['mae']<mean['mae'] and ridge['rmse']<mean['rmse']})
 report={'meta':{'generated_at':datetime.now(timezone.utc).isoformat(),'status':'research_only_clean_game_expected_points_rolling_validation','scope':'locked folds 2019-2021→2022, 2019-2022→2023, 2019-2023→2024; 2025 excluded/sealed','production_use':'none; Model A, projections, and site untouched','training_ready':False},'folds':rows,'all_folds_passed':all(x['passed'] for x in rows)}
 REPORT.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
if __name__=='__main__':main()
