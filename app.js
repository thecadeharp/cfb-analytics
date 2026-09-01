// ============================================================================
// CFB ANALYTICS — FRONTEND
// ============================================================================
//
// Static frontend.
// GitHub Actions creates the analytics JSON.
//
// ============================================================================


const DATA_URLS = {
  metrics: "./data/cfb_metrics.json",
  schedule: "./data/schedule.json",
  odds: "./data/odds.json",
  projections: "./data/projections.json",
};


let metricsData = null;
let scheduleData = null;
let oddsData = null;
let projectionsData = null;

let teams = {};
let projections = [];

let currentWeek = null;
let currentSearch = "";


// ============================================================================
// HELPERS
// ============================================================================

function hasValue(value) {
  return (
    value !== null &&
    value !== undefined &&
    !Number.isNaN(Number(value))
  );
}


function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}


function escapeJsString(value) {
  return String(value ?? "")
    .replaceAll("\\", "\\\\")
    .replaceAll("'", "\\'");
}


function formatNumber(value, digits = 1) {
  if (!hasValue(value)) {
    return "—";
  }

  return Number(value).toFixed(digits);
}


function formatSigned(value, digits = 1) {
  if (!hasValue(value)) {
    return "—";
  }

  const number = Number(value);

  if (number > 0) {
    return `+${number.toFixed(digits)}`;
  }

  return number.toFixed(digits);
}


function formatEPA(value) {
  if (!hasValue(value)) {
    return "—";
  }

  const number = Number(value);

  if (number > 0) {
    return `+${number.toFixed(3)}`;
  }

  return number.toFixed(3);
}


function formatPercent(value, digits = 1) {
  if (!hasValue(value)) {
    return "—";
  }

  return `${Number(value).toFixed(digits)}%`;
}


function formatRate(value, digits = 1) {
  if (!hasValue(value)) {
    return "—";
  }

  const number = Number(value);

  if (
    number < 0 ||
    number > 100
  ) {
    return "—";
  }

  return `${number.toFixed(digits)}%`;
}


function recordText(team) {
  const record = team?.record;

  if (!record) {
    return "—";
  }

  return `${record.wins ?? 0}-${record.losses ?? 0}`;
}


function statusClass(status) {
  if (status === "PLAY") {
    return "play";
  }

  if (status === "WATCH") {
    return "watch";
  }

  return "inline";
}


function displayStatus(status) {
  if (
    !status ||
    status === "NO MARKET"
  ) {
    return "NO LINE";
  }

  return status;
}


function shortSpread(spread) {
  if (!hasValue(spread)) {
    return "—";
  }

  const number = Number(spread);

  if (number === 0) {
    return "PK";
  }

  return formatSigned(number);
}


function gameDateText(dateString) {
  if (!dateString) {
    return "TBD";
  }

  const date = new Date(dateString);

  if (
    Number.isNaN(
      date.getTime()
    )
  ) {
    return "TBD";
  }

  return date.toLocaleString(
    "en-US",
    {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }
  );
}


function metricRank(
  team,
  section,
  rankField,
  value
) {
  if (!hasValue(value)) {
    return "";
  }

  const rank =
    team?.[section]?.[rankField];

  if (
    !rank ||
    rank <= 0
  ) {
    return "";
  }

  return `#${rank}`;
}


function powerRank(team) {
  const rank =
    team?.power_rating_rank;

  if (!rank) {
    return "—";
  }

  return `#${rank}`;
}


function getTeam(name) {
  return teams?.[name] ?? null;
}


// ============================================================================
// SPREAD DISPLAY HELPERS
// ============================================================================

function favoredLine(
  homeTeam,
  awayTeam,
  homeSpread
) {
  if (!hasValue(homeSpread)) {
    return "—";
  }

  const spread =
    Number(homeSpread);

  if (spread === 0) {
    return "Pick'em";
  }

  if (spread < 0) {
    return `${homeTeam} ${formatSigned(spread, 1)}`;
  }

  return `${awayTeam} ${formatSigned(-spread, 1)}`;
}


function marketSideForTeam(
  teamName,
  homeTeam,
  awayTeam,
  homeSpread
) {
  if (!hasValue(homeSpread)) {
    return "—";
  }

  const spread =
    Number(homeSpread);

  if (teamName === homeTeam) {
    return `${homeTeam} ${formatSigned(spread, 1)}`;
  }

  if (teamName === awayTeam) {
    return `${awayTeam} ${formatSigned(-spread, 1)}`;
  }

  return "—";
}


// ============================================================================
// LIVE DATA HELPERS
// ============================================================================

function liveSection(
  team,
  section
) {
  return (
    team?.[section]?.live_2026
    ?? {}
  );
}


function liveValue(
  team,
  section,
  field
) {
  const value =
    liveSection(
      team,
      section
    )?.[field];

  if (!hasValue(value)) {
    return null;
  }

  return Number(value);
}


function livePlays(
  team,
  section
) {
  const value =
    liveSection(
      team,
      section
    )?.n_plays;

  if (!hasValue(value)) {
    return 0;
  }

  return Number(value);
}


function liveNet(
  team,
  field
) {
  const offense =
    liveValue(
      team,
      "offense",
      field
    );

  const defense =
    liveValue(
      team,
      "defense",
      field
    );

  if (
    offense === null ||
    defense === null
  ) {
    return null;
  }

  return offense - defense;
}


function liveSampleLabel(team) {
  const offense =
    livePlays(
      team,
      "offense"
    );

  const defense =
    livePlays(
      team,
      "defense"
    );

  if (
    offense > 0 &&
    defense > 0
  ) {
    return "2026 live sample available";
  }

  return "Preseason model only";
}


// ============================================================================
// VIEW SWITCHING
// ============================================================================

function switchView(viewName) {
  document
    .querySelectorAll(".view")
    .forEach((view) => {
      view.classList.remove("active");
    });

  const requested =
    document.getElementById(
      `view-${viewName}`
    );

  if (requested) {
    requested
      .classList
      .add("active");
  }

  document
    .querySelectorAll(".nav-item")
    .forEach((button) => {
      button.classList.toggle(
        "active",
        button.dataset.view === viewName
      );
    });

  window.scrollTo({
    top: 0,
    behavior: "smooth",
  });
}


// ============================================================================
// MATCHUP VIEW SETUP
// ============================================================================

