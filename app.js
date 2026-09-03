// ============================================================================
// CFB ANALYTICS — FRONTEND
// Signal System v1: ALIGNED / SMALL EDGE / PLAY / MATERIAL DISAGREEMENT / OUTLIER
// ============================================================================

const DATA_URLS = {
  metrics: "./data/cfb_metrics.json",
  schedule: "./data/schedule.json",
  odds: "./data/odds.json",
  projections: "./data/projections.json",
  signalReport: "./data/reports/signal_report.json",
  advancedMetrics: "./data/advanced_metrics.json",
  externalRatings: "./data/external_ratings.json",
  rosterFoundation: "./data/roster_foundation.json",
  hfa: "./data/hfa_2026.json",
};

let metricsData = null;
let scheduleData = null;
let oddsData = null;
let projectionsData = null;
let signalReportData = null;
let advancedMetricsData = null;
let externalRatingsData = null;
let rosterFoundationData = null;
let hfaData = null;

let teams = {};
let projections = [];
let seasonProjections = {};

let currentWeek = null;
let currentSearch = "";
let currentRatingsMode = "overview";
let currentTeamConference = "ALL";
let currentAdvancedSample = "non_garbage";
let currentDossierTeamName = null;
let tapeTeamA = null;
let tapeTeamB = null;
let tapeVenue = "neutral";


// ============================================================================
// HELPERS
// ============================================================================

function hasValue(value) {
  return value !== null && value !== undefined && !Number.isNaN(Number(value));
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
  if (!hasValue(value)) return "—";
  return Number(value).toFixed(digits);
}

function formatSigned(value, digits = 1) {
  if (!hasValue(value)) return "—";
  const number = Number(value);
  return number > 0 ? `+${number.toFixed(digits)}` : number.toFixed(digits);
}

function formatEPA(value) {
  if (!hasValue(value)) return "—";
  const number = Number(value);
  return number > 0 ? `+${number.toFixed(3)}` : number.toFixed(3);
}

function formatPercent(value, digits = 1) {
  if (!hasValue(value)) return "—";
  return `${Number(value).toFixed(digits)}%`;
}

function formatRate(value, digits = 1) {
  if (!hasValue(value)) return "—";
  const number = Number(value);
  if (number < 0 || number > 100) return "—";
  return `${number.toFixed(digits)}%`;
}

function recordText(team) {
  const record = team?.record;
  if (!record) return "—";
  return `${record.wins ?? 0}-${record.losses ?? 0}`;
}

function canonicalSignal(status) {
  if (!status || status === "NO MARKET") return "NO LINE";

  switch (status) {
    case "AGREE W/ MARKET":
    case "ALIGNED":
      return "ALIGNED";
    case "LEAN":
    case "SLIGHT EDGE":
    case "SMALL EDGE":
      return "SMALL EDGE";
    case "EDGE":
    case "PLAY":
      return "PLAY";
    case "STRONG EDGE":
    case "MATERIAL DISAGREEMENT":
      return "MATERIAL DISAGREEMENT";
    case "OUTLIER":
      return "OUTLIER";
    default:
      return status;
  }
}

function statusClass(status) {
  switch (canonicalSignal(status)) {
    case "MATERIAL DISAGREEMENT": return "material";
    case "PLAY": return "play";
    case "SMALL EDGE": return "small-edge";
    case "OUTLIER": return "outlier";
    case "ALIGNED": return "agree";
    default: return "inline";
  }
}

function displayStatus(status) {
  return canonicalSignal(status);
}

function signalStats(status) {
  const signal = canonicalSignal(status);
  return signalReportData?.signals?.[signal] ?? null;
}

function signalConfidence(status) {
  if (canonicalSignal(status) === "NO LINE") return "—";
  return signalStats(status)?.confidence ?? "DEVELOPING";
}

function confidenceClass(confidence) {
  switch (String(confidence || "").toUpperCase()) {
    case "ESTABLISHED": return "confidence-established";
    case "VALIDATED": return "confidence-validated";
    case "DEVELOPING": return "confidence-developing";
    default: return "agree";
  }
}

function signalRecordText(status) {
  if (canonicalSignal(status) === "NO LINE") return "—";
  return signalStats(status)?.record?.record_text ?? "0-0";
}

function signalAtsText(status) {
  if (canonicalSignal(status) === "NO LINE") return "No market";
  const pct = signalStats(status)?.record?.ats_win_pct_ex_pushes;
  return hasValue(pct) ? `${formatNumber(pct, 1)}% ATS` : "ATS tracking";
}

function signalClvText(status) {
  const clv = signalStats(status)?.clv?.average_clv_points;
  return hasValue(clv) ? `${formatSigned(clv, 2)} avg CLV` : "CLV tracking";
}

function signalBeatCloseText(status) {
  const pct = signalStats(status)?.clv?.beat_close_pct_ex_pushes;
  return hasValue(pct) ? `${formatNumber(pct, 1)}% beat close` : "Beat-close tracking";
}

function statusEdgeClass(status) {
  switch (canonicalSignal(status)) {
    case "MATERIAL DISAGREEMENT": return "edge-material";
    case "PLAY": return "edge-play";
    case "SMALL EDGE": return "edge-small";
    case "OUTLIER": return "edge-outlier";
    default: return "";
  }
}

function shortSpread(spread) {
  if (!hasValue(spread)) return "—";
  const number = Number(spread);
  if (number === 0) return "PK";
  return formatSigned(number);
}

