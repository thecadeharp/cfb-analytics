(function () {
  "use strict";
  const DATA_URL = "data/reports/benchmark_center.json";
  const state = { sport: "cfb", days: "all", venue: "all", view: "predictive" };
  let data = null;
  const $ = selector => document.querySelector(selector);
  const fmt = (value, digits = 1) => value == null ? "—" : Number(value).toFixed(digits);
  const signed = (value, digits = 2) => value == null ? "—" : `${value > 0 ? "+" : ""}${fmt(value, digits)}`;
  const tone = value => value == null ? "" : value > 0 ? "positive" : value < 0 ? "negative" : "";
  const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
  const slice = () => data.slices[`${state.sport}|${state.days}|${state.venue}`];

  function filtered(rows) {
    let result = rows.filter(row => row.sport === state.sport);
    if (state.venue !== "all") result = result.filter(row => row.venue === state.venue);
    if (state.days !== "all") {
      const dated = data.observations.filter(row => row.sport === state.sport && row.date).map(row => row.date).sort();
      if (!dated.length) return [];
      const cutoff = new Date(`${dated[dated.length - 1]}T00:00:00Z`);
      cutoff.setUTCDate(cutoff.getUTCDate() - Number(state.days));
      result = result.filter(row => row.date && new Date(`${row.date}T00:00:00Z`) >= cutoff);
    }
    return result;
  }

  function ci(metric, digits = 1, suffix = "") {
    if (!metric || metric.value == null) return "—";
    return `${fmt(metric.value, digits)}${suffix} · 95% CI ${fmt(metric.ci_low, digits)}–${fmt(metric.ci_high, digits)}${suffix}`;
  }

  function signedCi(metric, digits = 2) {
    if (!metric || metric.value == null) return "—";
    return `${signed(metric.value, digits)} · 95% CI ${signed(metric.ci_low, digits)} to ${signed(metric.ci_high, digits)}`;
  }

  function metricCard(label, metric, options = {}) {
    const value = options.signed ? signed(metric.value, options.digits ?? 1) : `${fmt(metric.value, options.digits ?? 1)}${options.suffix || ""}`;
    const low = options.signed ? signed(metric.ci_low, options.digits ?? 1) : `${fmt(metric.ci_low, options.digits ?? 1)}${options.suffix || ""}`;
    const high = options.signed ? signed(metric.ci_high, options.digits ?? 1) : `${fmt(metric.ci_high, options.digits ?? 1)}${options.suffix || ""}`;
    const klass = options.klass || (options.signed ? tone(metric.value) : "");
    return `<article class="metric"><div class="metric-label">${label}</div><div class="metric-value ${klass}">${value}</div><small>95% CI ${low} to ${high} · n=${metric.n}</small></article>`;
  }

  function tableHtml(groups) {
    const minimum = data.meta.minimum_interpretive_sample;
    return groups.map(row => `<tr>
      <td><strong>${escapeHtml(row.signal)}</strong></td>
      <td>${row.wins}-${row.losses}${row.pushes ? `-${row.pushes}` : ""}</td>
      <td>${ci(row.hit_rate, 1, "%")}</td>
      <td class="${tone(row.mean_clv.value)}">${signedCi(row.mean_clv)}</td>
      <td>${ci(row.beat_close, 1, "%")}</td>
      <td>results ${row.n_results}<br><span class="muted">CLV ${row.n_clv}</span></td>
      <td><span class="sample-badge ${row.n_results >= minimum ? "ready" : ""}">${row.n_results >= minimum ? `n=${row.n_results}` : `SMALL SAMPLE · n=${row.n_results}`}</span></td>
    </tr>`).join("") || '<tr><td colspan="7">No graded decisions match these filters.</td></tr>';
  }

  function renderPredictive(current) {
    const predictive = current.predictive;
    const m = predictive.metrics;
    const label = state.sport === "cfb" ? "College football" : "College basketball";
    $("#sport-kicker").textContent = `${label} / prospective frozen`;
    $("#sample-copy").textContent = `${predictive.n_observations} settled projections match the current filters. Intervals are precomputed in the static audit build.`;
    $("#metrics").innerHTML = [
      metricCard("Margin MAE", m.margin_mae, {klass:"positive"}),
      metricCard("Margin RMSE", m.margin_rmse),
      metricCard("Signed margin bias", m.margin_bias, {signed:true}),
      metricCard("Winner accuracy", m.winner_accuracy, {suffix:"%", klass:"blue"}),
      metricCard("Total MAE", m.total_mae, {klass:"positive"}),
      metricCard("Total RMSE", m.total_rmse),
      metricCard("Signed total bias", m.total_bias, {signed:true}),
      metricCard("Within 7 points", m.within_7, {suffix:"%", klass:"yellow"})
    ].join("");
    $("#brier-pill").textContent = ci(m.brier, 4);
    $("#calibration").innerHTML = predictive.calibration.map(row => `<div class="calibration-row"><strong>${row.label}</strong><div class="bar"><span class="predicted" style="width:${row.predicted}%"></span><span class="actual" style="width:${row.actual.value}%"></span></div><div class="calibration-meta">${fmt(row.predicted)}% predicted · ${fmt(row.actual.value)}% actual · 95% CI ${fmt(row.actual.ci_low)}–${fmt(row.actual.ci_high)}% · n=${row.actual.n}</div></div>`).join("") || "No probability observations match these filters.";
  }

  function renderMarket(current) {
    const market = current.market;
    const label = state.sport === "cfb" ? "College football" : "College basketball";
    $("#signal-title").textContent = `${label} spread signal performance`;
    $("#signal-table").innerHTML = tableHtml(market.spread);
    $("#totals-section").hidden = state.sport !== "cbb";
    if (state.sport === "cbb") $("#total-table").innerHTML = tableHtml(market.total);
    const coverage = market.source_coverage;
    $("#source-pill").textContent = `${coverage.n_with_source} / ${coverage.n_games} SOURCED`;
    $("#source-coverage").innerHTML = coverage.providers.map(row => `<article class="source-card"><strong>${escapeHtml(row.source)}</strong><span>${row.games} games</span><div><i style="width:${Math.min(100, row.coverage_pct)}%"></i></div><small>${fmt(row.coverage_pct)}% of filtered decisions</small></article>`).join("") || '<article class="source-card"><strong>No source coverage</strong><small>No market decisions match these filters.</small></article>';
  }

  function render() {
    const current = slice();
    const label = state.sport === "cfb" ? "College football" : "College basketball";
    $("#freeze-copy").textContent = data.methodology[state.sport === "cfb" ? "cfb_freeze" : "cbb_freeze"];
    $("#predictive-view").hidden = state.view !== "predictive";
    $("#market-view").hidden = state.view !== "market";
    renderPredictive(current);
    renderMarket(current);
    $("#active-notes").innerHTML = data.active_notes[state.sport].map((note, index) => `<article class="note"><strong>CALIBRATION NOTE ${String(index + 1).padStart(2,"0")}</strong><p>${escapeHtml(note)}</p></article>`).join("");
    const labels = {cfb_freeze:"CFB freeze rule",cfb_close:"CFB closing proxy",cbb_freeze:"CBB freeze rule",cbb_market:"CBB market contract",clv:"CLV baseline",intervals:"Uncertainty intervals",sample:"Sample warning",historical:"Backtest boundary"};
    $("#methodology").innerHTML = Object.entries(data.methodology).map(([key, value]) => `<article class="method"><strong>${labels[key]}</strong><p>${escapeHtml(value)}</p></article>`).join("");
    document.title = `THI ${label} Benchmark & Calibration Center`;
  }

  function csvEscape(value) { const text = Array.isArray(value) ? value.join("|") : String(value ?? ""); return /[",\n]/.test(text) ? `"${text.replaceAll('"','""')}"` : text; }
  function exportCsv() {
    const rows = filtered(data.observations);
    const fields = ["season","sport","game_id","date","venue","away_team","home_team","predicted_margin","actual_margin","margin_error","predicted_total","actual_total","total_error","home_win_probability","brier","model_version","freeze_ts","freeze_ts_status","market_policy_version","grading_policy_version","env_status","line_sources"];
    const csv = [fields.join(","), ...rows.map(row => fields.map(field => csvEscape(row[field])).join(","))].join("\n");
    const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([csv], {type:"text/csv"}));
    link.download = `thi-${state.sport}-benchmark-${state.days}-${state.venue}.csv`; link.click(); URL.revokeObjectURL(link.href);
  }

  document.querySelectorAll("#sport-filter button").forEach(button => button.addEventListener("click", () => {
    state.sport = button.dataset.value; document.querySelectorAll("#sport-filter button").forEach(item => item.classList.toggle("active", item === button)); render();
  }));
  document.querySelectorAll(".audit-nav button").forEach(button => button.addEventListener("click", () => {
    state.view = button.dataset.view; document.querySelectorAll(".audit-nav button").forEach(item => item.classList.toggle("active", item === button)); render();
  }));
  $("#date-filter").addEventListener("change", event => { state.days = event.target.value; render(); });
  $("#venue-filter").addEventListener("change", event => { state.venue = event.target.value; render(); });
  $("#export-csv").addEventListener("click", exportCsv);

  fetch(DATA_URL, {cache:"no-store"}).then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }).then(payload => {
    data = payload; $("#generated").textContent = `Updated ${new Date(data.meta.generated_at_utc).toLocaleString()}`;
    $("#loading").hidden = true; $("#benchmark-app").hidden = false; render();
  }).catch(error => { $("#loading").textContent = `Benchmark data is temporarily unavailable. ${error.message}`; });
})();