function ensureMatchupView() {
  if (
    document.getElementById(
      "view-matchup"
    )
  ) {
    return;
  }

  const main =
    document.querySelector(
      "main.page"
    );

  if (!main) {
    return;
  }

  const section =
    document.createElement(
      "section"
    );

  section.id = "view-matchup";
  section.className = "view";

  section.innerHTML = `
    <button
      class="back-button"
      onclick="switchView('projections')"
    >
      ← Back to projections
    </button>

    <div id="matchup-container">
    </div>
  `;

  main.appendChild(section);


  const style =
    document.createElement(
      "style"
    );

  style.textContent = `

    .projection-table tbody tr.game-row {
      cursor: pointer;
    }

    .projection-table tbody tr.game-row:hover {
      background: #fafaf8;
    }

    .matchup-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 24px;
      margin-bottom: 24px;
    }

    .matchup-title {
      font-size: 34px;
      line-height: 1.06;
      font-weight: 800;
      letter-spacing: -1.2px;
      margin-top: 4px;
    }

    .matchup-subtitle {
      color: var(--muted);
      margin-top: 9px;
      font-size: 12px;
    }

    .analysis-grid {
      display: grid;
      grid-template-columns:
        repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 18px;
    }

    .analysis-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 18px;
      min-height: 105px;
    }

    .analysis-card.edge-card {
      border-color: var(--border-dark);
    }

    .analysis-label {
      font-family: var(--mono);
      color: var(--muted);
      font-size: 9px;
      letter-spacing: 1.2px;
      text-transform: uppercase;
      margin-bottom: 10px;
    }

    .analysis-value {
      font-size: 24px;
      font-weight: 800;
      letter-spacing: -0.8px;
    }

    .analysis-value.edge-play {
      color: var(--green);
    }

    .analysis-value.edge-watch {
      color: var(--amber);
    }

    .analysis-small {
      color: var(--muted);
      font-size: 11px;
      margin-top: 6px;
      line-height: 1.4;
    }

    .model-edge-banner {
      background: var(--surface);
      border: 1px solid var(--border-dark);
      border-radius: 12px;
      padding: 18px 20px;
      margin-bottom: 18px;

      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 20px;
    }

    .model-edge-banner-left {
      min-width: 0;
    }

    .model-edge-title {
      font-family: var(--mono);
      font-size: 9px;
      color: var(--muted);
      letter-spacing: 1.2px;
      text-transform: uppercase;
      margin-bottom: 7px;
    }

    .model-edge-side {
      font-size: 26px;
      font-weight: 800;
      letter-spacing: -0.8px;
    }

    .model-edge-context {
      margin-top: 6px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.45;
    }

    .analysis-layout {
      display: grid;
      grid-template-columns:
        minmax(0, 1fr)
        minmax(0, 1fr);
      gap: 12px;
    }

    .analysis-panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      overflow: hidden;
    }

    .analysis-panel.wide {
      grid-column: 1 / -1;
    }

    .analysis-panel-header {
      padding: 13px 16px;
      border-bottom:
        1px solid var(--border);
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
    }

    .analysis-panel-title {
      font-family: var(--mono);
      font-size: 9px;
      font-weight: 500;
      letter-spacing: 1.2px;
      text-transform: uppercase;
      color: var(--muted);
    }

    .analysis-panel-body {
      padding: 0 16px;
    }

    .analysis-row {
      display: grid;
      grid-template-columns:
        minmax(0, 1fr)
        auto;
      gap: 18px;
      align-items: center;
      min-height: 48px;
      border-bottom:
        1px solid #eeeeeb;
    }

    .analysis-row:last-child {
      border-bottom: none;
    }

    .analysis-row-label {
      color: var(--muted);
      font-size: 12px;
    }

    .analysis-row-value {
      font-family: var(--mono);
      font-size: 12px;
      font-weight: 500;
      text-align: right;
    }

    .insight-card {
      padding: 15px 0;
      border-bottom:
        1px solid #eeeeeb;
    }

    .insight-card:last-child {
      border-bottom: none;
    }

    .insight-title {
      font-family: var(--mono);
      color: var(--muted);
      font-size: 9px;
      letter-spacing: 1.1px;
      text-transform: uppercase;
      margin-bottom: 5px;
    }

    .insight-text {
      font-size: 12px;
      line-height: 1.55;
    }

    .sample-warning {
      background: #fafaf8;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 13px 15px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.55;
      margin-bottom: 12px;
    }

    .adjustment-positive {
      color: var(--green);
    }

    .adjustment-negative {
      color: var(--red);
    }

    .adjustment-neutral {
      color: var(--muted);
    }

    .win-prob-wrap {
      margin-top: 12px;
    }

    .win-prob-bar {
      height: 7px;
      border-radius: 999px;
      overflow: hidden;
      background: #ecece8;
    }

    .win-prob-fill {
      height: 100%;
      background: var(--green);
    }

    .win-prob-labels {
      display: flex;
      justify-content: space-between;
      margin-top: 7px;
      font-family: var(--mono);
      font-size: 10px;
      color: var(--muted);
    }

    @media (max-width: 900px) {

      .analysis-grid {
        grid-template-columns:
          repeat(2, minmax(0, 1fr));
      }

      .analysis-layout {
        grid-template-columns: 1fr;
      }

      .analysis-panel.wide {
        grid-column: auto;
      }

      .matchup-header {
        flex-direction: column;
      }

      .model-edge-banner {
        align-items: flex-start;
        flex-direction: column;
      }
    }

    @media (max-width: 520px) {

      .analysis-grid {
        grid-template-columns: 1fr;
      }

      .matchup-title {
        font-size: 27px;
      }

      .model-edge-side {
        font-size: 23px;
      }
    }
  `;

  document.head.appendChild(style);
}


// ============================================================================
// DATA
// ============================================================================

async function loadJson(url) {
  const response =
    await fetch(
      `${url}?v=${Date.now()}`
    );

  if (!response.ok) {
    throw new Error(
      `${url} returned HTTP ${response.status}`
    );
  }

  return response.json();
}


async function init() {
  try {

    ensureMatchupView();

    [
      metricsData,
      scheduleData,
      oddsData,
      projectionsData,
    ] = await Promise.all([
      loadJson(DATA_URLS.metrics),
      loadJson(DATA_URLS.schedule),
      loadJson(DATA_URLS.odds),
      loadJson(DATA_URLS.projections),
    ]);

    teams =
      metricsData?.teams ?? {};

    projections =
      projectionsData?.games ?? [];

    updateHeader();

    buildWeekTabs();

    renderProjections();
    renderTeams();
    renderRatings();

    attachEvents();

  } catch (error) {

    console.error(
      "Frontend initialization failed:",
      error
    );

    const container =
      document.getElementById(
        "projections-container"
      );

    if (container) {

      container.innerHTML = `
        <div class="empty-state">

          Unable to load analytics data.

          <br><br>

          <span
            style="
              font-family:var(--mono);
              font-size:11px;
            "
          >
            ${escapeHtml(error.message)}
          </span>

        </div>
      `;
    }
  }
}


