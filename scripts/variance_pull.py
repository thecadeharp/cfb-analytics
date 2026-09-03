"""
HAMMER TIME CFB — variance_pull.py v4
Simplified and debugged cohort building.
"""

import subprocess
subprocess.run(["pip", "install", "requests", "pandas", "numpy"], capture_output=True)

import requests, json, time, os
import pandas as pd
import numpy as np
from datetime import datetime

API_KEY  = "Cc1tNdU6zu7dSX/c5DzpoL9X25p07Gao6SITBOzABwxgO1I1WKhoWsHBl9uw0Omr"
BASE_URL = "https://api.collegefootballdata.com"
HEADERS  = {"Authorization": f"Bearer {API_KEY}"}
YEARS    = list(range(2013, 2026))

def cfbd(endpoint, params=None):
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE_URL}{endpoint}", headers=HEADERS,
                           params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 2:
                print(f"  ⚠ Failed {endpoint} {params}: {e}")
                return []
            time.sleep(2)

# ── FETCH TEAMS ───────────────────────────────────────────────────────────────
print("📋 Fetching FBS teams...")
teams_data = cfbd("/teams/fbs", {"year": 2025})
fbs_teams = {t["school"] for t in teams_data}
team_confs = {t["school"]: t.get("conference", "Independent") for t in teams_data}
print(f"   {len(fbs_teams)} FBS teams")

# ── FETCH COACHES — one call per year ─────────────────────────────────────────
print("\n🏈 Fetching head coaches by year...")
# hc[team][year] = "Coach Name"
hc = {}

for year in YEARS:
    yr = cfbd("/coaches", {"year": year, "minGames": 1})
    for coach in yr:
        first = (coach.get("first_name") or "").strip()
        last  = (coach.get("last_name") or "").strip()
        name  = f"{first} {last}".strip()
        if not name:
            continue
        for s in (coach.get("seasons") or []):
            if int(s.get("year", 0)) == year and s.get("school") and s.get("games", 0) >= 6:
                school = s["school"]
                if school not in hc:
                    hc[school] = {}
                hc[school][year] = name
    time.sleep(0.3)

# Verify — print a team with known HC change
print(f"   Alabama coaches: {hc.get('Alabama', {})}")
print(f"   LSU coaches: {hc.get('LSU', {})}")

# ── FETCH RECORDS ─────────────────────────────────────────────────────────────
print("\n📊 Fetching season records...")
rec = {}
for year in YEARS:
    for r in cfbd("/records", {"year": year}):
        team = r.get("team")
        if team:
            if team not in rec: rec[team] = {}
            rec[team][year] = {
                "wins":   r.get("total", {}).get("wins", 0),
                "losses": r.get("total", {}).get("losses", 0),
            }
    time.sleep(0.2)
print(f"   Done")

# ── FETCH PASSING YARDS PER TEAM PER YEAR ─────────────────────────────────────
print("\n🏈 Fetching passing stats...")
# qb[team][year] = "Player Name"
qb = {}

for year in YEARS:
    yr = cfbd("/stats/player/season", {
        "year": year,
        "category": "passing",
        "seasonType": "regular"
    })
    # Collect all YDS entries
    team_best = {}  # team -> (player, yards)
    for p in yr:
        if p.get("statType") != "YDS":
            continue
        team = p.get("team")
        player = (p.get("player") or "").strip()
        yards = float(p.get("stat") or 0)
        if not team or not player or yards < 200:
            continue
        if team not in team_best or yards > team_best[team][1]:
            team_best[team] = (player, yards)

    for team, (player, yards) in team_best.items():
        if team not in qb: qb[team] = {}
        qb[team][year] = player

    time.sleep(0.3)

# Verify
print(f"   Alabama QBs: {qb.get('Alabama', {})}")
print(f"   Georgia QBs: {qb.get('Georgia', {})}")
print(f"   LSU QBs: {qb.get('LSU', {})}")