function gameDateText(dateString) {
  if (!dateString) return "TBD";
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return "TBD";
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function metricRank(team, section, rankField, value) {
  if (!hasValue(value)) return "";
  const rank = team?.[section]?.[rankField];
  if (!rank || rank <= 0) return "";
  return `#${rank}`;
}

function powerRank(team) {
  const rank = team?.power_rating_rank;
  return rank ? `#${rank}` : "—";
}

function spPlusRank(team, field) {
  const target = team?.sp_plus?.[field];
  if (!hasValue(target)) return "";

  const ascending = field === "defense";
  const values = Object.values(teams)
    .filter(item => hasValue(item?.sp_plus?.[field]))
    .map(item => Number(item.sp_plus[field]));

  const targetNumber = Number(target);
  const better = values.filter(value =>
    ascending ? value < targetNumber : value > targetNumber
  ).length;

  return `#${better + 1} Overall`;
}

function teamLogoInitials(teamName) {
  const words = String(teamName || "?").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return words.slice(0, 2).map(word => word[0]).join("").toUpperCase();
}

function teamLogoMarkup(teamName, size = "table") {
  const external = externalRatingsData?.teams?.[teamName] ?? {};
  const logo = external.logo || external.logo_dark || "";
  const color = String(external.color || "18212b").replace(/^#/, "");
  const initials = escapeHtml(teamLogoInitials(teamName));

  return `
    <span
      class="team-logo team-logo-${escapeHtml(size)}"
      style="--team-color:#${escapeHtml(color)}"
      aria-hidden="true"
    >
      ${
        logo
          ? `
            <img
              src="${escapeHtml(logo)}"
              alt=""
              loading="lazy"
              onerror="
                this.style.display='none';
                this.nextElementSibling.style.display='grid';
              "
            >
            <span
              class="team-logo-fallback"
              style="display:none;"
            >${initials}</span>
          `
          : `
            <span class="team-logo-fallback">${initials}</span>
          `
      }
    </span>
  `;
}

window.teamLogoMarkup = teamLogoMarkup;

function average(values) {
  const valid = values.filter(hasValue).map(Number);
  if (!valid.length) return null;
  return valid.reduce((sum, value) => sum + value, 0) / valid.length;
}

function conferenceStandings() {
  const grouped = new Map();

  Object.values(teams).forEach(team => {
    const conference = team.conference || "Independent";
    if (!grouped.has(conference)) grouped.set(conference, []);
    grouped.get(conference).push(team);
  });

  return Array.from(grouped, ([conference, members]) => {
    const liveMembers = members.filter(team =>
      livePlays(team, "offense") > 0 && livePlays(team, "defense") > 0
    );
    const topTeam = [...members].sort(
      (a, b) => Number(b.power_rating ?? -999) - Number(a.power_rating ?? -999)
    )[0];

    return {
      conference,
      teamCount: members.length,
      liveCount: liveMembers.length,
      topTeam: topTeam?.team || "—",
      modelRating: average(members.map(team => team.power_rating)),
      spPlus: average(members.map(team => team?.sp_plus?.overall)),
      specialTeams: average(members.map(team =>
        externalRatingsData?.teams?.[team.team]?.fpi_special_teams
      )),
      netEpa: average(liveMembers.map(team => liveNet(team, "epa_play"))),
      netSuccess: average(liveMembers.map(team => liveNet(team, "success_rate"))),
      offExplosive: average(liveMembers.map(team => liveValue(team, "offense", "explosive_rate"))),
      defHavoc: average(liveMembers.map(team => liveValue(team, "defense", "havoc_rate"))),
    };
  }).sort((a, b) => Number(b.modelRating ?? -999) - Number(a.modelRating ?? -999));
}

function conferenceNames() {
  return [...new Set(
    Object.values(teams).map(team => team.conference || "FBS Independents")
  )].sort((a, b) => a.localeCompare(b));
}

function filteredTeamsByConference() {
  const data = sortedTeams();
  if (currentTeamConference === "ALL") return data;
  return data.filter(
    team => (team.conference || "FBS Independents") === currentTeamConference
  );
}

function conferenceFilterMarkup(idSuffix, label = "Filter teams by conference") {
  const selectId = `conference-team-filter-${idSuffix}`;
  return `
    <div class="conference-filter-bar">
      <label class="conference-filter-label" for="${selectId}">
        Conference
      </label>
      <select
        id="${selectId}"
        class="conference-filter-select"
        aria-label="${escapeHtml(label)}"
        onchange="setTeamConference(this.value)"
      >
        <option value="ALL" ${currentTeamConference === "ALL" ? "selected" : ""}>
          All Conferences
        </option>
        ${conferenceNames().map(conference => `
          <option
            value="${escapeHtml(conference)}"
            ${currentTeamConference === conference ? "selected" : ""}
          >${escapeHtml(conference)}</option>
        `).join("")}
      </select>
      <span class="conference-filter-count">
        ${filteredTeamsByConference().length} teams
      </span>
    </div>
  `;
}

function getTeam(name) {
  return teams?.[name] ?? null;
}


// ============================================================================
// SPREAD DISPLAY
// ============================================================================

function favoredLine(homeTeam, awayTeam, homeSpread) {
  if (!hasValue(homeSpread)) return "—";
  const spread = Number(homeSpread);
  if (spread === 0) return "Pick'em";
  if (spread < 0) return `${homeTeam} ${formatSigned(spread, 1)}`;
  return `${awayTeam} ${formatSigned(-spread, 1)}`;
}

function marketSideForTeam(teamName, homeTeam, awayTeam, homeSpread) {
  if (!hasValue(homeSpread)) return "—";
  const spread = Number(homeSpread);
  if (teamName === homeTeam) return `${homeTeam} ${formatSigned(spread, 1)}`;
  if (teamName === awayTeam) return `${awayTeam} ${formatSigned(-spread, 1)}`;
  return "—";
}


// ============================================================================
// LIVE DATA HELPERS
// ============================================================================

function liveSection(team, section) {
  return team?.[section]?.live_2026 ?? {};
}

function liveValue(team, section, field) {
  const value = liveSection(team, section)?.[field];
  return hasValue(value) ? Number(value) : null;
}

function livePlays(team, section) {
  const value = liveSection(team, section)?.n_plays;
  return hasValue(value) ? Number(value) : 0;
}

function liveNet(team, field) {
  const offense = liveValue(team, "offense", field);
  const defense = liveValue(team, "defense", field);
  if (offense === null || defense === null) return null;
  return offense - defense;
}

function liveSampleLabel(team) {
  const offense = livePlays(team, "offense");
  const defense = livePlays(team, "defense");
  return offense > 0 && defense > 0
    ? "2026 live sample available"
    : "Preseason model only";
}


// ============================================================================
// SEASON HELPERS
// ============================================================================

function getSeasonProjection(teamName) {
  return seasonProjections?.[teamName] ?? null;
}

function usefulWinDistribution(distribution) {
  if (!distribution) return [];

  const entries = Object.entries(distribution)
    .map(([wins, probability]) => ({
      wins: Number(wins),
      probability: Number(probability),
    }))
    .filter(item => !Number.isNaN(item.wins) && !Number.isNaN(item.probability));

  if (!entries.length) return [];

  const meaningful = entries.filter(item => item.probability >= 0.5);
  if (!meaningful.length) return entries;

  const minWins = Math.min(...meaningful.map(item => item.wins));
  const maxWins = Math.max(...meaningful.map(item => item.wins));

  return entries.filter(
    item => item.wins >= Math.max(0, minWins - 1) && item.wins <= maxWins + 1
  );
}

function seasonLocationLabel(location) {
  if (location === "home") return "vs";
  if (location === "away") return "@";
  return "N";
}

function projectionSourceLabel(source) {
  if (source === "fcs_fallback") return "FCS fallback";
  if (source === "completed_result") return "Final";
  return "Model";
}


// ============================================================================
// VIEW SWITCHING + DYNAMIC STYLES
// ============================================================================

function switchView(viewName) {
  if (viewName === "teams") viewName = "ratings";
  document.querySelectorAll(".view").forEach(view => view.classList.remove("active"));

  const requested = document.getElementById(`view-${viewName}`);
  if (requested) requested.classList.add("active");

  document.querySelectorAll(".nav-item").forEach(button => {
    button.classList.toggle("active", button.dataset.view === viewName);
  });

  window.scrollTo({ top: 0, behavior: "smooth" });
}

function ensureMatchupView() {
  if (!document.getElementById("view-matchup")) {
    const main = document.querySelector("main.page");
    if (main) {
      const section = document.createElement("section");
      section.id = "view-matchup";
      section.className = "view";
      section.innerHTML = `
        <button class="back-button" onclick="switchView('projections')">
          ← Back to projections
        </button>
        <div id="matchup-container"></div>
      `;
      main.appendChild(section);
    }
  }

  if (document.getElementById("cfb-signal-system-v1")) return;

  const style = document.createElement("style");
  style.id = "cfb-signal-system-v1";
  style.textContent = `
    .projection-table tbody tr.game-row { cursor:pointer; }
    .projection-table tbody tr.game-row:hover { background:#fafaf8; }

    .status.small-edge {
      background:#edf3fb;
      color:#355f91;
      border:1px solid #c9d7e8;
    }

    .status.play {
      background:var(--green);
      color:#ffffff;
      border:1px solid var(--green);
    }

    .status.material {
      background:#c77700;
      color:#ffffff;
      border:1px solid #ad6500;
    }

    .status.outlier {
      background:#fff0df;
      color:#9a4d00;
      border:1px solid #e6b77d;
    }

    .confidence-developing {
      background:#f8e7a1 !important;
      color:#4e3b00 !important;
      border:1px solid #d9bd53 !important;
    }

    .confidence-validated {
      background:var(--green) !important;
      color:#ffffff !important;
      border:1px solid var(--green) !important;
    }

    .confidence-established {
      background:#5b4bc4 !important;
      color:#ffffff !important;
      border:1px solid #4a3cab !important;
      box-shadow:0 0 0 1px rgba(91,75,196,.08);
    }

    .status.agree {
      background: #f4f4f2;
      color: var(--muted);
      border: 1px solid var(--border);
      min-width: 116px;
    }

    .disagreement-number.material { color:#b86600; }
    .disagreement-number.play { color:var(--green); }
    .disagreement-number.small-edge { color:#355f91; }
    .disagreement-number.outlier { color:#9a4d00; }
    .disagreement-number.agree { color:var(--muted); }

    .summary-material { color:#b86600; font-weight:600; }
    .summary-play { color:var(--green); font-weight:600; }
    .summary-small { color:#355f91; font-weight:600; }
    .summary-outlier { color:#9a4d00; font-weight:600; }

    .signal-guide {
      margin:16px 0 18px;
      background:var(--surface);
      border:1px solid var(--border);
      border-radius:12px;
      overflow:hidden;
    }

    .signal-guide summary {
      list-style:none;
      cursor:pointer;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:18px;
      padding:14px 16px;
      font-weight:700;
      font-size:12px;
    }

    .signal-guide summary::-webkit-details-marker { display:none; }
    .signal-guide summary::after { content:"+"; font-family:var(--mono); color:var(--muted); font-size:16px; }
    .signal-guide[open] summary::after { content:"−"; }
    .signal-guide-body { border-top:1px solid var(--border); padding:16px; }
    .signal-guide-copy { color:var(--muted); font-size:11px; line-height:1.6; margin-bottom:14px; max-width:960px; }
    .signal-legend-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:8px; margin-bottom:14px; }
    .signal-legend-item { border:1px solid var(--border); border-radius:9px; padding:11px; min-width:0; }
    .signal-legend-name { font-family:var(--mono); font-size:9px; font-weight:700; letter-spacing:.5px; }
    .signal-legend-range { margin-top:5px; color:var(--muted); font-size:10px; }
    .confidence-legend { display:flex; flex-wrap:wrap; gap:8px 12px; align-items:center; }
    .confidence-legend-note { color:var(--muted); font-size:10px; line-height:1.5; }
    .signal-record { color:var(--muted); font-size:9px; margin-top:5px; font-family:var(--mono); white-space:nowrap; }

    .matchup-header {
      display:flex; justify-content:space-between; align-items:flex-start;
      gap:24px; margin-bottom:24px;
    }

    .matchup-title {
      font-size:34px; line-height:1.06; font-weight:800;
      letter-spacing:-1.2px; margin-top:4px;
    }

    .matchup-subtitle {
      color:var(--muted); margin-top:9px; font-size:12px;
    }

    .model-edge-banner {
      background:var(--surface); border:1px solid var(--border-dark);
      border-radius:12px; padding:18px 20px; margin-bottom:18px;
      display:flex; justify-content:space-between; align-items:center; gap:20px;
    }

    .model-edge-title, .analysis-label, .analysis-panel-title,
    .season-summary-label {
      font-family:var(--mono); color:var(--muted);
      font-size:9px; letter-spacing:1.2px; text-transform:uppercase;
    }

    .model-edge-title { margin-bottom:7px; }

    .model-edge-side {
      font-size:26px; font-weight:800; letter-spacing:-0.8px;
    }

    .model-edge-context, .analysis-small, .season-summary-note {
      color:var(--muted); font-size:11px; margin-top:6px; line-height:1.4;
    }

    .edge-material { color:#b86600; }
    .edge-play { color:var(--green); }
    .edge-small { color:#355f91; }
    .edge-outlier { color:#9a4d00; }

    .analysis-grid {
      display:grid; grid-template-columns:repeat(4,minmax(0,1fr));
      gap:10px; margin-bottom:18px;
    }

    .analysis-card, .season-summary-card {
      background:var(--surface); border:1px solid var(--border);
      border-radius:12px; padding:18px;
    }

    .dossier-rank-inline {
      color:var(--muted);
      font-family:var(--mono);
      font-size:10px;
      font-weight:500;
      letter-spacing:0;
      white-space:nowrap;
    }

    .team-with-logo {
      display:inline-flex; align-items:center; gap:9px; min-width:0;
    }

    .team-logo {
      position:relative; display:inline-grid; place-items:center; flex:0 0 auto;
      overflow:hidden; border-radius:50%; background:#f2f2ef;
      border:1px solid rgba(24,33,43,.08);
    }

    .team-logo-table { width:25px; height:25px; }
    .team-logo-projection { width:22px; height:22px; }
    .team-logo-matchup { width:44px; height:44px; }
    .team-logo-dossier { width:58px; height:58px; }

    .team-logo img {
      position:absolute; inset:2px; width:calc(100% - 4px); height:calc(100% - 4px);
      object-fit:contain; z-index:2;
    }

    .team-logo-fallback {
      color:var(--team-color); font-family:var(--mono); font-size:8px;
      font-weight:800; letter-spacing:-.3px;
    }

    .team-logo-dossier .team-logo-fallback { font-size:13px; }
    .dossier-team-heading { display:flex; align-items:center; gap:14px; }

    .ratings-toggle {
      display:flex;
      gap:6px;
      padding:12px 16px;
      border-bottom:1px solid var(--border);
      background:var(--surface);
    }

    .ratings-toggle-button {
      appearance:none;
      border:1px solid var(--border);
      border-radius:999px;
      background:#ffffff;
      color:var(--muted);
      cursor:pointer;
      font-family:var(--mono);
      font-size:9px;
      font-weight:700;
      letter-spacing:.5px;
      padding:8px 12px;
      text-transform:uppercase;
    }

    .ratings-toggle-button.active {
      background:var(--ink);
      border-color:var(--ink);
      color:#ffffff;
    }

    .conference-filter-bar {
      display:flex;
      align-items:center;
      gap:10px;
      padding:12px 16px;
      border-bottom:1px solid var(--border);
      background:var(--surface);
    }

    .conference-filter-label {
      color:var(--muted);
      font-family:var(--mono);
      font-size:9px;
      font-weight:700;
      letter-spacing:.7px;
      text-transform:uppercase;
    }

    .conference-filter-select {
      appearance:none;
      min-width:190px;
      border:1px solid var(--border);
      border-radius:8px;
      background:#ffffff;
      color:var(--ink);
      cursor:pointer;
      font-family:var(--sans);
      font-size:11px;
      font-weight:600;
      padding:9px 32px 9px 11px;
      background-image:linear-gradient(45deg,transparent 50%,var(--muted) 50%),linear-gradient(135deg,var(--muted) 50%,transparent 50%);
      background-position:calc(100% - 15px) 50%,calc(100% - 11px) 50%;
      background-size:4px 4px,4px 4px;
      background-repeat:no-repeat;
    }

    .conference-filter-count {
      color:var(--muted);
      font-family:var(--mono);
      font-size:9px;
      margin-left:auto;
      white-space:nowrap;
    }

    .analysis-value {
      font-size:24px; font-weight:800; letter-spacing:-0.8px; margin-top:10px;
    }

    .analysis-layout {
      display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr);
      gap:12px;
    }

    .analysis-panel {
      background:var(--surface); border:1px solid var(--border);
      border-radius:12px; overflow:hidden;
    }

    .analysis-panel.wide { grid-column:1 / -1; }

    .analysis-panel-header {
      padding:13px 16px; border-bottom:1px solid var(--border);
      display:flex; justify-content:space-between; gap:10px; align-items:center;
    }

    .analysis-panel-body { padding:0 16px; }

    .analysis-row {
      display:grid; grid-template-columns:minmax(0,1fr) auto;
      gap:18px; align-items:center; min-height:48px;
      border-bottom:1px solid #eeeeeb;
    }

    .analysis-row:last-child { border-bottom:none; }

    .analysis-row-label { color:var(--muted); font-size:12px; }

    .analysis-row-value {
      font-family:var(--mono); font-size:12px; font-weight:500; text-align:right;
    }

    .insight-card { padding:15px 0; border-bottom:1px solid #eeeeeb; }
    .insight-card:last-child { border-bottom:none; }

    .insight-title {
      font-family:var(--mono); color:var(--muted); font-size:9px;
      letter-spacing:1.1px; text-transform:uppercase; margin-bottom:5px;
    }

    .insight-text { font-size:12px; line-height:1.55; }

    .sample-warning {
      background:#fafaf8; border:1px solid var(--border); border-radius:10px;
      padding:13px 15px; color:var(--muted); font-size:11px;
      line-height:1.55; margin-bottom:12px;
    }

    .adjustment-positive { color:var(--green); }
    .adjustment-negative { color:var(--red); }
    .adjustment-neutral { color:var(--muted); }

    .win-prob-wrap { margin-top:12px; }

    .win-prob-bar {
      height:7px; border-radius:999px; overflow:hidden; background:#ecece8;
    }

    .win-prob-fill { height:100%; background:var(--green); }

    .win-prob-labels {
      display:flex; justify-content:space-between; margin-top:7px;
      font-family:var(--mono); font-size:10px; color:var(--muted);
    }

    .season-outlook { margin-top:12px; }

    .season-summary-grid {
      display:grid; grid-template-columns:repeat(4,minmax(0,1fr));
      gap:10px; margin-bottom:12px;
    }

    .season-summary-value {
      font-size:23px; font-weight:800; letter-spacing:-0.7px; margin-top:8px;
    }

    .season-two-column {
      display:grid; grid-template-columns:minmax(0,1.3fr) minmax(0,.7fr);
      gap:12px; margin-bottom:12px;
    }

    .distribution-wrap { padding:18px 16px; }

    .distribution-row {
      display:grid; grid-template-columns:30px minmax(0,1fr) 50px;
      gap:10px; align-items:center; margin-bottom:10px;
    }

    .distribution-wins, .distribution-prob {
      font-family:var(--mono); font-size:11px; font-weight:500;
    }

    .distribution-prob { text-align:right; }

    .distribution-track {
      height:8px; border-radius:999px; background:#ecece8; overflow:hidden;
    }

    .distribution-fill {
      height:100%; background:var(--green); border-radius:999px;
    }

    .alt-table, .season-schedule-table {
      width:100%; border-collapse:collapse; font-size:11px;
    }

    .alt-table th, .alt-table td, .season-schedule-table th,
    .season-schedule-table td {
      padding:11px 10px; border-bottom:1px solid #eeeeeb;
    }

    .alt-table th, .season-schedule-table th {
      color:var(--muted); font-family:var(--mono); font-size:8px;
      letter-spacing:1px; text-transform:uppercase; text-align:left;
    }

    .alt-table td:nth-child(2), .alt-table td:nth-child(3),
    .alt-table th:nth-child(2), .alt-table th:nth-child(3),
    .season-schedule-table th:nth-child(4), .season-schedule-table td:nth-child(4),
    .season-schedule-table th:nth-child(5), .season-schedule-table td:nth-child(5) {
      text-align:right;
    }

    .alt-strong { font-weight:800; }

    .fcs-tag {
      font-family:var(--mono); font-size:8px; color:var(--muted); margin-left:5px;
    }

    @media (max-width:900px) {
      .signal-legend-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }

      .analysis-grid, .season-summary-grid {
        grid-template-columns:repeat(2,minmax(0,1fr));
      }

      .analysis-layout, .season-two-column { grid-template-columns:1fr; }
      .analysis-panel.wide { grid-column:auto; }

      .matchup-header, .model-edge-banner {
        flex-direction:column; align-items:flex-start;
      }
    }

    @media (max-width:520px) {
      .signal-legend-grid { grid-template-columns:1fr; }
      .analysis-grid, .season-summary-grid { grid-template-columns:1fr; }
      .matchup-title { font-size:27px; }
      .model-edge-side { font-size:23px; }
    }
  `;

  document.head.appendChild(style);
}


// ============================================================================
// DATA
// ============================================================================

async function loadJson(url) {
  const response = await fetch(`${url}?v=${Date.now()}`);
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
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
      signalReportData,
      advancedMetricsData,
      externalRatingsData,
      rosterFoundationData,
      hfaData
    ] = await Promise.all([
      loadJson(DATA_URLS.metrics),
      loadJson(DATA_URLS.schedule),
      loadJson(DATA_URLS.odds),
      loadJson(DATA_URLS.projections),
      loadJson(DATA_URLS.signalReport).catch(() => null),
      loadJson(DATA_URLS.advancedMetrics).catch(() => null),
      loadJson(DATA_URLS.externalRatings).catch(() => null),
      loadJson(DATA_URLS.rosterFoundation).catch(() => null),
      loadJson(DATA_URLS.hfa),
    ]);

    teams = metricsData?.teams ?? {};
    projections = projectionsData?.games ?? [];
    seasonProjections = projectionsData?.season_projections ?? {};

    updateHeader();
    buildWeekTabs();
    renderProjections();
    renderTeams();
    renderRatings();
    initializeMatchupAnalysis();
    attachEvents();

    document.dispatchEvent(new CustomEvent("hammer:data-ready"));
  } catch (error) {
    console.error("Frontend initialization failed:", error);

    const container = document.getElementById("projections-container");
    if (container) {
      container.innerHTML = `
        <div class="empty-state">
          Unable to load analytics data.
          <br><br>
          ${escapeHtml(error.message)}
        </div>
      `;
    }
  }
}


