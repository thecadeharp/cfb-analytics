(() => {
  "use strict";

  const RESULTS_URL = "./data/results.json";
  const POSTGAME_URL = "./data/postgame_analytics.json";
  const STYLE_ID = "hammer-final-matchup-styles";
  const POSTGAME_SECTION_ID = "hammer-postgame-analysis";

  let finalGames = [];
  let postgameGames = [];
  let observer = null;
  let applying = false;

  // ==========================================================================
  // HELPERS
  // ==========================================================================

  function canonical(value) {
    return String(value || "")
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/&/g, "and")
      .replace(/[.'’(),_-]/g, " ")
      .replace(/\buniversity\b/g, "")
      .replace(/\bst\b/g, "state")
      .replace(/\bmich\b/g, "michigan")
      .replace(/\s+/g, " ")
      .trim();
  }

  function normalizedTeam(value) {
    const text = canonical(value);

    const aliases = {
      "umass": "massachusetts",
      "massachusetts": "massachusetts",

      "usc": "southern california",
      "southern cal": "southern california",
      "southern california": "southern california",

      "jacksonville state": "jacksonville state",
      "north dakota state": "north dakota state",
      "new mexico state": "new mexico state",
      "florida state": "florida state",
      "sacramento state": "sacramento state",
      "eastern michigan": "eastern michigan",
      "san jose state": "san jose state",

      "hawaii": "hawaii",
      "hawai i": "hawaii",

      "n c a and t": "north carolina a and t",
      "nc a and t": "north carolina a and t",
      "north carolina a and t": "north carolina a and t",

      "georgia state": "georgia state",

      "liu": "long island",
      "long island": "long island",
      "long island university": "long island"
    };

    return aliases[text] || text;
  }

  function sameTeam(a, b) {
    return normalizedTeam(a) === normalizedTeam(b);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function number(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function fmt(value, digits = 1) {
    const parsed = number(value);
    return parsed === null ? "—" : parsed.toFixed(digits);
  }

  function fmtSigned(value, digits = 1) {
    const parsed = number(value);
    if (parsed === null) return "—";
    return `${parsed > 0 ? "+" : ""}${parsed.toFixed(digits)}`;
  }

  function fmtPct(value) {
    const parsed = number(value);
    return parsed === null ? "—" : `${parsed.toFixed(1)}%`;
  }

  function fmtInt(value) {
    const parsed = number(value);
    return parsed === null ? "—" : String(Math.round(parsed));
  }

  function matchupFind(rows, away, home) {
    return (
      rows.find(game =>
        sameTeam(game?.away_team, away) &&
        sameTeam(game?.home_team, home)
      ) || null
    );
  }

  // ==========================================================================
  // STYLES
  // ==========================================================================

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;

    const style = document.createElement("style");
    style.id = STYLE_ID;

    style.textContent = `
      #matchup-container .projected-score-card.hammer-final-score-card {
        border-color: var(--border-dark);
      }

      #matchup-container .hammer-final-score-card .projected-score-title {
        color: var(--muted);
      }

      #matchup-container .hammer-final-pregame-block {
        margin-top: 13px;
        padding-top: 12px;
        border-top: 1px solid #eeeeeb;
      }

      #matchup-container .hammer-final-pregame-heading {
        margin-bottom: 9px;
        color: var(--muted);
        font-family: var(--mono);
        font-size: 8px;
        font-weight: 700;
        letter-spacing: 1px;
        text-transform: uppercase;
      }

      #matchup-container .hammer-final-pregame-score {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
        gap: 12px;
        align-items: center;
      }

      #matchup-container .hammer-final-pregame-team {
        min-width: 0;
      }

      #matchup-container .hammer-final-pregame-team:last-child {
        text-align: right;
      }

      #matchup-container .hammer-final-pregame-name {
        color: var(--muted);
        font-size: 10px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      #matchup-container .hammer-final-pregame-points {
        margin-top: 3px;
        color: var(--muted);
        font-family: var(--mono);
        font-size: 17px;
        font-weight: 700;
      }

      #matchup-container .hammer-final-pregame-separator {
        color: var(--muted);
        font-family: var(--mono);
        font-size: 9px;
        font-weight: 700;
      }

      #matchup-container .hammer-final-pregame-note {
        margin-top: 9px;
        color: var(--muted);
        font-family: var(--mono);
        font-size: 8px;
        line-height: 1.5;
      }

      .hammer-postgame-board-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        margin-top: 6px;
        margin-left: 6px;
        padding: 4px 7px;
        border: 1px solid #c8b15b;
        border-radius: 999px;
        background: #fff7d6;
        color: #6c5a13;
        font-family: var(--mono);
        font-size: 8px;
        font-weight: 900;
        letter-spacing: .65px;
        line-height: 1;
        text-transform: uppercase;
        white-space: nowrap;
      }

      .hammer-postgame-board-badge.pending {
        border-color: var(--border);
        background: #f4f4f2;
        color: var(--muted);
      }

      #${POSTGAME_SECTION_ID} {
        margin-top: 22px;
        padding: 18px;
        border: 1px solid var(--border-dark);
        border-radius: var(--radius);
        background: var(--surface);
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-kicker {
        color: var(--muted);
        font-family: var(--mono);
        font-size: 8px;
        font-weight: 900;
        letter-spacing: 1.3px;
        text-transform: uppercase;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-title {
        margin-top: 5px;
        color: var(--ink);
        font-size: 20px;
        font-weight: 900;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-subtitle {
        margin-top: 5px;
        color: var(--muted);
        font-size: 11px;
        line-height: 1.55;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-beta {
        display: inline-flex;
        margin-top: 10px;
        padding: 5px 8px;
        border: 1px solid #e1c86c;
        border-radius: 999px;
        background: #fff8dd;
        color: #6f5d1a;
        font-family: var(--mono);
        font-size: 8px;
        font-weight: 900;
        letter-spacing: .7px;
        text-transform: uppercase;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-headlines {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
        margin-top: 16px;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-card {
        padding: 13px;
        border: 1px solid var(--border);
        border-radius: 10px;
        background: #fafaf8;
        min-width: 0;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-card-label {
        color: var(--muted);
        font-family: var(--mono);
        font-size: 8px;
        font-weight: 900;
        letter-spacing: .7px;
        text-transform: uppercase;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-card-value {
        margin-top: 6px;
        color: var(--ink);
        font-family: var(--mono);
        font-size: 18px;
        font-weight: 900;
        line-height: 1.1;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-card-note {
        margin-top: 6px;
        color: var(--muted);
        font-size: 9px;
        line-height: 1.45;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        margin-top: 14px;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-panel {
        padding: 13px;
        border: 1px solid var(--border);
        border-radius: 10px;
        background: #fff;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-panel-title {
        margin-bottom: 10px;
        color: var(--ink);
        font-family: var(--mono);
        font-size: 9px;
        font-weight: 900;
        letter-spacing: .65px;
        text-transform: uppercase;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-row {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto auto;
        gap: 10px;
        align-items: center;
        padding: 6px 0;
        border-top: 1px solid #f0f0ed;
        font-size: 10px;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-row:first-of-type {
        border-top: 0;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-row-label {
        color: var(--muted);
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-row-away,
      #${POSTGAME_SECTION_ID} .hammer-pg-row-home {
        min-width: 56px;
        text-align: right;
        color: var(--ink);
        font-family: var(--mono);
        font-weight: 800;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-team-head {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto auto;
        gap: 10px;
        padding-bottom: 6px;
        color: var(--muted);
        font-family: var(--mono);
        font-size: 8px;
        font-weight: 900;
        text-transform: uppercase;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-team-head span:nth-child(2),
      #${POSTGAME_SECTION_ID} .hammer-pg-team-head span:nth-child(3) {
        min-width: 56px;
        text-align: right;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-footer {
        margin-top: 14px;
        padding-top: 12px;
        border-top: 1px solid var(--border);
        color: var(--muted);
        font-size: 9px;
        line-height: 1.55;
      }

      #${POSTGAME_SECTION_ID}.pending {
        background: #fafaf8;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-pending {
        margin-top: 12px;
        padding: 12px;
        border: 1px dashed var(--border-dark);
        border-radius: 10px;
        color: var(--muted);
        font-size: 11px;
        line-height: 1.6;
      }

      @media (max-width: 760px) {
        #${POSTGAME_SECTION_ID} .hammer-pg-headlines {
          grid-template-columns: 1fr;
        }

        #${POSTGAME_SECTION_ID} .hammer-pg-grid {
          grid-template-columns: 1fr;
        }
      }

      @media (max-width: 600px) {
        #matchup-container .hammer-final-pregame-score {
          gap: 8px;
        }

        #matchup-container .hammer-final-pregame-points {
          font-size: 15px;
        }

        #${POSTGAME_SECTION_ID} {
          padding: 14px;
        }

        #${POSTGAME_SECTION_ID} .hammer-pg-card-value {
          font-size: 16px;
        }
      }
    `;

    document.head.appendChild(style);
  }

  // ==========================================================================
  // DATA
  // ==========================================================================

  async function fetchJson(url) {
    const response = await fetch(
      `${url}?v=${Date.now()}`,
      { cache: "no-store" }
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    return response.json();
  }

  async function loadData() {
    const [resultsResult, postgameResult] = await Promise.allSettled([
      fetchJson(RESULTS_URL),
      fetchJson(POSTGAME_URL)
    ]);

    if (resultsResult.status === "fulfilled") {
      const payload = resultsResult.value;
      finalGames = Array.isArray(payload?.games)
        ? payload.games.filter(game =>
            ["final", "completed"].includes(
              String(game?.game_state || game?.status || "").toLowerCase()
            )
          )
        : [];
    }

    if (postgameResult.status === "fulfilled") {
      postgameGames = Array.isArray(postgameResult.value?.games)
        ? postgameResult.value.games
        : [];
    }

    applyAll();
  }

  // ==========================================================================
  // SCORE CARD / CURRENT MATCHUP
  // ==========================================================================

  function currentScoreCard() {
    return document.querySelector(
      "#matchup-container .projected-score-card"
    );
  }

  function scoreCardTeams(card) {
    if (!card) return null;

    const teams = Array.from(
      card.querySelectorAll(".projected-team")
    );

    if (teams.length < 2) return null;

    const awayName = teams[0]
      .querySelector(".projected-team-name")
      ?.textContent
      ?.trim();

    const homeName = teams[1]
      .querySelector(".projected-team-name")
      ?.textContent
      ?.trim();

    if (!awayName || !homeName) return null;

    return {
      awayName,
      homeName,
      awayNode: teams[0],
      homeNode: teams[1]
    };
  }

  function findFinal(awayName, homeName) {
    return matchupFind(finalGames, awayName, homeName);
  }

  function findPostgame(awayName, homeName) {
    return matchupFind(postgameGames, awayName, homeName);
  }

  function readPregameProjection(nodes) {
    const awayScore = nodes.awayNode
      .querySelector(".projected-team-score")
      ?.textContent
      ?.trim();

    const homeScore = nodes.homeNode
      .querySelector(".projected-team-score")
      ?.textContent
      ?.trim();

    if (
      awayScore === undefined ||
      awayScore === null ||
      homeScore === undefined ||
      homeScore === null
    ) {
      return null;
    }

    return {
      awayName: nodes.awayName,
      homeName: nodes.homeName,
      awayScore,
      homeScore
    };
  }

  function pregameMarkup(projection) {
    return `
      <div class="hammer-final-pregame-block">
        <div class="hammer-final-pregame-heading">
          Pregame Model Projection
        </div>

        <div class="hammer-final-pregame-score">
          <div class="hammer-final-pregame-team">
            <div class="hammer-final-pregame-name">
              ${escapeHtml(projection.awayName)}
            </div>
            <div class="hammer-final-pregame-points">
              ${escapeHtml(projection.awayScore)}
            </div>
          </div>

          <div class="hammer-final-pregame-separator">
            —
          </div>

          <div class="hammer-final-pregame-team">
            <div class="hammer-final-pregame-name">
              ${escapeHtml(projection.homeName)}
            </div>
            <div class="hammer-final-pregame-points">
              ${escapeHtml(projection.homeScore)}
            </div>
          </div>
        </div>

        <div class="hammer-final-pregame-note">
          Pregame projection preserved for reference. Actual final score shown above.
        </div>
      </div>
    `;
  }

  function applyFinalToCurrentMatchup() {
    const card = currentScoreCard();
    if (!card) return null;

    const nodes = scoreCardTeams(card);
    if (!nodes) return null;

    const final = findFinal(nodes.awayName, nodes.homeName);
    if (!final) {
      removePostgameSection();
      return null;
    }

    if (card.dataset.hammerFinalApplied !== "true") {
      const projection = readPregameProjection(nodes);
      if (!projection) return final;

      const awayPoints = Number(final.away_points);
      const homePoints = Number(final.home_points);

      if (
        !Number.isFinite(awayPoints) ||
        !Number.isFinite(homePoints)
      ) {
        return final;
      }

      const title = card.querySelector(".projected-score-title");
      const separator = card.querySelector(".projected-score-separator");
      const awayNameNode = nodes.awayNode.querySelector(".projected-team-name");
      const awayScoreNode = nodes.awayNode.querySelector(".projected-team-score");
      const homeNameNode = nodes.homeNode.querySelector(".projected-team-name");
      const homeScoreNode = nodes.homeNode.querySelector(".projected-team-score");

      if (
        !title ||
        !awayNameNode ||
        !awayScoreNode ||
        !homeNameNode ||
        !homeScoreNode
      ) {
        return final;
      }

      card.dataset.hammerFinalApplied = "true";
      title.textContent = "Final Score";
      awayNameNode.textContent = final.away_team || projection.awayName;
      awayScoreNode.textContent = String(awayPoints);
      homeNameNode.textContent = final.home_team || projection.homeName;
      homeScoreNode.textContent = String(homePoints);

      if (separator) {
        separator.textContent = "FINAL";
      }

      const oldPregame = card.querySelector(
        ".hammer-final-pregame-block"
      );

      if (oldPregame) {
        oldPregame.remove();
      }

      card.insertAdjacentHTML(
        "beforeend",
        pregameMarkup(projection)
      );

      card.classList.add("hammer-final-score-card");
    }

    return final;
  }

  // ==========================================================================
  // POSTGAME ANALYSIS MARKUP
  // ==========================================================================

  function removePostgameSection() {
    document.getElementById(POSTGAME_SECTION_ID)?.remove();
  }

  function metricRow(label, away, home) {
    return `
      <div class="hammer-pg-row">
        <span class="hammer-pg-row-label">${escapeHtml(label)}</span>
        <span class="hammer-pg-row-away">${escapeHtml(away)}</span>
        <span class="hammer-pg-row-home">${escapeHtml(home)}</span>
      </div>
    `;
  }

  function panel(title, awayName, homeName, rows) {
    return `
      <div class="hammer-pg-panel">
        <div class="hammer-pg-panel-title">${escapeHtml(title)}</div>
        <div class="hammer-pg-team-head">
          <span>Metric</span>
          <span>${escapeHtml(awayName)}</span>
          <span>${escapeHtml(homeName)}</span>
        </div>
        ${rows.join("")}
      </div>
    `;
  }

  function pendingPostgameMarkup(final, postgame) {
    return `
      <section id="${POSTGAME_SECTION_ID}" class="pending">
        <div class="hammer-pg-kicker">🔨 Postgame Analysis</div>
        <div class="hammer-pg-title">Postgame analysis pending</div>
        <div class="hammer-pg-subtitle">
          The final score is official. THI is waiting for matching play-by-play
          before publishing efficiency, drive, variance and Reality Check metrics.
        </div>
        <div class="hammer-pg-pending">
          ${escapeHtml(
            postgame?.source_note ||
            "The automatic settlement workflow will retry this game. No retrospective metric is fabricated while PBP is unavailable."
          )}
        </div>
      </section>
    `;
  }

  function availablePostgameMarkup(final, pg) {
    const away = pg.away_team || final.away_team;
    const home = pg.home_team || final.home_team;

    const headline = pg.headline || {};
    const pwe = headline.postgame_win_expectancy || {};
    const adjusted = headline.adjusted_final_score || {};
    const reality = headline.reality_check || {};

    const efficiency = pg.efficiency || {};
    const explosive = pg.explosiveness || {};
    const turnovers = pg.turnovers || {};
    const finishing = pg.finishing_drives || {};
    const drive = pg.drive_efficiency || {};
    const field = pg.field_position || {};
    const early = pg.early_downs || {};
    const money = pg.money_downs || {};
    const redzone = pg.red_zone || {};
    const control = pg.game_control || {};
    const garbage = pg.garbage_time || {};
    const variance = pg.variance || {};

    const panels = [
      panel(
        "Efficiency",
        away,
        home,
        [
          metricRow(
            "EPA / Play",
            fmt(efficiency.away_epa_per_play, 3),
            fmt(efficiency.home_epa_per_play, 3)
          ),
          metricRow(
            "Success Rate",
            fmtPct(efficiency.away_success_rate),
            fmtPct(efficiency.home_success_rate)
          ),
          metricRow(
            "Game Control",
            fmtPct(control.away_pct),
            fmtPct(control.home_pct)
          )
        ]
      ),

      panel(
        "Explosiveness + Turnovers",
        away,
        home,
        [
          metricRow(
            "Explosive Rate",
            fmtPct(explosive.away_explosive_rate),
            fmtPct(explosive.home_explosive_rate)
          ),
          metricRow(
            "Explosive Plays",
            fmtInt(explosive.away_explosive_plays),
            fmtInt(explosive.home_explosive_plays)
          ),
          metricRow(
            "Explosive EPA Dependence",
            fmtPct(explosive.away_explosive_epa_dependence_pct),
            fmtPct(explosive.home_explosive_epa_dependence_pct)
          ),
          metricRow(
            "Turnovers",
            fmtInt(turnovers.away_turnovers),
            fmtInt(turnovers.home_turnovers)
          )
        ]
      ),

      panel(
        "Finishing Drives",
        away,
        home,
        [
          metricRow(
            "Scoring Opportunities",
            fmtInt(finishing.away_scoring_opportunities),
            fmtInt(finishing.home_scoring_opportunities)
          ),
          metricRow(
            "Pts / Opportunity",
            fmt(finishing.away_points_per_opportunity, 2),
            fmt(finishing.home_points_per_opportunity, 2)
          ),
          metricRow(
            "Pts / Drive",
            fmt(drive.away_points_per_drive, 2),
            fmt(drive.home_points_per_drive, 2)
          ),
          metricRow(
            "Yards / Drive",
            fmt(drive.away_yards_per_drive, 1),
            fmt(drive.home_yards_per_drive, 1)
          ),
          metricRow(
            "Scoring Drive Rate",
            fmtPct(drive.away_scoring_drive_rate),
            fmtPct(drive.home_scoring_drive_rate)
          )
        ]
      ),

      panel(
        "Downs + Red Zone",
        away,
        home,
        [
          metricRow(
            "Early Down EPA / Play",
            fmt(early.away_epa_per_play, 3),
            fmt(early.home_epa_per_play, 3)
          ),
          metricRow(
            "Early Down Success",
            fmtPct(early.away_success_rate),
            fmtPct(early.home_success_rate)
          ),
          metricRow(
            "3rd/4th Down EPA / Play",
            fmt(money.away_epa_per_play, 3),
            fmt(money.home_epa_per_play, 3)
          ),
          metricRow(
            "3rd/4th Down Success",
            fmtPct(money.away_success_rate),
            fmtPct(money.home_success_rate)
          ),
          metricRow(
            "Red Zone EPA / Play",
            fmt(redzone.away_epa_per_play, 3),
            fmt(redzone.home_epa_per_play, 3)
          ),
          metricRow(
            "Red Zone Success",
            fmtPct(redzone.away_success_rate),
            fmtPct(redzone.home_success_rate)
          )
        ]
      ),

      panel(
        "Field Position + Variance",
        away,
        home,
        [
          metricRow(
            "Avg Start Yds to Goal",
            fmt(field.away_avg_start_yards_to_goal, 1),
            fmt(field.home_avg_start_yards_to_goal, 1)
          ),
          metricRow(
            "Turnover Luck Proxy",
            turnovers.home_turnover_luck_proxy_points === null ||
            turnovers.home_turnover_luck_proxy_points === undefined
              ? "—"
              : fmtSigned(-Number(turnovers.home_turnover_luck_proxy_points), 1),
            fmtSigned(turnovers.home_turnover_luck_proxy_points, 1)
          ),
          metricRow(
            "Garbage-Time Play Rate",
            fmtPct(garbage.garbage_time_play_rate),
            fmtPct(garbage.garbage_time_play_rate)
          ),
          metricRow(
            "Game Variance Score",
            fmt(variance.game_variance_score, 1),
            fmt(variance.game_variance_score, 1)
          )
        ]
      ),

      panel(
        "Overperformance Diagnostics",
        away,
        home,
        [
          metricRow(
            "Money Down vs Early",
            fmtSigned(money.away_overperformance_vs_early_pp, 1) + " pp",
            fmtSigned(money.home_overperformance_vs_early_pp, 1) + " pp"
          ),
          metricRow(
            "Field Position Edge",
            field.home_field_position_edge_yards === null ||
            field.home_field_position_edge_yards === undefined
              ? "—"
              : fmtSigned(-Number(field.home_field_position_edge_yards), 1) + " yd",
            fmtSigned(field.home_field_position_edge_yards, 1) + " yd"
          ),
          metricRow(
            "EPA Margin",
            efficiency.epa_margin === null ||
            efficiency.epa_margin === undefined
              ? "—"
              : fmtSigned(-Number(efficiency.epa_margin), 3),
            fmtSigned(efficiency.epa_margin, 3)
          ),
          metricRow(
            "Success Rate Margin",
            efficiency.success_rate_margin_pp === null ||
            efficiency.success_rate_margin_pp === undefined
              ? "—"
              : fmtSigned(-Number(efficiency.success_rate_margin_pp), 1) + " pp",
            fmtSigned(efficiency.success_rate_margin_pp, 1) + " pp"
          )
        ]
      )
    ];

    return `
      <section id="${POSTGAME_SECTION_ID}">
        <div class="hammer-pg-kicker">🔨 Postgame Analysis</div>
        <div class="hammer-pg-title">What actually happened?</div>
        <div class="hammer-pg-subtitle">
          Retrospective play-by-play diagnostics. The frozen pregame THI projection
          above is never rewritten after the game.
        </div>
        <div class="hammer-pg-beta">
          ${escapeHtml(pg.calibration_status || "BETA — historical calibration pending")}
        </div>

        <div class="hammer-pg-headlines">
          <div class="hammer-pg-card">
            <div class="hammer-pg-card-label">Postgame Win Expectancy</div>
            <div class="hammer-pg-card-value">
              ${escapeHtml(away)} ${fmtPct(pwe.away_pct)}
              ·
              ${escapeHtml(home)} ${fmtPct(pwe.home_pct)}
            </div>
            <div class="hammer-pg-card-note">
              Process-based retrospective probability, not the live win probability.
            </div>
          </div>

          <div class="hammer-pg-card">
            <div class="hammer-pg-card-label">Adjusted Final Score</div>
            <div class="hammer-pg-card-value">
              ${escapeHtml(away)} ${fmt(adjusted.away, 1)}
              —
              ${escapeHtml(home)} ${fmt(adjusted.home, 1)}
            </div>
            <div class="hammer-pg-card-note">
              Score estimate from underlying efficiency, possessions and field position.
            </div>
          </div>

          <div class="hammer-pg-card">
            <div class="hammer-pg-card-label">THI Reality Check</div>
            <div class="hammer-pg-card-value">
              ${escapeHtml(reality.label || "—")}
            </div>
            <div class="hammer-pg-card-note">
              ${escapeHtml(reality.note || "")}
            </div>
          </div>
        </div>

        <div class="hammer-pg-grid">
          ${panels.join("")}
        </div>

        <div class="hammer-pg-footer">
          <strong>Garbage-time impact:</strong>
          ${fmtInt(garbage.garbage_time_plays)} of
          ${fmtInt(garbage.total_scrimmage_plays)} qualifying scrimmage plays
          flagged (${fmtPct(garbage.garbage_time_play_rate)}).
          <br>
          <strong>Turnover Luck:</strong>
          ${escapeHtml(turnovers.note || "Displayed as a transparent turnover-leverage proxy.")}
          <br>
          Source: ${escapeHtml(pg.source || "SportsDataverse/cfbfastR PBP")}.
          Postgame Win Expectancy and Adjusted Final Score remain beta until the
          historical calibration suite is completed.
        </div>
      </section>
    `;
  }

  function renderPostgame(final) {
    const container = document.getElementById("matchup-container");
    if (!container || !final) return;

    const postgame = findPostgame(
      final.away_team,
      final.home_team
    );

    removePostgameSection();

    if (!postgame || postgame.analysis_status !== "available") {
      container.insertAdjacentHTML(
        "beforeend",
        pendingPostgameMarkup(final, postgame)
      );
      return;
    }

    container.insertAdjacentHTML(
      "beforeend",
      availablePostgameMarkup(final, postgame)
    );
  }

  // ==========================================================================
  // PROJECTIONS BOARD AVAILABILITY BADGES
  // ==========================================================================

  function boardRowTeams(row) {
    const names = Array.from(
      row.querySelectorAll(".matchup-cell .team-name")
    )
      .map(node => node.textContent?.trim())
      .filter(Boolean);

    if (names.length < 2) return null;

    return {
      away: names[0],
      home: names[1]
    };
  }

  function decorateBoardPostgameBadges() {
    const rows = document.querySelectorAll(
      "#projections-container .projection-table tbody tr.game-row"
    );

    rows.forEach(row => {
      row.querySelectorAll(".hammer-postgame-board-badge")
        .forEach(node => node.remove());

      const teams = boardRowTeams(row);
      if (!teams) return;

      const final = findFinal(teams.away, teams.home);
      if (!final) return;

      const pg = findPostgame(teams.away, teams.home);

      const badge = document.createElement("span");
      badge.className = "hammer-postgame-board-badge";

      if (pg?.analysis_status === "available") {
        badge.textContent = "POSTGAME ANALYSIS AVAILABLE";
      } else {
        badge.classList.add("pending");
        badge.textContent = "POSTGAME ANALYSIS PENDING";
      }

      const meta =
        row.querySelector(".hammer-game-status-meta") ||
        row.querySelector(".matchup-cell");

      meta?.appendChild(badge);
    });
  }

  // ==========================================================================
  // APPLY / OBSERVER
  // ==========================================================================

  function applyAll() {
    if (applying) return;

    applying = true;

    try {
      const final = applyFinalToCurrentMatchup();
      if (final) {
        renderPostgame(final);
      }
      decorateBoardPostgameBadges();
    } finally {
      applying = false;
    }
  }

  function scheduleApply() {
    requestAnimationFrame(applyAll);
  }

  function installObserver() {
    const targets = [
      document.getElementById("matchup-container"),
      document.getElementById("projections-container")
    ].filter(Boolean);

    if (!targets.length) {
      setTimeout(installObserver, 250);
      return;
    }

    if (observer) {
      observer.disconnect();
    }

    observer = new MutationObserver(() => {
      if (!applying) {
        scheduleApply();
      }
    });

    targets.forEach(target => {
      observer.observe(
        target,
        {
          childList: true,
          subtree: true
        }
      );
    });

    scheduleApply();
  }

  // ==========================================================================
  // START
  // ==========================================================================

  async function start() {
    installStyles();

    await loadData();

    installObserver();

    // Open browsers update once per minute. The source workflow refreshes every
    // five minutes and postgame PBP retries automatically when necessary.
    setInterval(
      loadData,
      60000
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      start,
      { once: true }
    );
  } else {
    start();
  }
})();