# ── AP POLL ───────────────────────────────────────────────────────────────────
print("\n📰 Fetching AP Poll...")
ap = {}
for year in YEARS:
    for stype, week in [("postseason", 1), ("regular", 16), ("regular", 15)]:
        polls = cfbd("/rankings", {"year": year, "week": week, "seasonType": stype})
        found = False
        for pw in polls:
            for poll in (pw.get("polls") or []):
                if "AP" in poll.get("poll", ""):
                    for ri in (poll.get("ranks") or []):
                        if ri.get("school") and ri.get("rank"):
                            ap[f"{ri['school']}_{year}"] = ri["rank"]
                    found = True
        if found: break
        time.sleep(0.1)
    time.sleep(0.2)
print(f"   {len(ap)} rankings")

# ── BUILD COHORTS ─────────────────────────────────────────────────────────────
print("\n🏗️  Building cohorts...")
rows = []

for team in sorted(fbs_teams):
    team_hc = hc.get(team, {})
    team_qb = qb.get(team, {})
    team_rec = rec.get(team, {})

    for year in YEARS[1:]:
        prev = year - 1

        # Need records for both years
        cr = team_rec.get(year)
        pr = team_rec.get(prev)
        if not cr or not pr:
            continue
        if cr["wins"] + cr["losses"] < 8:
            continue

        # Need coaches for both years
        ch = team_hc.get(year)
        ph = team_hc.get(prev)
        if not ch or not ph:
            continue

        # Need QBs for both years
        cq = team_qb.get(year)
        pq = team_qb.get(prev)
        if not cq or not pq:
            continue

        hc_chg = ch != ph
        qb_chg = cq.lower() != pq.lower()

        if not hc_chg and not qb_chg:
            continue

        # Experienced transfer check
        exp = False
        if qb_chg:
            cq_lo = cq.lower()
            for other in fbs_teams:
                if other == team: continue
                other_qb = qb.get(other, {}).get(prev, "")
                if other_qb.lower() == cq_lo:
                    exp = True
                    break

        qb_type = "EXPERIENCED TRANSFER" if exp else "1ST-YR STARTER"

        if hc_chg and qb_chg:
            cohort = "full_reset"
        elif not hc_chg and qb_chg:
            cohort = "qb_swap"
        elif hc_chg and not qb_chg:
            cohort = "coordinator"
        else:
            continue

        delta = cr["wins"] - pr["wins"]
        ap_rank = ap.get(f"{team}_{year}")

        rows.append({
            "team": team, "conference": team_confs.get(team,"Independent"),
            "season": year, "cohort": cohort,
            "head_coach": ch, "prev_head_coach": ph, "hc_changed": hc_chg,
            "new_qb": cq, "prev_qb": pq, "qb_type": qb_type, "exp_transfer": exp,
            "prev_wins": pr["wins"], "wins": cr["wins"], "losses": cr["losses"],
            "delta": delta, "ap_rank": ap_rank,
            "result_boom_bust": "BOOM" if delta >= 3 else ("BUST" if delta <= -3 else None),
        })

df = pd.DataFrame(rows) if rows else pd.DataFrame()
print(f"   Total observations: {len(df)}")
if len(df) > 0:
    for c in ["full_reset","qb_swap","coordinator"]:
        print(f"   {c}: {len(df[df.cohort==c])}")

