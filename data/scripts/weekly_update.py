"""
HAMMER TIME CFB ANALYTICS
weekly_update.py

Runs automatically every Tuesday via GitHub Actions.
Pulls the most recent week's games, recalculates metrics,
and updates cfb_metrics.json in the repo.
"""

import requests
import pandas as pd
import numpy as np
import json
import time
import os
import sys
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
API_KEY  = os.environ.get("CFBD_API_KEY", "")
YEAR     = 2026
BASE_URL = "https://api.collegefootballdata.com"
HEADERS  = {"Authorization": f"Bearer {API_KEY}"}
DATA_PATH = "data/cfb_metrics.json"

if not API_KEY:
    print("❌ CFBD_API_KEY environment variable not set")
    sys.exit(1)

# ── HELPERS (same as historical_pull.py) ─────────────────────────────────────
def cfbd(endpoint, params=None):
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE_URL}{endpoint}", headers=HEADERS,
                           params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 2:
                print(f"  ⚠ Failed {endpoint}: {e}")
                return []
            time.sleep(2)

def z_score(series):
    s = series.copy().astype(float)
    mean, std = s.mean(), s.std()
    if std == 0:
        return pd.Series(0.0, index=series.index)
    return (s - mean) / std

EP_TABLE = {
    (1, 1):  1.62, (1, 2):  1.50, (1, 3):  1.35, (1, 4):  1.18,
    (1, 5):  1.00, (1, 6):  0.82, (1, 7):  0.65, (1, 8):  0.50,
    (1, 9):  0.38, (1,10):  0.28, (1,11):  0.18, (1,12):  0.08,
    (2, 1):  2.10, (2, 2):  1.95, (2, 3):  1.75, (2, 4):  1.52,
    (2, 5):  1.28, (2, 6):  1.05, (2, 7):  0.83, (2, 8):  0.62,
    (2, 9):  0.44, (2,10):  0.28, (2,11):  0.14, (2,12): -0.02,
    (3, 1):  2.85, (3, 2):  2.45, (3, 3):  2.05, (3, 4):  1.65,
    (3, 5):  1.28, (3, 6):  0.95, (3, 7):  0.65, (3, 8):  0.38,
    (3, 9):  0.14, (3,10): -0.08, (3,11): -0.28, (3,12): -0.45,
    (4, 1):  1.20, (4, 2):  0.85, (4, 3):  0.50, (4, 4):  0.18,
    (4, 5): -0.15, (4, 6): -0.45, (4, 7): -0.72, (4, 8): -0.95,
    (4, 9):-1.15,  (4,10):-1.32,  (4,11):-1.48,  (4,12):-1.62,
}

YARD_LINE_ADJUSTMENT = {
    (1, 10):   3.5, (11, 20):  2.8, (21, 30):  2.2,
    (31, 40):  1.7, (41, 50):  1.2, (51, 60):  0.7,
    (61, 70):  0.3, (71, 80): -0.1, (81, 90): -0.5, (91,100): -1.0,
}

def get_yard_adj(yards_to_goal):
    ytg = max(1, min(99, int(yards_to_goal or 50)))
    for (lo, hi), adj in YARD_LINE_ADJUSTMENT.items():
        if lo <= ytg <= hi:
            return adj
    return 0.0

def calc_ep(down, distance, yards_to_goal):
    if pd.isna(down) or pd.isna(distance):
        return 0.0
    d = int(down)
    dist_bucket = min(12, max(1, int(distance)))
    base = EP_TABLE.get((d, dist_bucket), 0.0)
    adj = get_yard_adj(yards_to_goal)
    return base + adj * 0.3

