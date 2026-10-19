# Punt & Rally product audit for THI

Date: 2026-10-19

Implementation status: the first THI-native release is complete in `thi-visual-explorer.js` and `thi-visual-explorer.css`. It publishes the CFB Metric Explorer and Rating History inside THI Ratings. Schedule Stress, Projection Accuracy Explorer, deeper position-room views, drive/control charts, and Regression Watch remain sequenced below.

This audit reviews public Punt & Rally pages for product and presentation ideas. It is an inspiration and gap analysis, not a data-ingestion plan. THI should calculate every public metric from its own permitted sources and document its own methodology. Punt & Rally ratings, tables, formulas, and page content should not be copied into THI.

## What Punt & Rally does well

### Reusable two-axis metric explorer

The chart page uses one familiar quadrant scatterplot for many questions: success versus explosiveness, rush versus pass performance, front-seven versus secondary havoc, offense versus defense, line play, scoring opportunities, field position, penalties, and PPA. Conference filters and team logos make a large national dataset easy to scan.

### Longitudinal context

Its rating tracker shows current rating, weekly movement, season movement, best rating, and a small week-by-week trend. This gives ranking changes context that a current table cannot provide.

### Tables built around a specific question

The schedule, home-field, situational, regression, and projection-accuracy pages each answer a narrow question. They expose sample sizes and caveats near the result instead of mixing every available statistic into one board.

### Position-specific player presentation

Player pages and leaderboards change the visible columns by role. Passing, rushing, receiving, defense, kicking, punting, and returns are not forced into one generic rating table.

## THI overlap

THI already has much of the underlying data needed for these ideas:

- `data/advanced_metrics.json`: EPA, success, explosiveness, standard and passing downs, early and late downs, havoc, front-seven and secondary havoc, line yards, second-level and open-field yards, power success, stuff rate, scoring opportunities, and related samples.
- `data/thi_observed_ratings.json`: opponent-adjusted team values, ranks, percentiles, bands, and reliability.
- `data/ratings_snapshots/`: weekly observed-rating snapshots from Week 3 onward.
- `data/thi_power_ratings.json`: current power rating, rank, previous-week comparable rating, and performance-only weekly change.
- `data/player_intelligence.json`: verified player identity, position, traditional production, workload share, total and adjusted EPA, success rate, and position ranks.
- `data/postgame_analytics.json`: postgame win expectancy, expected margin, EPA, success, explosiveness, turnovers, down splits, drives, and other retrospective analysis.
- `data/schedule_context.json`: rest, road streaks, travel, time zones, lookahead, previous result, and conference familiarity.
- `data/hfa_ratings.json`: validated team-specific home-field estimates and historical validation.
- `data/reports/weekly_model_scorecard.json` and model-tracking reports: frozen projection results and accuracy summaries.

The largest gap is not raw data. It is presenting the data across teams, across weeks, and by position in ways that answer one clear question.

## Recommended build order

### P0 — CFB Metric Explorer

Add a `Metric Explorer` view inside Team Data or THI Ratings. Reuse the visual language of the existing CBB efficiency landscape while giving CFB its own selectors.

Initial chart presets:

1. Offensive success rate vs explosive-play rate.
2. Defensive success rate allowed vs explosive-play rate allowed.
3. Rush EPA vs pass EPA.
4. Early-down EPA vs passing-down EPA.
5. Front-seven havoc vs secondary havoc.
6. Offensive line yards vs defensive line yards allowed.
7. Power rating vs current-form rating.
8. Current form vs résumé.
9. Net EPA vs scoreboard luck.
10. Offensive scoring-opportunity rate vs points per opportunity.

Required behavior:

- Conference and team search filters.
- Team logos or short labels with collision handling.
- Median quadrant lines and plain-language quadrant labels.
- Desktop hover and mobile tap detail cards.
- Minimum-sample controls and visible reliability labels.
- Week selector using frozen snapshots where available.
- Shareable URL state for metric, conference, week, and selected team.
- A methodology drawer stating source, sample, garbage-time treatment, opponent adjustment, and whether the view is descriptive or predictive.

This is the highest-value addition because THI already has nearly every input and the interface can serve many analyses without creating another large static table.

### P0 — Rating Trajectory

Add a compact trend chart to THI Ratings and each team dossier:

- THI Power rating and rank by week.
- Current Form rating and rank by week.
- Résumé rank by week when frozen snapshots exist.
- Weekly change and season change.
- Data-quality or reliability band by week.
- An event marker for opponent/result, major quarterback availability change, or model-version boundary when verified.

The build must preserve model-version boundaries. Values from incompatible model versions should not be joined into a continuous line without an explicit break.

### P1 — Schedule Stress Board

Build a separate schedule view that ranks upcoming three- and four-game windows using THI opponent power and venue-adjusted win probabilities for a fixed benchmark team.

Display:

- Expected losses for an average Top-25 benchmark.
- Opponent power, venue, travel distance, time-zone change, rest, and consecutive-road-game count.
- Next opponent and bye-week placement.
- A window score with an explanation of every component.

Keep it descriptive and separate from Model A until a frozen historical validation shows that any fatigue or travel adjustment improves predictions.

### P1 — Projection Accuracy Explorer

Expand Model Tracking beyond headline ATS results:

- Margin MAE, RMSE, signed bias, median absolute error, and percent within 3/7/10 points.
- Total MAE and signed total bias.
- SU accuracy, Brier score, and calibration by win-probability bin.
- ATS and totals records only where a frozen market line existed.
- Cuts by week, conference, projected-spread bucket, market-spread bucket, confidence status, home/road/neutral, favorite/underdog, and closing-line availability.
- Exact sample sizes and uncertainty intervals.
- Frozen snapshot timestamp and model/data version.

Margin error should remain the primary model-quality measure. ATS and O/U records are market comparisons and should never be presented without their denominator and frozen line definition.

### P1 — Position Room and Player Profile views

Keep the existing THI Production rating, but make the supporting statistics position-specific.

- QB: attempts, completion rate, yards/attempt, TD/INT, EPA/dropback, adjusted EPA/opportunity, success, designed-rush and scramble production when reliably identified.
- RB: carries, rush share, yards/carry, EPA/carry, success, stuff, power, line/second-level/open-field yards, targets and receiving EPA where supported.
- WR/TE: targets, target share, receptions, catch rate, yards/target, receiving EPA/target, success, explosive receptions, and route/depth metrics only when coverage clears an audit.
- DL/LB/DB: tackles, TFL, sacks, interceptions, pass breakups, forced fumbles, verified disruption events, and reliability/sample context.
- K/P/returners: dedicated tables only after consistent national stat coverage is verified.

Add a team `Position Rooms` panel that shows the top verified players, depth coverage, class, transfer status, workload share, and availability. It should describe observed production; it should not imitate a proprietary snap grade.

### P2 — Drive and Control views

THI already has postgame drive and play data. Add two focused displays:

1. Drive Efficiency: points per drive, scoring rate, three-and-out rate, starting field position, points per opportunity, explosive-drive rate, and red-zone TD rate.
2. Game Control Timeline: postgame win-expectancy trajectory, lead changes, largest swing, time leading, and decisive sequence.

The timeline must be labeled retrospective and kept distinct from the existing THI Game Control rating, which has a different definition.

### P2 — Regression Watch

Extend the current Luck & Conversion panel into a descriptive regression board:

- Actual wins versus expected wins.
- One-score record.
- Turnover points and fumble-recovery deviation.
- Actual margin versus underlying expected margin.
- Third/fourth-down conversion deviation.
- Explosive-play dependency.
- Finishing-drives overperformance.

Do not label a team as due to improve or decline until a frozen, walk-forward model validates that the feature predicts future results. Until then use `Overperforming underlying profile` and `Underperforming underlying profile`.

## Useful ideas that THI already covers

- Postgame win expectancy and luck.
- Advanced offense/defense metrics and matchup comparisons.
- Team-specific home-field advantage.
- Situational schedule context.
- Frozen projection grading and public model tracking.
- Player production ratings and position ranks.
- Team dossiers, season results, spread results, and totals results.

These areas need clearer visual summaries and navigation more than duplicate pages.

## Ideas to withhold

- Do not ingest Punt & Rally ratings, rankings, tables, or calculated outputs.
- Do not recreate named proprietary composites such as another site's power, Ash, Detmer, Momentum Control, or Composite Control rating.
- Do not publish blocking credit, yards after contact, missed tackles forced, route participation, pressure rate, or coverage grades unless THI has a permitted national source and passes a coverage audit.
- Do not treat text-parsed run direction or depth of target as complete without publishing placement coverage and uncertainty.
- Do not turn descriptive situational splits into Model A adjustments without walk-forward validation.
- Do not promote tiny ATS or player samples with color alone. Show `n`, uncertainty, and the break-even reference.

## CBB adaptation

The existing CBB efficiency landscape already establishes the visual foundation. Once CBB rosters and live samples clear their gates, add chart presets for:

- Offensive efficiency vs defensive efficiency.
- Tempo vs net efficiency.
- eFG% vs turnover rate.
- Offensive-rebound rate vs free-throw rate.
- Roster continuity vs structural power.
- Current form vs preseason baseline.

Projected and observed data must remain visually distinct, and the provisional preseason disclosure must stay attached to every preseason view.

## Source pages reviewed

- https://www.puntandrally.com/chart.php
- https://www.puntandrally.com/advancedstats.php
- https://www.puntandrally.com/playerstats.php
- https://www.puntandrally.com/airandground.php
- https://www.puntandrally.com/productive_players.php
- https://www.puntandrally.com/ratingtracker.php
- https://www.puntandrally.com/composite_leaderboard.php
- https://www.puntandrally.com/game_control.php
- https://www.puntandrally.com/projection_accuracy.php
- https://www.puntandrally.com/what-matters-most.php
- https://www.puntandrally.com/winexpectancy.php
- https://www.puntandrally.com/regressionwatch.php
- https://www.puntandrally.com/toughest_stretches.php
- https://www.puntandrally.com/backtest_situational.php
- https://www.puntandrally.com/backtest_elevation.php
- https://www.puntandrally.com/homefieldadvantage.php
- https://www.puntandrally.com/teamprofile.php?team=Ohio%20State
- https://www.puntandrally.com/playersearch.php?name=Jeremiah%20Smith&team=Ohio%20State
- https://www.puntandrally.com/css_leaderboard.php
- https://www.puntandrally.com/spreadstats.php
- https://www.puntandrally.com/aboutus.php