// ============================================================================
// HEADER
// ============================================================================

function updateHeader() {
  const header =
    document.getElementById(
      "data-updated"
    );

  if (!header) {
    return;
  }

  const generated =
    projectionsData?.meta?.generated
    ||
    metricsData?.meta?.generated;

  if (!generated) {

    header.textContent =
      "2026 model";

    return;
  }

  const date =
    new Date(generated);

  if (
    Number.isNaN(
      date.getTime()
    )
  ) {

    header.textContent =
      "2026 model";

    return;
  }

  header.textContent =
    `Updated ${
      date.toLocaleDateString(
        "en-US",
        {
          month: "short",
          day: "numeric",
        }
      )
    }`;
}


// ============================================================================
// WEEK TABS
// ============================================================================

function availableWeeks() {
  const weeks =
    projections
      .map(
        game =>
          game.week
      )
      .filter(
        week =>
          week !== null &&
          week !== undefined
      )
      .map(Number)
      .filter(
        week =>
          !Number.isNaN(week)
      );

  return [
    ...new Set(weeks)
  ].sort(
    (a, b) =>
      a - b
  );
}


function determineDefaultWeek(
  weeks
) {
  if (!weeks.length) {
    return null;
  }

  const marketWeeks =
    projections
      .filter(
        game =>
          hasValue(
            game?.market?.home_spread
          )
      )
      .map(
        game =>
          Number(game.week)
      )
      .filter(
        week =>
          !Number.isNaN(week)
      );

  if (
    marketWeeks.length
  ) {
    return Math.min(
      ...marketWeeks
    );
  }

  return weeks[0];
}


function buildWeekTabs() {
  const container =
    document.getElementById(
      "week-tabs"
    );

  if (!container) {
    return;
  }

  const weeks =
    availableWeeks();

  if (!weeks.length) {

    container.innerHTML = "";

    return;
  }

  if (
    currentWeek === null
  ) {

    currentWeek =
      determineDefaultWeek(
        weeks
      );
  }

  container.innerHTML =
    weeks
      .map(
        week => `
          <button
            class="
              week-tab
              ${
                Number(week)
                ===
                Number(currentWeek)
                  ? "active"
                  : ""
              }
            "
            onclick="
              selectWeek(${week})
            "
          >
            ${
              week === 0
                ? "Week 0"
                : `Week ${week}`
            }
          </button>
        `
      )
      .join("");
}


function selectWeek(week) {
  currentWeek =
    Number(week);

  buildWeekTabs();

  renderProjections();
}


// ============================================================================
// PROJECTION BOARD
// ============================================================================

function projectionGamesForCurrentView() {
  return projections

    .filter(
      game => {

        if (
          currentWeek !== null &&
          Number(game.week)
          !==
          Number(currentWeek)
        ) {
          return false;
        }

        if (!currentSearch) {
          return true;
        }

        const query =
          currentSearch.toLowerCase();

        const home =
          game?.home?.team
            ?.toLowerCase()
          ?? "";

        const away =
          game?.away?.team
            ?.toLowerCase()
          ?? "";

        return (
          home.includes(query)
          ||
          away.includes(query)
        );
      }
    )

    .sort(
      (a, b) => {

        const aDisagreement =
          a?.comparison?.disagreement
          ?? -1;

        const bDisagreement =
          b?.comparison?.disagreement
          ?? -1;

        if (
          bDisagreement
          !==
          aDisagreement
        ) {
          return (
            bDisagreement -
            aDisagreement
          );
        }

        return (
          new Date(
            a.start_date || 0
          ).getTime()
          -
          new Date(
            b.start_date || 0
          ).getTime()
        );
      }
    );
}


function renderProjections() {
  const container =
    document.getElementById(
      "projections-container"
    );

  const summary =
    document.getElementById(
      "projection-summary"
    );

  if (!container) {
    return;
  }

  const games =
    projectionGamesForCurrentView();

  const marketGames =
    games.filter(
      game =>
        hasValue(
          game?.market?.home_spread
        )
    );

  const plays =
    games.filter(
      game =>
        game?.comparison?.status
        === "PLAY"
    );

  const watches =
    games.filter(
      game =>
        game?.comparison?.status
        === "WATCH"
    );


  if (summary) {

    summary.innerHTML = `
      ${games.length} games
      · ${marketGames.length} lined
      · <strong>
          ${plays.length} plays
        </strong>
      · ${watches.length} watch
    `;
  }


  if (!games.length) {

    container.innerHTML = `
      <div class="empty-state">
        No games match this week/search.
      </div>
    `;

    return;
  }


  container.innerHTML = `
    <table class="projection-table">

      <thead>

        <tr>
          <th>Matchup</th>
          <th>Our Line</th>
          <th>Market</th>
          <th>Total</th>

          <th class="align-right">
            Disagreement
          </th>

          <th class="align-right">
            Status
          </th>
        </tr>

      </thead>

      <tbody>
        ${
          games
            .map(
              renderProjectionRow
            )
            .join("")
        }
      </tbody>

    </table>
  `;
}