def calc_epa(play):
    try:
        ep_before = calc_ep(play.get('down'), play.get('distance'),
                           play.get('yards_to_goal'))
        play_type = str(play.get('play_type', '')).lower()
        yards_gained = play.get('yards_gained', 0) or 0
        if any(x in play_type for x in ['touchdown', 'td']):
            ep_after = -2.0 if 'safety' in play_type else 6.96
        elif 'field goal' in play_type and 'made' in play_type:
            ep_after = 3.0
        elif 'field goal' in play_type and 'missed' in play_type:
            ep_after = -0.5
        elif any(x in play_type for x in ['interception', 'fumble']):
            ep_after = -ep_before - 1.5
        elif 'punt' in play_type:
            new_ytg = max(1, (play.get('yards_to_goal', 50) or 50) - yards_gained + 40)
            ep_after = -calc_ep(1, 10, new_ytg)
        elif 'sack' in play_type:
            new_dist = max(1, (play.get('distance', 10) or 10) - yards_gained)
            new_ytg = max(1, (play.get('yards_to_goal', 50) or 50) - yards_gained)
            ep_after = calc_ep(2, new_dist, new_ytg)
        else:
            new_ytg_goal = max(1, (play.get('yards_to_goal', 50) or 50) - yards_gained)
            new_dist = max(1, (play.get('distance', 10) or 10) - yards_gained)
            if yards_gained >= (play.get('distance', 10) or 10):
                ep_after = calc_ep(1, 10, new_ytg_goal)
            else:
                next_down = int(play.get('down', 1) or 1) + 1
                if next_down > 4:
                    ep_after = -calc_ep(1, 10, max(1, 100 - new_ytg_goal))
                else:
                    ep_after = calc_ep(next_down, new_dist, new_ytg_goal)
        return ep_after - ep_before
    except Exception:
        return 0.0

def is_garbage_time(play):
    try:
        period = int(play.get('period', 1) or 1)
        score_diff = abs(
            (play.get('home_score', 0) or 0) -
            (play.get('away_score', 0) or 0)
        )
        if period >= 4 and score_diff >= 28: return True
        if period >= 3 and score_diff >= 38: return True
        return False
    except:
        return False

def is_success(row):
    try:
        yards = row.get("yards_gained", 0) or 0
        dist = row.get("distance", 10) or 10
        down = int(row.get("down", 1) or 1)
        if down == 1: return yards >= dist * 0.5
        elif down == 2: return yards >= dist * 0.7
        else: return yards >= dist
    except:
        return False

WEIGHTS = {
    "net_epa":           0.30,
    "net_epa_pass":      0.15,
    "net_epa_rush":      0.15,
    "net_sr":            0.10,
    "def_havoc_created": 0.20,
    "off_havoc_allowed": 0.10,
}

# ── DETECT CURRENT WEEK ───────────────────────────────────────────────────────
print(f"🗓️  Running weekly update for {YEAR} season...")
print(f"   Timestamp: {datetime.now().isoformat()}")

# Find the most recently completed week
completed_week = 0
for week in range(1, 16):
    games = cfbd("/games", {"year": YEAR, "week": week, "division": "fbs"})
    completed = [g for g in games if g.get("home_points") is not None]
    if completed:
        completed_week = week
        print(f"   Week {week}: {len(completed)} completed games found")
    else:
        if week > 1:
            break

if completed_week == 0:
    print("   No completed games found yet for 2026 season.")
    print("   Exiting — nothing to update.")
    sys.exit(0)

print(f"\n✅ Most recent completed week: {completed_week}")

# ── LOAD EXISTING DATA ────────────────────────────────────────────────────────
print(f"\n📂 Loading existing metrics from {DATA_PATH}...")
try:
    with open(DATA_PATH) as f:
        existing = json.load(f)
    print(f"   Loaded data for {len(existing.get('teams', {}))} teams")
    print(f"   Previous update: {existing.get('meta', {}).get('generated', 'unknown')}")
except FileNotFoundError:
    print("   ⚠ No existing data found — creating from scratch")
    existing = {"meta": {}, "teams": {}}

# ── FETCH ALL COMPLETED 2026 PLAYS ───────────────────────────────────────────
print(f"\n🎮 Fetching 2026 play-by-play through Week {completed_week}...")

# Get FBS teams
teams_data = cfbd("/teams/fbs", {"year": YEAR})
fbs_teams = {t["school"] for t in teams_data}
team_conferences = {t["school"]: t.get("conference", "Ind") for t in teams_data}

