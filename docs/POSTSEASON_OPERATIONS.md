# THI CFB Postseason Operations Contract

## Navigation and schedule identity

- Regular-season games remain grouped by numbered week.
- Postseason games are grouped by stable labels: Conference Championships, CFP First Round, CFP Quarterfinals, CFP Semifinals, CFP National Championship, and Bowl Games.
- Raw provider week numbers are never the postseason source of truth because they can restart at Week 1.
- CFBD game ID plus the verified postseason registry is the source of truth for CFP round and bowl identity.
- Bowl Games are sorted chronologically and display their official bowl name on the matchup page.
- The regular-season bye board is not rendered for a postseason group.

## Projection layers

THI must preserve two separate concepts throughout bowl season:

1. **Model A baseline:** the normal projection produced without manually rewriting team strength after the matchup is announced.
2. **Verified availability scenario:** a separately labeled projection showing the effect of confirmed opt-outs, transfer departures, suspensions, and injuries relative to the best identified replacement.

The availability scenario must never silently overwrite Model A. Each layer receives its own value, timestamp, method version, and source coverage. Public ATS, total, and CLV grading remains tied to the projection/market pair frozen under the published grading contract.

Traditional bowl projections are research-only and are excluded from the official ATS, totals, moneyline, CLV, beat-close, confidence-tier, and YTD records. Conference championships and CFP games remain eligible for the official record. The projection board must label the traditional-bowl distinction visibly.

## Player absence valuation

The existing `thi-availability-impact-v1` layer is the starting point. It uses roster identity, workload share, player production rating, position leverage, and replacement quality. Current per-player caps are intentionally conservative:

- QB: 6.0 points, with the full range reserved for an elite starter with a large verified replacement gap.
- RB: 1.2 points.
- WR: 1.3 points.
- TE: 0.8 points.
- OL: 0.65 points.
- DL: 0.8 points.
- LB: 0.65 points.
- DB: 0.7 points.
- Special teams: 0.35 points.

Multiple absences receive diminishing weights. Non-QB exposure is capped at 4.0 points and combined report exposure at 8.0 points. Those are display/research values until a prospective validation gate authorizes any model use.

## Bowl availability policy

- **Confirmed out / opt-out / portal departure / suspension:** eligible for the verified availability scenario after a timestamped primary or authoritative source is stored.
- **Questionable / game-time decision / unconfirmed report:** shown as uncertainty; it does not receive a full automatic deduction.
- **No verified report:** status is unknown, never “fully healthy.”
- **Coaching changes:** displayed separately from player availability and not priced into Model A without prospective validation.
- **Motivation narratives:** never priced as a manual adjustment.

Every bowl matchup should expose roster certainty as `CONFIRMED`, `DEVELOPING`, or `UNSTABLE`. An unstable roster can hold the public market-comparison signal while leaving the baseline projection visible.

## Freeze cadence

- Assignment freeze: immediately after the official matchup is announced.
- Roster checkpoints: 48 hours and 24 hours before kickoff.
- Pregame freeze: the last verified snapshot before kickoff under the existing market contract.
- Late scratches remain visible as timestamped post-freeze context; they do not retroactively rewrite the frozen record.

## Release sequence

1. Ingest and classify postseason games; render named filters.
2. Populate the verified game registry after Selection Day and bowl announcements.
3. Expand availability sources to explicit opt-out and transfer-departure statuses.
4. Publish the baseline and verified scenario side by side with roster certainty.
5. Keep adjusted-scenario performance in a separate research ledger until sample and CLV gates justify any future promotion.
