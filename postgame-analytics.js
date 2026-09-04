(() => {
  "use strict";

  const DATA_URL = "./data/postgame_analytics.json";
  const SETTLED_URL = "./data/reports/settled_results.json";
  const SIGNAL_URL = "./data/reports/signal_report.json";
  const STYLE_ID = "hammer-postgame-analytics-styles";
  const PANEL_ID = "hammer-postgame-analysis";

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
        display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; padding:14px;
      }
      #${PANEL_ID} .pg-card {
        min-width:0; padding:16px; border:1px solid var(--border); border-radius:10px;
        background:#fbfbfa;
      }
      #${PANEL_ID} .pg-label {
        color:var(--muted); font-family:var(--mono); font-size:8px; font-weight:800;
        letter-spacing:.9px; text-transform:uppercase;
      }
      #${PANEL_ID} .pg-value { margin-top:8px; font-size:22px; font-weight:850; line-height:1.1; }
      #${PANEL_ID} .pg-value.pg-reality { color:#76526f; font-size:16px; }
      #${PANEL_ID} .pg-team { display:block; margin-top:5px; color:var(--muted); font-size:9px; }
      #${PANEL_ID} .pg-section { padding:0 14px 14px; }
      #${PANEL_ID} .pg-section-title {
        padding:12px 2px 9px; color:var(--muted); font-family:var(--mono);
        font-size:8px; font-weight:800; letter-spacing:1px; text-transform:uppercase;
      }
      #${PANEL_ID} .pg-metrics { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
      #${PANEL_ID} .pg-metric {
        display:grid; grid-template-columns:minmax(130px,.85fr) minmax(0,1.15fr);
        align-items:center; gap:12px; padding:11px 13px; border:1px solid var(--border);
        border-radius:9px; background:#fff;
      }
      #${PANEL_ID} .pg-metric-name { color:var(--muted); font-size:9px; }
      #${PANEL_ID} .pg-metric-value { text-align:right; font-family:var(--mono); font-size:9px; font-weight:750; }
      #${PANEL_ID} .pg-team-pair { display:flex; justify-content:flex-end; gap:8px; flex-wrap:wrap; }
      #${PANEL_ID} .pg-team-pair span:first-child { color:#76526f; }
      #${PANEL_ID} .pg-method {
        margin:0 14px 14px; padding:11px 13px; border-radius:9px; background:#f6f6f3;
        color:var(--muted); font-size:8px; line-height:1.55;
      }
      #${PANEL_ID} .pg-pending { padding:24px; color:var(--muted); text-align:center; font-size:10px; }
      @media (max-width:760px) {
        #${PANEL_ID} .pg-headlines, #${PANEL_ID} .pg-metrics { grid-template-columns:1fr; }
        #${PANEL_ID} .pg-header { padding:16px; }
        #${PANEL_ID} .pg-headlines, #${PANEL_ID} .pg-section { padding-left:10px; padding-right:10px; }
        #${PANEL_ID} .pg-metric { grid-template-columns:1fr; gap:6px; }
        #${PANEL_ID} .pg-metric-value, #${PANEL_ID} .pg-team-pair { text-align:left; justify-content:flex-start; }
      }
    `;
    document.head.appendChild(style);
  }

  function gameData(gameId) {
    return payload?.games?.[String(gameId)] || null;
  }

  function settledData(gameId) {
    return settledByGame.get(String(gameId)) || null;
  }

  function settledByRenderedTeams() {
    const names = Array.from(
      document.querySelectorAll("#matchup-container .projected-team-name")
    ).map(node => canonical(node.textContent));
    if (names.length < 2) return null;
    return Array.from(settledByGame.values()).find(row =>
      canonical(row.away_team) === names[0] && canonical(row.home_team) === names[1]
    ) || null;
  }

  function favoredLine(home, away, homeSpread) {
    if (!hasValue(homeSpread)) return "—";
    const spread = Number(homeSpread);
    if (Math.abs(spread) < 0.001) return "Pick'em";
    const team = spread < 0 ? home : away;
    const line = spread < 0 ? spread : -spread;
    return `${team} ${line > 0 ? "+" : ""}${line.toFixed(1)}`;
  }

  function projectedScore(row) {
    const total = Number(hasValue(row?.public_total) ? row.public_total : row?.model_total);
    const spread = Number(hasValue(row?.public_home_spread) ? row.public_home_spread : row?.model_home_spread);
    if (!Number.isFinite(total) || !Number.isFinite(spread)) return "—";
    const home = Math.max(0, (total - spread) / 2);
    const away = Math.max(0, total - home);
    return `${row.away_team} ${Math.round(away)} — ${Math.round(home)} ${row.home_team}`;
  }

  function resultWord(value, noun) {
    if (value === "W") return `${noun} WIN`;
    if (value === "L") return `${noun} LOSS`;
    if (value === "P") return `${noun} PUSH`;
    return "—";
  }

  function confidenceFor(signal) {
    const exact = signalReport?.signals?.[signal];
    if (exact?.confidence) return exact.confidence;
    const wanted = canonical(signal);
    const match = Object.values(signalReport?.signals || {}).find(item => canonical(item?.signal) === wanted);
    return match?.confidence || "DEVELOPING";
  }

  function auditItem(label, value) {
    return `<div class="final-result-item"><span>${escapeHtml(label)}</span><span>${escapeHtml(value)}</span></div>`;
  }

  function applyPregameAudit() {
    const panel = document.querySelector("#matchup-container .final-result-panel");
    if (!panel || panel.dataset.hammerPregameExpanded === "true") return;
    const game = settledData(selectedGameId) || settledByRenderedTeams();
    if (!game) return;
    panel.dataset.hammerPregameExpanded = "true";
    const title = panel.querySelector(".final-result-title");
    if (title) title.textContent = "Pregame THI / Model Result · Frozen Before Kickoff";
    const grid = panel.querySelector(".final-result-grid");
    if (!grid) return;
    const modelLine = favoredLine(game.home_team, game.away_team, game.public_home_spread ?? game.model_home_spread);
    const marketLine = favoredLine(game.home_team, game.away_team, game.snapshot_home_spread);
    const close = favoredLine(game.home_team, game.away_team, game.closing_home_spread);
    const total = hasValue(game.public_total) ? game.public_total : game.model_total;
    grid.insertAdjacentHTML("beforeend", [
      auditItem("THI spread", modelLine),
      auditItem("Market spread at snapshot", marketLine),
      auditItem("Preferred side", game.preferred_side || "—"),
      auditItem("ATS result", resultWord(game.ats_result, "ATS")),
      auditItem("Signal confidence", confidenceFor(game.signal)),
      auditItem("Closing line", close),
      auditItem("CLV", hasValue(game.clv_points) ? formatSigned(game.clv_points, 1, " pts") : "—"),
      auditItem("Pregame projected score", projectedScore(game)),
      auditItem("Pregame THI total", hasValue(total) ? format(total, 1) : "—"),
      auditItem("Total result", resultWord(game.total_result, game.total_tier || "TOTAL")),
    ].join(""));
  }

  function findByRenderedTeams() {
    const names = Array.from(
      document.querySelectorAll("#matchup-container .projected-team-name")
    ).map(node => canonical(node.textContent));
    if (names.length < 2) return null;
    return Object.values(payload.games || {}).find(game =>
      canonical(game.away_team) === names[0] && canonical(game.home_team) === names[1]
    ) || null;
  }

  function activeGame() {
    return gameData(selectedGameId) || findByRenderedTeams();
  }

  function pair(game, key, digits = 3, suffix = "") {
    const away = game?.teams?.away?.[key];
    const home = game?.teams?.home?.[key];
    return `
      <div class="pg-team-pair">
        <span>${escapeHtml(game.away_team)} ${format(away, digits, suffix)}</span>
        <span>${escapeHtml(game.home_team)} ${format(home, digits, suffix)}</span>
      </div>
    `;
  }

  function metric(label, value) {
    return `<div class="pg-metric"><div class="pg-metric-name">${escapeHtml(label)}</div><div class="pg-metric-value">${value}</div></div>`;
  }

  function winnerExpectation(game) {
    const home = game?.headline?.home_win_expectancy_pct;
    const away = game?.headline?.away_win_expectancy_pct;
    if (!hasValue(home) || !hasValue(away)) return { team: "Unavailable", pct: "—" };
    return Number(home) >= Number(away)
      ? { team: game.home_team, pct: `${Number(home).toFixed(0)}%` }
      : { team: game.away_team, pct: `${Number(away).toFixed(0)}%` };
  }

  function adjustedScore(game) {
    const score = game?.headline?.adjusted_score;
    if (!score || !hasValue(score.away_points) || !hasValue(score.home_points)) return "—";
    return `${escapeHtml(game.away_team)} ${Math.round(score.away_points)} — ${Math.round(score.home_points)} ${escapeHtml(game.home_team)}`;
  }

  function panelMarkup(game) {
    const expectancy = winnerExpectation(game);
    const c = game.comparisons || {};
    return `
      <section id="${PANEL_ID}" aria-label="Postgame analysis">
        <div class="pg-shell">
          <div class="pg-header">
            <div class="pg-kicker">🔨 Postgame Analysis</div>
            <div class="pg-title">What really happened?</div>
            <div class="pg-note">Retrospective completed-game analysis. This layer does not revise the frozen pregame THI prediction or feed Model A.</div>
          </div>
          <div class="pg-headlines">
            <div class="pg-card">
              <div class="pg-label">Postgame Win Expectancy</div>
              <div class="pg-value">${escapeHtml(expectancy.pct)}</div>
              <span class="pg-team">${escapeHtml(expectancy.team)}</span>
            </div>
            <div class="pg-card">
              <div class="pg-label">Adjusted Score</div>
              <div class="pg-value" style="font-size:17px">${adjustedScore(game)}</div>
            </div>
            <div class="pg-card">
              <div class="pg-label">Reality Check</div>
              <div class="pg-value pg-reality">${escapeHtml(game?.headline?.reality_check || "INSUFFICIENT DATA")}</div>
            </div>
          </div>
          <div class="pg-section">
            <div class="pg-section-title">Efficiency and game shape</div>
            <div class="pg-metrics">
              ${metric("EPA Margin", hasValue(c.epa_margin_home) ? `${escapeHtml(game.home_team)} ${formatSigned(c.epa_margin_home)}` : "—")}
              ${metric("Success Rate Dominance", pair(game, "success_rate", 1, "%"))}
              ${metric("Explosive Play Dependence", pair(game, "explosive_epa_dependency_pct", 1, "%"))}
              ${metric("Turnover Luck", "— · held until turnover value is verified")}
              ${metric("Finishing Drives", pair(game, "points_per_opportunity", 2, " pts/opportunity"))}
              ${metric("Drive Efficiency", "— · pending verified drive possessions")}
              ${metric("Field Position / Hidden Yardage", pair(game, "average_start_ep", 2, " start EP"))}
              ${metric("Early-Down Performance", pair(game, "early_down_epa", 3, " EPA/play"))}
              ${metric("3rd/4th Down Variance", pair(game, "late_down_epa", 3, " EPA/play"))}
              ${metric("Red-Zone Overperformance", "— · pending verified drive possessions")}
              ${metric("Garbage-Time Impact", pair(game, "garbage_time_play_share_pct", 1, "% of plays"))}
              ${metric("Game Variance", pair(game, "play_epa_volatility", 3, " EPA σ"))}
            </div>
          </div>
          <div class="pg-method">Adjusted Score is derived from CFBD postgame win expectancy and the frozen THI total. Missing components remain unavailable; the final score alone is never used to fabricate efficiency metrics.</div>
        </div>
      </section>
    `;
  }

  function applyPanel() {
    const container = document.getElementById("matchup-container");
    if (!container) return;
    if (!container.querySelector(".hammer-final-score-card, .final-result-panel")) return;
    applyPregameAudit();
    const game = activeGame();
    if (!game || !["available", "partial"].includes(game.availability)) return;
    const existing = container.querySelector(`#${PANEL_ID}`);
    if (existing?.dataset?.gameId === String(game.game_id)) return;
    existing?.remove();
    container.insertAdjacentHTML("beforeend", panelMarkup(game));
    const inserted = container.querySelector(`#${PANEL_ID}`);
    if (inserted) inserted.dataset.gameId = String(game.game_id);
  }

  function addAvailabilityIndicators() {
    document.querySelectorAll("#view-projections tr.completed-row").forEach(row => {
      const onclick = row.getAttribute("onclick") || "";
      const match = onclick.match(/openMatchup\(['\"]([^'\"]+)/);
      if (!match || !gameData(match[1])) return;
      const target = row.querySelector(".matchup-cell");
      if (!target || target.querySelector(".hammer-postgame-available")) return;
      target.insertAdjacentHTML("beforeend", '<span class="hammer-postgame-available">🔨 Postgame analysis available</span>');
    });
  }

  function wrapOpenMatchup() {
    if (typeof window.openMatchup !== "function" || window.openMatchup.__hammerPostgameWrapped) return;
    const original = window.openMatchup;
    const wrapped = function(gameId) {
      selectedGameId = String(gameId ?? "");
      const result = original.apply(this, arguments);
      requestAnimationFrame(applyPanel);
      return result;
    };
    wrapped.__hammerPostgameWrapped = true;
    window.openMatchup = wrapped;
  }

  function installObserver() {
    observer?.disconnect();
    observer = new MutationObserver(() => {
      requestAnimationFrame(() => {
        addAvailabilityIndicators();
        applyPanel();
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  async function load() {
    try {
      const stamp = Date.now();
      const [analyticsResponse, settledResponse, signalResponse] = await Promise.all([
        fetch(`${DATA_URL}?v=${stamp}`, { cache: "no-store" }),
        fetch(`${SETTLED_URL}?v=${stamp}`, { cache: "no-store" }),
        fetch(`${SIGNAL_URL}?v=${stamp}`, { cache: "no-store" }),
      ]);
      if (!analyticsResponse.ok) throw new Error(`Postgame HTTP ${analyticsResponse.status}`);
      const parsed = await analyticsResponse.json();
      payload = parsed && typeof parsed === "object" ? parsed : { meta: {}, games: {} };
      if (settledResponse.ok) {
        const settled = await settledResponse.json();
        const rows = (settled?.rows || []).filter(row => row?.result_settled);
        const earliest = new Map();
        rows.forEach(row => {
          const id = String(row.game_key || "");
          if (!id) return;
          const current = earliest.get(id);
          if (!current || String(row.captured_at_utc || "") < String(current.captured_at_utc || "")) earliest.set(id, row);
        });
        settledByGame = earliest;
      }
      if (signalResponse.ok) signalReport = await signalResponse.json();
    } catch (error) {
      console.warn("[Hammer Postgame Analytics] Data unavailable:", error);
      payload = { meta: {}, games: {} };
    }
    wrapOpenMatchup();
    addAvailabilityIndicators();
    applyPanel();
  }

  async function start() {
    installStyles();
    wrapOpenMatchup();
    installObserver();
    await load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