# Get all game scores for context
all_game_scores = {}
for week in range(1, completed_week + 1):
    games = cfbd("/games", {"year": YEAR, "week": week, "division": "fbs"})
    for g in games:
        if g.get("home_points") is not None:
            all_game_scores[g["id"]] = {
                "home": g["home_team"],
                "away": g["away_team"],
                "home_score": g["home_points"],
                "away_score": g["away_points"],
            }
    time.sleep(0.3)

# Fetch all plays through completed week
all_plays = []
for week in range(1, completed_week + 1):
    week_plays = cfbd("/plays", {
        "year": YEAR,
        "week": week,
        "seasonType": "regular"
    })
    if not week_plays:
        continue
    filtered = []
    for p in week_plays:
        if p.get("offense") not in fbs_teams: continue
        if p.get("defense") not in fbs_teams: continue
        play_type = str(p.get("play_type", "")).lower()
        if any(x in play_type for x in ["kickoff", "extra point", "timeout",
                                          "end of", "coin toss", "penalty"]):
            continue
        gid = p.get("game_id")
        if gid in all_game_scores:
            gs = all_game_scores[gid]
            p["home_score"] = gs["home_score"]
            p["away_score"] = gs["away_score"]
        filtered.append(p)
    all_plays.extend(filtered)
    time.sleep(0.4)

print(f"   Total 2026 plays fetched: {len(all_plays):,}")

if not all_plays:
    print("   No 2026 plays available yet — keeping existing 2025 baseline data")
    sys.exit(0)

# ── CALCULATE METRICS ─────────────────────────────────────────────────────────
df = pd.DataFrame(all_plays)
df["epa"] = df.apply(calc_epa, axis=1)
df["garbage"] = df.apply(is_garbage_time, axis=1)
df["is_pass"] = df["play_type"].str.lower().str.contains("pass|sack|interception", na=False)
df["is_rush"] = df["play_type"].str.lower().str.contains("rush|run", na=False)
df["success"] = df.apply(is_success, axis=1)
df["explosive"] = (
    (df["is_pass"] & (df["yards_gained"] >= 15)) |
    (df["is_rush"] & (df["yards_gained"] >= 10))
)
df["havoc"] = df["play_type"].str.lower().str.contains(
    "sack|interception|fumble|tackle for loss|tfl|pass breakup|pbu", na=False)

clean = df[~df["garbage"]].copy()
print(f"   Clean plays: {len(clean):,}")

# Calculate metrics per team
def team_metrics(plays_df, team, side="offense"):
    team_plays = plays_df[plays_df["offense" if side == "offense" else "defense"] == team]
    if len(team_plays) < 5:
        return {}
    pass_plays = team_plays[team_plays["is_pass"]]
    rush_plays = team_plays[team_plays["is_rush"]]
    def sm(s): return float(s.mean()) if len(s) > 0 else 0.0
    return {
        "n_plays": len(team_plays),
        "epa_play": sm(team_plays["epa"]),
        "success_rate": sm(team_plays["success"]) * 100,
        "explosive_rate": sm(team_plays["explosive"]) * 100,
        "havoc_rate": sm(team_plays["havoc"]) * 100,
        "epa_pass": sm(pass_plays["epa"]) if len(pass_plays) > 3 else 0.0,
        "epa_rush": sm(rush_plays["epa"]) if len(rush_plays) > 3 else 0.0,
        "pass_sr": sm(pass_plays["success"]) * 100 if len(pass_plays) > 3 else 0.0,
        "rush_sr": sm(rush_plays["success"]) * 100 if len(rush_plays) > 3 else 0.0,
        "yds_play": sm(team_plays["yards_gained"].abs()),
    }

team_stats_2026 = {}
for team in sorted(fbs_teams):
    off = team_metrics(clean, team, "offense")
    def_ = team_metrics(clean, team, "defense")
    if off and def_:
        team_stats_2026[team] = {"offense": off, "defense": def_}