// ============================================================================
// HEADER + WEEK TABS
// ============================================================================

function updateHeader() {
  const header = document.getElementById("data-updated");
  if (!header) return;

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

function availableWeeks() {
  const weeks = projections
    .map(game => game.week)
    .filter(week => week !== null && week !== undefined)
    .map(Number)
    .filter(week => !Number.isNaN(week));

  return [...new Set(weeks)].sort((a, b) => a - b);
}

function determineDefaultWeek(weeks) {
  if (!weeks.length) return null;

  const marketWeeks = projections
    .filter(game => hasValue(game?.market?.home_spread))
    .map(game => Number(game.week))
    .filter(week => !Number.isNaN(week));

  return marketWeeks.length ? Math.min(...marketWeeks) : weeks[0];
}

function buildWeekTabs() {
  const container = document.getElementById("week-tabs");
  if (!container) return;

  const weeks = availableWeeks();

  if (!weeks.length) {
    container.innerHTML = "";
    return;
  }

  if (currentWeek === null) currentWeek = determineDefaultWeek(weeks);

  container.innerHTML = weeks.map(week => `
    <button
      class="week-tab ${Number(week) === Number(currentWeek) ? "active" : ""}"
      onclick="selectWeek(${week})"
    >
      ${week === 0 ? "Week 0" : `Week ${week}`}
    </button>
  `).join("");
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
    .filter(game => {
      if (
        currentWeek !== null &&
        Number(game.week) !== Number(currentWeek)
      ) return false;

      if (!currentSearch) return true;

      const query = currentSearch.toLowerCase();
      const home = game?.home?.team?.toLowerCase() ?? "";
      const away = game?.away?.team?.toLowerCase() ?? "";

      return home.includes(query) || away.includes(query);
    })
    .sort((a, b) => {
      const aDisagreement = a?.comparison?.disagreement ?? -1;
      const bDisagreement = b?.comparison?.disagreement ?? -1;

      if (bDisagreement !== aDisagreement) {
        return bDisagreement - aDisagreement;
      }

      return (
        new Date(a.start_date || 0).getTime() -
        new Date(b.start_date || 0).getTime()
      );
    });
}

function statusCount(games, ...statuses) {
  return games.filter(game => statuses.includes(game?.comparison?.status)).length;
}

function renderProjections() {
  const container = document.getElementById("projections-container");
  const summary = document.getElementById("projection-summary");
  if (!container) return;

  const games = projectionGamesForCurrentView();
  const marketGames = games.filter(game => hasValue(game?.market?.home_spread));

  const material = statusCount(games, "STRONG EDGE", "MATERIAL DISAGREEMENT");
  const plays = statusCount(games, "EDGE", "PLAY");
  const smallEdges = statusCount(games, "SLIGHT EDGE", "LEAN", "SMALL EDGE");
  const outliers = statusCount(games, "OUTLIER");

  if (summary) {
    summary.innerHTML = `
      ${games.length} games
      · ${marketGames.length} lined
      · <span class="summary-material">${material} material disagreements</span>
      · <span class="summary-play">${plays} plays</span>
      · <span class="summary-small">${smallEdges} small edges</span>
      ${outliers ? `· <span class="summary-outlier">${outliers} outliers</span>` : ""}
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
          <th class="align-right">Model Edge</th>
          <th class="align-right">Model Signal</th>
          <th class="align-right">Signal Confidence</th>
        </tr>
      </thead>
      <tbody>
        ${games.map(renderProjectionRow).join("")}
      </tbody>
    </table>
  `;
}

function renderProjectionRow(game) {
  const homeName = game?.home?.team ?? "Unknown";
  const awayName = game?.away?.team ?? "Unknown";

  const homeRank = game?.home?.power_rating_rank;
  const awayRank = game?.away?.power_rating_rank;

  const modelSpread = game?.projection?.home_spread;
  const modelTotal = game?.projection?.total;

  const marketSpread = game?.market?.home_spread;
  const marketTotal = game?.market?.total;
  const bookmaker = game?.market?.bookmaker;

  const disagreement = game?.comparison?.disagreement;
  const preferred = game?.comparison?.preferred_side;
  const status = game?.comparison?.signal ?? game?.comparison?.status;
  const confidence = signalConfidence(status);
  const cssStatus = statusClass(status);
  const confidenceCss = confidenceClass(confidence);

  const disagreementNote = hasValue(disagreement)
    ? (preferred ? `Model favors ${preferred}` : "Model agrees with market")
    : "No market line";

  const gameId = String(game.game_id ?? "");

  return `
    <tr
      class="game-row"
      onclick="openMatchup('${escapeJsString(gameId)}')"
    >
      <td class="matchup-cell">
        <div class="team-line">
          <span
            class="team-name"
            onclick="event.stopPropagation(); openDossier('${escapeJsString(awayName)}');"
          >
            ${escapeHtml(awayName)}
          </span>
          <span class="team-meta">${awayRank ? `#${awayRank}` : ""}</span>
        </div>

        <div class="team-line">
          <span class="at-symbol">@</span>
          <span
            class="team-name"
            onclick="event.stopPropagation(); openDossier('${escapeJsString(homeName)}');"
          >
            ${escapeHtml(homeName)}
          </span>
          <span class="team-meta">${homeRank ? `#${homeRank}` : ""}</span>
        </div>

        <div class="team-meta" style="margin-top:5px;">
          ${escapeHtml(gameDateText(game.start_date))}
        </div>
      </td>

      <td>
        <div class="line-primary">${escapeHtml(shortSpread(modelSpread))}</div>
        <div class="line-secondary">${escapeHtml(homeName)} home line</div>
      </td>

      <td>
        <div class="line-primary">${escapeHtml(shortSpread(marketSpread))}</div>
        <div class="line-secondary">
          ${bookmaker ? escapeHtml(bookmaker) : "No current market"}
        </div>
      </td>

      <td>
        <div class="line-primary">${formatNumber(modelTotal, 1)}</div>
        <div class="line-secondary">
          ${hasValue(marketTotal)
            ? `Market ${formatNumber(marketTotal, 1)}`
            : "Model total"}
        </div>
      </td>

      <td class="disagreement">
        <div class="disagreement-number ${cssStatus}">
          ${hasValue(disagreement) ? `${formatNumber(disagreement, 1)} pts` : "—"}
        </div>
        <div class="disagreement-note">${escapeHtml(disagreementNote)}</div>
      </td>

      <td class="status-cell">
        <span class="status ${cssStatus}">
          ${escapeHtml(displayStatus(status))}
        </span>
      </td>

      <td class="status-cell">
        <span class="status ${confidenceCss}">
          ${escapeHtml(confidence)}
        </span>
        <div class="signal-record">
          ${escapeHtml(signalRecordText(status))} · ${escapeHtml(signalAtsText(status))}
        </div>
      </td>
    </tr>
  `;
}


// ============================================================================
// GAME ANALYSIS
// ============================================================================

function findGame(gameId) {
  return projections.find(game => String(game.game_id) === String(gameId));
}

function openMatchup(gameId) {
  const game = findGame(gameId);
  if (!game) return;
  renderMatchup(game);
  switchView("matchup");
}

function adjustmentClass(value) {
  if (!hasValue(value)) return "adjustment-neutral";
  const number = Number(value);
  if (number > 0.05) return "adjustment-positive";
  if (number < -0.05) return "adjustment-negative";
  return "adjustment-neutral";
}

function adjustmentText(value) {
  if (!hasValue(value)) return "—";
  const number = Number(value);
  if (Math.abs(number) < 0.005) return "0.00";
  return formatSigned(number, 2);
}

function matchupComponentRow(label, value, active) {
  const shown = active ? adjustmentText(value) : "Withheld";
  const css = active ? adjustmentClass(value) : "adjustment-neutral";

  return `
    <div class="analysis-row">
      <div class="analysis-row-label">${escapeHtml(label)}</div>
      <div class="analysis-row-value ${css}">${escapeHtml(shown)}</div>
    </div>
  `;
}

function insightMarkup(insights) {
  if (!Array.isArray(insights) || !insights.length) {
    return `
      <div class="insight-card">
        <div class="insight-text">No additional model insight is available yet.</div>
      </div>
    `;
  }

  return insights.map(insight => `
    <div class="insight-card">
      <div class="insight-title">${escapeHtml(insight.title ?? "Model note")}</div>
      <div class="insight-text">${escapeHtml(insight.text ?? "")}</div>
    </div>
  `).join("");
}

function renderMatchup(game) {
  const container = document.getElementById("matchup-container");
  if (!container) return;

  const awayName = game?.away?.team ?? "Away";
  const homeName = game?.home?.team ?? "Home";

  const projection = game?.projection ?? {};
  const components = projection?.components ?? {};

  const matchup =
    components?.matchup_adjustment ??
    projection?.matchup_adjustment ??
    {};

  const matchupComponents = matchup?.components ?? {};
  const available = matchup?.available ?? {};

  const modelSpread = projection?.home_spread;
  const marketSpread = game?.market?.home_spread;
  const modelTotal = projection?.total;
  const marketTotal = game?.market?.total;

  const comparison = game?.comparison ?? {};
  const status = comparison?.signal ?? comparison?.status;
  const confidence = signalConfidence(status);
  const statusCss = statusClass(status);
  const confidenceCss = confidenceClass(confidence);
  const edgeClass = statusEdgeClass(status);

  const winProb = projection?.win_probability ?? {};
  const awayWin = hasValue(winProb.away) ? Number(winProb.away) : null;
  const homeWin = hasValue(winProb.home) ? Number(winProb.home) : null;

  const preferred = comparison?.preferred_side;
  const edgeSize = comparison?.disagreement;

  const sampleComparable = Boolean(matchup?.comparable_live_sample);

  const matchupNote =
    matchup?.note ??
    (sampleComparable
      ? "Comparable 2026 live samples are active."
      : "No comparable live sample; matchup adjustment is held at zero.");

  const ratingOnly = components?.rating_only_home_spread;
  const hfa = components?.home_field_advantage;
  const afterHfa = components?.spread_after_home_field;
  const matchupTotal = matchup?.total;

  const homeRating =
    components?.home_power_rating ??
    game?.home?.power_rating;

  const awayRating =
    components?.away_power_rating ??
    game?.away?.power_rating;

  const fairLine = favoredLine(homeName, awayName, modelSpread);
  const marketLine = favoredLine(homeName, awayName, marketSpread);

  const modelEdgeSide =
    preferred && hasValue(marketSpread)
      ? marketSideForTeam(preferred, homeName, awayName, marketSpread)
      : "No current market signal";

  container.innerHTML = `
    <div class="matchup-header">
      <div>
        <div class="eyebrow">Game analysis</div>
        <div class="matchup-title">
          ${escapeHtml(awayName)} @ ${escapeHtml(homeName)}
        </div>
        <div class="matchup-subtitle">
          Week ${game.week ?? "—"}
          · ${escapeHtml(gameDateText(game.start_date))}
          ${game.venue ? ` · ${escapeHtml(game.venue)}` : ""}
        </div>
      </div>

      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end;">
        <span class="status ${statusCss}">
          ${escapeHtml(displayStatus(status))}
        </span>
        <span class="status ${confidenceCss}">
          Signal Confidence: ${escapeHtml(confidence)}
        </span>
      </div>
    </div>

    <div class="model-edge-banner">
      <div>
        <div class="model-edge-title">Model Signal</div>
        <div class="model-edge-side ${edgeClass}">
          ${escapeHtml(modelEdgeSide)}
        </div>
        <div class="model-edge-context">
          ${hasValue(edgeSize)
            ? `${formatNumber(edgeSize, 1)}-point model edge versus the current market. Signal tier measures separation; confidence measures evidence.`
            : "No current market line is available."}
        </div>
      </div>

      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end;">
        <span class="status ${statusCss}">
          ${escapeHtml(displayStatus(status))}
        </span>
        <span class="status ${confidenceCss}">
          ${escapeHtml(confidence)}
        </span>
      </div>
    </div>

    <div class="analysis-grid">
      <div class="analysis-card">
        <div class="analysis-label">Fair Line</div>
        <div class="analysis-value">${escapeHtml(fairLine)}</div>
        <div class="analysis-small">Model-implied spread</div>
      </div>

      <div class="analysis-card">
        <div class="analysis-label">Market Line</div>
        <div class="analysis-value">${escapeHtml(marketLine)}</div>
        <div class="analysis-small">
          ${game?.market?.bookmaker ? escapeHtml(game.market.bookmaker) : "No current market"}
        </div>
      </div>

      <div class="analysis-card">
        <div class="analysis-label">Model Total</div>
        <div class="analysis-value">${formatNumber(modelTotal, 1)}</div>
        <div class="analysis-small">
          ${hasValue(marketTotal)
            ? `Market ${formatNumber(marketTotal, 1)}`
            : "No current market total"}
        </div>
      </div>

      <div class="analysis-card">
        <div class="analysis-label">Signal Size</div>
        <div class="analysis-value ${edgeClass}">
          ${hasValue(edgeSize) ? `${formatNumber(edgeSize, 1)} pts` : "—"}
        </div>
        <div class="analysis-small">
          ${preferred
            ? `Market side: ${escapeHtml(modelEdgeSide)}`
            : "No current directional signal"}
          <br>
          ${escapeHtml(signalRecordText(status))} · ${escapeHtml(signalAtsText(status))} ·
          ${escapeHtml(signalClvText(status))} · ${escapeHtml(signalBeatCloseText(status))}
        </div>
      </div>
    </div>

    <div class="analysis-layout">
      <div class="analysis-panel">
        <div class="analysis-panel-header">
          <div class="analysis-panel-title">Win probability</div>
        </div>
        <div class="analysis-panel-body">
          <div style="padding:17px 0 19px;">
            <div style="display:flex;justify-content:space-between;align-items:flex-end;">
              <div>
                <div class="analysis-small">${escapeHtml(awayName)}</div>
                <div class="analysis-value">${formatPercent(awayWin)}</div>
              </div>
              <div style="text-align:right;">
                <div class="analysis-small">${escapeHtml(homeName)}</div>
                <div class="analysis-value">${formatPercent(homeWin)}</div>
              </div>
            </div>

            ${hasValue(homeWin) ? `
              <div class="win-prob-wrap">
                <div class="win-prob-bar">
                  <div
                    class="win-prob-fill"
                    style="width:${Math.max(0, Math.min(100, homeWin))}%;"
                  ></div>
                </div>
                <div class="win-prob-labels">
                  <span>${escapeHtml(awayName)}</span>
                  <span>${escapeHtml(homeName)}</span>
                </div>
              </div>
            ` : ""}
          </div>
        </div>
      </div>

      <div class="analysis-panel">
        <div class="analysis-panel-header">
          <div class="analysis-panel-title">Power foundation</div>
        </div>
        <div class="analysis-panel-body">
          <div class="analysis-row">
            <div class="analysis-row-label">${escapeHtml(awayName)} power rating</div>
            <div class="analysis-row-value">${formatSigned(awayRating, 3)}</div>
          </div>

          <div class="analysis-row">
            <div class="analysis-row-label">${escapeHtml(homeName)} power rating</div>
            <div class="analysis-row-value">${formatSigned(homeRating, 3)}</div>
          </div>

          <div class="analysis-row">
            <div class="analysis-row-label">Rating-only fair line</div>
            <div class="analysis-row-value">
              ${escapeHtml(favoredLine(homeName, awayName, ratingOnly))}
            </div>
          </div>
        </div>
      </div>

      <div class="analysis-panel">
        <div class="analysis-panel-header">
          <div class="analysis-panel-title">Projection build</div>
        </div>

        <div class="analysis-panel-body">
          <div class="analysis-row">
            <div class="analysis-row-label">Rating-only line</div>
            <div class="analysis-row-value">
              ${escapeHtml(favoredLine(homeName, awayName, ratingOnly))}
            </div>
          </div>

          <div class="analysis-row">
            <div class="analysis-row-label">Home-field adjustment</div>
            <div class="analysis-row-value">
              ${hasValue(hfa) ? `${formatNumber(hfa, 1)} pts` : "—"}
            </div>
          </div>

          <div class="analysis-row">
            <div class="analysis-row-label">Line after home field</div>
            <div class="analysis-row-value">
              ${escapeHtml(favoredLine(homeName, awayName, afterHfa))}
            </div>
          </div>

          <div class="analysis-row">
            <div class="analysis-row-label">Live matchup adjustment</div>
            <div class="analysis-row-value ${adjustmentClass(matchupTotal)}">
              ${adjustmentText(matchupTotal)}
            </div>
          </div>

          <div class="analysis-row">
            <div class="analysis-row-label">Final fair line</div>
            <div class="analysis-row-value">${escapeHtml(fairLine)}</div>
          </div>
        </div>
      </div>

      <div class="analysis-panel">
        <div class="analysis-panel-header">
          <div class="analysis-panel-title">Live matchup layer</div>
          <div class="team-meta">${sampleComparable ? "ACTIVE" : "WITHHELD"}</div>
        </div>

        <div class="analysis-panel-body" style="padding-top:12px;padding-bottom:12px;">
          <div class="sample-warning">${escapeHtml(matchupNote)}</div>

          ${matchupComponentRow(
            "Passing",
            matchupComponents?.passing,
            Boolean(available?.passing)
          )}

          ${matchupComponentRow(
            "Rushing",
            matchupComponents?.rushing,
            Boolean(available?.rushing)
          )}

          ${matchupComponentRow(
            "Success rate",
            matchupComponents?.success_rate,
            Boolean(available?.success_rate)
          )}

          ${matchupComponentRow(
            "Explosiveness",
            matchupComponents?.explosiveness,
            Boolean(available?.explosiveness)
          )}

          ${matchupComponentRow(
            "Havoc",
            matchupComponents?.havoc,
            Boolean(available?.havoc)
          )}
        </div>
      </div>

      <div class="analysis-panel wide">
        <div class="analysis-panel-header">
          <div class="analysis-panel-title">Why the model differs</div>
        </div>
        <div class="analysis-panel-body">
          ${insightMarkup(game?.insights)}
        </div>
      </div>
    </div>
  `;
}


// ============================================================================
// TEAMS / RATINGS
// ============================================================================

function sortedTeams() {
  return Object.values(teams).sort(
    (a, b) => (a.power_rating_rank ?? 999) - (b.power_rating_rank ?? 999)
  );
}

function renderTeams() {
  const container = document.getElementById("teams-container");
  if (!container) return;

  const data = filteredTeamsByConference();
  const isConferenceView = currentTeamConference !== "ALL";

  container.innerHTML = `
    ${conferenceFilterMarkup("teams")}

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
          ${data.map((team, index) => `
            <tr
              style="cursor:pointer;"
              onclick="openDossier('${escapeJsString(team.team)}')"
            >
              <td class="team-meta">${isConferenceView ? `#${index + 1}` : powerRank(team)}</td>
              <td><strong>${escapeHtml(team.team)}</strong></td>
              <td class="team-meta">${escapeHtml(team.conference ?? "—")}</td>
              <td class="team-meta">${recordText(team)}</td>
              <td class="line-primary">${formatSigned(team.power_rating, 3)}</td>
              <td class="team-meta">${formatSigned(team?.sp_plus?.overall, 1)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderRatings() {
  const container = document.getElementById("ratings-container");
  if (!container) return;

  const data = filteredTeamsByConference();
  const isConferenceView = currentTeamConference !== "ALL";
  const throughWeek = Number(metricsData?.meta?.through_week);
  const liveWeight = Number(metricsData?.meta?.blend_weight);

  const weekLabel = Number.isFinite(throughWeek) && throughWeek > 0
    ? `Data through Week ${throughWeek}.`
    : "Preseason data; no 2026 games incorporated yet.";

  const weightLabel = Number.isFinite(liveWeight)
    ? `Live 2026 weight: ${formatPercent(liveWeight * 100, 0)}.`
    : "Live 2026 weight unavailable.";

  const externalWeek = externalRatingsData?.meta?.week;

  const externalLabel = externalRatingsData
    ? `ESPN FPI snapshot: Week ${externalWeek ?? "—"}.`
    : "External ratings are awaiting their first refresh.";

  const overviewTable = `
    ${conferenceFilterMarkup("ratings-overview")}

    <div class="table-scroll">
      <table class="projection-table">
        <thead>
          <tr>
            <th>${isConferenceView ? "Conference Rank" : "Power Rank"}</th>
            <th>Team</th>
            <th>Conference</th>
            <th>Record</th>
            <th>Model Rating</th>
            <th>SP+</th>
            <th>ESPN FPI</th>
            <th>Special Teams</th>
          </tr>
        </thead>

        <tbody>
          ${data.map((team, index) => {
            const external = externalRatingsData?.teams?.[team.team] ?? {};

            return `
              <tr
                style="cursor:pointer"
                onclick="openDossier('${escapeJsString(team.team)}')"
              >
                <td class="team-meta">
                  ${isConferenceView ? `#${index + 1}` : powerRank(team)}
                </td>

                <td>
                  <span class="team-with-logo">
                    ${teamLogoMarkup(team.team)}
                    <strong>${escapeHtml(team.team)}</strong>
                  </span>
                </td>

                <td class="team-meta">${escapeHtml(team.conference ?? "—")}</td>
                <td class="team-meta">${recordText(team)}</td>
                <td class="line-primary">${formatSigned(team.power_rating, 3)}</td>
                <td class="team-meta">${formatSigned(team?.sp_plus?.overall, 1)}</td>

                <td class="team-meta">
                  ${hasValue(external.fpi)
                    ? `${formatSigned(external.fpi, 1)} (${externalRank(external.fpi_rank)})`
                    : "—"}
                </td>

                <td class="team-meta">
                  ${hasValue(external.fpi_special_teams)
                    ? `${formatSigned(external.fpi_special_teams, 3)} (${externalMetricRank(
                        "fpi_special_teams",
                        external.fpi_special_teams
                      )})`
                    : "—"}
                </td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table>
    </div>
  `;

  const teamTable = `
    <div class="table-scroll">
      <table class="projection-table">
        <thead>
          <tr>
            <th>${isConferenceView ? "Conference Rank" : "Power Rank"}</th>
            <th>Team</th>
            <th>Model Rating</th>
            <th>Preseason SP+</th>
            <th>ESPN FPI</th>
            <th>Special Teams</th>
            <th>Team Talent</th>
            <th>Returning Production</th>
            <th>SOR Rank</th>
            <th>SOS Rank</th>
            <th>2026 Net EPA</th>
            <th>2026 Net Success</th>
            <th>2026 Off Explosive</th>
            <th>2026 Def Havoc</th>
            <th>Plays Tracked</th>
          </tr>
        </thead>

        <tbody>
          ${data.map((team, index) => {
            const external = externalRatingsData?.teams?.[team.team] ?? {};
            const roster = rosterFoundationData?.teams?.[team.team] ?? {};

            const offPlays = livePlays(team, "offense");
            const defPlays = livePlays(team, "defense");

            const playsTracked = offPlays > 0 && defPlays > 0
              ? `${formatNumber(offPlays, 0)} O / ${formatNumber(defPlays, 0)} D`
              : "—";

            return `
              <tr
                style="cursor:pointer;"
                onclick="openDossier('${escapeJsString(team.team)}')"
              >
                <td class="team-meta">
                  ${isConferenceView ? `#${index + 1}` : powerRank(team)}
                </td>

                <td>
                  <span class="team-with-logo">
                    ${teamLogoMarkup(team.team)}
                    <strong>${escapeHtml(team.team)}</strong>
                  </span>
                </td>

                <td class="line-primary">${formatSigned(team.power_rating, 3)}</td>
                <td class="team-meta">${formatSigned(team?.sp_plus?.overall, 1)}</td>

                <td class="team-meta">
                  ${hasValue(external.fpi)
                    ? `${formatSigned(external.fpi, 1)} (#${external.fpi_rank})`
                    : "—"}
                </td>

                <td class="team-meta">
                  ${hasValue(external.fpi_special_teams)
                    ? `${formatSigned(external.fpi_special_teams, 3)} (${externalMetricRank(
                        "fpi_special_teams",
                        external.fpi_special_teams
                      )})`
                    : "—"}
                </td>

                <td class="team-meta">
                  ${hasValue(roster.talent_rank) ? `#${roster.talent_rank}` : "—"}
                </td>

                <td class="team-meta">
                  ${hasValue(roster.returning_production_pct)
                    ? `${formatPercent(roster.returning_production_pct)} (#${roster.returning_production_rank})`
                    : "—"}
                </td>

                <td class="team-meta">
                  ${hasValue(external.sor_rank) ? `#${external.sor_rank}` : "—"}
                </td>

                <td class="team-meta">
                  ${hasValue(external.sos_rank) ? `#${external.sos_rank}` : "—"}
                </td>

                <td class="team-meta">${formatEPA(liveNet(team, "epa_play"))}</td>
                <td class="team-meta">${formatPercent(liveNet(team, "success_rate"))}</td>
                <td class="team-meta">${formatRate(liveValue(team, "offense", "explosive_rate"))}</td>
                <td class="team-meta">${formatRate(liveValue(team, "defense", "havoc_rate"))}</td>
                <td class="team-meta">${playsTracked}</td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table>
    </div>
  `;

  const conferenceTable = `
    <div class="table-scroll">
      <table class="projection-table">
        <thead>
          <tr>
            <th>Conference Rank</th>
            <th>Conference</th>
            <th>Avg Model Rating</th>
            <th>Avg SP+</th>
            <th>Avg Special Teams</th>
            <th>2026 Net EPA</th>
            <th>2026 Net Success</th>
            <th>2026 Off Explosive</th>
            <th>2026 Def Havoc</th>
            <th>Live Samples</th>
            <th>Top-Rated Team</th>
          </tr>
        </thead>

        <tbody>
          ${conferenceStandings().map((conference, index) => `
            <tr>
              <td class="team-meta">#${index + 1}</td>
              <td><strong>${escapeHtml(conference.conference)}</strong></td>
              <td class="line-primary">${formatSigned(conference.modelRating, 3)}</td>
              <td class="team-meta">${formatSigned(conference.spPlus, 1)}</td>
              <td class="team-meta">${formatSigned(conference.specialTeams, 3)}</td>
              <td class="team-meta">${formatEPA(conference.netEpa)}</td>
              <td class="team-meta">${formatPercent(conference.netSuccess)}</td>
              <td class="team-meta">${formatRate(conference.offExplosive)}</td>
              <td class="team-meta">${formatRate(conference.defHavoc)}</td>
              <td class="team-meta">${conference.liveCount}/${conference.teamCount} teams</td>

              <td class="team-meta">
                <span class="team-with-logo">
                  ${teamLogoMarkup(conference.topTeam)}
                  <span>${escapeHtml(conference.topTeam)}</span>
                </span>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;

  container.innerHTML = `
    <div class="ratings-note">
      <strong>How to read these ratings:</strong>
      Model Rating blends the frozen preseason baseline with current-season
      performance. The 2026 columns contain current-season results only.
      ${weightLabel} ${weekLabel} ${externalLabel}
      Special Teams is ESPN's FPI component and is display-only; it is not used
      by Model A.
    </div>

    <div class="ratings-toggle" role="group" aria-label="Ratings view">
      <button
        class="ratings-toggle-button ${currentRatingsMode === "overview" ? "active" : ""}"
        type="button"
        onclick="setRatingsMode('overview')"
      >Overview</button>

      <button
        class="ratings-toggle-button ${currentRatingsMode === "advanced" ? "active" : ""}"
        type="button"
        onclick="setRatingsMode('advanced')"
      >Advanced Ratings</button>

      <button
        class="ratings-toggle-button ${currentRatingsMode === "conferences" ? "active" : ""}"
        type="button"
        onclick="setRatingsMode('conferences')"
      >Conference Standings</button>
    </div>

    ${
      currentRatingsMode === "conferences"
        ? conferenceTable
        : currentRatingsMode === "advanced"
          ? `${conferenceFilterMarkup("ratings")}${teamTable}`
          : overviewTable
    }
  `;
}

function setRatingsMode(mode) {
  currentRatingsMode = ["overview", "advanced", "conferences"].includes(mode)
    ? mode
    : "overview";

  renderRatings();
}

function setTeamConference(conference) {
  currentTeamConference = conferenceNames().includes(conference)
    ? conference
    : "ALL";

  renderTeams();
  renderRatings();
}


// ============================================================================
// MATCHUP ANALYSIS
// ============================================================================

function modelClamp(value, cap) {
  return Math.max(-cap, Math.min(cap, value));
}

function modelRoundHalf(value) {
  const scaled = Number(value) * 2;
  const floor = Math.floor(scaled);
  const fraction = scaled - floor;

  if (Math.abs(fraction - 0.5) < 1e-10) {
    return (floor % 2 === 0 ? floor : floor + 1) / 2;
  }

  return Math.round(scaled) / 2;
}

function modelErf(value) {
  const sign = value < 0 ? -1 : 1;
  const x = Math.abs(value);
  const t = 1 / (1 + 0.3275911 * x);

  const polynomial =
    (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t;

  return sign * (1 - polynomial * Math.exp(-x * x));
}

function modelWinProbability(homeSpread) {
  const homeMargin = -Number(homeSpread);

  const probability = Math.max(
    0.01,
    Math.min(
      0.99,
      (1 + modelErf((homeMargin / 16) / Math.sqrt(2))) / 2
    )
  );

  return {
    home: probability * 100,
    away: (1 - probability) * 100
  };
}

function modelLiveNumber(team, side, field) {
  const value = team?.[side]?.live_2026?.[field];
  return hasValue(value) ? Number(value) : null;
}

function matchupGeneralSample(team) {
  return (
    modelLiveNumber(team, "offense", "n_plays") >= 35 &&
    modelLiveNumber(team, "defense", "n_plays") >= 35
  );
}

function matchupUnitSample(team, field, minimum) {
  return (
    modelLiveNumber(team, "offense", field) >= minimum &&
    modelLiveNumber(team, "defense", field) >= minimum
  );
}

function calculateInteractiveMatchupAdjustment(home, away) {
  const components = {
    passing: 0,
    rushing: 0,
    success_rate: 0,
    explosiveness: 0,
    havoc: 0,
  };

  const available = Object.fromEntries(
    Object.keys(components).map(key => [key, false])
  );

  if (
    matchupUnitSample(home, "pass_plays", 15) &&
    matchupUnitSample(away, "pass_plays", 15)
  ) {
    const values = [
      modelLiveNumber(home, "offense", "epa_pass"),
      modelLiveNumber(away, "defense", "epa_pass"),
      modelLiveNumber(away, "offense", "epa_pass"),
      modelLiveNumber(home, "defense", "epa_pass"),
    ];

    if (values.every(hasValue)) {
      const [
        homePass,
        awayPassDefense,
        awayPass,
        homePassDefense
      ] = values;

      components.passing = modelClamp(
        ((homePass - awayPassDefense) - (awayPass - homePassDefense)) * 1.25,
        1
      );

      available.passing = true;
    }
  }

  if (
    matchupUnitSample(home, "rush_plays", 15) &&
    matchupUnitSample(away, "rush_plays", 15)
  ) {
    const values = [
      modelLiveNumber(home, "offense", "epa_rush"),
      modelLiveNumber(away, "defense", "epa_rush"),
      modelLiveNumber(away, "offense", "epa_rush"),
      modelLiveNumber(home, "defense", "epa_rush"),
    ];

    if (values.every(hasValue)) {
      const [
        homeRush,
        awayRushDefense,
        awayRush,
        homeRushDefense
      ] = values;

      components.rushing = modelClamp(
        (homeRush - awayRushDefense) - (awayRush - homeRushDefense),
        0.75
      );

      available.rushing = true;
    }
  }

  if (matchupGeneralSample(home) && matchupGeneralSample(away)) {
    const successValues = [
      modelLiveNumber(home, "offense", "success_rate"),
      modelLiveNumber(away, "defense", "success_rate"),
      modelLiveNumber(away, "offense", "success_rate"),
      modelLiveNumber(home, "defense", "success_rate"),
    ];

    if (successValues.every(hasValue)) {
      const [
        homeSuccess,
        awaySuccessDefense,
        awaySuccess,
        homeSuccessDefense
      ] = successValues;

      components.success_rate = modelClamp(
        ((homeSuccess - awaySuccessDefense) - (awaySuccess - homeSuccessDefense)) * 0.035,
        0.75
      );

      available.success_rate = true;
    }

    const explosiveValues = [
      modelLiveNumber(home, "offense", "explosive_rate"),
      modelLiveNumber(away, "defense", "explosive_rate"),
      modelLiveNumber(away, "offense", "explosive_rate"),
      modelLiveNumber(home, "defense", "explosive_rate"),
    ];

    if (explosiveValues.every(hasValue)) {
      const [
        homeExplosive,
        awayExplosiveDefense,
        awayExplosive,
        homeExplosiveDefense
      ] = explosiveValues;

      components.explosiveness = modelClamp(
        ((homeExplosive - awayExplosiveDefense) - (awayExplosive - homeExplosiveDefense)) * 0.025,
        0.5
      );

      available.explosiveness = true;
    }

    const havocValues = [
      modelLiveNumber(home, "offense", "havoc_rate"),
      modelLiveNumber(home, "defense", "havoc_rate"),
      modelLiveNumber(away, "offense", "havoc_rate"),
      modelLiveNumber(away, "defense", "havoc_rate"),
    ];

    if (havocValues.every(hasValue)) {
      const [
        homeAllowed,
        homeCreated,
        awayAllowed,
        awayCreated
      ] = havocValues;

      components.havoc = modelClamp(
        ((homeCreated - awayAllowed) - (awayCreated - homeAllowed)) * 0.025,
        0.5
      );

      available.havoc = true;
    }
  }

  const total = modelClamp(
    Object.values(components).reduce((sum, value) => sum + value, 0),
    Number(projectionsData?.meta?.max_matchup_adjustment ?? 3)
  );

  return {
    components: Object.fromEntries(
      Object.entries(components).map(([key, value]) => [
        key,
        Number(value.toFixed(2))
      ])
    ),
    available,
    total: Number(total.toFixed(2)),
    comparable: Object.values(available).some(Boolean),
  };
}

function calculateInteractiveTotal(home, away) {
  const efficiency =
    Number(home?.offense?.epa_play ?? 0) +
    Number(away?.offense?.epa_play ?? 0) -
    Number(home?.defense?.epa_play ?? 0) -
    Number(away?.defense?.epa_play ?? 0);

  const success =
    Number(home?.offense?.success_rate ?? 0) +
    Number(away?.offense?.success_rate ?? 0) -
    85;

  return modelRoundHalf(
    Math.max(
      35,
      Math.min(
        80,
        52.5 + efficiency * 5 + success * 0.15
      )
    )
  );
}

function resolveMatchupTeam(value) {
  const target = String(value ?? "").trim().toLowerCase();

  return Object.keys(teams).find(
    name => name.toLowerCase() === target
  ) ?? null;
}

function matchupLocationText(teamA, teamB) {
  if (tapeVenue === "team_a_home") return `${teamB} at ${teamA}`;
  if (tapeVenue === "team_b_home") return `${teamA} at ${teamB}`;
  return `${teamA} vs. ${teamB} · Neutral site`;
}

function buildInteractiveProjection(teamAName, teamBName, venue) {
  const teamA = getTeam(teamAName);
  const teamB = getTeam(teamBName);

  const teamAHome = venue !== "team_b_home";
  const neutral = venue === "neutral";

  const home = teamAHome ? teamA : teamB;
  const away = teamAHome ? teamB : teamA;

  const homeName = home.team;
  const awayName = away.team;

  const slope = Number(
    projectionsData?.meta?.calibration?.slope ?? 10.4245
  );

  const ratingDifference =
    Number(home.power_rating) -
    Number(away.power_rating);

  const ratingPoints = ratingDifference * slope;
  const ratingOnlySpread = -ratingPoints;

  const hfa = neutral
    ? 0
    : Number(
        hfaData?.teams?.[homeName] ??
        hfaData?.meta?.default_hfa ??
        2
      );

  const afterHfa = ratingOnlySpread - hfa;

  const matchup = calculateInteractiveMatchupAdjustment(home, away);

  const homeSpread = modelRoundHalf(
    afterHfa - matchup.total
  );

  const total = calculateInteractiveTotal(home, away);
  const winProbability = modelWinProbability(homeSpread);

  const marginA = teamAHome
    ? -homeSpread
    : homeSpread;

  let scoreA = Math.round((total + marginA) / 2);
  let scoreB = Math.round((total - marginA) / 2);

  if (scoreA === scoreB && marginA !== 0) {
    if (marginA > 0) scoreA += 1;
    else scoreB += 1;
  }

  return {
    teamA,
    teamB,
    home,
    away,
    homeName,
    awayName,
    teamAHome,
    neutral,
    slope,
    ratingPoints,
    ratingOnlySpread: modelRoundHalf(ratingOnlySpread),
    hfa,
    afterHfa: modelRoundHalf(afterHfa),
    matchup,
    homeSpread,
    total,
    winProbability,
    scoreA,
    scoreB,
    teamAWin: teamAHome
      ? winProbability.home
      : winProbability.away,
    teamBWin: teamAHome
      ? winProbability.away
      : winProbability.home,
  };
}

function matchupProfileRows(offense, defense) {
  return `
    ${renderMetricRow(
      "Model EPA / Play",
      `${formatEPA(offense?.offense?.epa_play)} vs ${formatEPA(defense?.defense?.epa_play)} allowed`
    )}

    ${renderMetricRow(
      "Model Success Rate",
      `${formatRate(offense?.offense?.success_rate)} vs ${formatRate(defense?.defense?.success_rate)} allowed`
    )}

    ${renderMetricRow(
      "2026 EPA / Pass",
      `${formatEPA(modelLiveNumber(offense, "offense", "epa_pass"))} vs ${formatEPA(modelLiveNumber(defense, "defense", "epa_pass"))} allowed`
    )}

    ${renderMetricRow(
      "2026 EPA / Rush",
      `${formatEPA(modelLiveNumber(offense, "offense", "epa_rush"))} vs ${formatEPA(modelLiveNumber(defense, "defense", "epa_rush"))} allowed`
    )}

    ${renderMetricRow(
      "2026 Explosive Rate",
      `${formatRate(modelLiveNumber(offense, "offense", "explosive_rate"))} vs ${formatRate(modelLiveNumber(defense, "defense", "explosive_rate"))} allowed`
    )}

    ${renderMetricRow(
      "2026 Havoc",
      `${formatRate(modelLiveNumber(offense, "offense", "havoc_rate"))} allowed vs ${formatRate(modelLiveNumber(defense, "defense", "havoc_rate"))} created`
    )}
  `;
}

function matchupComponentRows(projection) {
  const labels = {
    passing: "Passing matchup",
    rushing: "Rushing matchup",
    success_rate: "Success-rate matchup",
    explosiveness: "Explosiveness matchup",
    havoc: "Havoc matchup",
  };

  return Object.entries(labels).map(([field, label]) =>
    renderMetricRow(
      label,
      projection.matchup.available[field]
        ? formatSigned(projection.matchup.components[field], 2)
        : "Withheld",
      projection.matchup.available[field]
        ? "active"
        : "sample not met"
    )
  ).join("");
}

function renderMatchupAnalysis(errorMessage = "") {
  const container = document.getElementById("tape-container");
  if (!container) return;

  const names = Object.keys(teams)
    .sort((a, b) => a.localeCompare(b));

  const options = names.map(
    name => `<option value="${escapeHtml(name)}"></option>`
  ).join("");

  const projection =
    tapeTeamA && tapeTeamB
      ? buildInteractiveProjection(
          tapeTeamA,
          tapeTeamB,
          tapeVenue
        )
      : null;

  const result = projection ? `
    <div class="tape-result">

      <div class="tape-scoreboard">
        <div class="tape-team">
          <div class="team-with-logo">
            ${teamLogoMarkup(projection.teamA.team, "matchup")}
            <div class="tape-team-name">
              ${escapeHtml(projection.teamA.team)}
            </div>
          </div>

          <div class="tape-team-meta">
            ${powerRank(projection.teamA)}
            · ${formatPercent(projection.teamAWin)} win probability
          </div>
        </div>

        <div>
          <div class="tape-score">
            ${projection.scoreA}–${projection.scoreB}
          </div>

          <div
            class="tape-team-meta"
            style="text-align:center;"
          >
            Projected final
          </div>
        </div>

        <div class="tape-team">
          <div class="team-with-logo">
            ${teamLogoMarkup(projection.teamB.team, "matchup")}
            <div class="tape-team-name">
              ${escapeHtml(projection.teamB.team)}
            </div>
          </div>

          <div class="tape-team-meta">
            ${powerRank(projection.teamB)}
            · ${formatPercent(projection.teamBWin)} win probability
          </div>
        </div>
      </div>

      <div class="tape-summary-grid">

        <div class="tape-summary-card">
          <div class="tape-summary-label">Fair Line</div>
          <div class="tape-summary-value">
            ${escapeHtml(
              favoredLine(
                projection.homeName,
                projection.awayName,
                projection.homeSpread
              )
            )}
          </div>
        </div>

        <div class="tape-summary-card">
          <div class="tape-summary-label">
            Projected Total
          </div>
          <div class="tape-summary-value">
            ${formatNumber(projection.total, 1)}
          </div>
        </div>

        <div class="tape-summary-card">
          <div class="tape-summary-label">Location</div>
          <div
            class="tape-summary-value"
            style="font-size:15px;"
          >
            ${escapeHtml(
              matchupLocationText(
                tapeTeamA,
                tapeTeamB
              )
            )}
          </div>
        </div>

        <div class="tape-summary-card">
          <div class="tape-summary-label">
            Model Version
          </div>
          <div
            class="tape-summary-value"
            style="font-size:15px;"
          >
            ${escapeHtml(
              projectionsData?.meta?.version ??
              "Model A"
            )}
          </div>
        </div>
      </div>

      <div class="tape-breakdown">

        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              Projection Build
            </div>
          </div>

          <div class="panel-body">
            ${renderMetricRow(
              "Rating-only line",
              favoredLine(
                projection.homeName,
                projection.awayName,
                projection.ratingOnlySpread
              )
            )}

            ${renderMetricRow(
              "Home-field advantage",
              projection.neutral
                ? "0.0"
                : `${formatNumber(projection.hfa, 1)} pts`,
              projection.neutral
                ? "neutral"
                : projection.homeName
            )}

            ${renderMetricRow(
              "Line after venue",
              favoredLine(
                projection.homeName,
                projection.awayName,
                projection.afterHfa
              )
            )}

            ${renderMetricRow(
              "Live matchup adjustment",
              formatSigned(
                projection.matchup.total,
                2
              ),
              projection.matchup.comparable
                ? "active"
                : "withheld"
            )}

            ${renderMetricRow(
              "Final fair line",
              favoredLine(
                projection.homeName,
                projection.awayName,
                projection.homeSpread
              )
            )}
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              Live Matchup Components
            </div>
          </div>

          <div class="panel-body">
            ${matchupComponentRows(projection)}
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              ${escapeHtml(projection.teamA.team)}
              Offense vs
              ${escapeHtml(projection.teamB.team)}
              Defense
            </div>
          </div>

          <div class="panel-body">
            ${matchupProfileRows(
              projection.teamA,
              projection.teamB
            )}
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              ${escapeHtml(projection.teamB.team)}
              Offense vs
              ${escapeHtml(projection.teamA.team)}
              Defense
            </div>
          </div>

          <div class="panel-body">
            ${matchupProfileRows(
              projection.teamB,
              projection.teamA
            )}
          </div>
        </div>
      </div>

      <div
        class="ratings-note"
        style="margin-top:12px;"
      >
        Hypothetical matchup only. It uses the current
        Model A rating scale, total formula, team-specific
        home-field table and sample-gated live matchup
        adjustments. It does not create a tracked projection,
        betting signal or official model result.
      </div>
    </div>
  ` : `
    <div
      class="empty-state"
      style="margin-top:16px;"
    >
      Search for two teams and run the matchup analysis.
    </div>
  `;

  container.innerHTML = `
    <div class="tape-controls">

      <div class="tape-field">
        <label for="matchup-team-a">
          Team A
        </label>

        <input
          id="matchup-team-a"
          list="matchup-team-options"
          type="search"
          placeholder="Search teams..."
          value="${escapeHtml(tapeTeamA ?? "")}"
        >
      </div>

      <div class="tape-field">
        <label for="matchup-team-b">
          Team B
        </label>

        <input
          id="matchup-team-b"
          list="matchup-team-options"
          type="search"
          placeholder="Search teams..."
          value="${escapeHtml(tapeTeamB ?? "")}"
        >
      </div>

      <datalist id="matchup-team-options">
        ${options}
      </datalist>

      <div class="tape-field">
        <label for="matchup-venue">
          Location
        </label>

        <select id="matchup-venue">
          <option
            value="neutral"
            ${tapeVenue === "neutral" ? "selected" : ""}
          >
            Neutral site
          </option>

          <option
            value="team_a_home"
            ${tapeVenue === "team_a_home" ? "selected" : ""}
          >
            Team A home
          </option>

          <option
            value="team_b_home"
            ${tapeVenue === "team_b_home" ? "selected" : ""}
          >
            Team B home
          </option>
        </select>
      </div>

      <button
        class="tape-button"
        type="button"
        onclick="runMatchupAnalysis()"
      >
        Run Analysis
      </button>
    </div>

    ${
      errorMessage
        ? `
          <div
            class="ratings-note"
            style="margin-top:10px;color:#9a4d00;"
          >
            ${escapeHtml(errorMessage)}
          </div>
        `
        : ""
    }

    ${result}
  `;
}

function initializeMatchupAnalysis() {
  renderMatchupAnalysis();
}

function runMatchupAnalysis() {
  const teamA = resolveMatchupTeam(
    document.getElementById("matchup-team-a")?.value
  );

  const teamB = resolveMatchupTeam(
    document.getElementById("matchup-team-b")?.value
  );

  const venue =
    document.getElementById("matchup-venue")?.value ??
    "neutral";

  if (!teamA || !teamB) {
    renderMatchupAnalysis(
      "Select two valid FBS teams from the search suggestions."
    );
    return;
  }

  if (teamA === teamB) {
    renderMatchupAnalysis(
      "Choose two different teams."
    );
    return;
  }

  tapeTeamA = teamA;
  tapeTeamB = teamB;

  tapeVenue = [
    "neutral",
    "team_a_home",
    "team_b_home"
  ].includes(venue)
    ? venue
    : "neutral";

  renderMatchupAnalysis();
}


// ============================================================================
// TEAM DOSSIER
// ============================================================================

function openDossier(teamName) {
  const team = getTeam(teamName);
  if (!team) return;

  currentDossierTeamName = teamName;

  renderDossier(team);
  switchView("dossier");
}

function advancedSide(teamName, side) {
  return (
    advancedMetricsData
      ?.teams
      ?.[teamName]
      ?.[currentAdvancedSample]
      ?.[side] ??
    null
  );
}

function externalRating(teamName) {
  return (
    externalRatingsData
      ?.teams
      ?.[teamName] ??
    null
  );
}

function rosterFoundation(teamName) {
  return (
    rosterFoundationData
      ?.teams
      ?.[teamName] ??
    null
  );
}

function externalRank(value) {
  return hasValue(value) && Number(value) > 0
    ? `#${Number(value)}`
    : "—";
}

function externalMetricRank(field, value) {
  if (!hasValue(value)) return "—";

  const target = Number(value);

  const values = Object.values(
    externalRatingsData?.teams ?? {}
  )
    .map(team => team?.[field])
    .filter(hasValue)
    .map(Number);

  const better = values.filter(
    item => item > target
  ).length;

  return `#${better + 1} Overall`;
}

function advancedRank(
  teamName,
  side,
  field,
  lowerIsBetter = false
) {
  const target =
    advancedSide(teamName, side)?.[field];

  if (!hasValue(target)) return "";

  const targetNumber = Number(target);

  const values = Object.keys(teams)
    .map(
      name =>
        advancedSide(name, side)?.[field]
    )
    .filter(hasValue)
    .map(Number);

  const better = values.filter(value =>
    lowerIsBetter
      ? value < targetNumber
      : value > targetNumber
  ).length;

  return `#${better + 1}`;
}

function advancedContext(
  teamName,
  side,
  field,
  sampleText = "",
  lowerIsBetter = false
) {
  const rank = advancedRank(
    teamName,
    side,
    field,
    lowerIsBetter
  );

  return [rank, sampleText]
    .filter(Boolean)
    .join(" · ");
}

function advancedMetricRows(teamName, side) {
  const data = advancedSide(teamName, side);

  if (!data || !data.n_plays) {
    return `
      <div
        class="empty-state"
        style="padding:24px 0;"
      >
        No current-season sample yet.
      </div>
    `;
  }

  const offense = side === "offense";

  return `
    ${renderMetricRow(
      "Early-Down EPA" + (offense ? "" : " Allowed"),
      formatEPA(data.early_down_epa),
      advancedContext(
        teamName,
        side,
        "early_down_epa",
        `${data.early_down_plays ?? 0} plays`,
        !offense
      )
    )}

    ${renderMetricRow(
      "Late-Down EPA" + (offense ? "" : " Allowed"),
      formatEPA(data.late_down_epa),
      advancedContext(
        teamName,
        side,
        "late_down_epa",
        `${data.late_down_plays ?? 0} plays`,
        !offense
      )
    )}

    ${renderMetricRow(
      "Standard-Down Success" + (offense ? "" : " Allowed"),
      formatRate(data.standard_down_success_rate),
      advancedContext(
        teamName,
        side,
        "standard_down_success_rate",
        `${data.standard_down_plays ?? 0} plays`,
        !offense
      )
    )}

    ${renderMetricRow(
      "Passing-Down Success" + (offense ? "" : " Allowed"),
      formatRate(data.passing_down_success_rate),
      advancedContext(
        teamName,
        side,
        "passing_down_success_rate",
        `${data.passing_down_plays ?? 0} plays`,
        !offense
      )
    )}

    ${renderMetricRow(
      offense
        ? "Stuff Rate Allowed"
        : "Stuff Rate Created",
      formatRate(data.stuff_rate),
      advancedContext(
        teamName,
        side,
        "stuff_rate",
        `${data.rush_attempts ?? 0} rushes`,
        offense
      )
    )}

    ${renderMetricRow(
      offense
        ? "Sack Rate Allowed"
        : "Sack Rate Created",
      formatRate(data.sack_rate),
      advancedContext(
        teamName,
        side,
        "sack_rate",
        `${data.pass_plays ?? 0} pass plays`,
        offense
      )
    )}

    ${renderMetricRow(
      offense
        ? "TFL Rate Allowed"
        : "TFL Rate Created",
      formatRate(data.tfl_rate),
      advancedContext(
        teamName,
        side,
        "tfl_rate",
        "",
        offense
      )
    )}

    ${renderMetricRow(
      "Power Success Rate" +
        (offense ? "" : " Allowed"),
      formatRate(data.power_success_rate),
      advancedContext(
        teamName,
        side,
        "power_success_rate",
        `${data.power_attempts ?? 0} attempts`,
        !offense
      )
    )}

    ${renderMetricRow(
      offense
        ? "Turnovers Lost"
        : "Turnovers Forced",
      formatNumber(data.turnovers, 0),
      advancedContext(
        teamName,
        side,
        "turnover_rate",
        "",
        offense
      )
    )}
  `;
}

function advancedSplitRows(teamName, side) {
  const data = advancedSide(teamName, side);

  if (!data || !data.n_plays) {
    return `
      <div
        class="empty-state"
        style="padding:24px 0;"
      >
        No current-season sample yet.
      </div>
    `;
  }

  const allowed =
    side === "defense"
      ? " Allowed"
      : "";

  const lowerIsBetter =
    side === "defense";

  return `
    ${renderMetricRow(
      "First-Half EPA" + allowed,
      formatEPA(data.first_half_epa),
      advancedContext(
        teamName,
        side,
        "first_half_epa",
        `${data.first_half_plays ?? 0} plays`,
        lowerIsBetter
      )
    )}

    ${renderMetricRow(
      "Second-Half EPA" + allowed,
      formatEPA(data.second_half_epa),
      advancedContext(
        teamName,
        side,
        "second_half_epa",
        `${data.second_half_plays ?? 0} plays`,
        lowerIsBetter
      )
    )}

    ${renderMetricRow(
      "Home EPA" + allowed,
      formatEPA(data.home_epa),
      advancedContext(
        teamName,
        side,
        "home_epa",
        `${data.home_plays ?? 0} plays`,
        lowerIsBetter
      )
    )}

    ${renderMetricRow(
      "Away EPA" + allowed,
      formatEPA(data.away_epa),
      advancedContext(
        teamName,
        side,
        "away_epa",
        `${data.away_plays ?? 0} plays`,
        lowerIsBetter
      )
    )}

    ${renderMetricRow(
      "Red-Zone EPA" + allowed,
      formatEPA(data.red_zone_epa),
      advancedContext(
        teamName,
        side,
        "red_zone_epa",
        `${data.red_zone_plays ?? 0} plays`,
        lowerIsBetter
      )
    )}

    ${renderMetricRow(
      "Red-Zone Success" + allowed,
      formatRate(data.red_zone_success_rate),
      advancedContext(
        teamName,
        side,
        "red_zone_success_rate",
        "",
        lowerIsBetter
      )
    )}

    ${renderMetricRow(
      side === "offense"
        ? "Line Yards / Rush"
        : "Line Yards / Rush Allowed",
      formatNumber(
        data.line_yards_per_rush,
        2
      ),
      advancedContext(
        teamName,
        side,
        "line_yards_per_rush",
        "",
        lowerIsBetter
      )
    )}

    ${renderMetricRow(
      side === "offense"
        ? "Second-Level Yards / Rush"
        : "Second-Level Yards / Rush Allowed",
      formatNumber(
        data.second_level_yards_per_rush,
        2
      ),
      advancedContext(
        teamName,
        side,
        "second_level_yards_per_rush",
        "",
        lowerIsBetter
      )
    )}

    ${renderMetricRow(
      side === "offense"
        ? "Open-Field Yards / Rush"
        : "Open-Field Yards / Rush Allowed",
      formatNumber(
        data.open_field_yards_per_rush,
        2
      ),
      advancedContext(
        teamName,
        side,
        "open_field_yards_per_rush",
        "",
        lowerIsBetter
      )
    )}
  `;
}

function setAdvancedSample(sample) {
  currentAdvancedSample =
    sample === "all_plays"
      ? "all_plays"
      : "non_garbage";

  const team =
    getTeam(currentDossierTeamName);

  if (team) {
    renderDossier(team);
  }
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

function renderSeasonOutlook(team) {
  const season =
    getSeasonProjection(team.team);

  if (!season) return "";

  const distribution =
    usefulWinDistribution(
      season.exact_win_distribution
    );

  const maxProbability = Math.max(
    1,
    ...distribution.map(
      item => item.probability
    )
  );

  const distributionHtml =
    distribution.map(item => `
      <div class="distribution-row">
        <div class="distribution-wins">
          ${item.wins}
        </div>

        <div class="distribution-track">
          <div
            class="distribution-fill"
            style="width:${Math.max(
              2,
              (
                item.probability /
                maxProbability
              ) * 100
            )}%;"
          ></div>
        </div>

        <div class="distribution-prob">
          ${formatPercent(
            item.probability
          )}
        </div>
      </div>
    `).join("");

  const altTotals =
    Object.entries(
      season.alt_win_totals ?? {}
    )
      .filter(([line]) => {
        const value = Number(line);

        return (
          value >= 5.5 &&
          value <= 11.5
        );
      })
      .sort(
        (a, b) =>
          Number(a[0]) -
          Number(b[0])
      );

  const altRows =
    altTotals.map(
      ([line, probabilities]) => {
        const over =
          Number(
            probabilities?.over ??
            0
          );

        const under =
          Number(
            probabilities?.under ??
            0
          );

        return `
          <tr>
            <td>
              ${escapeHtml(line)}
            </td>

            <td
              class="${
                over >= under
                  ? "alt-strong"
                  : ""
              }"
            >
              ${formatPercent(over)}
            </td>

            <td
              class="${
                under > over
                  ? "alt-strong"
                  : ""
              }"
            >
              ${formatPercent(under)}
            </td>
          </tr>
        `;
      }
    ).join("");

  const scheduleRows =
    (season.schedule ?? []).map(
      game => {
        const source =
          game.probability_source;

        const completed =
          source ===
          "completed_result";

        const fcs =
          game.opponent_type ===
          "FCS";

        let probabilityText =
          formatPercent(
            game.win_probability
          );

        if (completed) {
          probabilityText =
            Number(
              game.win_probability
            ) >= 99
              ? "WIN"
              : "LOSS";
        }

        return `
          <tr>
            <td>
              ${game.week ?? "—"}
            </td>

            <td>
              ${seasonLocationLabel(
                game.location
              )}
              ${escapeHtml(
                game.opponent
              )}

              ${
                fcs
                  ? `<span class="fcs-tag">FCS</span>`
                  : ""
              }
            </td>

            <td>
              ${projectionSourceLabel(
                source
              )}
            </td>

            <td>
              ${
                hasValue(
                  game.team_line
                )
                  ? shortSpread(
                      game.team_line
                    )
                  : "—"
              }
            </td>

            <td>
              <strong>
                ${probabilityText}
              </strong>
            </td>
          </tr>
        `;
      }
    ).join("");

  return `
    <div class="season-outlook">
      <div class="eyebrow">
        Season outlook
      </div>

      <div class="season-summary-grid">
        <div class="season-summary-card">
          <div class="season-summary-label">
            Projected Wins
          </div>

          <div class="season-summary-value">
            ${formatNumber(
              season.expected_wins,
              2
            )}
          </div>

          <div class="season-summary-note">
            ${formatNumber(
              season.expected_losses,
              2
            )}
            projected losses
          </div>
        </div>

        <div class="season-summary-card">
          <div class="season-summary-label">
            Most Likely Record
          </div>

          <div class="season-summary-value">
            ${escapeHtml(
              season.most_likely_record ??
              "—"
            )}
          </div>

          <div class="season-summary-note">
            ${formatPercent(
              season.most_likely_probability
            )}
            exact outcome
          </div>
        </div>

        <div class="season-summary-card">
          <div class="season-summary-label">
            Bowl Eligible
          </div>

          <div class="season-summary-value">
            ${formatPercent(
              season.bowl_eligible_probability
            )}
          </div>

          <div class="season-summary-note">
            Probability of 6+ wins
          </div>
        </div>

        <div class="season-summary-card">
          <div class="season-summary-label">
            10+ Wins
          </div>

          <div class="season-summary-value">
            ${formatPercent(
              season?.at_least?.["10_wins"]
            )}
          </div>

          <div class="season-summary-note">
            ${formatPercent(
              season?.at_least?.["11_wins"]
            )}
            for 11+
          </div>
        </div>
      </div>

      <div class="season-two-column">

        <div class="analysis-panel">
          <div class="analysis-panel-header">
            <div class="analysis-panel-title">
              Win Distribution
            </div>
          </div>

          <div class="distribution-wrap">
            ${distributionHtml}
          </div>
        </div>

        <div class="analysis-panel">
          <div class="analysis-panel-header">
            <div class="analysis-panel-title">
              Alt Win Totals
            </div>
          </div>

          <div style="padding:4px 10px 10px;">
            <table class="alt-table">
              <thead>
                <tr>
                  <th>Total</th>
                  <th>Over</th>
                  <th>Under</th>
                </tr>
              </thead>

              <tbody>
                ${altRows}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="analysis-panel">
        <div class="analysis-panel-header">
          <div class="analysis-panel-title">
            Full Season Schedule
          </div>

          <div class="team-meta">
            ${season.games ?? "—"}
            games
          </div>
        </div>

        <div style="overflow-x:auto;">
          <table class="season-schedule-table">
            <thead>
              <tr>
                <th>Week</th>
                <th>Opponent</th>
                <th>Source</th>
                <th>Model Line</th>
                <th>Win Probability</th>
              </tr>
            </thead>

            <tbody>
              ${scheduleRows}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;
}

function renderDossier(team) {
  const container =
    document.getElementById(
      "dossier-container"
    );

  if (!container) return;

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

  const external =
    externalRating(
      team.team
    );

  const roster =
    rosterFoundation(
      team.team
    );

  container.innerHTML = `
    <div class="dossier-header">
      <div>
        <div class="eyebrow">
          Team dossier
        </div>

        <div class="team-title-row dossier-team-heading">
          ${teamLogoMarkup(
            team.team,
            "dossier"
          )}

          <div class="team-title">
            ${escapeHtml(
              team.team
            )}
          </div>
        </div>

        <div class="team-dossier-sub">
          ${escapeHtml(
            team.conference ??
            "Independent"
          )}
          · ${recordText(team)}
          · ${escapeHtml(
            liveSampleLabel(team)
          )}
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
          ${formatSigned(
            team.power_rating,
            3
          )}

          <span class="dossier-rank-inline">
            (${powerRank(team)} Overall)
          </span>
        </div>
      </div>

      <div class="dossier-stat">
        <div class="dossier-label">
          SP+ Overall
        </div>

        <div class="dossier-value">
          ${formatSigned(
            team?.sp_plus?.overall,
            1
          )}

          <span class="dossier-rank-inline">
            (${spPlusRank(
              team,
              "overall"
            )})
          </span>
        </div>
      </div>

      <div class="dossier-stat">
        <div class="dossier-label">
          SP+ Offense
        </div>

        <div class="dossier-value">
          ${formatSigned(
            team?.sp_plus?.offense,
            1
          )}

          <span class="dossier-rank-inline">
            (${spPlusRank(
              team,
              "offense"
            )})
          </span>
        </div>
      </div>

      <div class="dossier-stat">
        <div class="dossier-label">
          SP+ Defense
        </div>

        <div class="dossier-value">
          ${formatSigned(
            team?.sp_plus?.defense,
            1
          )}

          <span class="dossier-rank-inline">
            (${spPlusRank(
              team,
              "defense"
            )})
          </span>
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

      <div class="dossier-stat">
        <div class="dossier-label">
          ESPN FPI
        </div>

        <div class="dossier-value">
          ${formatSigned(
            external?.fpi,
            1
          )}

          <span class="dossier-rank-inline">
            (${externalRank(
              external?.fpi_rank
            )} Overall)
          </span>
        </div>
      </div>

      <div class="dossier-stat">
        <div class="dossier-label">
          ESPN Special Teams
        </div>

        <div class="dossier-value">
          ${formatSigned(
            external?.fpi_special_teams,
            3
          )}

          <span class="dossier-rank-inline">
            (${externalMetricRank(
              "fpi_special_teams",
              external?.fpi_special_teams
            )})
          </span>
        </div>
      </div>
    </div>

    ${renderSeasonOutlook(team)}

    <div
      class="dossier-layout"
      style="margin-top:12px;"
    >

      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">
            Offensive Profile
          </div>
        </div>

        <div class="panel-body">
          ${renderMetricRow(
            "Model EPA / Play",
            formatEPA(offModelEPA),
            metricRank(
              team,
              "offense",
              "epa_play_rank",
              offModelEPA
            )
          )}

          ${renderMetricRow(
            "Model Success Rate",
            formatRate(offModelSR),
            metricRank(
              team,
              "offense",
              "sr_rank",
              offModelSR
            )
          )}

          ${renderMetricRow(
            "2026 EPA / Pass",
            formatEPA(
              offLive?.epa_pass
            )
          )}

          ${renderMetricRow(
            "2026 EPA / Rush",
            formatEPA(
              offLive?.epa_rush
            )
          )}

          ${renderMetricRow(
            "2026 Success Rate",
            formatRate(
              offLive?.success_rate
            )
          )}

          ${renderMetricRow(
            "2026 Explosive Rate",
            formatRate(
              offLive?.explosive_rate
            )
          )}

          ${renderMetricRow(
            "2026 Havoc Allowed",
            formatRate(
              offLive?.havoc_rate
            )
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
            "Model EPA / Play",
            formatEPA(defModelEPA),
            metricRank(
              team,
              "defense",
              "epa_play_rank",
              defModelEPA
            )
          )}

          ${renderMetricRow(
            "Model Success Rate Allowed",
            formatRate(defModelSR),
            metricRank(
              team,
              "defense",
              "sr_rank",
              defModelSR
            )
          )}

          ${renderMetricRow(
            "2026 EPA / Pass Allowed",
            formatEPA(
              defLive?.epa_pass
            )
          )}

          ${renderMetricRow(
            "2026 EPA / Rush Allowed",
            formatEPA(
              defLive?.epa_rush
            )
          )}

          ${renderMetricRow(
            "2026 Success Rate Allowed",
            formatRate(
              defLive?.success_rate
            )
          )}

          ${renderMetricRow(
            "2026 Explosive Rate Allowed",
            formatRate(
              defLive?.explosive_rate
            )
          )}

          ${renderMetricRow(
            "2026 Havoc Created",
            formatRate(
              defLive?.havoc_rate
            )
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
            "Model Net EPA / Play",
            formatEPA(
              team?.net?.epa
            )
          )}

          ${renderMetricRow(
            "Model Net Success Rate",
            formatPercent(
              team?.net?.sr
            )
          )}

          ${renderMetricRow(
            "2026 Net EPA / Pass",
            formatEPA(
              liveNet(
                team,
                "epa_pass"
              )
            )
          )}

          ${renderMetricRow(
            "2026 Net EPA / Rush",
            formatEPA(
              liveNet(
                team,
                "epa_rush"
              )
            )
          )}

          ${renderMetricRow(
            "2026 Net Success Rate",
            formatPercent(
              liveNet(
                team,
                "success_rate"
              )
            )
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
            powerRank(team)
          )}

          ${renderMetricRow(
            "Conference",
            escapeHtml(
              team.conference ??
              "—"
            )
          )}

          ${renderMetricRow(
            "2026 Offensive Plays",
            offPlays > 0
              ? formatNumber(
                  offPlays,
                  0
                )
              : "—"
          )}

          ${renderMetricRow(
            "2026 Defensive Plays",
            defPlays > 0
              ? formatNumber(
                  defPlays,
                  0
                )
              : "—"
          )}

          ${renderMetricRow(
            "Live Data Weight",
            metricsData
              ?.meta
              ?.blend_weight !== undefined
                ? formatPercent(
                    Number(
                      metricsData
                        .meta
                        .blend_weight
                    ) * 100,
                    0
                  )
                : "—"
          )}

          ${renderMetricRow(
            "Sample Status",
            escapeHtml(
              liveSampleLabel(team)
            )
          )}
        </div>
      </div>
    </div>

    <div
      class="panel"
      style="margin-top:12px;"
    >
      <div class="panel-header">
        <div>
          <div class="panel-title">
            Roster Foundation
          </div>

          <div
            class="team-meta"
            style="margin-top:5px;"
          >
            2026 preseason roster snapshot
            · display-only
            · not used by Model A
          </div>
        </div>
      </div>

      <div
        class="dossier-layout"
        style="padding:12px 16px 16px;"
      >
        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              Returning Production
            </div>
          </div>

          <div class="panel-body">
            ${renderMetricRow(
              "Combined",
              formatPercent(
                roster?.returning_production_pct
              ),
              externalRank(
                roster?.returning_production_rank
              )
            )}

            ${renderMetricRow(
              "Offense",
              formatPercent(
                roster?.returning_offense_pct
              ),
              externalRank(
                roster?.returning_offense_rank
              )
            )}

            ${renderMetricRow(
              "Defense",
              formatPercent(
                roster?.returning_defense_pct
              ),
              externalRank(
                roster?.returning_defense_rank
              )
            )}

            ${renderMetricRow(
              "Returning Players",
              formatNumber(
                roster?.returning_players,
                0
              )
            )}
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              Team Talent
            </div>
          </div>

          <div class="panel-body">
            ${renderMetricRow(
              "Talent Composite",
              formatNumber(
                roster?.talent_composite,
                2
              ),
              externalRank(
                roster?.talent_rank
              )
            )}

            ${renderMetricRow(
              "Blue-Chip Ratio",
              formatPercent(
                roster?.blue_chip_ratio_pct
              )
            )}

            ${renderMetricRow(
              "Rated Recruits",
              formatNumber(
                roster?.rated_recruits,
                0
              )
            )}
          </div>
        </div>
      </div>
    </div>

    <div
      class="panel"
      style="margin-top:12px;"
    >
      <div class="panel-header">
        <div>
          <div class="panel-title">
            External Ratings & Resume
          </div>

          <div
            class="team-meta"
            style="margin-top:5px;"
          >
            ESPN FPI Week
            ${externalRatingsData?.meta?.week ?? "—"}
            · display-only
            · not used by Model A
          </div>
        </div>
      </div>

      <div
        class="dossier-layout"
        style="padding:12px 16px 16px;"
      >
        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              Strength & Resume
            </div>
          </div>

          <div class="panel-body">
            ${renderMetricRow(
              "FPI",
              formatSigned(
                external?.fpi,
                1
              ),
              externalRank(
                external?.fpi_rank
              )
            )}

            ${renderMetricRow(
              "Strength of Record",
              externalRank(
                external?.sor_rank
              )
            )}

            ${renderMetricRow(
              "Strength of Schedule",
              externalRank(
                external?.sos_rank
              )
            )}

            ${renderMetricRow(
              "Remaining SOS",
              externalRank(
                external?.remaining_sos_rank
              )
            )}

            ${renderMetricRow(
              "Game Control",
              externalRank(
                external?.game_control_rank
              )
            )}
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              FPI Components
            </div>
          </div>

          <div class="panel-body">
            ${renderMetricRow(
              "Offensive Component",
              formatSigned(
                external?.fpi_offense,
                3
              )
            )}

            ${renderMetricRow(
              "Defensive Component",
              formatSigned(
                external?.fpi_defense,
                3
              )
            )}

            ${renderMetricRow(
              "Special Teams Component",
              formatSigned(
                external?.fpi_special_teams,
                3
              ),
              externalMetricRank(
                "fpi_special_teams",
                external?.fpi_special_teams
              )
            )}

            ${renderMetricRow(
              "Projected Record",
              hasValue(
                external?.projected_wins
              )
                ? `${formatNumber(
                    external.projected_wins,
                    1
                  )}–${formatNumber(
                    external.projected_losses,
                    1
                  )}`
                : "—"
            )}
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              Season Probabilities
            </div>
          </div>

          <div class="panel-body">
            ${renderMetricRow(
              "Win Conference",
              formatPercent(
                external?.win_conference_pct
              )
            )}

            ${renderMetricRow(
              "Make Playoff",
              formatPercent(
                external?.make_playoff_pct
              )
            )}

            ${renderMetricRow(
              "Make Title Game",
              formatPercent(
                external?.make_title_game_pct
              )
            )}

            ${renderMetricRow(
              "Win National Title",
              formatPercent(
                external?.win_title_pct
              )
            )}

            ${renderMetricRow(
              "Win Out",
              formatPercent(
                external?.win_out_pct
              )
            )}
          </div>
        </div>
      </div>
    </div>

    <div
      class="panel"
      style="margin-top:12px;"
    >
      <div
        class="panel-header"
        style="align-items:center; gap:12px; flex-wrap:wrap;"
      >
        <div>
          <div class="panel-title">
            Advanced 2026 Performance
          </div>

          <div
            class="team-meta"
            style="margin-top:5px;"
          >
            Display-only statistics
            · not used by Model A
          </div>
        </div>

        <div
          class="ratings-toggle"
          style="padding:0; border:0; margin-left:auto;"
        >
          <button
            type="button"
            class="ratings-toggle-button ${
              currentAdvancedSample ===
              "non_garbage"
                ? "active"
                : ""
            }"
            onclick="setAdvancedSample('non_garbage')"
          >
            Garbage Time Excluded
          </button>

          <button
            type="button"
            class="ratings-toggle-button ${
              currentAdvancedSample ===
              "all_plays"
                ? "active"
                : ""
            }"
            onclick="setAdvancedSample('all_plays')"
          >
            All Plays
          </button>
        </div>
      </div>

      <div
        class="sample-warning"
        style="margin:12px 16px 0;"
      >
        Current-season samples are descriptive
        and can move sharply early in the season.
        A dash means the minimum four-play sample
        has not been reached.
      </div>

      <div
        class="dossier-layout"
        style="padding:12px 16px 16px;"
      >
        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              Offense · Downs & Disruption
            </div>
          </div>

          <div class="panel-body">
            ${advancedMetricRows(
              team.team,
              "offense"
            )}
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              Defense · Downs & Disruption
            </div>
          </div>

          <div class="panel-body">
            ${advancedMetricRows(
              team.team,
              "defense"
            )}
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              Offense · Situational Splits
            </div>
          </div>

          <div class="panel-body">
            ${advancedSplitRows(
              team.team,
              "offense"
            )}
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              Defense · Situational Splits
            </div>
          </div>

          <div class="panel-body">
            ${advancedSplitRows(
              team.team,
              "defense"
            )}
          </div>
        </div>
      </div>
    </div>
  `;
}


// ============================================================================
// EVENTS / START
// ============================================================================

function attachEvents() {
  const search =
    document.getElementById(
      "team-search"
    );

  if (!search) return;

  search.addEventListener(
    "input",
    event => {
      currentSearch =
        event.target.value.trim();

      renderProjections();
    }
  );
}

document.addEventListener(
  "DOMContentLoaded",
  init
);
