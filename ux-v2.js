// ============================================================================
// CFB ANALYTICS — UX + WEATHER ENGINE v1
// Frontend/product layer only.
// Model A projection data remains untouched.
// ============================================================================

(() => {
  "use strict";

  const CONDITIONS_URL = "./data/game_conditions.json";
  const RESULTS_URL = "./data/reports/settled_results.json";

  let gameConditionsData = { games: {} };
  let settledResultsData = { rows: [] };
  let settledResultsByGame = new Map();
  let currentConferenceFilter = "";
  let currentSignalFilter = "";
  let currentConfidenceFilter = "";

  const CONFERENCE_OPTIONS = [
    ["", "All Conferences"],
    ["AAC", "AAC"],
    ["ACC", "ACC"],
    ["BIG TEN", "Big Ten"],
    ["BIG 12", "Big 12"],
    ["CUSA", "CUSA"],
    ["INDEPENDENT", "Independent"],
    ["MAC", "MAC"],
    ["MOUNTAIN WEST", "Mountain West"],
    ["PAC-12", "Pac-12"],
    ["SEC", "SEC"],
    ["SUN BELT", "Sun Belt"],
  ];

  const SIGNAL_OPTIONS = [
    ["", "All Signals"],
    ["ALIGNED", "Aligned"],
    ["SMALL EDGE", "Small Edge"],
    ["PLAY", "Play"],
    ["MATERIAL DISAGREEMENT", "Material Disagreement"],
    ["OUTLIER", "Outlier"],
  ];

  const CONFIDENCE_OPTIONS = [
    ["", "All Confidence"],
    ["DEVELOPING", "Developing"],
    ["VALIDATED", "Validated"],
    ["ESTABLISHED", "Established"],
  ];

  function normalizedConference(value) {
    const text = String(value || "").trim().toUpperCase();

    if (["AAC", "AMERICAN ATHLETIC", "AMERICAN ATHLETIC CONFERENCE"].includes(text)) return "AAC";
    if (["ACC", "ATLANTIC COAST CONFERENCE"].includes(text)) return "ACC";
    if (["BIG TEN", "BIG TEN CONFERENCE", "B1G"].includes(text)) return "BIG TEN";
    if (["BIG 12", "BIG 12 CONFERENCE", "B12"].includes(text)) return "BIG 12";
    if (["CONFERENCE USA", "C-USA", "CUSA"].includes(text)) return "CUSA";
    if (["FBS INDEPENDENTS", "INDEPENDENT", "INDEPENDENTS", "IND."].includes(text)) return "INDEPENDENT";
    if (["MAC", "MID-AMERICAN", "MID-AMERICAN CONFERENCE"].includes(text)) return "MAC";
    if (["MOUNTAIN WEST", "MOUNTAIN WEST CONFERENCE", "MWC"].includes(text)) return "MOUNTAIN WEST";
    if (["PAC-12", "PAC 12", "PAC-12 CONFERENCE"].includes(text)) return "PAC-12";
    if (["SEC", "SOUTHEASTERN CONFERENCE"].includes(text)) return "SEC";
    if (["SUN BELT", "SUN BELT CONFERENCE", "SBC"].includes(text)) return "SUN BELT";

    return text;
  }

  function uTeamLogo(teamName, size="projection") {
    return typeof window.teamLogoMarkup === "function"
      ? window.teamLogoMarkup(teamName, size)
      : "";
  }

  function conditionsForGame(game) {
    return gameConditionsData?.games?.[String(game?.game_id ?? "")] ?? null;
  }

  function indexSettledResults(payload) {
    const rows = Array.isArray(payload?.rows) ? payload.rows : [];
    const grouped = new Map();
    const indexed = new Map();

    rows
      .filter(row => row?.result_settled)
      .sort((a, b) => String(a?.captured_at_utc || "").localeCompare(String(b?.captured_at_utc || "")))
      .forEach(row => {
        const key = String(row?.game_key ?? row?.result_game_id ?? "");
        if (!key) return;
        if (!grouped.has(key)) grouped.set(key, []);
        grouped.get(key).push(row);
      });

    grouped.forEach(gameRows => {
      const official = { ...gameRows[0] };
      const weather = [...gameRows].reverse().find(row => row?.weather_applied);
      if (weather) {
        [
          "public_home_spread", "public_total", "weather_applied",
          "weather_conditions_line", "weather_impact", "weather_total_adjustment",
          "weather_spread_adjustment", "weather_spread_status", "public_margin_error",
          "public_abs_error",
        ].forEach(field => { official[field] = weather[field]; });
      }
      [official.game_key, official.result_game_id]
        .filter(value => value !== null && value !== undefined)
        .forEach(key => indexed.set(String(key), official));
    });

    settledResultsByGame = indexed;
  }

  function settledResultForGame(game) {
    return settledResultsByGame.get(String(game?.game_id ?? "")) ?? null;
  }

  function resultComparison(game) {
    const result = settledResultForGame(game);
    if (!result) return null;
    const modelSpread = Number(result.model_home_spread);
    const marketSpread = Number(result.snapshot_home_spread);
    return {
      disagreement:
        Number.isFinite(modelSpread) && Number.isFinite(marketSpread)
          ? Math.abs(modelSpread - marketSpread)
          : null,
      preferred_side: result.preferred_side ?? null,
      signal: result.signal ?? "NO MARKET",
    };
  }

  function effectiveModelSpread(game) {
    const result = settledResultForGame(game);
    if (hasValue(result?.public_home_spread)) return Number(result.public_home_spread);
    if (hasValue(result?.model_home_spread)) return Number(result.model_home_spread);
    const conditions = conditionsForGame(game);
    if (hasValue(conditions?.adjusted?.home_spread)) {
      return Number(conditions.adjusted.home_spread);
    }
    return game?.projection?.home_spread;
  }

  function effectiveModelTotal(game) {
    const result = settledResultForGame(game);
    if (hasValue(result?.public_total)) return Number(result.public_total);
    if (hasValue(result?.model_total)) return Number(result.model_total);
    const conditions = conditionsForGame(game);
    if (hasValue(conditions?.adjusted?.total)) {
      return Number(conditions.adjusted.total);
    }
    return game?.projection?.total;
  }

  function totalSignalForGame(game) {
    const modelTotal = Number(effectiveModelTotal(game));
    const marketTotal = Number(game?.market?.total);
    if (!Number.isFinite(modelTotal) || !Number.isFinite(marketTotal)) return null;
    const difference = modelTotal - marketTotal;
    const edge = Math.abs(difference);
    if (edge < 4) return null;
    return {
      direction: difference > 0 ? "OVER" : "UNDER",
      edge,
      marketTotal,
      tier: edge >= 7 ? "TOTAL WATCH" : "TOTAL LEAN",
      css: edge >= 7 ? "total-watch" : "total-lean",
    };
  }

  function totalSignalMarkup(game) {
    const signal = totalSignalForGame(game);
    if (!signal) return "";
    return `<div class="total-signal ${signal.css}">${signal.direction} ${formatNumber(signal.marketTotal,1)} · ${signal.tier} BY ${formatNumber(signal.edge,1)}</div>`;
  }

  function effectiveComparison(game) {
    const frozen = resultComparison(game);
    if (frozen) return frozen;

    const marketSpread = game?.market?.home_spread;
    const adjustedSpread = effectiveModelSpread(game);

    if (!hasValue(marketSpread) || !hasValue(adjustedSpread)) {
      return {
        disagreement: null,
        preferred_side: null,
        signal: "NO MARKET",
      };
    }

    const difference = Number(adjustedSpread) - Number(marketSpread);
    const disagreement = Math.abs(difference);

    let signal = "OUTLIER";
    if (disagreement <= 2.5) signal = "ALIGNED";
    else if (disagreement <= 5.0) signal = "SMALL EDGE";
    else if (disagreement <= 7.0) signal = "PLAY";
    else if (disagreement <= 10.0) signal = "MATERIAL DISAGREEMENT";

    const preferredSide =
      Math.abs(difference) < 0.001
        ? null
        : difference < 0
          ? game?.home?.team
          : game?.away?.team;

    return {
      disagreement,
      preferred_side: preferredSide,
      signal,
    };
  }

  function frozenProjectedScore(result) {
    const total = Number(hasValue(result?.public_total) ? result.public_total : result?.model_total);
    const homeSpread = Number(hasValue(result?.public_home_spread) ? result.public_home_spread : result?.model_home_spread);
    if (!Number.isFinite(total) || !Number.isFinite(homeSpread)) return null;
    return {
      home: Math.max(0, Math.round((total - homeSpread) / 2)),
      away: Math.max(0, Math.round((total + homeSpread) / 2)),
    };
  }

  function atsResultLabel(value) {
    if (value === "W") return "ATS WIN";
    if (value === "L") return "ATS LOSS";
    if (value === "P") return "ATS PUSH";
    return "NOT GRADED";
  }

  function totalResultLabel(value) {
    if (value === "W") return "TOTAL WIN";
    if (value === "L") return "TOTAL LOSS";
    if (value === "P") return "TOTAL PUSH";
    return "";
  }

  function atsResultClass(value) {
    if (value === "W") return "result-win";
    if (value === "L") return "result-loss";
    if (value === "P") return "result-push";
    return "result-pending";
  }

  function predictedWinnerCorrect(result) {
    const probability = Number(result?.model_home_win_probability);
    const homePoints = Number(result?.home_points);
    const awayPoints = Number(result?.away_points);
    if (![probability, homePoints, awayPoints].every(Number.isFinite) || homePoints === awayPoints) return null;
    return (probability >= 50) === (homePoints > awayPoints);
  }

  function gameMatchesConference(game) {
    if (!currentConferenceFilter) return true;
    const home = normalizedConference(game?.home?.conference);
    const away = normalizedConference(game?.away?.conference);
    return home === currentConferenceFilter || away === currentConferenceFilter;
  }

  function gameMatchesSignal(game) {
    if (!currentSignalFilter) return true;
    return canonicalSignal(effectiveComparison(game).signal) === currentSignalFilter;
  }

  function gameMatchesConfidence(game) {
    if (!currentConfidenceFilter) return true;
    return signalConfidence(effectiveComparison(game).signal) === currentConfidenceFilter;
  }

  function selectMarkup(id, label, options) {
    return `
      <label class="projection-filter">
        <span class="projection-filter-label">${escapeHtml(label)}</span>
        <select id="${id}" class="projection-filter-select">
          ${options.map(([value, text]) => `
            <option value="${escapeHtml(value)}">${escapeHtml(text)}</option>
          `).join("")}
        </select>
      </label>
    `;
  }

  function installFilterControls() {
    const controls = document.querySelector("#view-projections .projection-controls");
    const searchWrap = controls?.querySelector(".search-wrap");
    if (!controls || !searchWrap || document.getElementById("projection-filter-bar")) return;

    const filterBar = document.createElement("div");
    filterBar.id = "projection-filter-bar";
    filterBar.className = "projection-filter-bar";
    filterBar.innerHTML = `
      ${selectMarkup("conference-filter", "Conference", CONFERENCE_OPTIONS)}
      ${selectMarkup("signal-filter", "Model Signal", SIGNAL_OPTIONS)}
      ${selectMarkup("confidence-filter", "Confidence", CONFIDENCE_OPTIONS)}
      <button id="clear-projection-filters" class="clear-filter-button" type="button">Clear</button>
    `;

    searchWrap.insertAdjacentElement("afterend", filterBar);

    const conference = document.getElementById("conference-filter");
    const signal = document.getElementById("signal-filter");
    const confidence = document.getElementById("confidence-filter");
    const clear = document.getElementById("clear-projection-filters");

    conference?.addEventListener("change", event => {
      currentConferenceFilter = event.target.value;
      renderProjections();
    });

    signal?.addEventListener("change", event => {
      currentSignalFilter = event.target.value;
      renderProjections();
    });

    confidence?.addEventListener("change", event => {
      currentConfidenceFilter = event.target.value;
      renderProjections();
    });

    clear?.addEventListener("click", () => {
      currentConferenceFilter = "";
      currentSignalFilter = "";
      currentConfidenceFilter = "";

      if (conference) conference.value = "";
      if (signal) signal.value = "";
      if (confidence) confidence.value = "";

      const search = document.getElementById("team-search");
      if (search) search.value = "";
      currentSearch = "";
      renderProjections();
    });
  }

  function installStyles() {
    if (document.getElementById("cfb-weather-engine-v1")) return;

    const style = document.createElement("style");
    style.id = "cfb-weather-engine-v1";
    style.textContent = `
      #view-projections .projection-controls {
        display:grid;
        grid-template-columns:minmax(210px, 300px) minmax(0, 1fr);
        gap:10px 14px;
        align-items:end;
      }

      #view-projections .search-wrap { width:100%; }

      .projection-filter-bar {
        display:flex;
        gap:8px;
        align-items:flex-end;
        flex-wrap:wrap;
        min-width:0;
      }

      .projection-filter {
        display:flex;
        flex-direction:column;
        gap:5px;
      }

      .projection-filter-label {
        font-family:var(--mono);
        color:var(--muted);
        font-size:8px;
        letter-spacing:.9px;
        text-transform:uppercase;
        font-weight:700;
      }

      .projection-filter-select,
      .clear-filter-button {
        min-height:38px;
        border:1px solid var(--border);
        background:var(--surface);
        color:var(--text);
        border-radius:9px;
        font-size:11px;
        font-weight:600;
        padding:0 31px 0 11px;
        outline:none;
      }

      .projection-filter-select:focus { border-color:#aeb5b0; }

      .clear-filter-button {
        cursor:pointer;
        padding:0 13px;
        color:var(--muted);
      }

      .clear-filter-button:hover {
        color:var(--text);
        border-color:var(--border-dark);
      }

      #view-projections .projection-summary {
        grid-column:1 / -1;
        text-align:right;
      }

      .projection-summary .summary-filter {
        border:0;
        background:transparent;
        padding:0;
        font:inherit;
        cursor:pointer;
      }

      .projection-summary .summary-filter:hover {
        text-decoration:underline;
        text-underline-offset:3px;
      }

      .projection-table thead th {
        position:static;
        top:auto;
        z-index:auto;
        background:#f7f7f5;
        box-shadow:0 1px 0 var(--border);
      }

      .projection-table tbody tr.game-row {
        transition:background .12s ease, box-shadow .12s ease;
      }

      .projection-table tbody tr.game-row:hover {
        background:#f7f8f5;
        box-shadow:inset 3px 0 0 var(--green);
      }

      .weather-adjusted-dot {
        display:inline-block;
        width:6px;
        height:6px;
        border-radius:999px;
        background:#355f91;
        margin-left:5px;
        vertical-align:1px;
      }

      .total-signal {
        display:inline-flex; margin-top:5px; border-radius:999px;
        padding:3px 7px; font-family:var(--mono); font-size:8px;
        font-weight:700; letter-spacing:.25px; white-space:nowrap;
      }
      .total-signal.total-lean {
        color:#355f91; background:#eef3f8; border:1px solid #b8c9dc;
      }
      .total-signal.total-watch {
        color:#176b55; background:#e8f3ef; border:1px solid #9fcbbb;
      }

      .projected-score-card {
        grid-column:1 / -1;
        background:var(--surface);
        border:1px solid var(--border-dark);
        border-radius:12px;
        padding:18px;
      }

      .projected-score-title,
      .weather-audit-label {
        font-family:var(--mono);
        color:var(--muted);
        font-size:9px;
        letter-spacing:1.2px;
        text-transform:uppercase;
      }

      .projected-score-line {
        display:grid;
        grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);
        gap:14px;
        align-items:center;
        margin-top:13px;
      }

      .projected-team { min-width:0; }
      .projected-team:last-child { text-align:right; }

      .projected-team-name {
        color:var(--muted);
        font-size:11px;
        margin-bottom:3px;
        white-space:nowrap;
        overflow:hidden;
        text-overflow:ellipsis;
      }

      .projected-team-score {
        font-size:34px;
        line-height:1;
        font-weight:800;
        letter-spacing:-1px;
      }

      .projected-score-separator {
        color:var(--muted);
        font-family:var(--mono);
        font-size:11px;
      }

      .projected-score-meta {
        margin-top:13px;
        padding-top:11px;
        border-top:1px solid #eeeeeb;
        display:flex;
        gap:10px 18px;
        flex-wrap:wrap;
        color:var(--muted);
        font-family:var(--mono);
        font-size:10px;
      }

      .conditions-panel {
        margin-bottom:18px;
        background:var(--surface);
        border:1px solid var(--border);
        border-radius:12px;
        overflow:hidden;
      }

      .conditions-panel-header {
        padding:13px 16px;
        border-bottom:1px solid var(--border);
        display:flex;
        justify-content:space-between;
        gap:12px;
        align-items:center;
      }

      .conditions-title {
        font-family:var(--mono);
        color:var(--muted);
        font-size:9px;
        letter-spacing:1.2px;
        text-transform:uppercase;
      }

      .conditions-body { padding:16px; }

      .conditions-main {
        display:flex;
        align-items:center;
        gap:12px;
        flex-wrap:wrap;
      }

      .conditions-line {
        font-size:16px;
        font-weight:700;
        letter-spacing:-.2px;
      }

      .conditions-impact {
        display:inline-flex;
        align-items:center;
        justify-content:center;
        border-radius:999px;
        padding:6px 10px;
        font-family:var(--mono);
        font-size:9px;
        font-weight:700;
        letter-spacing:.4px;
        text-transform:uppercase;
      }

      .conditions-impact.minimal {
        background:#f4f4f2;
        color:var(--muted);
        border:1px solid var(--border);
      }

      .conditions-impact.moderate {
        background:#f8e7a1;
        color:#4e3b00;
        border:1px solid #d9bd53;
      }

      .conditions-impact.significant {
        background:#fff0df;
        color:#9a4d00;
        border:1px solid #e6b77d;
      }

      .conditions-note {
        margin-top:9px;
        color:var(--muted);
        font-size:11px;
        line-height:1.55;
      }

      .weather-output-grid {
        display:grid;
        grid-template-columns:repeat(3,minmax(0,1fr));
        gap:8px;
        margin-top:14px;
      }

      .weather-output-card {
        border:1px solid var(--border);
        border-radius:9px;
        padding:11px;
      }

      .weather-output-value {
        font-family:var(--mono);
        font-size:14px;
        font-weight:700;
        margin-top:5px;
      }

      .weather-audit {
        margin-top:14px;
        border-top:1px solid #eeeeeb;
        padding-top:12px;
      }

      .weather-audit-row {
        display:grid;
        grid-template-columns:minmax(0,1fr) auto;
        gap:14px;
        padding:6px 0;
        font-size:10px;
      }

      .weather-audit-row span:first-child { color:var(--muted); }
      .weather-audit-row span:last-child { font-family:var(--mono); font-weight:600; }

      .weather-source {
        margin-top:11px;
        color:var(--muted);
        font-size:9px;
        line-height:1.5;
      }

      .weather-source a {
        color:inherit;
        text-decoration:underline;
        text-underline-offset:2px;
      }

      .completed-row { background:#fafaf8; }
      .completed-row .team-line { align-items:center; }
      .final-score {
        margin-left:auto;
        font-family:var(--mono);
        font-size:15px;
        font-weight:800;
        color:var(--ink);
      }
      .final-label {
        display:inline-flex;
        margin-top:6px;
        font-family:var(--mono);
        font-size:9px;
        font-weight:800;
        letter-spacing:1px;
        color:var(--muted);
      }
      .result-badge {
        display:inline-flex;
        justify-content:center;
        border-radius:999px;
        padding:5px 8px;
        font-family:var(--mono);
        font-size:9px;
        font-weight:800;
        letter-spacing:.5px;
        white-space:nowrap;
      }
      .result-win { background:#dff3e5; color:#146b32; border:1px solid #9fd1ad; }
      .result-loss { background:#fde5e2; color:#a22b20; border:1px solid #e9aaa4; }
      .result-push { background:#f2eee2; color:#6b5a25; border:1px solid #d8cda9; }
      .result-pending { background:#f4f4f2; color:var(--muted); border:1px solid var(--border); }
      .final-result-panel {
        margin-bottom:18px;
        padding:18px;
        border:1px solid var(--border);
        border-radius:12px;
        background:var(--surface);
        box-shadow:inset 4px 0 0 var(--ink);
      }
      .final-result-title {
        font-family:var(--mono);
        color:var(--muted);
        font-size:9px;
        letter-spacing:1.2px;
        text-transform:uppercase;
      }
      .final-result-score {
        margin-top:8px;
        font-size:24px;
        font-weight:800;
        letter-spacing:-.5px;
      }
      .final-result-grid {
        display:grid;
        grid-template-columns:repeat(4,minmax(0,1fr));
        gap:9px;
        margin-top:14px;
      }
      .final-result-item {
        padding:10px;
        border:1px solid var(--border);
        border-radius:9px;
        background:#fafaf8;
      }
      .final-result-item span { display:block; }
      .final-result-item span:first-child {
        color:var(--muted);
        font-family:var(--mono);
        font-size:8px;
        letter-spacing:.7px;
        text-transform:uppercase;
      }
      .final-result-item span:last-child { margin-top:5px; font-size:12px; font-weight:700; }

      .testing-notice-bar {
        display:grid;
        grid-template-columns:auto minmax(0,1fr);
        align-items:center;
        gap:16px;
        margin:18px 0;
        padding:13px 18px;
        border:1px solid #d9bd53;
        border-radius:10px;
        background:#fff9df;
        color:#4e3b00;
        font-size:12px;
        line-height:1.45;
      }
      .testing-notice-bar strong {
        display:flex;
        align-items:center;
        align-self:stretch;
        padding-right:16px;
        border-right:1px solid rgba(126,94,0,.25);
        font-family:var(--mono);
        font-size:10px;
        letter-spacing:.75px;
        text-transform:uppercase;
        white-space:nowrap;
      }
      .testing-notice-bar span {
        display:block;
        text-align:left;
      }
      .testing-modal-backdrop {
        position:fixed;
        inset:0;
        z-index:9999;
        display:flex;
        align-items:center;
        justify-content:center;
        padding:20px;
        background:rgba(10,18,15,.72);
        backdrop-filter:blur(5px);
      }
      .testing-modal {
        width:min(520px,100%);
        padding:26px;
        border:1px solid rgba(255,255,255,.18);
        border-radius:16px;
        background:var(--surface);
        box-shadow:0 24px 80px rgba(0,0,0,.32);
      }
      .testing-modal-kicker {
        color:var(--green);
        font-family:var(--mono);
        font-size:10px;
        font-weight:800;
        letter-spacing:1.2px;
        text-transform:uppercase;
      }
      .testing-modal h2 {
        margin:8px 0 10px;
        font-size:26px;
        letter-spacing:-.5px;
      }
      .testing-modal p {
        margin:0;
        color:var(--muted);
        font-size:13px;
        line-height:1.65;
      }
      .testing-modal-points {
        margin:16px 0 20px;
        padding:13px 14px;
        border:1px solid var(--border);
        border-radius:10px;
        background:#fafaf8;
        font-size:11px;
        line-height:1.7;
      }
      .testing-modal-button {
        width:100%;
        border:0;
        border-radius:9px;
        padding:12px 16px;
        background:var(--green);
        color:#fff;
        cursor:pointer;
        font-family:var(--mono);
        font-size:10px;
        font-weight:800;
        letter-spacing:.7px;
        text-transform:uppercase;
      }
      .testing-modal-button:hover { filter:brightness(.94); }

      @media (max-width:900px) {
        #view-projections .projection-controls {
          grid-template-columns:1fr;
        }

        #view-projections .projection-summary {
          grid-column:auto;
          text-align:left;
        }

        .weather-output-grid { grid-template-columns:1fr; }
        .final-result-grid { grid-template-columns:1fr 1fr; }
      }

      @media (max-width:600px) {
        .testing-notice-bar {
          grid-template-columns:1fr;
          gap:7px;
          padding:13px 14px;
        }
        .testing-notice-bar strong {
          padding:0 0 7px;
          border-right:0;
          border-bottom:1px solid rgba(126,94,0,.25);
        }

        .projection-filter-bar {
          display:grid;
          grid-template-columns:1fr 1fr;
          width:100%;
        }

        .projection-filter:nth-child(3) { grid-column:1 / -1; }

        .projection-filter-select,
        .clear-filter-button { width:100%; }

        .projected-team-score { font-size:29px; }
      }
    `;

    document.head.appendChild(style);
  }

  function conditionImpactClass(value) {
    const impact = String(value || "Minimal").toLowerCase();
    if (impact === "significant") return "significant";
    if (impact === "moderate") return "moderate";
    return "minimal";
  }

  function installTestingNotice() {
    const projectionsView = document.getElementById("view-projections");
    const controls = projectionsView?.querySelector(".projection-controls");
    if (controls && !document.getElementById("testing-notice-bar")) {
      controls.insertAdjacentHTML(
        "beforebegin",
        `<div class="testing-notice-bar" id="testing-notice-bar">
          <strong>Projections: Live Testing</strong>
          <span>Week 1 begins prospective validation. Model lines, projected scores and signals are experimental—not betting recommendations. Team data, advanced metrics and power ratings remain available for research.</span>
        </div>`,
      );
    }

    const storageKey = "cfb-model-testing-notice-v1";
    try {
      if (window.localStorage.getItem(storageKey) === "accepted") return;
    } catch (_) {
      // Storage can be unavailable in strict/private browser modes.
    }

    const backdrop = document.createElement("div");
    backdrop.className = "testing-modal-backdrop";
    backdrop.setAttribute("role", "dialog");
    backdrop.setAttribute("aria-modal", "true");
    backdrop.setAttribute("aria-labelledby", "testing-modal-title");
    backdrop.innerHTML = `
      <div class="testing-modal">
        <div class="testing-modal-kicker">2026 Model · Public Testing</div>
        <h2 id="testing-modal-title">Welcome to The Hammer Index</h2>
        <p>
          Cade Harper's college football data platform is open for research. Model spreads, projected scores
          and signals are beginning prospective Week 1 validation and should not
          be treated as established betting recommendations.
        </p>
        <div class="testing-modal-points">
          <strong>Available now:</strong> team data, advanced metrics, power ratings,
          matchup projections, weather context and transparently tracked results.
        </div>
        <button class="testing-modal-button" type="button">Enter Site</button>
      </div>
    `;

    const close = () => {
      try { window.localStorage.setItem(storageKey, "accepted"); } catch (_) {}
      backdrop.remove();
      document.body.style.overflow = "";
    };

    backdrop.querySelector("button").addEventListener("click", close);
    backdrop.addEventListener("click", event => {
      if (event.target === backdrop) close();
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && document.body.contains(backdrop)) close();
    });

    document.body.appendChild(backdrop);
    document.body.style.overflow = "hidden";
    backdrop.querySelector("button").focus();
  }

  function projectedScore(game) {
    const total = Number(effectiveModelTotal(game));
    const homeSpread = Number(effectiveModelSpread(game));

    if (!Number.isFinite(total) || !Number.isFinite(homeSpread)) return null;

    const home = (total - homeSpread) / 2;
    const away = (total + homeSpread) / 2;

    return {
      away: Math.max(0, Math.round(away)),
      home: Math.max(0, Math.round(home)),
      total,
      homeSpread,
    };
  }

  function scoreCardMarkup(game) {
    const score = projectedScore(game);
    if (!score) return "";

    const awayName = game?.away?.team ?? "Away";
    const homeName = game?.home?.team ?? "Home";
    const conditions = conditionsForGame(game);
    const weatherAdjusted =
      hasValue(conditions?.adjustments?.total_points) &&
      Number(conditions.adjustments.total_points) !== 0;

    return `
      <div class="projected-score-card">
        <div class="projected-score-title">Projected Final Score</div>
        <div class="projected-score-line">
          <div class="projected-team">
            <div class="projected-team-name">${escapeHtml(awayName)}</div>
            <div class="projected-team-score">${score.away}</div>
          </div>
          <div class="projected-score-separator">FINAL</div>
          <div class="projected-team">
            <div class="projected-team-name">${escapeHtml(homeName)}</div>
            <div class="projected-team-score">${score.home}</div>
          </div>
        </div>
        <div class="projected-score-meta">
          <span>Adjusted fair spread ${escapeHtml(favoredLine(homeName, awayName, score.homeSpread))}</span>
          <span>Adjusted projected total ${formatNumber(score.total, 1)}</span>
          <span>${weatherAdjusted ? "Weather Engine v1 applied" : "No total weather adjustment"}</span>
        </div>
      </div>
    `;
  }

  function finalResultMarkup(game) {
    const result = settledResultForGame(game);
    if (!result) return "";

    const awayName = result.away_team || game?.away?.team || "Away";
    const homeName = result.home_team || game?.home?.team || "Home";
    const awayPoints = Number(result.away_points);
    const homePoints = Number(result.home_points);
    const frozenScore = frozenProjectedScore(result);
    const winnerCorrect = predictedWinnerCorrect(result);
    const snapshotSide = result.preferred_side && hasValue(result.snapshot_home_spread)
      ? marketSideForTeam(result.preferred_side, homeName, awayName, result.snapshot_home_spread)
      : "No graded side";
    const close = hasValue(result.closing_home_spread)
      ? favoredLine(homeName, awayName, result.closing_home_spread)
      : "Not captured";

    return `
      <div class="final-result-panel">
        <div class="final-result-title">Official Result · Frozen Pregame Audit</div>
        <div class="final-result-score">
          FINAL — ${escapeHtml(awayName)} ${Number.isFinite(awayPoints) ? awayPoints : "—"},
          ${escapeHtml(homeName)} ${Number.isFinite(homePoints) ? homePoints : "—"}
        </div>
        <div style="margin-top:10px;">
          <span class="result-badge ${atsResultClass(result.ats_result)}">${escapeHtml(atsResultLabel(result.ats_result))}</span>
        </div>
        <div class="final-result-grid">
          <div class="final-result-item">
            <span>Frozen public score</span>
            <span>${frozenScore ? `${escapeHtml(awayName)} ${frozenScore.away}–${frozenScore.home} ${escapeHtml(homeName)}` : "Not captured"}</span>
          </div>
          <div class="final-result-item">
            <span>Model side</span>
            <span>${escapeHtml(snapshotSide)}</span>
          </div>
          <div class="final-result-item">
            <span>Closing line</span>
            <span>${escapeHtml(close)}</span>
          </div>
          <div class="final-result-item">
            <span>Predicted winner</span>
            <span>${winnerCorrect === null ? "Not captured" : winnerCorrect ? "Correct" : "Incorrect"}</span>
          </div>
          <div class="final-result-item">
            <span>Margin error</span>
            <span>${hasValue(result.public_abs_error ?? result.model_abs_error) ? `${formatNumber(result.public_abs_error ?? result.model_abs_error, 1)} pts` : "—"}</span>
          </div>
          <div class="final-result-item">
            <span>Pregame signal</span>
            <span>${escapeHtml(displayStatus(result.signal))}</span>
          </div>
          <div class="final-result-item">
            <span>Snapshot line</span>
            <span>${escapeHtml(favoredLine(homeName, awayName, result.snapshot_home_spread))}</span>
          </div>
          <div class="final-result-item">
            <span>Weather snapshot</span>
            <span>${result.weather_applied ? escapeHtml(result.weather_conditions_line || "Applied") : "No adjustment captured"}</span>
          </div>
        </div>
      </div>
    `;
  }

  function adjustmentDisplay(value, suffix = " pts") {
    if (!hasValue(value)) return "—";
    const number = Number(value);
    if (Math.abs(number) < 0.001) return `0.0${suffix}`;
    return `${formatSigned(number, 1)}${suffix}`;
  }

  function conditionsMarkup(game) {
    const conditions = conditionsForGame(game);

    if (!conditions) {
      return `
        <div class="conditions-panel">
          <div class="conditions-panel-header">
            <div class="conditions-title">Game Conditions</div>
            <span class="conditions-impact minimal">Pending</span>
          </div>
          <div class="conditions-body">
            <div class="conditions-line">Forecast not available yet</div>
            <div class="conditions-note">
              Weather Engine v1 will populate when venue and forecast data are available.
            </div>
            <div class="weather-source">
              Model A remains untouched when forecast data is unavailable.
            </div>
          </div>
        </div>
      `;
    }

    const impact = conditions.impact || "Minimal";
    const css = conditionImpactClass(impact);
    const indoor = Boolean(conditions.indoor);

    let line = conditions.conditions_line || "Forecast unavailable";
    if (indoor) line = "Indoor · Climate controlled · Weather Neutral";

    const baseSpread = conditions?.baseline?.home_spread;
    const baseTotal = conditions?.baseline?.total;
    const adjustedSpread = conditions?.adjusted?.home_spread;
    const adjustedTotal = conditions?.adjusted?.total;
    const totalAdjustment = conditions?.adjustments?.total_points;
    const spreadAdjustment = conditions?.adjustments?.home_spread_points;
    const spreadStatus = conditions?.spread_logic?.status || "LOCKED";
    const spreadReason = conditions?.spread_logic?.reason || "Awaiting mature 2026 tendency data.";
    const breakdown = conditions?.adjustments?.breakdown ?? {};

    const homeName = game?.home?.team ?? "Home";
    const awayName = game?.away?.team ?? "Away";

    return `
      <div class="conditions-panel">
        <div class="conditions-panel-header">
          <div class="conditions-title">Game Conditions + Weather Engine v1</div>
          <span class="conditions-impact ${css}">${escapeHtml(impact)}</span>
        </div>

        <div class="conditions-body">
          <div class="conditions-main">
            <div class="conditions-line">${escapeHtml(line)}</div>
          </div>

          <div class="conditions-note">
            ${escapeHtml(conditions.note || "No material weather effect is projected.")}
          </div>

          <div class="weather-output-grid">
            <div class="weather-output-card">
              <div class="weather-audit-label">Weather Adjustment</div>
              <div class="weather-output-value">${escapeHtml(adjustmentDisplay(totalAdjustment))} total</div>
            </div>

            <div class="weather-output-card">
              <div class="weather-audit-label">Adjusted Total</div>
              <div class="weather-output-value">${formatNumber(adjustedTotal, 1)}</div>
            </div>

            <div class="weather-output-card">
              <div class="weather-audit-label">Spread Adjustment</div>
              <div class="weather-output-value">
                ${spreadStatus === "LOCKED"
                  ? "Locked"
                  : escapeHtml(adjustmentDisplay(spreadAdjustment))}
              </div>
            </div>
          </div>

          <div class="weather-audit">
            <div class="weather-audit-label">Audit Trail</div>

            <div class="weather-audit-row">
              <span>Model A fair spread</span>
              <span>${escapeHtml(favoredLine(homeName, awayName, baseSpread))}</span>
            </div>
            <div class="weather-audit-row">
              <span>Base projected total</span>
              <span>${formatNumber(baseTotal, 1)}</span>
            </div>
            <div class="weather-audit-row">
              <span>Wind</span>
              <span>${escapeHtml(adjustmentDisplay(breakdown.wind))}</span>
            </div>
            <div class="weather-audit-row">
              <span>Precipitation</span>
              <span>${escapeHtml(adjustmentDisplay(breakdown.precipitation))}</span>
            </div>
            <div class="weather-audit-row">
              <span>Temperature</span>
              <span>${escapeHtml(adjustmentDisplay(breakdown.temperature))}</span>
            </div>
            <div class="weather-audit-row">
              <span>Total weather adjustment</span>
              <span>${escapeHtml(adjustmentDisplay(totalAdjustment))}</span>
            </div>
            <div class="weather-audit-row">
              <span>Adjusted projected total</span>
              <span>${formatNumber(adjustedTotal, 1)}</span>
            </div>
            <div class="weather-audit-row">
              <span>Spread weather adjustment</span>
              <span>
                ${spreadStatus === "LOCKED"
                  ? `Locked — ${escapeHtml(spreadReason)}`
                  : escapeHtml(adjustmentDisplay(spreadAdjustment))}
              </span>
            </div>
            <div class="weather-audit-row">
              <span>Adjusted fair spread</span>
              <span>${escapeHtml(favoredLine(homeName, awayName, adjustedSpread))}</span>
            </div>
          </div>

          <div class="weather-source">
            Model A baseline remains stored unchanged for tracking and audit.
            Weather-adjusted spread feeds the public Model Signal only when the
            tendency-data gate is unlocked.
            · <a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Weather data by Open-Meteo</a>
          </div>
        </div>
      </div>
    `;
  }

  function setSignalFilter(signalName) {
    currentSignalFilter = signalName;
    const select = document.getElementById("signal-filter");
    if (select) select.value = signalName;
    renderProjections();
  }

  function signalBoardPriority(game) {
    const signal = canonicalSignal(effectiveComparison(game).signal);
    return {
      "PLAY": 5,
      "SMALL EDGE": 4,
      "ALIGNED": 3,
      "MATERIAL DISAGREEMENT": 2,
      "OUTLIER": 1,
      "NO MARKET": 0,
    }[signal] ?? 0;
  }

  projectionGamesForCurrentView = function projectionGamesForCurrentViewWeatherV1() {
    return projections
      .filter(game => {
        if (currentWeek !== null && Number(game.week) !== Number(currentWeek)) return false;

        if (currentSearch) {
          const query = currentSearch.toLowerCase();
          const home = game?.home?.team?.toLowerCase() ?? "";
          const away = game?.away?.team?.toLowerCase() ?? "";
          if (!home.includes(query) && !away.includes(query)) return false;
        }

        if (!gameMatchesConference(game)) return false;
        if (!gameMatchesSignal(game)) return false;
        if (!gameMatchesConfidence(game)) return false;

        return true;
      })
      .sort((a, b) => {
        const aFinal = settledResultForGame(a) ? 1 : 0;
        const bFinal = settledResultForGame(b) ? 1 : 0;
        if (aFinal !== bFinal) return aFinal - bFinal;

        const aPriority = signalBoardPriority(a);
        const bPriority = signalBoardPriority(b);
        if (bPriority !== aPriority) return bPriority - aPriority;

        const aDisagreement = effectiveComparison(a).disagreement ?? -1;
        const bDisagreement = effectiveComparison(b).disagreement ?? -1;

        if (bDisagreement !== aDisagreement) return bDisagreement - aDisagreement;

        return (
          new Date(a.start_date || 0).getTime() -
          new Date(b.start_date || 0).getTime()
        );
      });
  };

  function renderCompletedProjectionRow(game, result) {
    const homeName = result.home_team || game?.home?.team || "Unknown";
    const awayName = result.away_team || game?.away?.team || "Unknown";
    const homePoints = Number(result.home_points);
    const awayPoints = Number(result.away_points);
    const frozenScore = frozenProjectedScore(result);
    const confidence = signalConfidence(result.signal);
    const preferredLine = result.preferred_side && hasValue(result.snapshot_home_spread)
      ? marketSideForTeam(result.preferred_side, homeName, awayName, result.snapshot_home_spread)
      : "No graded side";
    const close = hasValue(result.closing_home_spread)
      ? shortSpread(result.closing_home_spread)
      : "—";
    const winnerCorrect = predictedWinnerCorrect(result);
    const gameId = String(game.game_id ?? "");

    return `
      <tr class="game-row completed-row" onclick="openMatchup('${escapeJsString(gameId)}')">
        <td class="matchup-cell">
          <div class="team-line">
            ${uTeamLogo(awayName)}<span class="team-name">${escapeHtml(awayName)}</span>
            <span class="final-score">${Number.isFinite(awayPoints) ? awayPoints : "—"}</span>
          </div>
          <div class="team-line">
            <span class="at-symbol">@</span>
            ${uTeamLogo(homeName)}<span class="team-name">${escapeHtml(homeName)}</span>
            <span class="final-score">${Number.isFinite(homePoints) ? homePoints : "—"}</span>
          </div>
          <span class="final-label">FINAL</span>
        </td>
        <td>
          <div class="line-primary">${escapeHtml(shortSpread(result.public_home_spread ?? result.model_home_spread))}</div>
          <div class="line-secondary">Frozen public line</div>
        </td>
        <td>
          <div class="line-primary">${escapeHtml(close)}</div>
          <div class="line-secondary">${hasValue(result.closing_home_spread) ? "Closing line" : `Snapshot ${escapeHtml(shortSpread(result.snapshot_home_spread))}`}</div>
        </td>
        <td>
          <div class="line-primary">${frozenScore ? `${frozenScore.away}–${frozenScore.home}` : "—"}</div>
          <div class="line-secondary">Frozen projected score</div>
          ${result.total_result ? `<span class="result-badge ${atsResultClass(result.total_result)}" style="margin-top:5px">${escapeHtml(totalResultLabel(result.total_result))}</span>` : ""}
        </td>
        <td class="disagreement">
          <span class="result-badge ${atsResultClass(result.ats_result)}">${escapeHtml(atsResultLabel(result.ats_result))}</span>
          <div class="disagreement-note">${escapeHtml(preferredLine)}</div>
        </td>
        <td class="status-cell">
          <span class="status ${statusClass(result.signal)}">${escapeHtml(displayStatus(result.signal))}</span>
        </td>
        <td class="status-cell">
          <span class="status ${confidenceClass(confidence)}">${escapeHtml(confidence)}</span>
          <div class="signal-record">Winner ${winnerCorrect === null ? "—" : winnerCorrect ? "correct" : "incorrect"} · ${hasValue(result.public_abs_error ?? result.model_abs_error) ? `${formatNumber(result.public_abs_error ?? result.model_abs_error, 1)} pt margin error` : "error pending"}</div>
        </td>
      </tr>
    `;
  }

  renderProjectionRow = function renderProjectionRowWeatherV1(game) {
    const settled = settledResultForGame(game);
    if (settled) return renderCompletedProjectionRow(game, settled);

    const homeName = game?.home?.team ?? "Unknown";
    const awayName = game?.away?.team ?? "Unknown";

    const homeRank = game?.home?.power_rating_rank;
    const awayRank = game?.away?.power_rating_rank;

    const modelSpread = effectiveModelSpread(game);
    const modelTotal = effectiveModelTotal(game);

    const marketSpread = game?.market?.home_spread;
    const marketTotal = game?.market?.total;
    const bookmaker = game?.market?.bookmaker;

    const comparison = effectiveComparison(game);
    const disagreement = comparison.disagreement;
    const preferred = comparison.preferred_side;
    const status = comparison.signal;
    const confidence = signalConfidence(status);
    const cssStatus = statusClass(status);
    const confidenceCss = confidenceClass(confidence);

    const conditions = conditionsForGame(game);
    const spreadWeatherApplied =
      conditions?.spread_logic?.status === "ACTIVE" &&
      hasValue(conditions?.adjustments?.home_spread_points) &&
      Math.abs(Number(conditions.adjustments.home_spread_points)) > 0.001;

    const disagreementNote = hasValue(disagreement)
      ? (preferred ? `Model favors ${preferred}` : "Model agrees with market")
      : "No market line";

    const gameId = String(game.game_id ?? "");

    return `
      <tr class="game-row" onclick="openMatchup('${escapeJsString(gameId)}')">
        <td class="matchup-cell">
          <div class="team-line">
            ${uTeamLogo(awayName)}
            <span class="team-name" onclick="event.stopPropagation(); openDossier('${escapeJsString(awayName)}');">
              ${escapeHtml(awayName)}
            </span>
            <span class="team-meta">${awayRank ? `#${awayRank}` : ""}</span>
          </div>

          <div class="team-line">
            <span class="at-symbol">@</span>
            ${uTeamLogo(homeName)}
            <span class="team-name" onclick="event.stopPropagation(); openDossier('${escapeJsString(homeName)}');">
              ${escapeHtml(homeName)}
            </span>
            <span class="team-meta">${homeRank ? `#${homeRank}` : ""}</span>
          </div>

          <div class="team-meta" style="margin-top:5px;">
            ${escapeHtml(gameDateText(game.start_date))}
          </div>
        </td>

        <td>
          <div class="line-primary">
            ${escapeHtml(shortSpread(modelSpread))}
            ${spreadWeatherApplied ? `<span class="weather-adjusted-dot" title="Weather-adjusted spread"></span>` : ""}
          </div>
          <div class="line-secondary">
            ${spreadWeatherApplied ? "Weather-adjusted fair line" : `${escapeHtml(homeName)} home line`}
          </div>
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
              : "Adjusted projected total"}
          </div>
          ${totalSignalMarkup(game)}
        </td>

        <td class="disagreement">
          <div class="disagreement-number ${cssStatus}">
            ${hasValue(disagreement) ? `${formatNumber(disagreement, 1)} pts` : "—"}
          </div>
          <div class="disagreement-note">${escapeHtml(disagreementNote)}</div>
        </td>

        <td class="status-cell">
          <span class="status ${cssStatus}">${escapeHtml(displayStatus(status))}</span>
        </td>

        <td class="status-cell">
          <span class="status ${confidenceCss}">${escapeHtml(confidence)}</span>
          <div class="signal-record">
            ${escapeHtml(signalRecordText(status))} · ${escapeHtml(signalAtsText(status))}
          </div>
        </td>
      </tr>
    `;
  };

  renderProjections = function renderProjectionsWeatherV1() {
    const container = document.getElementById("projections-container");
    const summary = document.getElementById("projection-summary");
    if (!container) return;

    const games = projectionGamesForCurrentView();
    const marketGames = games.filter(game => hasValue(game?.market?.home_spread));
    const completedGames = games.filter(game => settledResultForGame(game));

    const countCanonical = signal =>
      games.filter(game => canonicalSignal(effectiveComparison(game).signal) === signal).length;

    const material = countCanonical("MATERIAL DISAGREEMENT");
    const plays = countCanonical("PLAY");
    const smallEdges = countCanonical("SMALL EDGE");
    const outliers = countCanonical("OUTLIER");
    const totalWatches = games.filter(game => totalSignalForGame(game)?.tier === "TOTAL WATCH").length;
    const totalLeans = games.filter(game => totalSignalForGame(game)?.tier === "TOTAL LEAN").length;

    if (summary) {
      summary.innerHTML = `
        ${games.length} games
        · ${completedGames.length} final
        · ${marketGames.length} lined
        · <button class="summary-filter summary-play" onclick="setSignalFilter('PLAY')">${plays} plays</button>
        · <button class="summary-filter summary-small" onclick="setSignalFilter('SMALL EDGE')">${smallEdges} small edges</button>
        · <button class="summary-filter summary-material" onclick="setSignalFilter('MATERIAL DISAGREEMENT')">${material} material disagreements</button>
        ${outliers ? `· <button class="summary-filter summary-outlier" onclick="setSignalFilter('OUTLIER')">${outliers} outliers</button>` : ""}
        · <span class="summary-small">${totalWatches} total watches</span>
        · <span>${totalLeans} total leans</span>
      `;
    }

    if (!games.length) {
      container.innerHTML = `<div class="empty-state">No games match the selected week or filters.</div>`;
      return;
    }

    container.innerHTML = `
      <table class="projection-table">
        <thead>
          <tr>
            <th>Matchup</th>
            <th>Fair Line</th>
            <th>Market</th>
            <th>Total</th>
            <th class="align-right">Model Edge</th>
            <th class="align-right">Model Signal</th>
            <th class="align-right">Signal Confidence</th>
          </tr>
        </thead>
        <tbody>${games.map(renderProjectionRow).join("")}</tbody>
      </table>
    `;
  };

  const baseRenderMatchup = renderMatchup;

  renderMatchup = function renderMatchupWeatherV1(game) {
    // Render existing Model A matchup page first.
    baseRenderMatchup(game);

    const container = document.getElementById("matchup-container");
    if (!container) return;

    const conditions = conditionsForGame(game);
    const settled = settledResultForGame(game);
    const comparison = effectiveComparison(game);
    const adjustedSpread = effectiveModelSpread(game);
    const adjustedTotal = effectiveModelTotal(game);

    // Total weather adjustments are independent of the directional spread gate.
    // Keep the headline total in sync whenever Weather Engine data is available.
    const totalCard = container.querySelector(".analysis-grid .analysis-card:nth-child(3) .analysis-value");
    if (totalCard && hasValue(adjustedTotal)) {
      totalCard.textContent = formatNumber(adjustedTotal, 1);
      const totalSignal = totalSignalForGame(game);
      if (totalSignal) {
        totalCard.insertAdjacentHTML(
          "afterend",
          `<div class="total-signal ${totalSignal.css}">${totalSignal.direction} ${formatNumber(totalSignal.marketTotal,1)} · ${totalSignal.tier} BY ${formatNumber(totalSignal.edge,1)}</div>`,
        );
      }
    }

    // If a directional spread weather adjustment is active, update the headline
    // fair-line/signal display while leaving the deeper Model A projection build intact.
    if (
      conditions?.spread_logic?.status === "ACTIVE" &&
      hasValue(conditions?.adjustments?.home_spread_points) &&
      Math.abs(Number(conditions.adjustments.home_spread_points)) > 0.001
    ) {
      const homeName = game?.home?.team ?? "Home";
      const awayName = game?.away?.team ?? "Away";
      const status = comparison.signal;
      const confidence = signalConfidence(status);
      const statusCss = statusClass(status);
      const confidenceCss = confidenceClass(confidence);
      const edgeClass = statusEdgeClass(status);
      const preferred = comparison.preferred_side;
      const marketSpread = game?.market?.home_spread;

      const fairLineCard = container.querySelector(".analysis-grid .analysis-card:nth-child(1) .analysis-value");
      if (fairLineCard) fairLineCard.textContent = favoredLine(homeName, awayName, adjustedSpread);

      const signalCard = container.querySelector(".analysis-grid .analysis-card:nth-child(4) .analysis-value");
      if (signalCard) {
        signalCard.textContent = hasValue(comparison.disagreement)
          ? `${formatNumber(comparison.disagreement, 1)} pts`
          : "—";
        signalCard.className = `analysis-value ${edgeClass}`;
      }

      const banners = container.querySelectorAll(".model-edge-banner .status");
      if (banners[0]) {
        banners[0].className = `status ${statusCss}`;
        banners[0].textContent = displayStatus(status);
      }
      if (banners[1]) {
        banners[1].className = `status ${confidenceCss}`;
        banners[1].textContent = confidence;
      }

      const edgeSide = container.querySelector(".model-edge-side");
      if (edgeSide && preferred && hasValue(marketSpread)) {
        edgeSide.textContent = marketSideForTeam(preferred, homeName, awayName, marketSpread);
        edgeSide.className = `model-edge-side ${edgeClass}`;
      }
    }

    const grid = container.querySelector(".analysis-grid");
    if (grid) grid.insertAdjacentHTML("afterbegin", scoreCardMarkup(game));

    const layout = container.querySelector(".analysis-layout");
    if (layout) {
      if (!settled || conditions) layout.insertAdjacentHTML("beforebegin", conditionsMarkup(game));
      if (settled) layout.insertAdjacentHTML("beforebegin", finalResultMarkup(game));
    }
  };

  window.setSignalFilter = setSignalFilter;

  async function loadConditions() {
    try {
      const response = await fetch(`${CONDITIONS_URL}?v=${Date.now()}`);
      if (!response.ok) return;
      gameConditionsData = await response.json();

      // Re-render board after weather data arrives so adjusted totals/signals appear.
      if (Array.isArray(projections) && projections.length) {
        renderProjections();
      }
    } catch (error) {
      console.warn("Weather Engine v1 unavailable:", error);
    }
  }

  async function loadSettledResults() {
    try {
      const response = await fetch(`${RESULTS_URL}?v=${Date.now()}`);
      if (!response.ok) return;
      settledResultsData = await response.json();
      indexSettledResults(settledResultsData);

      if (Array.isArray(projections) && projections.length) renderProjections();
    } catch (error) {
      console.warn("Historical results unavailable:", error);
    }
  }

  installStyles();

  document.addEventListener("DOMContentLoaded", () => {
    installFilterControls();
    installTestingNotice();
    loadConditions();
    loadSettledResults();
  });
})();
