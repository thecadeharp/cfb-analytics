# Postgame expected score and roster availability: build contract

Status: research and source-link presentation are in progress. Do not replace the current beta `postgame_win_expectancy` or `adjusted_final_score` outputs until historical validation passes. This work is separate from Model A and its frozen pregame snapshots.

First research stage implemented: `scripts/research_expected_score.py` consumes the existing game-level historical table, fits a ridge baseline on 2019–2024 using *realized* drives and scoring-opportunity counts (no actual scores as inputs), and tests on sealed 2025 games. The manually dispatched `Expected Score Research` workflow writes a private-to-the-product research report at `data/research/expected_score_holdout_2025.json`; the repository is public, so this report is publicly inspectable but **not rendered on the site**. It does not yet extract a possession ledger or separate non-offensive scoring. Its MAE and calibration bins are diagnostics, not clearance to publish adjusted scores.

**Research correction (September 2026):** The play-by-play feed has out-of-order rows and score stamps that go backward. In one 2025 game, the historical builder selected a first-quarter score as the final because that row carried the highest `game_play_number`. The previously reported expected-score MAE must **not** be used as a trusted performance estimate until its targets and train/test selection are rebuilt and reevaluated from verified scores. Do not modify the production projection engine to address this research issue.

Second research stage: `scripts/research_possession_ledger.py` downloads the same historical annual play-by-play assets, maps possession drives using the historical builder's team-ID logic, and checks score stamps, field position, EPA samples, and opponent scores on possession drives. The manual `Possession Ledger Audit` workflow keeps the drive CSVs temporary and commits only `data/research/possession_ledger_audit.json`. The possession team's score change is a **proxy**, not yet a clean offensive-points label; this audit must be inspected before fitting a possession-level expected-score model. This stage does not change Model A or any visible postgame scores.

Third research stage: `scripts/reconstruct_scoring_events.py` counts tagged touchdowns, field goals, safeties, and defensive two-point returns by their identified scoring team. It never uses score changes on untagged plays. For older seasons missing PAT metadata, it accepts a 6/7/8 point increment only on that **tagged touchdown event** and only when the scoring team can be identified. It picks a candidate final score by period and clock, then admits only games whose tagged scoring total matches both teams' final score with no unresolved scoring event. The manual `Reconstruct Historical Scoring` workflow commits aggregate audit counts only. Even admitted games require cross-source final-score checks and drive-level attribution before model fitting or publication; excluded games may be a biased sample.

## Data that exists now

- Historical game, drive, and play records from published play-by-play; current `build_postgame_analytics.py` provides retrospective game summaries.
- Current advanced team metrics include points per opportunity (a drive reaching the opponent's 40). The accompanying Dossier panel reports EPA and success rate on plays at or inside the 40 with minimum samples, without predicting future improvement.
- The current postgame win expectancy is `sigmoid(quality_margin / 7.5)`. The current adjusted score blends observed total points and process summaries. Both are heuristic beta outputs, not a Monte Carlo simulation or calibrated win probabilities.

## Inputs not yet available

There is no verified player-by-game defensive snap ledger, dated injury/participation status, or per-player production share joined to the active roster in the site pipeline. Do not publish an injury-adjusted availability percentage, a 14-day defensive workload number, or a depth-based fatigue badge from incomplete records. A future source needs player/team/game IDs, actual snaps or participation, status and report timestamp, source attribution, corrections, and permissions for the intended display.

## Expected score proposal

1. Construct a historical **possession ledger**: game/team/drive IDs, field position at start, opponent, regulation and garbage-time flags, play-level EPA and success, possession result, offensive points, and non-offensive scores. Preserve score and clock at each play.
2. Define quality features known from the **completed game** and a target of realized offensive points per possession. Keep defensive and special-teams scores in separate channels. Do not train or evaluate a feature on that same game's final score or market line. Distinguish the retrospective task from a pregame forecast.
3. Fit a regularized scoring distribution on earlier seasons (rather than treating EPA as points). The first baseline is a possession-level expected-points model with opponent and field-position context. Summing expected possession points yields each team's expected offensive score; any special-teams/defensive component requires a separately justified model. Display a score interval alongside a point estimate.
4. Estimate retrospective win expectancy from the joint game-level scoring distribution, preserving shared pace and possession dependence. A simulation count such as 10,000 controls numerical noise only; it cannot fix a misspecified distribution. Record simulation seed and model version.
5. Validate on **future held-out seasons/weeks** with no training leakage: scoring MAE and calibration by point bands; win-probability reliability, Brier score, log loss, and coverage of score intervals. Compare against the current beta and simpler baselines. Break results out by FBS/FCS opponent, garbage-time share, and missing PBP.
6. Publish only after sample and quality gates pass. Show source, build date, sample size, model version, confidence/availability label, and the frozen pregame projection alongside—but never overwrite it. If PBP is delayed or incomplete, show pending rather than a fabricated estimate.

## Roster Notes v0.1

`data/roster_notes.json` stores official conference report index links for ACC, Big Ten, Big 12, SEC, and Pac-12 and optional team notes written by THI. The Dossier panel displays only notes with text, HTTPS source URL, verification UTC timestamp, and expiration UTC timestamp; notes older than seven days or past expiration do not display. An empty list means no verified note, never healthy. The index links do not imply all games are covered. No automated scraping, player-by-game joins, fatigue estimates, injury-adjusted availability, Model A changes, or per-player production shares are implemented.

Example note entry, after independent verification: `"Team Name": [{"text":"THI-written summary of the report", "source_url":"https://official-source.example/report", "verified_at_utc":"2026-09-23T18:00:00Z", "valid_until_utc":"2026-09-26T18:00:00Z"}]`. Only add a specific player status after inspecting the source and confirming display rights; do not paste or republish report tables.

## Next implementation gate

Finish the historical possession ledger and a documented evaluation protocol first. Keep the roster availability feature on hold until actual snap and dated injury inputs exist. No site labels should imply that low PPO is mathematically bound to regress upward or that an expected margin identifies a guaranteed market edge.
