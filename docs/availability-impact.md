# THI Availability Impact

THI Availability Impact is a display-only matchup research score. It summarizes the burden of currently verified player statuses on a 0–100 scale. It is not a point-spread adjustment, a player-value estimate, a medical forecast, or an input to Model A.

## Inputs

- Current, source-linked availability notes that pass THI's seven-day freshness gate.
- ESPN roster identity from `data/roster_assets.json`.
- Recorded current-season workload from CFBD/SportsDataverse box-score production.
- THI's position-specific player production rating when the roster identity and position group agree.

THI does not infer official starters, snap counts, injury severity, or a healthy roster when a report is missing.

## Point sensitivity

Each player also receives a conservative full-absence point sensitivity. This estimates how much a newly absent player could matter versus a full-strength baseline; it is not automatically deducted from Model A. Position ceilings are 6.0 points for QB, 1.2 for RB, 1.3 for WR, 0.8 for TE and DL, 0.65 for OL and LB, 0.70 for DB, and 0.35 for special teams. Recorded role, production and position leverage determine the value beneath the ceiling.

Quarterback uses a stricter replacement-aware curve. Production rating, observed role and the rating gap to the best observed backup determine the base value. Reaching 6.0 additionally requires a production rating of at least 94 and a replacement-gap score of at least 0.75. A clear but non-elite starter should generally remain in the 3–4 point range rather than inheriting the positional maximum.

The current report exposure applies the status-severity weight, discounts additional absences through diminishing returns, caps non-QB accumulation at four points and caps the full team exposure at eight. THI still requires a separate, timestamped adjustment before changing the availability-adjusted scenario. This prevents double-counting a season-long absence already reflected in the team's observed performance.

## Calculation

Each listed player receives a 0–10 impact score based on four disclosed components:

1. Status severity: Out/Unavailable 1.00, Doubtful 0.80, Questionable/Game-time decision 0.50, Limited 0.30, Probable 0.14, Available/Active 0.00.
2. Recorded workload share within the player's position group.
3. Position leverage, with quarterback highest and special teams lowest.
4. The player's THI production rating, when available.

Player scores roll into position-group totals and a team total capped at 100. The visible team tier is Low (1–14), Moderate (15–29), High (30–49), or Severe (50+). A missing player join receives a conservative role estimate and low evidence confidence rather than a fabricated starter label.

## Isolation and validation

The calculation runs in `availability-impact.js`. Automated tests verify status handling, player matching, position grouping, workload ordering, the 0–100 cap, and the rule that an available player adds zero impact. The availability refresh workflow runs these tests but commits only the source snapshot.

The published Model A line remains unchanged. Any manually sourced availability-adjusted scenario continues to appear separately and requires an explicit point-value input; the impact score never creates that input automatically.
