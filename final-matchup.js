(() => {
  "use strict";

  // ==========================================================================
  // THE HAMMER INDEX — FINAL MATCHUP + CANONICAL POSTGAME UI
  //
  // Responsibilities:
  // 1) Preserve frozen pregame projection and replace headline score with FINAL.
  // 2) Read data/postgame_analytics.json.
  // 3) Render the exact canonical postgame metric package.
  // 4) Maintain exactly ONE projection-board postgame status pill:
  //      AVAILABLE -> purple existing pill says POSTGAME ANALYSIS AVAILABLE
  //      PENDING   -> same purple existing pill says POSTGAME ANALYSIS PENDING
  //    This file NEVER creates a second yellow postgame badge.
  // 5) Never call a game "pending" merely because the JSON fetch failed.
  // ==========================================================================

  const RESULTS_URL = "./data/results.json";
  const POSTGAME_URL = "./data/postgame_analytics.json";
  const STYLE_ID = "hammer-final-matchup-styles-v3";
  const POSTGAME_SECTION_ID = "hammer-postgame-analysis";

  let finalGames = [];
  let postgameGames = [];
  let postgameDataLoaded = false;
  let observer = null;
  let applying = false;

  // ==========================================================================
  // NORMALIZATION
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

  function matchupFind(rows, away, home) {
    return (
      rows.find(game =>
        sameTeam(game?.away_team, away) &&
        sameTeam(game?.home_team, home)
      ) || null
    );
  }

  // ==========================================================================
  // FORMATTERS
  // ==========================================================================

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function numeric(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function fmt(value, digits = 1) {
    const number = numeric(value);
    return number === null
      ? "—"
      : number.toFixed(digits);
  }

  function fmtSigned(value, digits = 1) {
    const number = numeric(value);

    if (number === null) {
      return "—";
    }

    return (
      `${number > 0 ? "+" : ""}${number.toFixed(digits)}`
    );
  }

  function fmtPct(value) {
    const number = numeric(value);
    return number === null
      ? "—"
      : `${number.toFixed(1)}%`;
  }

  function fmtInt(value) {
    const number = numeric(value);
    return number === null
      ? "—"
      : String(Math.round(number));
  }

  // ==========================================================================
  // STYLES
  // ==========================================================================

  function installStyles() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }

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
        margin-top:13px;
        padding-top:12px;
        border-top:1px solid #eeeeeb;
      }

      #matchup-container .hammer-final-pregame-heading {
        margin-bottom:9px;
        color:var(--muted);
        font-family:var(--mono);
        font-size:8px;
        font-weight:700;
        letter-spacing:1px;
        text-transform:uppercase;
      }

      #matchup-container .hammer-final-pregame-score {
        display:grid;
        grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);
        gap:12px;
        align-items:center;
      }

      #matchup-container .hammer-final-pregame-team {
        min-width:0;
      }

      #matchup-container .hammer-final-pregame-team:last-child {
        text-align:right;
      }

      #matchup-container .hammer-final-pregame-name {
        color:var(--muted);
        font-size:10px;
        white-space:nowrap;
        overflow:hidden;
        text-overflow:ellipsis;
      }

      #matchup-container .hammer-final-pregame-points {
        margin-top:3px;
        color:var(--muted);
        font-family:var(--mono);
        font-size:17px;
        font-weight:700;
      }

      #matchup-container .hammer-final-pregame-separator {
        color:var(--muted);
        font-family:var(--mono);
        font-size:9px;
        font-weight:700;
      }

      #matchup-container .hammer-final-pregame-note {
        margin-top:9px;
        color:var(--muted);
        font-family:var(--mono);
        font-size:8px;
        line-height:1.5;
      }

      /*
       * IMPORTANT:
       * No yellow postgame badge exists anymore.
       * Any leftover badge from an older cached script is forcibly hidden.
       */
      .hammer-postgame-board-badge {
        display:none !important;
      }

      .thi-postgame-status-purple {
        display:inline-flex;
        align-items:center;
        justify-content:center;
        margin-top:6px;
        margin-left:6px;
        padding:4px 7px;
        border:1px solid #b8a1d8;
        border-radius:999px;
        background:#f3eef9;
        color:#6d4c8f;
        font-family:var(--mono);
        font-size:8px;
        font-weight:900;
        letter-spacing:.65px;
        line-height:1;
        text-transform:uppercase;
        white-space:nowrap;
      }

      .thi-postgame-status-purple.pending {
        border-color:#c8bdd8;
        background:#f6f3fa;
        color:#7f6c92;
      }

      #${POSTGAME_SECTION_ID} {
        margin-top:22px;
        padding:18px;
        border:1px solid var(--border-dark);
        border-radius:var(--radius);
        background:var(--surface);
      }

      #${POSTGAME_SECTION_ID}.pending {
        background:#fafaf8;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-kicker {
        color:var(--muted);
        font-family:var(--mono);
        font-size:8px;
        font-weight:900;
        letter-spacing:1.3px;
        text-transform:uppercase;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-title {
        margin-top:5px;
        color:var(--ink);
        font-size:20px;
        font-weight:900;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-subtitle {
        margin-top:5px;
        color:var(--muted);
        font-size:11px;
        line-height:1.55;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-beta {
        display:inline-flex;
        margin-top:10px;
        padding:5px 8px;
        border:1px solid #e1c86c;
        border-radius:999px;
        background:#fff8dd;
        color:#6f5d1a;
        font-family:var(--mono);
        font-size:8px;
        font-weight:900;
        letter-spacing:.7px;
        text-transform:uppercase;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-headlines {
        display:grid;
        grid-template-columns:repeat(3,minmax(0,1fr));
        gap:10px;
        margin-top:16px;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-card {
        min-width:0;
        padding:13px;
        border:1px solid var(--border);
        border-radius:10px;
        background:#fafaf8;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-card-label {
        color:var(--muted);
        font-family:var(--mono);
        font-size:8px;
        font-weight:900;
        letter-spacing:.7px;
        text-transform:uppercase;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-card-value {
        margin-top:6px;
        color:var(--ink);
        font-family:var(--mono);
        font-size:18px;
        font-weight:900;
        line-height:1.15;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-card-note {
        margin-top:6px;
        color:var(--muted);
        font-size:9px;
        line-height:1.45;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-grid {
        display:grid;
        grid-template-columns:repeat(2,minmax(0,1fr));
        gap:10px;
        margin-top:14px;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-panel {
        padding:13px;
        border:1px solid var(--border);
        border-radius:10px;
        background:#fff;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-panel-title {
        margin-bottom:10px;
        color:var(--ink);
        font-family:var(--mono);
        font-size:9px;
        font-weight:900;
        letter-spacing:.65px;
        text-transform:uppercase;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-team-head,
      #${POSTGAME_SECTION_ID} .hammer-pg-row {
        display:grid;
        grid-template-columns:minmax(0,1fr) minmax(64px,auto) minmax(64px,auto);
        gap:10px;
        align-items:center;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-team-head {
        padding-bottom:6px;
        color:var(--muted);
        font-family:var(--mono);
        font-size:8px;
        font-weight:900;
        text-transform:uppercase;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-row {
        padding:6px 0;
        border-top:1px solid #f0f0ed;
        font-size:10px;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-row-label {
        color:var(--muted);
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-row-away,
      #${POSTGAME_SECTION_ID} .hammer-pg-row-home,
      #${POSTGAME_SECTION_ID} .hammer-pg-team-head span:nth-child(2),
      #${POSTGAME_SECTION_ID} .hammer-pg-team-head span:nth-child(3) {
        text-align:right;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-row-away,
      #${POSTGAME_SECTION_ID} .hammer-pg-row-home {
        color:var(--ink);
        font-family:var(--mono);
        font-weight:800;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-footer {
        margin-top:14px;
        padding-top:12px;
        border-top:1px solid var(--border);
        color:var(--muted);
        font-size:9px;
        line-height:1.6;
      }

      #${POSTGAME_SECTION_ID} .hammer-pg-pending {
        margin-top:12px;
        padding:12px;
        border:1px dashed var(--border-dark);
        border-radius:10px;
        color:var(--muted);
        font-size:11px;
        line-height:1.6;
      }

      @media (max-width:760px) {
        #${POSTGAME_SECTION_ID} .hammer-pg-headlines,
        #${POSTGAME_SECTION_ID} .hammer-pg-grid {
          grid-template-columns:1fr;
        }
      }

      @media (max-width:600px) {
        #matchup-container .hammer-final-pregame-score {
          gap:8px;
        }

        #matchup-container .hammer-final-pregame-points {
          font-size:15px;
        }

        #${POSTGAME_SECTION_ID} {
          padding:14px;
        }

        #${POSTGAME_SECTION_ID} .hammer-pg-card-value {
          font-size:16px;
        }

        #${POSTGAME_SECTION_ID} .hammer-pg-team-head,
        #${POSTGAME_SECTION_ID} .hammer-pg-row {
          grid-template-columns:minmax(0,1fr) 62px 62px;
          gap:7px;
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
      {
        cache: "no-store"
      }
    );

    if (!response.ok) {
      throw new Error(
        `${url} returned HTTP ${response.status}`
      );
    }

    return response.json();
  }

  async function loadData() {
    const [resultsResult, postgameResult] =
      await Promise.allSettled([
        fetchJson(RESULTS_URL),
        fetchJson(POSTGAME_URL)
      ]);

    if (resultsResult.status === "fulfilled") {
      const payload = resultsResult.value;

      finalGames = Array.isArray(payload?.games)
        ? payload.games.filter(game =>
            ["final", "completed"].includes(
              String(
                game?.game_state ||
                game?.status ||
                ""
              ).toLowerCase()
            )
          )
        : [];
    }

    if (postgameResult.status === "fulfilled") {
      postgameDataLoaded = true;
      postgameGames = Array.isArray(
        postgameResult.value?.games
      )
        ? postgameResult.value.games
        : [];
    } else {
      /*
       * CRITICAL:
       * Do not convert every final to PENDING when the entire JSON request fails.
       * Preserve the last successfully loaded postgame data instead.
       */
      console.warn(
        "[THI Postgame] postgame_analytics.json unavailable:",
        postgameResult.reason
      );
    }

    applyAll();
  }

  // ==========================================================================
  // FINAL SCORE CARD
  // ==========================================================================

  function currentScoreCard() {
    return document.querySelector(
      "#matchup-container .projected-score-card"
    );
  }

  function scoreCardTeams(card) {
    if (!card) {
      return null;
    }

    const teams = Array.from(
      card.querySelectorAll(".projected-team")
    );

    if (teams.length < 2) {
      return null;
    }

    const awayName = teams[0]
      .querySelector(".projected-team-name")
      ?.textContent
      ?.trim();

    const homeName = teams[1]
      .querySelector(".projected-team-name")
      ?.textContent
      ?.trim();

    if (!awayName || !homeName) {
      return null;
    }

    return {
      awayName,
      homeName,
      awayNode: teams[0],
      homeNode: teams[1]
    };
  }

  function findFinal(away, home) {
    return matchupFind(
      finalGames,
      away,
      home
    );
  }

  function findPostgameForFinal(final) {
    if (!final) {
      return null;
    }

    const finalId = String(final.game_id || "").trim();

    if (finalId) {
      const byId = postgameGames.find(game =>
        String(game?.game_id || "").trim() === finalId
      );

      if (byId) {
        return byId;
      }
    }

    return matchupFind(
      postgameGames,
      final.away_team,
      final.home_team
    );
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

    if (!card) {
      return null;
    }

    const nodes = scoreCardTeams(card);

    if (!nodes) {
      return null;
    }

    const final = findFinal(
      nodes.awayName,
      nodes.homeName
    );

    if (!final) {
      removePostgameSection();
      return null;
    }

    if (
      card.dataset.hammerFinalApplied
      !== "true"
    ) {
      const projection =
        readPregameProjection(nodes);

      if (!projection) {
        return final;
      }

      const awayPoints =
        Number(final.away_points);

      const homePoints =
        Number(final.home_points);

      if (
        !Number.isFinite(awayPoints) ||
        !Number.isFinite(homePoints)
      ) {
        return final;
      }

      const title =
        card.querySelector(
          ".projected-score-title"
        );

      const separator =
        card.querySelector(
          ".projected-score-separator"
        );

      const awayNameNode =
        nodes.awayNode.querySelector(
          ".projected-team-name"
        );

      const awayScoreNode =
        nodes.awayNode.querySelector(
          ".projected-team-score"
        );

      const homeNameNode =
        nodes.homeNode.querySelector(
          ".projected-team-name"
        );

      const homeScoreNode =
        nodes.homeNode.querySelector(
          ".projected-team-score"
        );

      if (
        !title ||
        !awayNameNode ||
        !awayScoreNode ||
        !homeNameNode ||
        !homeScoreNode
      ) {
        return final;
      }

      card.dataset.hammerFinalApplied =
        "true";

      title.textContent =
        "Final Score";

      awayNameNode.textContent =
        final.away_team ||
        projection.awayName;

      awayScoreNode.textContent =
        String(awayPoints);

      homeNameNode.textContent =
        final.home_team ||
        projection.homeName;

      homeScoreNode.textContent =
        String(homePoints);

      if (separator) {
        separator.textContent =
          "FINAL";
      }

      const oldPregame =
        card.querySelector(
          ".hammer-final-pregame-block"
        );

      if (oldPregame) {
        oldPregame.remove();
      }

      card.insertAdjacentHTML(
        "beforeend",
        pregameMarkup(projection)
      );

      card.classList.add(
        "hammer-final-score-card"
      );
    }

    return final;
  }

  // ==========================================================================
  // POSTGAME PAGE
  // ==========================================================================

  function removePostgameSection() {
    document
      .getElementById(POSTGAME_SECTION_ID)
      ?.remove();
  }

  function metricRow(
    label,
    awayValue,
    homeValue
  ) {
    return `
      <div class="hammer-pg-row">
        <span class="hammer-pg-row-label">
          ${escapeHtml(label)}
        </span>
        <span class="hammer-pg-row-away">
          ${escapeHtml(awayValue)}
        </span>
        <span class="hammer-pg-row-home">
          ${escapeHtml(homeValue)}
        </span>
      </div>
    `;
  }

  function panel(
    title,
    awayName,
    homeName,
    rows
  ) {
    return `
      <div class="hammer-pg-panel">
        <div class="hammer-pg-panel-title">
          ${escapeHtml(title)}
        </div>

        <div class="hammer-pg-team-head">
          <span>Metric</span>
          <span>${escapeHtml(awayName)}</span>
          <span>${escapeHtml(homeName)}</span>
        </div>

        ${rows.join("")}
      </div>
    `;
  }

  function pendingPostgameMarkup(postgame) {
    return `
      <section
        id="${POSTGAME_SECTION_ID}"
        class="pending"
      >
        <div class="hammer-pg-kicker">
          🔨 Postgame Analysis
        </div>

        <div class="hammer-pg-title">
          Postgame analysis pending
        </div>

        <div class="hammer-pg-subtitle">
          The final score is official. THI is waiting for matching
          play-by-play before publishing the full retrospective package.
        </div>

        <div class="hammer-pg-pending">
          ${escapeHtml(
            postgame?.source_note ||
            "The automatic settlement workflow will retry this game. No postgame metric is fabricated while PBP is unavailable."
          )}
        </div>
      </section>
    `;
  }

  function availablePostgameMarkup(
    final,
    pg
  ) {
    const awayName =
      pg.away_team ||
      final.away_team;

    const homeName =
      pg.home_team ||
      final.home_team;

    const away =
      pg.away_metrics || {};

    const home =
      pg.home_metrics || {};

    const headline =
      pg.headline || {};

    const pwe =
      headline.postgame_win_expectancy || {};

    const adjusted =
      headline.adjusted_final_score || {};

    const reality =
      headline.reality_check || {};

    const aOverall =
      away.overall || {};

    const hOverall =
      home.overall || {};

    const aPass =
      away.passing || {};

    const hPass =
      home.passing || {};

    const aRush =
      away.rushing || {};

    const hRush =
      home.rushing || {};

    const aStd =
      away.standard_downs || {};

    const hStd =
      home.standard_downs || {};

    const aPd =
      away.passing_downs || {};

    const hPd =
      home.passing_downs || {};

    const aEarly =
      away.early_downs || {};

    const hEarly =
      home.early_downs || {};

    const aMoney =
      away.third_fourth_downs || {};

    const hMoney =
      home.third_fourth_downs || {};

    const aFourth =
      away.fourth_down || {};

    const hFourth =
      home.fourth_down || {};

    const aExplosive =
      away.explosiveness || {};

    const hExplosive =
      home.explosiveness || {};

    const aNeg =
      away.negative_play_rates || {};

    const hNeg =
      home.negative_play_rates || {};

    const aDrive =
      away.drives || {};

    const hDrive =
      home.drives || {};

    const aOpp =
      away.scoring_opportunities || {};

    const hOpp =
      home.scoring_opportunities || {};

    const aRz =
      away.red_zone || {};

    const hRz =
      home.red_zone || {};

    const aField =
      away.field_position || {};

    const hField =
      home.field_position || {};

    const aTurn =
      away.turnovers || {};

    const hTurn =
      home.turnovers || {};

    const context =
      pg.game_context || {};

    const panels = [
      panel(
        "Overall EPA",
        awayName,
        homeName,
        [
          metricRow(
            "EPA / Play",
            fmt(aOverall.epa_per_play, 3),
            fmt(hOverall.epa_per_play, 3)
          ),
          metricRow(
            "Total EPA",
            fmtSigned(aOverall.epa_total, 2),
            fmtSigned(hOverall.epa_total, 2)
          ),
          metricRow(
            "Success Rate",
            fmtPct(aOverall.success_rate),
            fmtPct(hOverall.success_rate)
          ),
          metricRow(
            "EPA Volatility",
            fmt(away.epa_volatility, 3),
            fmt(home.epa_volatility, 3)
          )
        ]
      ),

      panel(
        "Pass + Rush",
        awayName,
        homeName,
        [
          metricRow(
            "Pass EPA / Play",
            fmt(aPass.epa_per_play, 3),
            fmt(hPass.epa_per_play, 3)
          ),
          metricRow(
            "Pass Total EPA",
            fmtSigned(aPass.epa_total, 2),
            fmtSigned(hPass.epa_total, 2)
          ),
          metricRow(
            "Pass Success Rate",
            fmtPct(aPass.success_rate),
            fmtPct(hPass.success_rate)
          ),
          metricRow(
            "Rush EPA / Play",
            fmt(aRush.epa_per_play, 3),
            fmt(hRush.epa_per_play, 3)
          ),
          metricRow(
            "Rush Total EPA",
            fmtSigned(aRush.epa_total, 2),
            fmtSigned(hRush.epa_total, 2)
          ),
          metricRow(
            "Rush Success Rate",
            fmtPct(aRush.success_rate),
            fmtPct(hRush.success_rate)
          )
        ]
      ),

      panel(
        "Explosiveness",
        awayName,
        homeName,
        [
          metricRow(
            "Explosive Plays",
            fmtInt(aExplosive.explosive_plays),
            fmtInt(hExplosive.explosive_plays)
          ),
          metricRow(
            "Explosive-Play Rate",
            fmtPct(aExplosive.explosive_play_rate),
            fmtPct(hExplosive.explosive_play_rate)
          ),
          metricRow(
            "Explosive EPA Dependency",
            fmtPct(aExplosive.explosive_epa_dependency),
            fmtPct(hExplosive.explosive_epa_dependency)
          )
        ]
      ),

      panel(
        "Standard + Passing Downs",
        awayName,
        homeName,
        [
          metricRow(
            "Standard Down EPA / Play",
            fmt(aStd.epa_per_play, 3),
            fmt(hStd.epa_per_play, 3)
          ),
          metricRow(
            "Standard Down Success",
            fmtPct(aStd.success_rate),
            fmtPct(hStd.success_rate)
          ),
          metricRow(
            "Passing Down EPA / Play",
            fmt(aPd.epa_per_play, 3),
            fmt(hPd.epa_per_play, 3)
          ),
          metricRow(
            "Passing Down Success",
            fmtPct(aPd.success_rate),
            fmtPct(hPd.success_rate)
          )
        ]
      ),

      panel(
        "Early + Money Downs",
        awayName,
        homeName,
        [
          metricRow(
            "Early Down EPA / Play",
            fmt(aEarly.epa_per_play, 3),
            fmt(hEarly.epa_per_play, 3)
          ),
          metricRow(
            "Early Down Success",
            fmtPct(aEarly.success_rate),
            fmtPct(hEarly.success_rate)
          ),
          metricRow(
            "3rd/4th EPA / Play",
            fmt(aMoney.epa_per_play, 3),
            fmt(hMoney.epa_per_play, 3)
          ),
          metricRow(
            "3rd/4th Success",
            fmtPct(aMoney.success_rate),
            fmtPct(hMoney.success_rate)
          )
        ]
      ),

      panel(
        "Fourth Down",
        awayName,
        homeName,
        [
          metricRow(
            "Attempts",
            fmtInt(aFourth.attempts),
            fmtInt(hFourth.attempts)
          ),
          metricRow(
            "Success Rate",
            fmtPct(aFourth.success_rate),
            fmtPct(hFourth.success_rate)
          ),
          metricRow(
            "EPA / Play",
            fmt(aFourth.epa_per_play, 3),
            fmt(hFourth.epa_per_play, 3)
          ),
          metricRow(
            "Total EPA",
            fmtSigned(aFourth.epa_total, 2),
            fmtSigned(hFourth.epa_total, 2)
          )
        ]
      ),

      panel(
        "Negative Plays Allowed",
        awayName,
        homeName,
        [
          metricRow(
            "Sack Rate Allowed",
            fmtPct(aNeg.sack_rate_allowed),
            fmtPct(hNeg.sack_rate_allowed)
          ),
          metricRow(
            "Stuff Rate Allowed",
            fmtPct(aNeg.stuff_rate_allowed),
            fmtPct(hNeg.stuff_rate_allowed)
          ),
          metricRow(
            "TFL Rate Allowed",
            fmtPct(aNeg.tfl_rate_allowed),
            fmtPct(hNeg.tfl_rate_allowed)
          )
        ]
      ),

      panel(
        "Drive Efficiency",
        awayName,
        homeName,
        [
          metricRow(
            "Drives",
            fmtInt(aDrive.drives),
            fmtInt(hDrive.drives)
          ),
          metricRow(
            "Points / Drive",
            fmt(aDrive.points_per_drive, 2),
            fmt(hDrive.points_per_drive, 2)
          ),
          metricRow(
            "Yards / Drive",
            fmt(aDrive.yards_per_drive, 1),
            fmt(hDrive.yards_per_drive, 1)
          ),
          metricRow(
            "Drive Success Rate",
            fmtPct(aDrive.drive_success_rate),
            fmtPct(hDrive.drive_success_rate)
          ),
          metricRow(
            "Three-and-Out Rate",
            fmtPct(aDrive.three_and_out_rate),
            fmtPct(hDrive.three_and_out_rate)
          )
        ]
      ),

      panel(
        "Scoring Opportunities",
        awayName,
        homeName,
        [
          metricRow(
            "Opportunities",
            fmtInt(aOpp.opportunities),
            fmtInt(hOpp.opportunities)
          ),
          metricRow(
            "Points / Opportunity",
            fmt(aOpp.points_per_opportunity, 2),
            fmt(hOpp.points_per_opportunity, 2)
          )
        ]
      ),

      panel(
        "Red Zone",
        awayName,
        homeName,
        [
          metricRow(
            "Trips",
            fmtInt(aRz.trips),
            fmtInt(hRz.trips)
          ),
          metricRow(
            "Points / Trip",
            fmt(aRz.points_per_trip, 2),
            fmt(hRz.points_per_trip, 2)
          ),
          metricRow(
            "Overperformance",
            (
              numeric(aRz.overperformance_points_per_trip) === null
                ? "—"
                : `${fmtSigned(aRz.overperformance_points_per_trip, 2)} pts/trip`
            ),
            (
              numeric(hRz.overperformance_points_per_trip) === null
                ? "—"
                : `${fmtSigned(hRz.overperformance_points_per_trip, 2)} pts/trip`
            )
          )
        ]
      ),

      panel(
        "Field Position + Turnovers",
        awayName,
        homeName,
        [
          metricRow(
            "Avg Start — Yds to Goal",
            fmt(aField.avg_start_yards_to_goal, 1),
            fmt(hField.avg_start_yards_to_goal, 1)
          ),
          metricRow(
            "Turnovers",
            fmtInt(aTurn.turnovers),
            fmtInt(hTurn.turnovers)
          ),
          metricRow(
            "Turnover EPA Impact",
            fmtSigned(aTurn.turnover_epa_impact, 2),
            fmtSigned(hTurn.turnover_epa_impact, 2)
          )
        ]
      )
    ];

    return `
      <section id="${POSTGAME_SECTION_ID}">
        <div class="hammer-pg-kicker">
          🔨 Postgame Analysis
        </div>

        <div class="hammer-pg-title">
          What actually happened?
        </div>

        <div class="hammer-pg-subtitle">
          Retrospective play-by-play analysis. The frozen pregame THI projection
          above is never rewritten after the game.
        </div>

        <div class="hammer-pg-beta">
          ${escapeHtml(
            pg.calibration_status ||
            "BETA — historical calibration pending"
          )}
        </div>

        <div class="hammer-pg-headlines">
          <div class="hammer-pg-card">
            <div class="hammer-pg-card-label">
              Postgame Win Expectancy
            </div>
            <div class="hammer-pg-card-value">
              ${escapeHtml(awayName)} ${fmtPct(pwe.away_pct)}
              ·
              ${escapeHtml(homeName)} ${fmtPct(pwe.home_pct)}
            </div>
            <div class="hammer-pg-card-note">
              Retrospective process-based probability, not live win probability.
            </div>
          </div>

          <div class="hammer-pg-card">
            <div class="hammer-pg-card-label">
              Adjusted Final Score
            </div>
            <div class="hammer-pg-card-value">
              ${escapeHtml(awayName)} ${fmt(adjusted.away, 1)}
              —
              ${escapeHtml(homeName)} ${fmt(adjusted.home, 1)}
            </div>
            <div class="hammer-pg-card-note">
              BETA estimate from the underlying efficiency and possession profile.
            </div>
          </div>

          <div class="hammer-pg-card">
            <div class="hammer-pg-card-label">
              THI Reality Check
            </div>
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
          <strong>Garbage-time share:</strong>
          ${fmtInt(context.garbage_time_plays)} of
          ${fmtInt(context.total_scrimmage_plays)}
          qualifying scrimmage plays
          (${fmtPct(context.garbage_time_share)}).
          <br>
          <strong>Competitive plays used:</strong>
          ${fmtInt(context.competitive_scrimmage_plays)}.
          <br>
          <strong>Definitions:</strong>
          Standard downs = 1st down, 2nd-and-7 or less, 3rd/4th-and-4 or less.
          Passing downs = 2nd-and-8+, 3rd/4th-and-5+.
          Drive Success Rate = share of drives with positive cumulative EPA.
          Scoring opportunity = drive reaching the opponent 40.
          Red-zone trip = drive reaching the opponent 20.
          <br>
          <strong>Source:</strong>
          ${escapeHtml(
            pg.source ||
            "SportsDataverse/cfbfastR PBP"
          )}.
          PWE, Adjusted Final Score, and Red-Zone Overperformance remain beta
          until the historical calibration work is completed.
        </div>
      </section>
    `;
  }

  function renderPostgame(final) {
    const container =
      document.getElementById(
        "matchup-container"
      );

    if (!container || !final) {
      return;
    }

    const postgame =
      findPostgameForFinal(final);

    removePostgameSection();

    /*
     * If the whole file has not loaded successfully, do not falsely render
     * "pending." Just leave the section absent until a successful refresh.
     */
    if (!postgameDataLoaded) {
      return;
    }

    /*
     * Only an explicit pending record is PENDING.
     */
    if (
      postgame?.analysis_status
      === "pending"
    ) {
      container.insertAdjacentHTML(
        "beforeend",
        pendingPostgameMarkup(
          postgame
        )
      );
      return;
    }

    if (
      postgame?.analysis_status
      === "available"
    ) {
      container.insertAdjacentHTML(
        "beforeend",
        availablePostgameMarkup(
          final,
          postgame
        )
      );
    }
  }

  // ==========================================================================
  // PROJECTION BOARD STATUS — ONE PURPLE PILL ONLY
  // ==========================================================================

  function boardRowTeams(row) {
    const names = Array.from(
      row.querySelectorAll(
        ".matchup-cell .team-name"
      )
    )
      .map(node =>
        node.textContent?.trim()
      )
      .filter(Boolean);

    if (names.length < 2) {
      return null;
    }

    return {
      away: names[0],
      home: names[1]
    };
  }

  function directText(node) {
    return Array.from(
      node.childNodes
    )
      .filter(child =>
        child.nodeType
        === Node.TEXT_NODE
      )
      .map(child =>
        child.textContent || ""
      )
      .join(" ")
      .replace(/\s+/g, " ")
      .trim()
      .toUpperCase();
  }

  function existingPostgamePurplePill(row) {
    return (
      row.querySelector(".thi-postgame-status-purple") ||
      Array.from(
        row.querySelectorAll("*")
      ).find(node => {
        if (
          node.classList?.contains(
            "hammer-postgame-board-badge"
          )
        ) {
          return false;
        }

        const own = directText(node);

        return (
          own === "POSTGAME ANALYSIS AVAILABLE" ||
          own === "POSTGAME ANALYSIS PENDING"
        );
      }) ||
      null
    );
  }

  function ensurePurplePostgamePill(row) {
    let pill = existingPostgamePurplePill(row);

    if (pill) {
      pill.classList.add("thi-postgame-status-purple");
      return pill;
    }

    const meta =
      row.querySelector(".hammer-game-status-meta") ||
      row.querySelector(".matchup-cell");

    if (!meta) {
      return null;
    }

    pill = document.createElement("span");
    pill.className = "thi-postgame-status-purple";
    meta.appendChild(pill);

    return pill;
  }

  function decorateBoardPostgameStatus() {
    /*
     * Remove every legacy duplicate from older postgame code.
     * We then render exactly ONE purple postgame state.
     */
    document
      .querySelectorAll(
        ".hammer-postgame-board-badge"
      )
      .forEach(node =>
        node.remove()
      );

    const rows =
      document.querySelectorAll(
        "#projections-container .projection-table tbody tr.game-row"
      );

    rows.forEach(row => {
      /*
       * Remove duplicate custom purple pills if a mutation race ever produced one.
       */
      const existingCustom = Array.from(
        row.querySelectorAll(".thi-postgame-status-purple")
      );

      existingCustom
        .slice(1)
        .forEach(node => node.remove());

      const teams =
        boardRowTeams(row);

      if (!teams) {
        return;
      }

      const final =
        findFinal(
          teams.away,
          teams.home
        );

      if (!final) {
        return;
      }

      /*
       * If postgame JSON itself has not loaded, do not invent a state.
       */
      if (!postgameDataLoaded) {
        return;
      }

      const pg =
        findPostgameForFinal(final);

      /*
       * Only an explicit backend state is surfaced.
       * Missing record is neither COMPLETE nor PENDING.
       */
      if (
        pg?.analysis_status !== "available" &&
        pg?.analysis_status !== "pending"
      ) {
        return;
      }

      const pill =
        ensurePurplePostgamePill(row);

      if (!pill) {
        return;
      }

      const available =
        pg.analysis_status === "available";

      pill.textContent =
        available
          ? "POSTGAME ANALYSIS AVAILABLE"
          : "POSTGAME ANALYSIS PENDING";

      pill.classList.toggle(
        "pending",
        !available
      );

      pill.dataset.postgameStatus =
        pg.analysis_status;
    });
  }

  // ==========================================================================
  // APPLY / OBSERVER
  // ==========================================================================

  function applyAll() {
    if (applying) {
      return;
    }

    applying = true;

    try {
      const final =
        applyFinalToCurrentMatchup();

      if (final) {
        renderPostgame(final);
      }

      decorateBoardPostgameStatus();

    } finally {
      applying = false;
    }
  }

  function scheduleApply() {
    requestAnimationFrame(
      applyAll
    );
  }

  function installObserver() {
    const targets = [
      document.getElementById(
        "matchup-container"
      ),
      document.getElementById(
        "projections-container"
      )
    ].filter(Boolean);

    if (!targets.length) {
      setTimeout(
        installObserver,
        250
      );
      return;
    }

    if (observer) {
      observer.disconnect();
    }

    observer =
      new MutationObserver(() => {
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

    setInterval(
      loadData,
      60000
    );
  }

  if (
    document.readyState
    === "loading"
  ) {
    document.addEventListener(
      "DOMContentLoaded",
      start,
      {
        once: true
      }
    );
  } else {
    start();
  }
})();
