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
  results: "./data/results.json",
  liveScores: "./data/live_scores.json",
  openWeeklyRatings: "./data/open_weekly_ratings.json",
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
let resultsData = null;
let liveScoresData = null;
let openWeeklyRatingsData = null;

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
let detailReturnState = null;


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
