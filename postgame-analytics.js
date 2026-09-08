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
        #${SCORECARD_ID} .perf-header { display:block; }
        #${SCORECARD_ID} .perf-note { margin-top:6px; text-align:left; }
        #${SCORECARD_ID} .perf-grid { grid-template-columns:repeat(2,minmax(0,1fr)); padding:9px; }
        #${SCORECARD_ID} .perf-ytd { padding:0 9px 10px; }
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

  function flattenCanonicalTeam(stats = {}) {
    return {
      epa_per_play: stats?.overall?.epa_per_play,
      total_epa: stats?.overall?.epa_total,
      success_rate: stats?.overall?.success_rate,
      pass_epa: stats?.passing?.epa_per_play,
      pass_success_rate: stats?.passing?.success_rate,
      rush_epa: stats?.rushing?.epa_per_play,
      rush_success_rate: stats?.rushing?.success_rate,
      standard_down_epa: stats?.standard_downs?.epa_per_play,
      standard_down_success_rate: stats?.standard_downs?.success_rate,
      passing_down_epa: stats?.passing_downs?.epa_per_play,
      passing_down_success_rate: stats?.passing_downs?.success_rate,
      early_down_epa: stats?.early_downs?.epa_per_play,
      late_down_epa: stats?.third_fourth_downs?.epa_per_play,
      third_fourth_down_success_rate: stats?.third_fourth_downs?.success_rate,
      fourth_down_attempts: stats?.fourth_down?.attempts,
      fourth_down_success_rate: stats?.fourth_down?.success_rate,
      fourth_down_epa: stats?.fourth_down?.epa_per_play,
      explosive_play_rate: stats?.explosiveness?.explosive_play_rate,
      explosive_epa_dependency_pct: stats?.explosiveness?.explosive_epa_dependency,
      sack_rate_allowed: stats?.negative_play_rates?.sack_rate_allowed,
      stuff_rate_allowed: stats?.negative_play_rates?.stuff_rate_allowed,
      tfl_rate_allowed: stats?.negative_play_rates?.tfl_rate_allowed,
      points_per_opportunity: stats?.scoring_opportunities?.points_per_opportunity,
      points_per_drive: stats?.drives?.points_per_drive,
      drive_success_rate: stats?.drives?.drive_success_rate,
      three_and_out_rate: stats?.drives?.three_and_out_rate,
      drives_tracked: stats?.drives?.drives,
      average_drive_start_yardline: stats?.field_position?.avg_start_yards_to_goal,
      red_zone_trips: stats?.red_zone?.trips,
      red_zone_points_per_trip: stats?.red_zone?.points_per_trip,
      red_zone_overperformance: stats?.red_zone?.overperformance_points_per_trip,
      play_epa_volatility: stats?.epa_volatility,
      turnover_epa_impact: stats?.turnovers?.turnover_epa_impact,
    };
  }

  function normalizeGame(game) {
    if (!game || game.teams) return game;
    const away = flattenCanonicalTeam(game.away_metrics);
    const home = flattenCanonicalTeam(game.home_metrics);
    const pgwe = game?.headline?.postgame_win_expectancy || {};
    const adjusted = game?.headline?.adjusted_final_score || {};
    const reality = game?.headline?.reality_check || {};
    const efficiency = game?.headline?.efficiency_margin || {};
    const expected = game?.headline?.expected_margin || {};
    const homeEfficiency = hasValue(efficiency.home)
      ? Number(efficiency.home)
      : (hasValue(home.epa_per_play) && hasValue(away.epa_per_play)
          ? Number(home.epa_per_play) - Number(away.epa_per_play)
          : null);
    const homeExpected = hasValue(expected.home)
      ? Number(expected.home)
      : (hasValue(reality.adjusted_margin) ? Number(reality.adjusted_margin) : null);
    const garbageShare = game?.game_context?.garbage_time_share;
    away.garbage_time_play_share_pct = garbageShare;
    home.garbage_time_play_share_pct = garbageShare;
    return {
      ...game,
      availability: game.analysis_status,
      headline: {
        ...game.headline,
        away_win_expectancy_pct: pgwe.away_pct,
        home_win_expectancy_pct: pgwe.home_pct,
        efficiency_margin_home: homeEfficiency,
        expected_margin_home: homeExpected,
        adjusted_score: { away_points: adjusted.away, home_points: adjusted.home },
        reality_check: reality.label,
        reality_note: reality.note,
      },
      teams: { away, home },
      comparisons: {
        epa_margin_home: homeEfficiency,
        turnover_epa_swing_home:
          hasValue(home.turnover_epa_impact) && hasValue(away.turnover_epa_impact)
            ? Number(home.turnover_epa_impact) - Number(away.turnover_epa_impact)
            : null,
      },
    };
  }

  function normalizePayload(parsed) {
    const games = parsed?.games;
    if (Array.isArray(games)) {
      const indexed = {};
      games.forEach(raw => {
        const game = normalizeGame(raw);
        if (game?.game_id) indexed[String(game.game_id)] = game;
      });
      return { ...parsed, games: indexed };
    }
    const indexed = {};
    Object.entries(games || {}).forEach(([id, raw]) => { indexed[id] = normalizeGame(raw); });
    return { ...(parsed || {}), games: indexed };
  }

  function canonicalSignalName(value) {
    const raw = String(value || "").toUpperCase();
    const translations = signalReport?.signal_system?.legacy_label_translation || {};
    if (translations[raw]) return translations[raw];
    const wanted = canonical(raw);
    const match = Object.entries(translations).find(([key]) => canonical(key) === wanted);
    return match?.[1] || raw || "UNCLASSIFIED";
  }

  function activeProjectionWeek() {
    const label = document.querySelector("#week-tabs .week-tab.active")?.textContent || "";
    const match = label.match(/(?:Week\s*)?(\d+)/i);
    return match ? Number(match[1]) : null;
  }

  function record(rows, field = "ats_result") {
    const values = rows.map(row => String(row?.[field] || "").toUpperCase()).filter(value => ["W", "L", "P"].includes(value));
    const wins = values.filter(value => value === "W").length;
    const losses = values.filter(value => value === "L").length;
    const pushes = values.filter(value => value === "P").length;
    const decisions = wins + losses;
    return { wins, losses, pushes, decisions, pct: decisions ? 100 * wins / decisions : null };
  }

  function mean(rows, field) {
    const values = rows.map(row => Number(row?.[field])).filter(Number.isFinite);
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  }

  function recordText(value) {
    if (!value.decisions && !value.pushes) return "0-0";
    return `${value.wins}-${value.losses}${value.pushes ? `-${value.pushes}` : ""}`;
  }

  function performanceStats(rows) {
    const ats = record(rows);
    const playRows = rows.filter(row => canonicalSignalName(row.signal) === "PLAY");
    const play = record(playRows);
    const totalRows = rows.filter(row => row.total_tier && ["W", "L", "P"].includes(String(row.total_result || "").toUpperCase()));
    const totals = record(totalRows, "total_result");
    const winnerRows = rows.filter(row => hasValue(row.actual_home_margin) && hasValue(row.public_home_spread ?? row.model_home_spread) && Math.abs(Number(row.public_home_spread ?? row.model_home_spread)) > 0.001);
    let winnerCorrect = 0;
    winnerRows.forEach(row => {
      const line = Number(row.public_home_spread ?? row.model_home_spread);
      const margin = Number(row.actual_home_margin);
      if ((line < 0 && margin > 0) || (line > 0 && margin < 0)) winnerCorrect += 1;
    });
    const postgame = rows.filter(row => gameData(row.game_key)).length;
    return { rows, ats, play, totals, totalRows, winnerCorrect, winnerDecisions:winnerRows.length, postgame,
      error:mean(rows, "public_abs_error") ?? mean(rows, "model_abs_error"), clv:mean(rows, "clv_points") };
  }

  function perfStat(label, value, sub = "") {
    return `<div class="perf-stat"><div class="perf-label">${escapeHtml(label)}</div><div class="perf-value">${escapeHtml(value)}</div><div class="perf-sub">${escapeHtml(sub)}</div></div>`;
  }

  function signalRows(rows) {
    const order = signalReport?.signal_system?.order || ["ALIGNED", "SMALL EDGE", "PLAY", "MATERIAL DISAGREEMENT", "OUTLIER"];
    const spreadRows = order.map(signal => {
      const subset = rows.filter(row => canonicalSignalName(row.signal) === signal);
      const rec = record(subset);
      const clv = mean(subset, "clv_points");
      const beat = subset.filter(row => hasValue(row.clv_points) && Number(row.clv_points) > 0).length;
      const clvDecisions = subset.filter(row => hasValue(row.clv_points) && Number(row.clv_points) !== 0).length;
      const confidence = signalReport?.signals?.[signal]?.confidence || "DEVELOPING";
      return { label:signal, sample:subset.length, rec, clv, beatPct:clvDecisions ? 100*beat/clvDecisions : null, confidence };
    });
    const totalRows = ["TOTAL WATCH", "TOTAL LEAN"].map(tier => {
      const subset = rows.filter(row => String(row.total_tier || "").toUpperCase() === tier);
      return { label:tier, sample:subset.length, rec:record(subset,"total_result"), clv:null, beatPct:null, confidence:"TESTING" };
    });
    return [...spreadRows, ...totalRows];
  }

  function scorecardMarkup(week, weeklyRows, ytdRows) {
    const weekly = performanceStats(weeklyRows);
    const ytd = performanceStats(ytdRows);
    const body = signalRows(ytdRows).map(item => `<tr>
      <td>${escapeHtml(item.label)}</td><td>${item.sample}</td><td>${escapeHtml(recordText(item.rec))}</td>
      <td>${hasValue(item.rec.pct) ? `${Number(item.rec.pct).toFixed(1)}%` : "—"}</td>
      <td>${hasValue(item.clv) ? formatSigned(item.clv,1," pts") : "—"}</td>
      <td>${hasValue(item.beatPct) ? `${Number(item.beatPct).toFixed(1)}%` : "—"}</td>
      <td><span class="perf-confidence">${escapeHtml(item.confidence)}</span></td></tr>`).join("");
    const weekLabel = week === null ? "Selected Week" : `Week ${week}`;
    return `<div class="perf-shell">
      <div class="perf-header"><div><div class="perf-kicker">🔨 Transparent Model Tracking</div><div class="perf-title">${weekLabel} Performance</div></div>
      <div class="perf-note">Live prospective results. Small samples are descriptive—not proof of future performance. Pushes are excluded from win percentages.</div></div>
      <div class="perf-grid">
        ${perfStat("Games Final",weekly.rows.length,`${weekly.postgame} postgame analyses available`)}
        ${perfStat("Predicted Winners",`${weekly.winnerCorrect}-${Math.max(0,weekly.winnerDecisions-weekly.winnerCorrect)}`,hasValue(weekly.winnerDecisions) && weekly.winnerDecisions ? `${(100*weekly.winnerCorrect/weekly.winnerDecisions).toFixed(1)}% correct` : "No decisions")}
        ${perfStat("Overall ATS",recordText(weekly.ats),hasValue(weekly.ats.pct) ? `${weekly.ats.pct.toFixed(1)}%` : "No decisions")}
        ${perfStat("Play Tier ATS",recordText(weekly.play),hasValue(weekly.play.pct) ? `${weekly.play.pct.toFixed(1)}%` : "No decisions")}
        ${perfStat("Flagged Totals",recordText(weekly.totals),hasValue(weekly.totals.pct) ? `${weekly.totals.pct.toFixed(1)}%` : "No decisions")}
        ${perfStat("Average Margin Error",hasValue(weekly.error) ? `${weekly.error.toFixed(1)} pts` : "—","Absolute THI projection error")}
        ${perfStat("Average CLV",hasValue(weekly.clv) ? formatSigned(weekly.clv,1," pts") : "—","Preferred-side closing value")}
        ${perfStat("Season ATS",recordText(ytd.ats),hasValue(ytd.ats.pct) ? `${ytd.ats.pct.toFixed(1)}% YTD` : "No decisions")}
      </div>
      <div class="perf-ytd"><div class="perf-ytd-title">Season-to-Date · Every Signal and Testing Key</div>
        <div class="perf-table-wrap"><table><thead><tr><th>Signal / Key</th><th>Games</th><th>Record</th><th>Win %</th><th>Avg CLV</th><th>Beat Close</th><th>Confidence</th></tr></thead><tbody>${body}</tbody></table></div>
      </div></div>`;
  }

  function applyPerformanceScorecard() {
    const tabs = document.getElementById("week-tabs");
    if (!tabs || !settledByGame.size) return;
    const week = activeProjectionWeek();
    const ytdRows = Array.from(settledByGame.values()).filter(row => row.result_settled);
    const weeklyRows = ytdRows.filter(row => week === null || Number(row.week) === Number(week));
    const signature = `${week}|${weeklyRows.length}|${ytdRows.length}|${payload?.meta?.generated_at_utc || ""}|${signalReport?.generated_at_utc || ""}`;
    let card = document.getElementById(SCORECARD_ID);
    if (!card) { card = document.createElement("section"); card.id = SCORECARD_ID; tabs.insertAdjacentElement("afterend",card); }
    if (card.dataset.signature === signature) return;
    card.dataset.signature = signature;
    card.innerHTML = scorecardMarkup(week,weeklyRows,ytdRows);
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

  function marginLeader(game, value, digits, suffix) {
    if (!hasValue(value)) return { team: "Unavailable", value: "—" };
    const numeric = Number(value);
    return {
      team: numeric >= 0 ? game.home_team : game.away_team,
      value: `${Math.abs(numeric).toFixed(digits)}${suffix}`,
    };
  }

  function panelMarkup(game) {
    const expectancy = winnerExpectation(game);
    const c = game.comparisons || {};
    const efficiency = marginLeader(game, game?.headline?.efficiency_margin_home ?? c.epa_margin_home, 3, " EPA/play");
    const expected = marginLeader(game, game?.headline?.expected_margin_home, 1, " pts");
    return `
      <section id="${PANEL_ID}" aria-label="Postgame analysis">
        <div class="pg-shell">
          <div class="pg-header">
            <div class="pg-kicker">🔨 Postgame Analysis</div>
            <div class="pg-title">Did We Get Beat That Bad?</div>
            <div class="pg-note">Retrospective completed-game analysis. This layer does not revise the frozen pregame THI prediction or feed Model A.</div>
          </div>
          <div class="pg-headlines">
            <div class="pg-card">
              <div class="pg-label">Postgame Win Expectancy</div>
              <div class="pg-value">${escapeHtml(expectancy.pct)}</div>
              <span class="pg-team">${escapeHtml(expectancy.team)}</span>
            </div>
            <div class="pg-card">
              <div class="pg-label">Efficiency Margin</div>
              <div class="pg-value" style="font-size:18px">${escapeHtml(efficiency.value)}</div>
              <span class="pg-team">${escapeHtml(efficiency.team)} · non-garbage EPA/play edge</span>
            </div>
            <div class="pg-card">
              <div class="pg-label">Expected Margin</div>
              <div class="pg-value">${escapeHtml(expected.value)}</div>
              <span class="pg-team">${escapeHtml(expected.team)} · retrospective</span>
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
            <div class="pg-section-title">Core efficiency and game shape</div>
            <div class="pg-metrics">
              ${metric("EPA Margin", hasValue(c.epa_margin_home) ? `${escapeHtml(game.home_team)} ${formatSigned(c.epa_margin_home)}` : "—")}
              ${metric("EPA per Play", pair(game, "epa_per_play", 3, " EPA/play"))}
              ${metric("Total EPA", pair(game, "total_epa", 2, " EPA"))}
              ${metric("Success Rate Dominance", pair(game, "success_rate", 1, "%"))}
              ${metric("Explosive Play Rate", pair(game, "explosive_play_rate", 1, "%"))}
              ${metric("Explosive Play Dependence", pair(game, "explosive_epa_dependency_pct", 1, "%"))}
              ${metric("Turnover Impact", hasValue(c.turnover_epa_swing_home) ? `${escapeHtml(game.home_team)} ${formatSigned(c.turnover_epa_swing_home)} EPA swing` : "—")}
              ${metric("Game Variance", pair(game, "play_epa_volatility", 3, " EPA σ"))}
              ${metric("Garbage-Time Impact", pair(game, "garbage_time_play_share_pct", 1, "% of plays"))}
            </div>
          </div>
          <div class="pg-section">
            <div class="pg-section-title">Play type and down-state splits</div>
            <div class="pg-metrics">
              ${metric("Pass EPA", pair(game, "pass_epa", 3, " EPA/play"))}
              ${metric("Pass Success Rate", pair(game, "pass_success_rate", 1, "%"))}
              ${metric("Rush EPA", pair(game, "rush_epa", 3, " EPA/play"))}
              ${metric("Rush Success Rate", pair(game, "rush_success_rate", 1, "%"))}
              ${metric("Standard-Down EPA", pair(game, "standard_down_epa", 3, " EPA/play"))}
              ${metric("Standard-Down Success", pair(game, "standard_down_success_rate", 1, "%"))}
              ${metric("Passing-Down EPA", pair(game, "passing_down_epa", 3, " EPA/play"))}
              ${metric("Passing-Down Success", pair(game, "passing_down_success_rate", 1, "%"))}
              ${metric("Early-Down Performance", pair(game, "early_down_epa", 3, " EPA/play"))}
              ${metric("3rd/4th Down EPA", pair(game, "late_down_epa", 3, " EPA/play"))}
              ${metric("3rd/4th Down Success", pair(game, "third_fourth_down_success_rate", 1, "%"))}
              ${metric("Fourth-Down Attempts", pair(game, "fourth_down_attempts", 0, " attempts"))}
              ${metric("Fourth-Down Success", pair(game, "fourth_down_success_rate", 1, "%"))}
              ${metric("Fourth-Down EPA", pair(game, "fourth_down_epa", 3, " EPA/play"))}
              ${metric("Sack Rate Allowed", pair(game, "sack_rate_allowed", 1, "% of dropbacks"))}
              ${metric("Stuff Rate Allowed", pair(game, "stuff_rate_allowed", 1, "% of rushes"))}
              ${metric("TFL Rate Allowed", pair(game, "tfl_rate_allowed", 1, "% of plays"))}
            </div>
          </div>
          <div class="pg-section">
            <div class="pg-section-title">Drive and field-position profile</div>
            <div class="pg-metrics">
              ${metric("Finishing Drives", pair(game, "points_per_opportunity", 2, " pts/opportunity"))}
              ${metric("Drive Efficiency", pair(game, "points_per_drive", 2, " pts/drive"))}
              ${metric("Drive Success Rate", pair(game, "drive_success_rate", 1, "%"))}
              ${metric("Three-and-Out Rate", pair(game, "three_and_out_rate", 1, "%"))}
              ${metric("Drives Tracked", pair(game, "drives_tracked", 0, " drives"))}
              ${metric("Field Position / Hidden Yardage", pair(game, "average_drive_start_yardline", 1, " avg start"))}
              ${metric("Red-Zone Trips", pair(game, "red_zone_trips", 0, " trips"))}
              ${metric("Red-Zone Points per Trip", pair(game, "red_zone_points_per_trip", 2, " pts/trip"))}
              ${metric("Red-Zone Overperformance", pair(game, "red_zone_overperformance", 2, " pts/trip vs baseline"))}
            </div>
          </div>
          <div class="pg-method"><strong>PGWE / EM — BETA:</strong> Efficiency Margin is the non-garbage-time EPA/play differential. Expected Margin translates the complete underlying performance profile into a scoreboard margin, and Postgame Win Expectancy converts that margin into a win probability. Adjusted Score uses the same retrospective game-quality margin. This display-only layer makes no CFBD calls and never changes Model A.</div>
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

  function wrapSelectWeek() {
    if (typeof window.selectWeek !== "function" || window.selectWeek.__hammerScorecardWrapped) return;
    const original = window.selectWeek;
    const wrapped = function() {
      const result = original.apply(this, arguments);
      requestAnimationFrame(applyPerformanceScorecard);
      return result;
    };
    wrapped.__hammerScorecardWrapped = true;
    window.selectWeek = wrapped;
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
      payload = parsed && typeof parsed === "object"
        ? normalizePayload(parsed)
        : { meta: {}, games: {} };
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
    wrapSelectWeek();
    addAvailabilityIndicators();
    applyPanel();
    applyPerformanceScorecard();
  }

  async function start() {
    installStyles();
    wrapOpenMatchup();
    wrapSelectWeek();
    installObserver();
    await load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