# Build metrics dataframe and calculate ratings
rows = []
for team, data in team_stats_2026.items():
    o, d = data["offense"], data["defense"]
    rows.append({
        "team": team,
        "off_epa": o.get("epa_play", 0),
        "off_sr": o.get("success_rate", 0),
        "off_epa_pass": o.get("epa_pass", 0),
        "off_epa_rush": o.get("epa_rush", 0),
        "off_pass_sr": o.get("pass_sr", 0),
        "off_rush_sr": o.get("rush_sr", 0),
        "off_havoc_allowed": o.get("havoc_rate", 0),
        "off_expl": o.get("explosive_rate", 0),
        "def_epa": d.get("epa_play", 0),
        "def_sr": d.get("success_rate", 0),
        "def_epa_pass": d.get("epa_pass", 0),
        "def_epa_rush": d.get("epa_rush", 0),
        "def_pass_sr": d.get("pass_sr", 0),
        "def_rush_sr": d.get("rush_sr", 0),
        "def_havoc_created": d.get("havoc_rate", 0),
        "def_expl": d.get("explosive_rate", 0),
    })

mdf = pd.DataFrame(rows).set_index("team")
mdf["net_epa"] = mdf["off_epa"] - mdf["def_epa"]
mdf["net_sr"] = mdf["off_sr"] - mdf["def_sr"]
mdf["net_epa_pass"] = mdf["off_epa_pass"] - mdf["def_epa_pass"]
mdf["net_epa_rush"] = mdf["off_epa_rush"] - mdf["def_epa_rush"]

z = pd.DataFrame(index=mdf.index)
for col in WEIGHTS:
    s = mdf[col] if col in mdf.columns else pd.Series(0, index=mdf.index)
    z[col] = z_score(-s if col == "off_havoc_allowed" else s)
mdf["power_rating"] = sum(z[col] * w for col, w in WEIGHTS.items())

# Fetch updated records
records_data = cfbd("/records", {"year": YEAR})
records_2026 = {r["team"]: r for r in records_data}

sp_data = cfbd("/ratings/sp", {"year": 2025})
sp_lookup = {s["team"]: s for s in sp_data}

# ── BLEND 2025 BASELINE + 2026 LIVE DATA ────────────────────────────────────
print("\n🔀 Blending 2025 historical baseline with 2026 live data...")

# How much to weight 2026 data vs 2025 baseline
# Scales from 0 (week 1) to 1 (week 10+)
blend_weight = min(1.0, completed_week / 10)
print(f"   Week {completed_week} — 2026 data weight: {blend_weight:.0%}")

# Build final output
output = {
    "meta": {
        "year": YEAR,
        "generated": datetime.now().isoformat(),
        "through_week": completed_week,
        "total_plays_2026": len(clean),
        "blend_weight": blend_weight,
        "type": "weekly_update"
    },
    "teams": {}
}

