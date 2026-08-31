// ============================================================================
// CFB ANALYTICS — FRONTEND
// ============================================================================
//
// The browser NEVER calls CFBD or The Odds API directly.
//
// GitHub Actions builds these files:
//   data/cfb_metrics.json
//   data/schedule.json
//   data/odds.json
//   data/projections.json
//
// This frontend only reads those static JSON files.
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

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}


function formatNumber(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "—";
  }

  return Number(value).toFixed(digits);
}


function formatSigned(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "—";
  }

  const number = Number(value);

  if (number > 0) {
    return `+${number.toFixed(digits)}`;
  }

  return number.toFixed(digits);
}


function formatEPA(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "—";
  }

  const number = Number(value);

  if (number > 0) {
    return `+${number.toFixed(3)}`;
  }

  return number.toFixed(3);
}


function formatPercent(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "—";
  }

  return `${Number(value).toFixed(digits)}%`;
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
  if (!status || status === "NO MARKET") {
    return "NO LINE";
  }

  return status;
}


function spreadText(spread, homeTeam) {
  if (spread === null || spread === undefined) {
    return "—";
  }

  const number = Number(spread);

  if (number === 0) {
    return "PK";
  }

  return `${homeTeam} ${formatSigned(number)}`;
}


function shortSpread(spread) {
  if (spread === null || spread === undefined) {
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

  if (Number.isNaN(date.getTime())) {
    return "TBD";
  }

  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}


function metricRank(team, section, rankField) {
  const rank = team?.[section]?.[rankField];

  if (!rank || rank <= 0) {
    return "—";
  }

  return `#${rank}`;
}


function powerRank(team) {
  const rank = team?.power_rating_rank;

  if (!rank) {
    return "—";
  }

  return `#${rank}`;
}


function getTeam(name) {
  return teams?.[name] ?? null;
}


function getProjectionTeams(game) {
  return {
    awayName: game?.away?.team,
    homeName: game?.home?.team,
    away: getTeam(game?.away?.team),
    home: getTeam(game?.home?.team),
  };
}


// ============================================================================
// VIEW SWITCHING
// ============================================================================

function switchView(viewName) {
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.remove("active");
  });

  const requested = document.getElementById(`view-${viewName}`);

  if (requested) {
    requested.classList.add("active");
  }

  document.querySelectorAll(".nav-item").forEach((button) => {
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
// DATA LOADING
// ============================================================================

async function loadJson(url) {
  const response = await fetch(`${url}?v=${Date.now()}`);

  if (!response.ok) {
    throw new Error(`${url} returned HTTP ${response.status}`);
  }

  return response.json();
}


async function init() {
  try {
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

    teams = metricsData?.teams ?? {};
    projections = projectionsData?.games ?? [];

    updateHeader();

    buildWeekTabs();
    renderProjections();

    renderTeams();
    renderRatings();

    attachEvents();

  } catch (error) {
    console.error("Frontend initialization failed:", error);

    const container = document.getElementById(
      "projections-container"
    );

    if (container) {
      container.innerHTML = `
        <div class="empty-state">
          Unable to load analytics data.<br><br>
          <span style="font-family:var(--mono);font-size:11px;">
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
  const header = document.getElementById("data-updated");

  if (!header) {
    return;
  }

  const generated =
    projectionsData?.meta?.generated ||
    metricsData?.meta?.generated;

  if (!generated) {
    header.textContent = "2026 model";
    return;
  }

  const date = new Date(generated);

  if (Number.isNaN(date.getTime())) {
    header.textContent = "2026 model";
    return;
  }

  header.textContent = `Updated ${date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  })}`;
}


// ============================================================================
// WEEK TABS
// ============================================================================

function availableWeeks() {
  const weeks = projections
    .map((game) => game.week)
    .filter((week) => week !== null && week !== undefined)
    .map(Number)
    .filter((week) => !Number.isNaN(week));

  return [...new Set(weeks)].sort((a, b) => a - b);
}


function determineDefaultWeek(weeks) {
  if (!weeks.length) {
    return null;
  }

  const gamesWithMarket = projections.filter((game) => {
    return (
      game?.market?.home_spread !== null &&
      game?.market?.home_spread !== undefined
    );
  });

  if (gamesWithMarket.length) {
    const marketWeeks = gamesWithMarket
      .map((game) => Number(game.week))
      .filter((week) => !Number.isNaN(week));

    if (marketWeeks.length) {
      return Math.min(...marketWeeks);
    }
  }

  const upcoming = projections
    .filter((game) => {
      if (!game.start_date) {
        return false;
      }

      return new Date(game.start_date).getTime() >= Date.now();
    })
    .sort(
      (a, b) =>
        new Date(a.start_date).getTime() -
        new Date(b.start_date).getTime()
    );

  if (upcoming.length && upcoming[0].week !== null) {
    return Number(upcoming[0].week);
  }

  return weeks[0];
}


function buildWeekTabs() {
  const container = document.getElementById("week-tabs");

  if (!container) {
    return;
  }

  const weeks = availableWeeks();

  if (!weeks.length) {
    container.innerHTML = "";
    return;
  }

  if (currentWeek === null) {
    currentWeek = determineDefaultWeek(weeks);
  }

  container.innerHTML = weeks
    .map((week) => {
      const active = Number(week) === Number(currentWeek);

      return `
        <button
          class="week-tab ${active ? "active" : ""}"
          onclick="selectWeek(${week})"
        >
          ${week === 0 ? "Week 0" : `Week ${week}`}
        </button>
      `;
    })
    .join("");
}


function selectWeek(week) {
  currentWeek = Number(week);

  buildWeekTabs();
  renderProjections();
}


// ============================================================================
// PROJECTION BOARD
// ============================================================================

function projectionGamesForCurrentView() {
  return projections
    .filter((game) => {
      if (
        currentWeek !== null &&
        Number(game.week) !== Number(currentWeek)
      ) {
        return false;
      }

      if (!currentSearch) {
        return true;
      }

      const query = currentSearch.toLowerCase();

      const home =
        game?.home?.team?.toLowerCase() ?? "";

      const away =
        game?.away?.team?.toLowerCase() ?? "";

      return (
        home.includes(query) ||
        away.includes(query)
      );
    })
    .sort((a, b) => {
      const aDisagreement =
        a?.comparison?.disagreement ?? -1;

      const bDisagreement =
        b?.comparison?.disagreement ?? -1;

      if (bDisagreement !== aDisagreement) {
        return bDisagreement - aDisagreement;
      }

      return (
        new Date(a.start_date || 0).getTime() -
        new Date(b.start_date || 0).getTime()
      );
    });
}


function renderProjections() {
  const container = document.getElementById(
    "projections-container"
  );

  const summary = document.getElementById(
    "projection-summary"
  );

  if (!container) {
    return;
  }

  if (!projections.length) {
    container.innerHTML = `
      <div class="empty-state">
        No projections are currently available.
      </div>
    `;

    if (summary) {
      summary.textContent = "0 games";
    }

    return;
  }

  const games = projectionGamesForCurrentView();

  const marketGames = games.filter(
    (game) =>
      game?.market?.home_spread !== null &&
      game?.market?.home_spread !== undefined
  );

  const plays = games.filter(
    (game) =>
      game?.comparison?.status === "PLAY"
  );

  const watches = games.filter(
    (game) =>
      game?.comparison?.status === "WATCH"
  );

  if (summary) {
    summary.innerHTML = `
      ${games.length} games
      · ${marketGames.length} lined
      · <strong>${plays.length} plays</strong>
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

  const rows = games.map(renderProjectionRow).join("");

  container.innerHTML = `
    <table class="projection-table">
      <thead>
        <tr>
          <th>Matchup</th>
          <th>Our Line</th>
          <th>Market</th>
          <th>Total</th>
          <th class="align-right">Disagreement</th>
          <th class="align-right">Status</th>
        </tr>
      </thead>

      <tbody>
        ${rows}
      </tbody>
    </table>
  `;
}


function renderProjectionRow(game) {
  const homeName = game?.home?.team ?? "Unknown";
  const awayName = game?.away?.team ?? "Unknown";

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

  let disagreementNote = "No market line";

  if (
    disagreement !== null &&
    disagreement !== undefined
  ) {
    disagreementNote = preferred
      ? `Model favors ${preferred}`
      : "Model agrees with market";
  }

  return `
    <tr>

      <td class="matchup-cell">

        <div
          class="team-line"
          onclick="openDossier('${escapeJsString(awayName)}')"
        >
          <span class="team-name">
            ${escapeHtml(awayName)}
          </span>

          <span class="team-meta">
            ${awayRank ? `#${awayRank}` : ""}
          </span>
        </div>

        <div class="team-line">
          <span class="at-symbol">@</span>

          <span
            class="team-name"
            onclick="openDossier('${escapeJsString(homeName)}')"
          >
            ${escapeHtml(homeName)}
          </span>

          <span class="team-meta">
            ${homeRank ? `#${homeRank}` : ""}
          </span>
        </div>

        <div
          class="team-meta"
          style="margin-top:5px;"
        >
          ${escapeHtml(gameDateText(game.start_date))}
        </div>

      </td>


      <td>
        <div class="line-primary">
          ${escapeHtml(shortSpread(modelSpread))}
        </div>

        <div class="line-secondary">
          ${escapeHtml(homeName)} home line
        </div>
      </td>


      <td>
        <div class="line-primary">
          ${escapeHtml(shortSpread(marketSpread))}
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
          ${formatNumber(modelTotal, 1)}
        </div>

        <div class="line-secondary">
          ${
            marketTotal !== null &&
            marketTotal !== undefined
              ? `Market ${formatNumber(marketTotal, 1)}`
              : "Model total"
          }
        </div>
      </td>


      <td class="disagreement">

        <div
          class="disagreement-number ${cssStatus}"
        >
          ${
            disagreement !== null &&
            disagreement !== undefined
              ? `${formatNumber(disagreement, 1)} pts`
              : "—"
          }
        </div>

        <div class="disagreement-note">
          ${escapeHtml(disagreementNote)}
        </div>

      </td>


      <td class="status-cell">
        <span class="status ${cssStatus}">
          ${escapeHtml(displayStatus(status))}
        </span>
      </td>

    </tr>
  `;
}


function escapeJsString(value) {
  return String(value ?? "")
    .replaceAll("\\", "\\\\")
    .replaceAll("'", "\\'");
}


// ============================================================================
// TEAM DATABASE
// ============================================================================

function sortedTeams() {
  return Object.values(teams).sort((a, b) => {
    const ar =
      a.power_rating_rank ?? 999;

    const br =
      b.power_rating_rank ?? 999;

    return ar - br;
  });
}


function renderTeams() {
  const container = document.getElementById(
    "teams-container"
  );

  if (!container) {
    return;
  }

  const data = sortedTeams();

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

          ${data
            .map(
              (team) => `
              <tr
                style="cursor:pointer;"
                onclick="openDossier('${escapeJsString(team.team)}')"
              >
                <td class="team-meta">
                  ${powerRank(team)}
                </td>

                <td>
                  <strong>${escapeHtml(team.team)}</strong>
                </td>

                <td class="team-meta">
                  ${escapeHtml(team.conference ?? "—")}
                </td>

                <td class="team-meta">
                  ${recordText(team)}
                </td>

                <td class="line-primary">
                  ${formatSigned(team.power_rating, 3)}
                </td>

                <td class="team-meta">
                  ${formatSigned(team?.sp_plus?.overall, 1)}
                </td>
              </tr>
            `
            )
            .join("")}

        </tbody>

      </table>

    </div>
  `;
}


// ============================================================================
// POWER RATINGS
// ============================================================================

function renderRatings() {
  const container = document.getElementById(
    "ratings-container"
  );

  if (!container) {
    return;
  }

  const data = sortedTeams();

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

          ${data
            .map(
              (team) => `
              <tr
                style="cursor:pointer;"
                onclick="openDossier('${escapeJsString(team.team)}')"
              >
                <td class="team-meta">
                  ${powerRank(team)}
                </td>

                <td>
                  <strong>${escapeHtml(team.team)}</strong>

                  <span
                    class="team-meta"
                    style="margin-left:7px;"
                  >
                    ${escapeHtml(team.conference ?? "")}
                  </span>
                </td>

                <td class="line-primary">
                  ${formatSigned(team.power_rating, 3)}
                </td>

                <td class="team-meta">
                  ${formatSigned(team?.sp_plus?.overall, 1)}
                </td>

                <td class="team-meta">
                  ${formatEPA(team?.net?.epa)}
                </td>

                <td class="team-meta">
                  ${formatEPA(team?.offense?.epa_play)}
                </td>

                <td class="team-meta">
                  ${formatEPA(team?.defense?.epa_play)}
                </td>

                <td class="team-meta">
                  ${formatPercent(team?.defense?.havoc_created)}
                </td>
              </tr>
            `
            )
            .join("")}

        </tbody>

      </table>

    </div>
  `;
}


// ============================================================================
// TEAM DOSSIER
// ============================================================================

function openDossier(teamName) {
  const team = getTeam(teamName);

  if (!team) {
    return;
  }

  renderDossier(team);

  switchView("dossier");
}


function teamSchedule(teamName) {
  return projections
    .filter((game) => {
      return (
        game?.home?.team === teamName ||
        game?.away?.team === teamName
      );
    })
    .sort((a, b) => {
      const aw =
        a.week ?? 99;

      const bw =
        b.week ?? 99;

      return aw - bw;
    });
}


function renderMetricRow(
  name,
  value,
  rank
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
        ${rank || "—"}
      </div>

    </div>
  `;
}


function renderDossier(team) {
  const container = document.getElementById(
    "dossier-container"
  );

  if (!container) {
    return;
  }

  const games = teamSchedule(team.team);

  const upcomingGames = games.filter((game) => {
    if (!game.start_date) {
      return true;
    }

    return (
      new Date(game.start_date).getTime() >=
      Date.now() - 86400000
    );
  });

  const scheduleRows = upcomingGames
    .slice(0, 12)
    .map((game) => {
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

      let teamSpread = null;

      if (
        modelSpread !== null &&
        modelSpread !== undefined
      ) {
        teamSpread =
          home === team.team
            ? modelSpread
            : -modelSpread;
      }

      return `
        <div class="metric-row">

          <div>
            <div
              style="font-weight:600;font-size:12px;"
            >
              Week ${game.week ?? "—"}
              · ${location}
              ${escapeHtml(opponent)}
            </div>

            <div
              class="team-meta"
              style="margin-top:4px;"
            >
              ${escapeHtml(gameDateText(game.start_date))}
            </div>
          </div>

          <div class="metric-value">
            ${shortSpread(teamSpread)}
          </div>

          <div class="metric-rank">
            ${
              game?.comparison?.status &&
              game?.comparison?.status !== "NO MARKET"
                ? escapeHtml(game.comparison.status)
                : ""
            }
          </div>

        </div>
      `;
    })
    .join("");

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
          ${escapeHtml(team.conference ?? "Independent")}
          · ${recordText(team)}
          · 2026 model profile
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
          ${formatSigned(team.power_rating, 3)}
        </div>
      </div>


      <div class="dossier-stat">
        <div class="dossier-label">
          SP+ Overall
        </div>

        <div class="dossier-value">
          ${formatSigned(team?.sp_plus?.overall, 1)}
        </div>
      </div>


      <div class="dossier-stat">
        <div class="dossier-label">
          SP+ Offense
        </div>

        <div class="dossier-value">
          ${formatSigned(team?.sp_plus?.offense, 1)}
        </div>
      </div>


      <div class="dossier-stat">
        <div class="dossier-label">
          SP+ Defense
        </div>

        <div class="dossier-value">
          ${formatSigned(team?.sp_plus?.defense, 1)}
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

          ${renderMetricRow(
            "EPA / Play",
            formatEPA(team?.offense?.epa_play),
            metricRank(team, "offense", "epa_play_rank")
          )}

          ${renderMetricRow(
            "EPA / Pass",
            formatEPA(team?.offense?.epa_pass),
            metricRank(team, "offense", "epa_pass_rank")
          )}

          ${renderMetricRow(
            "EPA / Rush",
            formatEPA(team?.offense?.epa_rush),
            metricRank(team, "offense", "epa_rush_rank")
          )}

          ${renderMetricRow(
            "Success Rate",
            formatPercent(team?.offense?.success_rate),
            metricRank(team, "offense", "sr_rank")
          )}

          ${renderMetricRow(
            "Explosive Rate",
            formatPercent(team?.offense?.explosive_rate),
            metricRank(team, "offense", "expl_rank")
          )}

          ${renderMetricRow(
            "Havoc Allowed",
            formatPercent(team?.offense?.havoc_allowed),
            metricRank(team, "offense", "havoc_rank")
          )}

        </div>

      </div>


      <div class="panel">

        <div class="panel-header">
          <div class="panel-title">
            Defensive Profile
          </div>
        </div>

        <div class="panel-body">

          ${renderMetricRow(
            "EPA / Play",
            formatEPA(team?.defense?.epa_play),
            metricRank(team, "defense", "epa_play_rank")
          )}

          ${renderMetricRow(
            "EPA / Pass",
            formatEPA(team?.defense?.epa_pass),
            metricRank(team, "defense", "epa_pass_rank")
          )}

          ${renderMetricRow(
            "EPA / Rush",
            formatEPA(team?.defense?.epa_rush),
            metricRank(team, "defense", "epa_rush_rank")
          )}

          ${renderMetricRow(
            "Success Rate Allowed",
            formatPercent(team?.defense?.success_rate),
            metricRank(team, "defense", "sr_rank")
          )}

          ${renderMetricRow(
            "Explosive Rate Allowed",
            formatPercent(team?.defense?.explosive_rate),
            metricRank(team, "defense", "expl_rank")
          )}

          ${renderMetricRow(
            "Havoc Created",
            formatPercent(team?.defense?.havoc_created),
            metricRank(team, "defense", "havoc_rank")
          )}

        </div>

      </div>


      <div class="panel">

        <div class="panel-header">
          <div class="panel-title">
            Net Efficiency
          </div>
        </div>

        <div class="panel-body">

          ${renderMetricRow(
            "Net EPA / Play",
            formatEPA(team?.net?.epa),
            team?.net?.epa_rank
              ? `#${team.net.epa_rank}`
              : "—"
          )}

          ${renderMetricRow(
            "Net EPA / Pass",
            formatEPA(team?.net?.epa_pass),
            "—"
          )}

          ${renderMetricRow(
            "Net EPA / Rush",
            formatEPA(team?.net?.epa_rush),
            "—"
          )}

          ${renderMetricRow(
            "Net Success Rate",
            formatPercent(team?.net?.sr),
            "—"
          )}

        </div>

      </div>


      <div class="panel">

        <div class="panel-header">
          <div class="panel-title">
            Model Context
          </div>
        </div>

        <div class="panel-body">

          ${renderMetricRow(
            "Power Rank",
            powerRank(team),
            ""
          )}

          ${renderMetricRow(
            "Conference",
            escapeHtml(team.conference ?? "—"),
            ""
          )}

          ${renderMetricRow(
            "Offensive Plays",
            formatNumber(team?.offense?.n_plays, 0),
            ""
          )}

          ${renderMetricRow(
            "Defensive Plays",
            formatNumber(team?.defense?.n_plays, 0),
            ""
          )}

          ${renderMetricRow(
            "Live Data Weight",
            metricsData?.meta?.blend_weight !== undefined
              ? formatPercent(
                  Number(metricsData.meta.blend_weight) * 100,
                  0
                )
              : "—",
            ""
          )}

        </div>

      </div>


      <div class="panel schedule-panel">

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
            scheduleRows ||
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
  const search = document.getElementById(
    "team-search"
  );

  if (search) {
    search.addEventListener("input", (event) => {
      currentSearch =
        event.target.value.trim();

      renderProjections();
    });
  }
}


// ============================================================================
// START
// ============================================================================

document.addEventListener(
  "DOMContentLoaded",
  init
);