function renderProjectionRow(game) {
  const homeName =
    game?.home?.team
    ?? "Unknown";

  const awayName =
    game?.away?.team
    ?? "Unknown";

  const homeRank =
    game?.home?.power_rating_rank;

  const awayRank =
    game?.away?.power_rating_rank;

  const modelSpread =
    game?.projection?.home_spread;

  const modelTotal =
    game?.projection?.total;

  const marketSpread =
    game?.market?.home_spread;

  const marketTotal =
    game?.market?.total;

  const bookmaker =
    game?.market?.bookmaker;

  const disagreement =
    game?.comparison?.disagreement;

  const preferred =
    game?.comparison?.preferred_side;

  const status =
    game?.comparison?.status;

  const cssStatus =
    statusClass(status);


  const disagreementNote =
    hasValue(disagreement)
      ? (
          preferred
            ? `Model favors ${preferred}`
            : "Model agrees with market"
        )
      : "No market line";


  const gameId =
    String(
      game.game_id ?? ""
    );


  return `
    <tr
      class="game-row"
      onclick="
        openMatchup(
          '${escapeJsString(gameId)}'
        )
      "
    >

      <td class="matchup-cell">

        <div class="team-line">

          <span
            class="team-name"
            onclick="
              event.stopPropagation();
              openDossier(
                '${escapeJsString(awayName)}'
              );
            "
          >
            ${escapeHtml(awayName)}
          </span>

          <span class="team-meta">
            ${
              awayRank
                ? `#${awayRank}`
                : ""
            }
          </span>

        </div>


        <div class="team-line">

          <span class="at-symbol">
            @
          </span>

          <span
            class="team-name"
            onclick="
              event.stopPropagation();
              openDossier(
                '${escapeJsString(homeName)}'
              );
            "
          >
            ${escapeHtml(homeName)}
          </span>

          <span class="team-meta">
            ${
              homeRank
                ? `#${homeRank}`
                : ""
            }
          </span>

        </div>


        <div
          class="team-meta"
          style="margin-top:5px;"
        >
          ${
            escapeHtml(
              gameDateText(
                game.start_date
              )
            )
          }
        </div>

      </td>


      <td>

        <div class="line-primary">
          ${
            escapeHtml(
              shortSpread(
                modelSpread
              )
            )
          }
        </div>

        <div class="line-secondary">
          ${escapeHtml(homeName)}
          home line
        </div>

      </td>


      <td>

        <div class="line-primary">
          ${
            escapeHtml(
              shortSpread(
                marketSpread
              )
            )
          }
        </div>

        <div class="line-secondary">
          ${
            bookmaker
              ? escapeHtml(bookmaker)
              : "No current market"
          }
        </div>

      </td>


      <td>

        <div class="line-primary">
          ${
            formatNumber(
              modelTotal,
              1
            )
          }
        </div>

        <div class="line-secondary">
          ${
            hasValue(marketTotal)
              ? `Market ${
                  formatNumber(
                    marketTotal,
                    1
                  )
                }`
              : "Model total"
          }
        </div>

      </td>


      <td class="disagreement">

        <div
          class="
            disagreement-number
            ${cssStatus}
          "
        >
          ${
            hasValue(disagreement)
              ? `${
                  formatNumber(
                    disagreement,
                    1
                  )
                } pts`
              : "—"
          }
        </div>

        <div class="disagreement-note">
          ${
            escapeHtml(
              disagreementNote
            )
          }
        </div>

      </td>


      <td class="status-cell">

        <span
          class="
            status
            ${cssStatus}
          "
        >
          ${
            escapeHtml(
              displayStatus(status)
            )
          }
        </span>

      </td>

    </tr>
  `;
}


// ============================================================================
// GAME LOOKUP
// ============================================================================

function findGame(gameId) {
  return projections.find(
    game =>
      String(game.game_id)
      ===
      String(gameId)
  );
}


// ============================================================================
// GAME ANALYSIS HELPERS
// ============================================================================

function openMatchup(gameId) {
  const game =
    findGame(gameId);

  if (!game) {
    return;
  }

  renderMatchup(game);

  switchView(
    "matchup"
  );
}


function adjustmentClass(value) {
  if (!hasValue(value)) {
    return "adjustment-neutral";
  }

  const number =
    Number(value);

  if (number > 0.05) {
    return "adjustment-positive";
  }

  if (number < -0.05) {
    return "adjustment-negative";
  }

  return "adjustment-neutral";
}


function adjustmentText(value) {
  if (!hasValue(value)) {
    return "—";
  }

  const number =
    Number(value);

  if (
    Math.abs(number)
    < 0.005
  ) {
    return "0.00";
  }

  return formatSigned(
    number,
    2
  );
}


function matchupComponentRow(
  label,
  value,
  active
) {
  const shown =
    active
      ? adjustmentText(value)
      : "Withheld";

  const css =
    active
      ? adjustmentClass(value)
      : "adjustment-neutral";

  return `
    <div class="analysis-row">

      <div class="analysis-row-label">
        ${escapeHtml(label)}
      </div>

      <div
        class="
          analysis-row-value
          ${css}
        "
      >
        ${escapeHtml(shown)}
      </div>

    </div>
  `;
}


function insightMarkup(insights) {
  if (
    !Array.isArray(insights)
    ||
    !insights.length
  ) {
    return `
      <div class="insight-card">

        <div class="insight-text">
          No additional model insight is available
          for this matchup yet.
        </div>

      </div>
    `;
  }

  return insights
    .map(
      insight => `
        <div class="insight-card">

          <div class="insight-title">
            ${
              escapeHtml(
                insight.title
                ?? "Model note"
              )
            }
          </div>

          <div class="insight-text">
            ${
              escapeHtml(
                insight.text
                ?? ""
              )
            }
          </div>

        </div>
      `
    )
    .join("");
}


// ============================================================================
// GAME ANALYSIS
// ============================================================================

function renderMatchup(game) {
  const container =
    document.getElementById(
      "matchup-container"
    );

  if (!container) {
    return;
  }


  const awayName =
    game?.away?.team
    ?? "Away";

  const homeName =
    game?.home?.team
    ?? "Home";


  const projection =
    game?.projection
    ?? {};

  const components =
    projection?.components
    ?? {};

  const matchup =
    components?.matchup_adjustment
    ??
    projection?.matchup_adjustment
    ??
    {};

  const matchupComponents =
    matchup?.components
    ?? {};

  const available =
    matchup?.available
    ?? {};


  const modelSpread =
    projection?.home_spread;

  const marketSpread =
    game?.market?.home_spread;

  const modelTotal =
    projection?.total;

  const marketTotal =
    game?.market?.total;


  const comparison =
    game?.comparison
    ?? {};

  const winProb =
    projection?.win_probability
    ?? {};


  const awayWin =
    hasValue(winProb.away)
      ? Number(winProb.away)
      : null;

  const homeWin =
    hasValue(winProb.home)
      ? Number(winProb.home)
      : null;


  const preferred =
    comparison?.preferred_side;

  const status =
    comparison?.status;

  const statusCss =
    statusClass(status);


  const sampleComparable =
    Boolean(
      matchup?.comparable_live_sample
    );


  const matchupNote =
    matchup?.note
    ??
    (
      sampleComparable
        ? "Comparable 2026 live samples are active."
        : "No comparable live sample; matchup adjustment is held at zero."
    );


  const ratingOnly =
    components?.rating_only_home_spread;

  const hfa =
    components?.home_field_advantage;

  const afterHfa =
    components?.spread_after_home_field;

  const matchupTotal =
    matchup?.total;


  const homeRating =
    components?.home_power_rating
    ??
    game?.home?.power_rating;

  const awayRating =
    components?.away_power_rating
    ??
    game?.away?.power_rating;


  const fairLine =
    favoredLine(
      homeName,
      awayName,
      modelSpread
    );


  const marketLine =
    favoredLine(
      homeName,
      awayName,
      marketSpread
    );


  const modelEdgeSide =
    (
      preferred &&
      hasValue(marketSpread)
    )
      ? marketSideForTeam(
          preferred,
          homeName,
          awayName,
          marketSpread
        )
      : "No actionable market edge";


  const edgeSize =
    comparison?.disagreement;


  const edgeClass =
    status === "PLAY"
      ? "edge-play"
      : status === "WATCH"
        ? "edge-watch"
        : "";


  container.innerHTML = `

    <div class="matchup-header">

      <div>

        <div class="eyebrow">
          Game analysis
        </div>

        <div class="matchup-title">
          ${escapeHtml(awayName)}
          @
          ${escapeHtml(homeName)}
        </div>

        <div class="matchup-subtitle">
          Week ${game.week ?? "—"}
          ·
          ${
            escapeHtml(
              gameDateText(
                game.start_date
              )
            )
          }

          ${
            game.venue
              ? ` · ${
                  escapeHtml(
                    game.venue
                  )
                }`
              : ""
          }
        </div>

      </div>


      <div>

        <span
          class="
            status
            ${statusCss}
          "
        >
          ${
            escapeHtml(
              displayStatus(status)
            )
          }
        </span>

      </div>

    </div>


    <!-- ============================================================
         MODEL EDGE
    ============================================================= -->

    <div class="model-edge-banner">

      <div class="model-edge-banner-left">

        <div class="model-edge-title">
          Model Edge
        </div>

        <div
          class="
            model-edge-side
            ${edgeClass}
          "
        >
          ${escapeHtml(modelEdgeSide)}
        </div>

        <div class="model-edge-context">

          ${
            hasValue(edgeSize)
              ? `${
                  formatNumber(
                    edgeSize,
                    1
                  )
                }-point difference between the model fair line and current market.`
              : "No current market line is available for comparison."
          }

        </div>

      </div>


      <div>

        <span
          class="
            status
            ${statusCss}
          "
        >
          ${
            escapeHtml(
              displayStatus(status)
            )
          }
        </span>

      </div>

    </div>


    <!-- ============================================================
         TOP CARDS
    ============================================================= -->

    <div class="analysis-grid">


      <div class="analysis-card">

        <div class="analysis-label">
          Fair Line
        </div>

        <div class="analysis-value">
          ${escapeHtml(fairLine)}
        </div>

        <div class="analysis-small">
          Model-implied spread
        </div>

      </div>


      <div class="analysis-card">

        <div class="analysis-label">
          Market Line
        </div>

        <div class="analysis-value">
          ${escapeHtml(marketLine)}
        </div>

        <div class="analysis-small">
          ${
            game?.market?.bookmaker
              ? escapeHtml(
                  game.market.bookmaker
                )
              : "No current market"
          }
        </div>

      </div>


      <div class="analysis-card">

        <div class="analysis-label">
          Model Total
        </div>

        <div class="analysis-value">
          ${
            formatNumber(
              modelTotal,
              1
            )
          }
        </div>

        <div class="analysis-small">

          ${
            hasValue(marketTotal)
              ? `Market ${formatNumber(
                  marketTotal,
                  1
                )}`
              : "No current market total"
          }

        </div>

      </div>


      <div class="analysis-card">

        <div class="analysis-label">
          Line Difference
        </div>

        <div
          class="
            analysis-value
            ${edgeClass}
          "
        >
          ${
            hasValue(edgeSize)
              ? `${formatNumber(
                  edgeSize,
                  1
                )} pts`
              : "—"
          }
        </div>

        <div class="analysis-small">
          ${
            preferred
              ? `Market side: ${
                  escapeHtml(
                    modelEdgeSide
                  )
                }`
              : "No current side edge"
          }
        </div>

      </div>

    </div>


    <div class="analysis-layout">


      <!-- ==========================================================
           WIN PROBABILITY
      =========================================================== -->

      <div class="analysis-panel">

        <div class="analysis-panel-header">

          <div class="analysis-panel-title">
            Win probability
          </div>

        </div>


        <div class="analysis-panel-body">

          <div
            style="
              padding:17px 0 19px;
            "
          >

            <div
              style="
                display:flex;
                justify-content:space-between;
                align-items:flex-end;
                gap:20px;
              "
            >

              <div>

                <div
                  style="
                    font-size:12px;
                    color:var(--muted);
                  "
                >
                  ${escapeHtml(awayName)}
                </div>

                <div
                  style="
                    font-size:23px;
                    font-weight:800;
                  "
                >
                  ${
                    formatPercent(
                      awayWin,
                      1
                    )
                  }
                </div>

              </div>


              <div
                style="
                  text-align:right;
                "
              >

                <div
                  style="
                    font-size:12px;
                    color:var(--muted);
                  "
                >
                  ${escapeHtml(homeName)}
                </div>

                <div
                  style="
                    font-size:23px;
                    font-weight:800;
                  "
                >
                  ${
                    formatPercent(
                      homeWin,
                      1
                    )
                  }
                </div>

              </div>

            </div>


            ${
              hasValue(homeWin)
                ? `
                  <div class="win-prob-wrap">

                    <div class="win-prob-bar">

                      <div
                        class="win-prob-fill"
                        style="
                          width:${Math.max(
                            0,
                            Math.min(
                              100,
                              homeWin
                            )
                          )}%;
                        "
                      >
                      </div>

                    </div>

                    <div class="win-prob-labels">

                      <span>
                        ${escapeHtml(awayName)}
                      </span>

                      <span>
                        ${escapeHtml(homeName)}
                      </span>

                    </div>

                  </div>
                `
                : ""
            }

          </div>

        </div>

      </div>


      <!-- ==========================================================
           POWER FOUNDATION
      =========================================================== -->

      <div class="analysis-panel">

        <div class="analysis-panel-header">

          <div class="analysis-panel-title">
            Power foundation
          </div>

        </div>


        <div class="analysis-panel-body">

          <div class="analysis-row">

            <div class="analysis-row-label">
              ${escapeHtml(awayName)}
              power rating
            </div>

            <div class="analysis-row-value">
              ${
                formatSigned(
                  awayRating,
                  3
                )
              }
            </div>

          </div>


          <div class="analysis-row">

            <div class="analysis-row-label">
              ${escapeHtml(homeName)}
              power rating
            </div>

            <div class="analysis-row-value">
              ${
                formatSigned(
                  homeRating,
                  3
                )
              }
            </div>

          </div>


          <div class="analysis-row">

            <div class="analysis-row-label">
              Rating-only fair line
            </div>

            <div class="analysis-row-value">
              ${
                escapeHtml(
                  favoredLine(
                    homeName,
                    awayName,
                    ratingOnly
                  )
                )
              }
            </div>

          </div>

        </div>

      </div>


      <!-- ==========================================================
           PROJECTION BUILD
      =========================================================== -->

      <div class="analysis-panel">

        <div class="analysis-panel-header">

          <div class="analysis-panel-title">
            Projection build
          </div>

        </div>


        <div class="analysis-panel-body">


          <div class="analysis-row">

            <div class="analysis-row-label">
              Rating-only line
            </div>

            <div class="analysis-row-value">
              ${
                escapeHtml(
                  favoredLine(
                    homeName,
                    awayName,
                    ratingOnly
                  )
                )
              }
            </div>

          </div>


          <div class="analysis-row">

            <div class="analysis-row-label">
              Home-field adjustment
            </div>

            <div class="analysis-row-value">
              ${
                hasValue(hfa)
                  ? `${formatNumber(
                      hfa,
                      1
                    )} pts`
                  : "—"
              }
            </div>

          </div>


          <div class="analysis-row">

            <div class="analysis-row-label">
              Line after home field
            </div>

            <div class="analysis-row-value">
              ${
                escapeHtml(
                  favoredLine(
                    homeName,
                    awayName,
                    afterHfa
                  )
                )
              }
            </div>

          </div>


          <div class="analysis-row">

            <div class="analysis-row-label">
              Live matchup adjustment
            </div>

            <div
              class="
                analysis-row-value
                ${
                  adjustmentClass(
                    matchupTotal
                  )
                }
              "
            >
              ${
                adjustmentText(
                  matchupTotal
                )
              }
            </div>

          </div>


          <div class="analysis-row">

            <div class="analysis-row-label">
              Final fair line
            </div>

            <div class="analysis-row-value">
              ${escapeHtml(fairLine)}
            </div>

          </div>


        </div>

      </div>


      <!-- ==========================================================
           LIVE MATCHUP LAYER
      =========================================================== -->

      <div class="analysis-panel">

        <div class="analysis-panel-header">

          <div class="analysis-panel-title">
            Live matchup layer
          </div>

          <div class="team-meta">
            ${
              sampleComparable
                ? "ACTIVE"
                : "WITHHELD"
            }
          </div>

        </div>


        <div
          class="analysis-panel-body"
          style="
            padding-top:12px;
            padding-bottom:12px;
          "
        >

          <div class="sample-warning">
            ${escapeHtml(matchupNote)}
          </div>


          ${
            matchupComponentRow(
              "Passing",
              matchupComponents?.passing,
              Boolean(
                available?.passing
              )
            )
          }


          ${
            matchupComponentRow(
              "Rushing",
              matchupComponents?.rushing,
              Boolean(
                available?.rushing
              )
            )
          }


          ${
            matchupComponentRow(
              "Success rate",
              matchupComponents?.success_rate,
              Boolean(
                available?.success_rate
              )
            )
          }


          ${
            matchupComponentRow(
              "Explosiveness",
              matchupComponents?.explosiveness,
              Boolean(
                available?.explosiveness
              )
            )
          }


          ${
            matchupComponentRow(
              "Havoc",
              matchupComponents?.havoc,
              Boolean(
                available?.havoc
              )
            )
          }

        </div>

      </div>


      <!-- ==========================================================
           WHY MODEL DIFFERS
      =========================================================== -->

      <div
        class="
          analysis-panel
          wide
        "
      >

        <div class="analysis-panel-header">

          <div class="analysis-panel-title">
            Why the model differs
          </div>

        </div>


        <div class="analysis-panel-body">

          ${
            insightMarkup(
              game?.insights
            )
          }

        </div>

      </div>


    </div>
  `;
}


// ============================================================================
// TEAM DATABASE
// ============================================================================

function sortedTeams() {
  return Object
    .values(teams)
    .sort(
      (a, b) =>
        (
          a.power_rating_rank
          ?? 999
        )
        -
        (
          b.power_rating_rank
          ?? 999
        )
    );
}


function renderTeams() {
  const container =
    document.getElementById(
      "teams-container"
    );

  if (!container) {
    return;
  }

  const data =
    sortedTeams();

  if (!data.length) {

    container.innerHTML = `
      <div class="empty-state">
        No team data available.
      </div>
    `;

    return;
  }


  container.innerHTML = `
    <div class="table-scroll">

      <table class="projection-table">

        <thead>

          <tr>
            <th>Rank</th>
            <th>Team</th>
            <th>Conference</th>
            <th>Record</th>
            <th>Power Rating</th>
            <th>SP+</th>
          </tr>

        </thead>


        <tbody>

          ${
            data
              .map(
                team => `

                  <tr
                    style="
                      cursor:pointer;
                    "
                    onclick="
                      openDossier(
                        '${escapeJsString(team.team)}'
                      )
                    "
                  >

                    <td class="team-meta">
                      ${powerRank(team)}
                    </td>

                    <td>
                      <strong>
                        ${escapeHtml(team.team)}
                      </strong>
                    </td>

                    <td class="team-meta">
                      ${
                        escapeHtml(
                          team.conference
                          ?? "—"
                        )
                      }
                    </td>

                    <td class="team-meta">
                      ${recordText(team)}
                    </td>

                    <td class="line-primary">
                      ${
                        formatSigned(
                          team.power_rating,
                          3
                        )
                      }
                    </td>

                    <td class="team-meta">
                      ${
                        formatSigned(
                          team?.sp_plus?.overall,
                          1
                        )
                      }
                    </td>

                  </tr>
                `
              )
              .join("")
          }

        </tbody>

      </table>

    </div>
  `;
}


// ============================================================================
// RATINGS
// ============================================================================

function renderRatings() {
  const container =
    document.getElementById(
      "ratings-container"
    );

  if (!container) {
    return;
  }

  const data =
    sortedTeams();


  container.innerHTML = `
    <div class="table-scroll">

      <table class="projection-table">

        <thead>

          <tr>
            <th>Rank</th>
            <th>Team</th>
            <th>Power Rating</th>
            <th>SP+</th>
            <th>Net EPA</th>
            <th>Off EPA/Play</th>
            <th>Def EPA/Play</th>
            <th>Def Havoc</th>
          </tr>

        </thead>


        <tbody>

          ${
            data
              .map(
                team => `

                  <tr
                    style="
                      cursor:pointer;
                    "
                    onclick="
                      openDossier(
                        '${escapeJsString(team.team)}'
                      )
                    "
                  >

                    <td class="team-meta">
                      ${powerRank(team)}
                    </td>

                    <td>

                      <strong>
                        ${escapeHtml(team.team)}
                      </strong>

                      <span
                        class="team-meta"
                        style="
                          margin-left:7px;
                        "
                      >
                        ${
                          escapeHtml(
                            team.conference
                            ?? ""
                          )
                        }
                      </span>

                    </td>

                    <td class="line-primary">
                      ${
                        formatSigned(
                          team.power_rating,
                          3
                        )
                      }
                    </td>

                    <td class="team-meta">
                      ${
                        formatSigned(
                          team?.sp_plus?.overall,
                          1
                        )
                      }
                    </td>

                    <td class="team-meta">
                      ${
                        formatEPA(
                          team?.net?.epa
                        )
                      }
                    </td>

                    <td class="team-meta">
                      ${
                        formatEPA(
                          team?.offense?.epa_play
                        )
                      }
                    </td>

                    <td class="team-meta">
                      ${
                        formatEPA(
                          team?.defense?.epa_play
                        )
                      }
                    </td>

                    <td class="team-meta">
                      ${
                        formatRate(
                          team?.defense?.havoc_created
                        )
                      }
                    </td>

                  </tr>
                `
              )
              .join("")
          }

        </tbody>

      </table>

    </div>
  `;
}


// ============================================================================
// TEAM DOSSIER
// ============================================================================

function openDossier(teamName) {
  const team =
    getTeam(teamName);

  if (!team) {
    return;
  }

  renderDossier(team);

  switchView(
    "dossier"
  );
}


function teamSchedule(teamName) {
  return projections

    .filter(
      game =>
        game?.home?.team
        === teamName
        ||
        game?.away?.team
        === teamName
    )

    .sort(
      (a, b) =>
        (
          a.week
          ?? 99
        )
        -
        (
          b.week
          ?? 99
        )
    );
}


function renderMetricRow(
  name,
  value,
  rank = ""
) {
  return `
    <div class="metric-row">

      <div class="metric-name">
        ${escapeHtml(name)}
      </div>

      <div class="metric-value">
        ${value}
      </div>

      <div class="metric-rank">
        ${rank || ""}
      </div>

    </div>
  `;
}


function renderDossier(team) {
  const container =
    document.getElementById(
      "dossier-container"
    );

  if (!container) {
    return;
  }


  const games =
    teamSchedule(
      team.team
    );


  const upcomingGames =
    games.filter(
      game => {

        if (!game.start_date) {
          return true;
        }

        return (
          new Date(
            game.start_date
          ).getTime()
          >=
          Date.now()
          -
          86400000
        );
      }
    );


  const scheduleRows =
    upcomingGames
      .slice(
        0,
        12
      )
      .map(
        game => {

          const home =
            game.home.team;

          const away =
            game.away.team;

          const opponent =
            home === team.team
              ? away
              : home;

          const location =
            home === team.team
              ? "vs"
              : "@";

          const modelSpread =
            game?.projection?.home_spread;

          let teamSpread =
            null;

          if (
            hasValue(
              modelSpread
            )
          ) {

            teamSpread =
              home === team.team
                ? Number(
                    modelSpread
                  )
                : -Number(
                    modelSpread
                  );
          }


          return `
            <div
              class="metric-row"
              style="
                cursor:pointer;
              "
              onclick="
                openMatchup(
                  '${escapeJsString(String(game.game_id ?? ""))}'
                )
              "
            >

              <div>

                <div
                  style="
                    font-weight:600;
                    font-size:12px;
                  "
                >
                  Week ${
                    game.week
                    ?? "—"
                  }
                  · ${location}
                  ${escapeHtml(opponent)}
                </div>

                <div
                  class="team-meta"
                  style="
                    margin-top:4px;
                  "
                >
                  ${
                    escapeHtml(
                      gameDateText(
                        game.start_date
                      )
                    )
                  }
                </div>

              </div>


              <div class="metric-value">
                ${
                  shortSpread(
                    teamSpread
                  )
                }
              </div>


              <div class="metric-rank">
                ${
                  game?.comparison?.status
                  &&
                  game?.comparison?.status
                  !== "NO MARKET"

                    ? escapeHtml(
                        game.comparison.status
                      )

                    : ""
                }
              </div>

            </div>
          `;
        }
      )
      .join("");


  const offLive =
    liveSection(
      team,
      "offense"
    );

  const defLive =
    liveSection(
      team,
      "defense"
    );


  const offModelEPA =
    team?.offense?.epa_play;

  const defModelEPA =
    team?.defense?.epa_play;


  const offModelSR =
    team?.offense?.success_rate;

  const defModelSR =
    team?.defense?.success_rate;


  const offPlays =
    livePlays(
      team,
      "offense"
    );

  const defPlays =
    livePlays(
      team,
      "defense"
    );


  container.innerHTML = `

    <div class="dossier-header">

      <div>

        <div class="eyebrow">
          Team dossier
        </div>

        <div class="team-title-row">

          <div class="team-title">
            ${escapeHtml(team.team)}
          </div>

        </div>

        <div class="team-dossier-sub">

          ${
            escapeHtml(
              team.conference
              ?? "Independent"
            )
          }

          · ${recordText(team)}

          · ${
            escapeHtml(
              liveSampleLabel(team)
            )
          }

        </div>

      </div>


      <div class="sim-wins">

        <div class="sim-wins-label">
          Power rank
        </div>

        <div class="sim-wins-number">
          ${powerRank(team)}
        </div>

      </div>

    </div>


    <div class="dossier-stat-grid">

      <div class="dossier-stat">

        <div class="dossier-label">
          Power Rating
        </div>

        <div class="dossier-value">
          ${
            formatSigned(
              team.power_rating,
              3
            )
          }
        </div>

      </div>


      <div class="dossier-stat">

        <div class="dossier-label">
          SP+ Overall
        </div>

        <div class="dossier-value">
          ${
            formatSigned(
              team?.sp_plus?.overall,
              1
            )
          }
        </div>

      </div>


      <div class="dossier-stat">

        <div class="dossier-label">
          SP+ Offense
        </div>

        <div class="dossier-value">
          ${
            formatSigned(
              team?.sp_plus?.offense,
              1
            )
          }
        </div>

      </div>


      <div class="dossier-stat">

        <div class="dossier-label">
          SP+ Defense
        </div>

        <div class="dossier-value">
          ${
            formatSigned(
              team?.sp_plus?.defense,
              1
            )
          }
        </div>

      </div>


      <div class="dossier-stat">

        <div class="dossier-label">
          Record
        </div>

        <div class="dossier-value">
          ${recordText(team)}
        </div>

      </div>

    </div>


    <div class="dossier-layout">


      <div class="panel">

        <div class="panel-header">

          <div class="panel-title">
            Offensive Profile
          </div>

        </div>

        <div class="panel-body">

          ${
            renderMetricRow(
              "Model EPA / Play",
              formatEPA(
                offModelEPA
              ),
              metricRank(
                team,
                "offense",
                "epa_play_rank",
                offModelEPA
              )
            )
          }

          ${
            renderMetricRow(
              "Model Success Rate",
              formatRate(
                offModelSR
              ),
              metricRank(
                team,
                "offense",
                "sr_rank",
                offModelSR
              )
            )
          }

          ${
            renderMetricRow(
              "2026 EPA / Pass",
              formatEPA(
                offLive?.epa_pass
              )
            )
          }

          ${
            renderMetricRow(
              "2026 EPA / Rush",
              formatEPA(
                offLive?.epa_rush
              )
            )
          }

          ${
            renderMetricRow(
              "2026 Success Rate",
              formatRate(
                offLive?.success_rate
              )
            )
          }

          ${
            renderMetricRow(
              "2026 Explosive Rate",
              formatRate(
                offLive?.explosive_rate
              )
            )
          }

          ${
            renderMetricRow(
              "2026 Havoc Allowed",
              formatRate(
                offLive?.havoc_rate
              )
            )
          }

        </div>

      </div>


      <div class="panel">

        <div class="panel-header">

          <div class="panel-title">
            Defensive Profile
          </div>

        </div>

        <div class="panel-body">

          ${
            renderMetricRow(
              "Model EPA / Play",
              formatEPA(
                defModelEPA
              ),
              metricRank(
                team,
                "defense",
                "epa_play_rank",
                defModelEPA
              )
            )
          }

          ${
            renderMetricRow(
              "Model Success Rate Allowed",
              formatRate(
                defModelSR
              ),
              metricRank(
                team,
                "defense",
                "sr_rank",
                defModelSR
              )
            )
          }

          ${
            renderMetricRow(
              "2026 EPA / Pass Allowed",
              formatEPA(
                defLive?.epa_pass
              )
            )
          }

          ${
            renderMetricRow(
              "2026 EPA / Rush Allowed",
              formatEPA(
                defLive?.epa_rush
              )
            )
          }

          ${
            renderMetricRow(
              "2026 Success Rate Allowed",
              formatRate(
                defLive?.success_rate
              )
            )
          }

          ${
            renderMetricRow(
              "2026 Explosive Rate Allowed",
              formatRate(
                defLive?.explosive_rate
              )
            )
          }

          ${
            renderMetricRow(
              "2026 Havoc Created",
              formatRate(
                defLive?.havoc_rate
              )
            )
          }

        </div>

      </div>


      <div class="panel">

        <div class="panel-header">

          <div class="panel-title">
            Net Efficiency
          </div>

        </div>

        <div class="panel-body">

          ${
            renderMetricRow(
              "Model Net EPA / Play",
              formatEPA(
                team?.net?.epa
              )
            )
          }

          ${
            renderMetricRow(
              "Model Net Success Rate",
              formatPercent(
                team?.net?.sr
              )
            )
          }

          ${
            renderMetricRow(
              "2026 Net EPA / Pass",
              formatEPA(
                liveNet(
                  team,
                  "epa_pass"
                )
              )
            )
          }

          ${
            renderMetricRow(
              "2026 Net EPA / Rush",
              formatEPA(
                liveNet(
                  team,
                  "epa_rush"
                )
              )
            )
          }

          ${
            renderMetricRow(
              "2026 Net Success Rate",
              formatPercent(
                liveNet(
                  team,
                  "success_rate"
                )
              )
            )
          }

        </div>

      </div>


      <div class="panel">

        <div class="panel-header">

          <div class="panel-title">
            Model Context
          </div>

        </div>

        <div class="panel-body">

          ${
            renderMetricRow(
              "Power Rank",
              powerRank(team)
            )
          }

          ${
            renderMetricRow(
              "Conference",
              escapeHtml(
                team.conference
                ?? "—"
              )
            )
          }

          ${
            renderMetricRow(
              "2026 Offensive Plays",
              offPlays > 0
                ? formatNumber(
                    offPlays,
                    0
                  )
                : "—"
            )
          }

          ${
            renderMetricRow(
              "2026 Defensive Plays",
              defPlays > 0
                ? formatNumber(
                    defPlays,
                    0
                  )
                : "—"
            )
          }

          ${
            renderMetricRow(
              "Live Data Weight",
              metricsData?.meta?.blend_weight
                !== undefined

                ? formatPercent(
                    Number(
                      metricsData
                        .meta
                        .blend_weight
                    )
                    * 100,
                    0
                  )

                : "—"
            )
          }

          ${
            renderMetricRow(
              "Sample Status",
              escapeHtml(
                liveSampleLabel(team)
              )
            )
          }

        </div>

      </div>


      <div
        class="
          panel
          schedule-panel
        "
      >

        <div class="panel-header">

          <div class="panel-title">
            2026 Schedule & Model Lines
          </div>

          <div class="team-meta">
            ${games.length} games
          </div>

        </div>


        <div class="panel-body">

          ${
            scheduleRows
            ||
            `
              <div class="empty-state">
                No upcoming schedule available.
              </div>
            `
          }

        </div>

      </div>

    </div>
  `;
}


// ============================================================================
// EVENTS
// ============================================================================

function attachEvents() {
  const search =
    document.getElementById(
      "team-search"
    );

  if (search) {

    search.addEventListener(
      "input",
      event => {

        currentSearch =
          event.target.value
            .trim();

        renderProjections();
      }
    );
  }
}


// ============================================================================
// START
// ============================================================================

document.addEventListener(
  "DOMContentLoaded",
  init
);