for team in fbs_teams:
    baseline = existing.get("teams", {}).get(team, {})
    live_row = mdf.loc[team] if team in mdf.index else None
    live_ts = team_stats_2026.get(team, {})
    rec = records_2026.get(team, {})
    sp = sp_lookup.get(team, {})

    wins = rec.get("total", {}).get("wins", 0)
    losses = rec.get("total", {}).get("losses", 0)

    if live_row is not None:
        # Blend ratings
        base_pr = baseline.get("power_rating", 0) or 0
        live_pr = float(live_row.get("power_rating", 0))
        blended_pr = base_pr * (1 - blend_weight) + live_pr * blend_weight

        def blend(base_key, live_val, key):
            base_val = (baseline.get(base_key) or {}).get(key, 0) or 0
            return round(base_val * (1 - blend_weight) + live_val * blend_weight, 3)

        output["teams"][team] = {
            "team": team,
            "conference": team_conferences.get(team, "Ind"),
            "record": {
                "wins": wins, "losses": losses,
                "conf_wins": rec.get("conferenceGames", {}).get("wins", 0),
                "conf_losses": rec.get("conferenceGames", {}).get("losses", 0),
            },
            "sp_plus": {
                "overall": sp.get("rating"),
                "offense": sp.get("offense", {}).get("rating") if isinstance(sp.get("offense"), dict) else None,
                "defense": sp.get("defense", {}).get("rating") if isinstance(sp.get("defense"), dict) else None,
            },
            "power_rating": round(blended_pr, 3),
            "power_rating_rank": 0,  # recalculated below
            "offense": {
                "epa_play":      blend("offense", float(live_row.get("off_epa", 0)), "epa_play"),
                "success_rate":  blend("offense", float(live_row.get("off_sr", 0)), "success_rate"),
                "explosive_rate":blend("offense", float(live_row.get("off_expl", 0)), "explosive_rate"),
                "epa_pass":      blend("offense", float(live_row.get("off_epa_pass", 0)), "epa_pass"),
                "epa_rush":      blend("offense", float(live_row.get("off_epa_rush", 0)), "epa_rush"),
                "pass_sr":       blend("offense", float(live_row.get("off_pass_sr", 0)), "pass_sr"),
                "rush_sr":       blend("offense", float(live_row.get("off_rush_sr", 0)), "rush_sr"),
                "havoc_allowed": blend("offense", float(live_row.get("off_havoc_allowed", 0)), "havoc_allowed"),
                "n_plays":       int(live_ts.get("offense", {}).get("n_plays", 0)),
            },
            "defense": {
                "epa_play":       blend("defense", float(live_row.get("def_epa", 0)), "epa_play"),
                "success_rate":   blend("defense", float(live_row.get("def_sr", 0)), "success_rate"),
                "explosive_rate": blend("defense", float(live_row.get("def_expl", 0)), "explosive_rate"),
                "epa_pass":       blend("defense", float(live_row.get("def_epa_pass", 0)), "epa_pass"),
                "epa_rush":       blend("defense", float(live_row.get("def_epa_rush", 0)), "epa_rush"),
                "pass_sr":        blend("defense", float(live_row.get("def_pass_sr", 0)), "pass_sr"),
                "rush_sr":        blend("defense", float(live_row.get("def_rush_sr", 0)), "rush_sr"),
                "havoc_created":  blend("defense", float(live_row.get("def_havoc_created", 0)), "havoc_created"),
                "n_plays":        int(live_ts.get("defense", {}).get("n_plays", 0)),
            },
            "net": {
                "epa":      round(float(live_row.get("net_epa", 0)), 3),
                "sr":       round(float(live_row.get("net_sr", 0)), 1),
                "epa_pass": round(float(live_row.get("net_epa_pass", 0)), 3),
                "epa_rush": round(float(live_row.get("net_epa_rush", 0)), 3),
            }
        }
    else:
        # No 2026 data yet — use 2025 baseline
        output["teams"][team] = baseline
        if output["teams"][team]:
            output["teams"][team]["record"] = {
                "wins": wins, "losses": losses,
                "conf_wins": rec.get("conferenceGames", {}).get("wins", 0),
                "conf_losses": rec.get("conferenceGames", {}).get("losses", 0),
            }

# Recalculate ranks
all_ratings = [(t, d.get("power_rating", 0)) 
               for t, d in output["teams"].items() if d]
all_ratings.sort(key=lambda x: x[1], reverse=True)
for rank, (team, _) in enumerate(all_ratings, 1):
    if output["teams"].get(team):
        output["teams"][team]["power_rating_rank"] = rank

# ── SAVE ──────────────────────────────────────────────────────────────────────
os.makedirs("data", exist_ok=True)
with open(DATA_PATH, "w") as f:
    json.dump(output, f, indent=2, default=str)

size_kb = os.path.getsize(DATA_PATH) / 1024
print(f"\n✅ Weekly update complete")
print(f"   Teams updated: {len(output['teams'])}")
print(f"   Through Week: {completed_week}")
print(f"   File size: {size_kb:.1f} KB")
print(f"   Saved to: {DATA_PATH}")