# ── OUTPUT ────────────────────────────────────────────────────────────────────
def build_cohort(cdf, key):
    if cdf is None or len(cdf) == 0:
        return {"aggregate":{"n":0},"distribution":[],"qb_split":{},
                "analysis":"Data building in progress.","qualifying_2026":[],"biggest_swings":[]}
    n = len(cdf)
    avg  = float(cdf["delta"].mean())
    std  = float(cdf["delta"].std())
    boom = float((cdf["delta"]>=3).mean()*100)
    bust = float((cdf["delta"]<=-3).mean()*100)
    w10  = float((cdf["wins"]>=10).mean()*100)
    ap25 = float(cdf["ap_rank"].notna().mean()*100)
    best = int(cdf["delta"].max())
    worst= int(cdf["delta"].min())

    dist = []
    for label,mask in [
        ("-4 or worse", cdf["delta"]<=-4),
        ("-3 to -1",    (cdf["delta"]>=-3)&(cdf["delta"]<=-1)),
        ("0 to +2",     (cdf["delta"]>=0)&(cdf["delta"]<=2)),
        ("+3 to +5",    (cdf["delta"]>=3)&(cdf["delta"]<=5)),
        ("+6 or more",  cdf["delta"]>=6),
    ]:
        cnt = int(mask.sum())
        dist.append({"bucket":label,"count":cnt,"pct":round(cnt/n*100,1)})

    def ss(sub):
        if len(sub)==0: return {"n":0}
        return {"n":len(sub),
                "avg_delta":round(float(sub["delta"].mean()),1),
                "boom_rate":round(float((sub["delta"]>=3).mean()*100),1),
                "bust_rate":round(float((sub["delta"]<=-3).mean()*100),1),
                "won_10_plus":round(float((sub["wins"]>=10).mean()*100),1)}

    swings = []
    for _,row in cdf.nlargest(20,"delta").iterrows():
        swings.append({
            "season":int(row["season"]),"team":row["team"],
            "conference":row["conference"],"head_coach":row["head_coach"],
            "new_qb":row["new_qb"],"qb_type":row["qb_type"],
            "change_type":row["qb_type"],"prev_wins":int(row["prev_wins"]),
            "wins":int(row["wins"]),"delta":int(row["delta"]),
            "result_boom_bust":row["result_boom_bust"],
            "result_ap":int(row["ap_rank"]) if pd.notna(row.get("ap_rank")) else None,
            "what_happened":f"{row['new_qb']} — {int(row['wins'])} wins ({'+' if row['delta']>=0 else ''}{int(row['delta'])} from {int(row['prev_wins'])})",
        })

    analyses = {
        "full_reset": f"The full reset is the highest-variance situation in college football. Across {n} team-seasons since 2013, the average win change is {avg:+.1f} with a standard deviation of ±{std:.1f}. {boom:.0f}% of these teams gained 3 or more wins and {bust:.0f}% lost 3 or more. Price matters more than direction here.",
        "qb_swap": f"Swapping only the quarterback with staff intact produced an average change of {avg:+.1f} wins across {n} team-seasons with ±{std:.1f} standard deviation. Continuity of scheme puts a floor under the season and a ceiling on it.",
        "coordinator": f"A coordinator-only change produced an average of {avg:+.1f} wins across {n} team-seasons with ±{std:.1f} standard deviation. The scheme shift matters but QB continuity limits the variance significantly.",
    }

    return {
        "aggregate":{"n":n,"avg_win_change":round(avg,1),"std_dev":round(std,1),
                     "best_swing":f"+{best}","worst_swing":str(worst),
                     "boom_rate":round(boom,1),"bust_rate":round(bust,1),
                     "won_10_plus":round(w10,1),"finished_ap_25":round(ap25,1),
                     "ap_top_10":int((cdf["ap_rank"]<=10).sum())},
        "distribution":dist,
        "qb_split":{"experienced_transfer":ss(cdf[cdf.exp_transfer==True]),
                    "first_year_starter":ss(cdf[cdf.exp_transfer==False])},
        "analysis":analyses.get(key,""),
        "qualifying_2026":[],
        "biggest_swings":swings,
    }

out = {
    "meta":{"generated":datetime.now().isoformat(),"years":f"{YEARS[0]}-{YEARS[-1]}",
            "total_observations":len(df)},
    "cohorts":{}
}
for key in ["full_reset","qb_swap","coordinator"]:
    sub = df[df.cohort==key].copy() if len(df)>0 else pd.DataFrame()
    out["cohorts"][key] = build_cohort(sub, key)

with open("variance_historical.json","w") as f:
    json.dump(out, f, indent=2, default=str)

kb = os.path.getsize("variance_historical.json")/1024
print(f"\n✅ Done! {kb:.1f} KB")
for key in ["full_reset","qb_swap","coordinator"]:
    n = out["cohorts"][key]["aggregate"]["n"]
    avg = out["cohorts"][key]["aggregate"].get("avg_win_change","—")
    print(f"   {key}: N={n}, avg={avg}")
print("📥 Right-click variance_historical.json → Download")
