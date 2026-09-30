(() => {
  "use strict";

  const DATA_URL = "./data/postgame_analytics.json";
  const SETTLED_URL = "./data/reports/settled_results.json";
  const SIGNAL_URL = "./data/reports/signal_report.json";
  const STYLE_ID = "hammer-postgame-analytics-styles";
  const PANEL_ID = "hammer-postgame-analysis";
  const SCORECARD_ID = "hammer-performance-scorecard";

  let payload = { meta: {}, games: {} };
  let settledByGame = new Map();
  let signalReport = { signals: {} };
  let selectedGameId = null;
  let observer = null;

  function hasValue(value) {
    return value !== null && value !== undefined && Number.isFinite(Number(value));
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function canonical(value) {
    return String(value || "")
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/&/g, "and")
      .replace(/[^a-z0-9]+/g, "")
      .trim();
  }

  function format(value, digits = 3, suffix = "") {
    if (!hasValue(value)) return "—";
    return `${Number(value).toFixed(digits)}${suffix}`;
  }

  function formatSigned(value, digits = 3, suffix = "") {
    if (!hasValue(value)) return "—";
    const numeric = Number(value);
    return `${numeric > 0 ? "+" : ""}${numeric.toFixed(digits)}${suffix}`;
  }

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      .hammer-postgame-available {
        display:inline-flex; align-items:center; gap:5px; margin-top:6px;
        padding:4px 7px; border:1px solid #b9a2b7; border-radius:999px;
        background:#f7f1f6; color:#76526f; font-family:var(--mono);
        font-size:7px; font-weight:800; letter-spacing:.55px; text-transform:uppercase;
      }
      #${SCORECARD_ID} { margin:14px 0; }
      #${SCORECARD_ID} .perf-shell { border:1px solid var(--border); border-radius:13px; background:var(--surface); overflow:hidden; }
      #${SCORECARD_ID} .perf-header { display:flex; justify-content:space-between; gap:14px; align-items:flex-start; padding:15px 17px; border-bottom:1px solid var(--border); }
      #${SCORECARD_ID} .perf-kicker { color:#76526f; font-family:var(--mono); font-size:8px; font-weight:800; letter-spacing:1px; text-transform:uppercase; }
      #${SCORECARD_ID} .perf-title { margin-top:4px; font-size:18px; font-weight:850; }
      #${SCORECARD_ID} .perf-note { max-width:560px; color:var(--muted); font-size:9px; line-height:1.5; text-align:right; }
      #${SCORECARD_ID} .perf-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; padding:12px; }
      #${SCORECARD_ID} .perf-stat { padding:11px 12px; border:1px solid var(--border); border-radius:9px; background:#fbfbfa; }
      #${SCORECARD_ID} .perf-label { color:var(--muted); font-family:var(--mono); font-size:7px; font-weight:800; letter-spacing:.65px; text-transform:uppercase; }
      #${SCORECARD_ID} .perf-value { margin-top:5px; font-size:17px; font-weight:850; }
      #${SCORECARD_ID} .perf-sub { margin-top:3px; color:var(--muted); font-size:8px; }
      #${SCORECARD_ID} .perf-ytd { padding:0 12px 13px; }
      #${SCORECARD_ID} .perf-ytd-title { padding:10px 1px 8px; color:var(--muted); font-family:var(--mono); font-size:8px; font-weight:800; letter-spacing:.9px; text-transform:uppercase; }
      #${SCORECARD_ID} .perf-table-wrap { overflow-x:auto; border:1px solid var(--border); border-radius:9px; }
      #${SCORECARD_ID} table { width:100%; border-collapse:collapse; min-width:720px; }
      #${SCORECARD_ID} th, #${SCORECARD_ID} td { padding:8px 10px; border-bottom:1px solid var(--border); text-align:right; font-size:8px; white-space:nowrap; }
      #${SCORECARD_ID} th { color:var(--muted); font-family:var(--mono); font-size:7px; letter-spacing:.6px; text-transform:uppercase; background:#fafaf8; }
      #${SCORECARD_ID} th:first-child, #${SCORECARD_ID} td:first-child { text-align:left; }
      #${SCORECARD_ID} tr:last-child td { border-bottom:0; }
      #${SCORECARD_ID} .perf-confidence { display:inline-flex; padding:3px 6px; border:1px solid var(--border); border-radius:999px; font-family:var(--mono); font-size:7px; }
      #${PANEL_ID} { margin-top:18px; }
      #${PANEL_ID} .pg-shell {
        border:1px solid var(--border); border-radius:13px; background:var(--surface);
        overflow:hidden;
      }
      #${PANEL_ID} .pg-header { padding:18px 20px; border-bottom:1px solid var(--border); }
      #${PANEL_ID} .pg-kicker {
        color:#76526f; font-family:var(--mono); font-size:8px; font-weight:800;
        letter-spacing:1.2px; text-transform:uppercase;
      }
      #${PANEL_ID} .pg-title { margin-top:5px; font-size:22px; font-weight:800; }
      #${PANEL_ID} .pg-note { margin-top:5px; color:var(--muted); font-size:10px; line-height:1.55; }
      #${PANEL_ID} .pg-headlines {
        display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; padding:14px;
      }
