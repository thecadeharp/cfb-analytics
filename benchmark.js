(function () {
  "use strict";
  const DATA_URL = "data/reports/benchmark_center.json";
  const state = { sport: "cfb", days: "all", venue: "all" };
  let data = null;
  const $ = selector => document.querySelector(selector);
  const number = value => value == null || value === "" || typeof value === "boolean"
    ? null : Number.isFinite(Number(value)) ? Number(value) : null;
  const mean = rows => rows.length ? rows.reduce((sum, value) => sum + value, 0) / rows.length : null;
  const fmt = (value, digits = 1) => value == null ? "—" : Number(value).toFixed(digits);
  const signed = (value, digits = 2) => value == null ? "—" : `${value > 0 ? "+" : ""}${fmt(value, digits)}`;
  const tone = value => value == null ? "" : value > 0 ? "positive" : value < 0 ? "negative" : "";
  const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);

  function filtered(rows) {
    let result = rows.filter(row => row.sport === state.sport);
    if (state.venue !== "all") result = result.filter(row => row.venue === state.venue);
    if (state.days !== "all") {
      const dated = result.map(row => row.date).filter(Boolean).sort();
      const anchor = dated.length ? new Date(`${dated[dated.length - 1]}T23:59:59Z`) : new Date();
      const cutoff = new Date(anchor.getTime() - Number(state.days) * 86400000);
      result = result.filter(row => row.date && new Date(`${row.date}T00:00:00Z`) >= cutoff);
    }
    return result;
  }

  function metricData(rows) {
    const margin = rows.map(row => number(row.margin_error)).filter(value => value != null);
    const total = rows.map(row => number(row.total_error)).filter(value => value != null);
    const brier = rows.map(row => number(row.brier)).filter(value => value != null);
    const winners = rows.filter(row => number(row.predicted_margin) !== 0 && number(row.actual_margin) !== 0);
    const block = values => ({
      n: values.length,
      mae: mean(values.map(Math.abs)),
      rmse: values.length ? Math.sqrt(mean(values.map(value => value * value))) : null,
      bias: mean(values),
      within7: values.length ? 100 * values.filter(value => Math.abs(value) <= 7).length / values.length : null
    });
    return {
      margin: block(margin), total: block(total), brier: mean(brier),
      winnerAccuracy: winners.length ? 100 * winners.filter(row => (row.predicted_margin > 0) === (row.actual_margin > 0)).length / winners.length : null,
      winnerN: winners.length
    };
  }

  function metricCard(label, value, sub, klass = "") {
    return `<article class="metric"><div class="metric-label">${label}</div><div class="metric-value ${klass}">${value}</div><small>${sub}</small></article>`;
  }

  function calibration(rows) {
    const usable = rows.filter(row => number(row.home_win_probability) != null && number(row.actual_margin) !== 0).map(row => {
      const home = row.home_win_probability / 100;
      return { confidence: Math.max(home, 1 - home), hit: (home >= .5) === (row.actual_margin > 0) ? 1 : 0 };
    });
    const bins = [[.5,.55],[.55,.6],[.6,.7],[.7,.8],[.8,.9],[.9,1.001]];
    return bins.map(([low, high]) => {
      const sample = usable.filter(row => row.confidence >= low && row.confidence < high);
      return sample.length ? {
        label: `${Math.round(low * 100)}–${high > 1 ? 100 : Math.round(high * 100)}%`, n: sample.length,
        predicted: 100 * mean(sample.map(row => row.confidence)), actual: 100 * mean(sample.map(row => row.hit))
      } : null;
    }).filter(Boolean);
  }

  function decisionRows(kind) {
    const key = state.sport === "cfb" ? "cfb_spread" : kind === "total" ? "cbb_total" : "cbb_spread";
    return filtered(data.decisions[key] || []);
  }

  function signalGroups(rows) {
    const groups = new Map();
    rows.forEach(row => {
      const signal = String(row.signal || "UNCLASSIFIED").replaceAll("_", " ").toUpperCase();
      if (!groups.has(signal)) groups.set(signal, []);
      groups.get(signal).push(row);
    });
    return [...groups.entries()].map(([signal, sample]) => {
      const resultKey = state.sport === "cfb" ? "ats_result" : "result";
      const wins = sample.filter(row => row[resultKey] === "W").length;
      const losses = sample.filter(row => row[resultKey] === "L").length;
      const pushes = sample.filter(row => row[resultKey] === "P").length;
      const graded = wins + losses;
      const clv = sample.map(row => number(row.clv)).filter(value => value != null);
      const decisiveClv = clv.filter(value => value !== 0);
      return { signal, n: sample.length, wins, losses, pushes, hit: graded ? 100 * wins / graded : null,
        avgClv: mean(clv), beat: decisiveClv.length ? 100 * decisiveClv.filter(value => value > 0).length / decisiveClv.length : null, clvN: clv.length };
    }).sort((a, b) => b.n - a.n);
  }

  function tableHtml(groups) {
    const minimum = data.meta.minimum_interpretive_sample;
    return groups.map(row => `<tr><td><strong>${escapeHtml(row.signal)}</strong></td><td>${row.wins}-${row.losses}${row.pushes ? `-${row.pushes}` : ""}</td><td>${fmt(row.hit)}%</td><td class="${tone(row.avgClv)}">${signed(row.avgClv)}</td><td>${fmt(row.beat)}%</td><td>${row.clvN} / ${row.n}</td><td><span class="sample-badge ${row.n >= minimum ? "ready" : ""}">${row.n >= minimum ? `n=${row.n}` : `SMALL SAMPLE · n=${row.n}`}</span></td></tr>`).join("") || '<tr><td colspan="7">No graded decisions match these filters.</td></tr>';
  }

  function render() {
    const rows = filtered(data.observations);
    const metrics = metricData(rows);
    const label = state.sport === "cfb" ? "College football" : "College basketball";
    $("#sport-kicker").textContent = `${label} / prospective frozen`;
    $("#sample-copy").textContent = `${rows.length} settled projections match the current filters.`;
    $("#freeze-copy").textContent = data.methodology[state.sport === "cfb" ? "cfb_freeze" : "cbb_freeze"];
    $("#metrics").innerHTML = [
      metricCard("Margin MAE", fmt(metrics.margin.mae), `Average absolute miss · n=${metrics.margin.n}`, "positive"),
      metricCard("Margin RMSE", fmt(metrics.margin.rmse), "Penalizes the largest misses"),
      metricCard("Signed margin bias", signed(metrics.margin.bias), "Positive = projected margins ran high", tone(metrics.margin.bias)),
      metricCard("Winner accuracy", `${fmt(metrics.winnerAccuracy)}%`, `${metrics.winnerN} decisive games`, "blue"),
      metricCard("Total MAE", fmt(metrics.total.mae), `Average absolute miss · n=${metrics.total.n}`, "positive"),
      metricCard("Total RMSE", fmt(metrics.total.rmse), "Penalizes the largest misses"),
      metricCard("Signed total bias", signed(metrics.total.bias), "Positive = projected totals ran high", tone(metrics.total.bias)),
      metricCard("Within 7 points", `${fmt(metrics.margin.within7)}%`, "Margin error", "yellow")
    ].join("");
    $("#brier-pill").textContent = `BRIER ${fmt(metrics.brier, 4)} · n=${rows.filter(row => row.brier != null).length}`;
    $("#calibration").innerHTML = calibration(rows).map(row => `<div class="calibration-row"><strong>${row.label}</strong><div class="bar"><span class="predicted" style="width:${row.predicted}%"></span><span class="actual" style="width:${row.actual}%"></span></div><div class="calibration-meta">${fmt(row.predicted)}% predicted · ${fmt(row.actual)}% actual · n=${row.n}</div></div>`).join("") || "No probability observations match these filters.";
    $("#signal-title").textContent = `${label} spread signal performance`;
    $("#signal-table").innerHTML = tableHtml(signalGroups(decisionRows("spread")));
    $("#totals-section").hidden = state.sport !== "cbb";
    if (state.sport === "cbb") $("#total-table").innerHTML = tableHtml(signalGroups(decisionRows("total")));
    $("#active-notes").innerHTML = data.active_notes[state.sport].map((note, index) => `<article class="note"><strong>CALIBRATION NOTE ${String(index + 1).padStart(2,"0")}</strong><p>${escapeHtml(note)}</p></article>`).join("");
    const labels = {cfb_freeze:"CFB freeze rule",cbb_freeze:"CBB freeze rule",clv:"CLV baseline",sample:"Sample warning",historical:"Backtest boundary"};
    $("#methodology").innerHTML = Object.entries(data.methodology).map(([key, value]) => `<article class="method"><strong>${labels[key]}</strong><p>${escapeHtml(value)}</p></article>`).join("");
  }

  function csvEscape(value) { const text = String(value ?? ""); return /[",\n]/.test(text) ? `"${text.replaceAll('"','""')}"` : text; }
  function exportCsv() {
    const rows = filtered(data.observations);
    const fields = ["sport","game_id","date","venue","away_team","home_team","predicted_margin","actual_margin","margin_error","predicted_total","actual_total","total_error","home_win_probability","brier","model_version","captured_at_utc"];
    const csv = [fields.join(","), ...rows.map(row => fields.map(field => csvEscape(row[field])).join(","))].join("\n");
    const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([csv], {type:"text/csv"}));
    link.download = `thi-${state.sport}-benchmark-${state.days}-${state.venue}.csv`; link.click(); URL.revokeObjectURL(link.href);
  }

  document.querySelectorAll("#sport-filter button").forEach(button => button.addEventListener("click", () => {
    state.sport = button.dataset.value; document.querySelectorAll("#sport-filter button").forEach(item => item.classList.toggle("active", item === button)); render();
  }));
  $("#date-filter").addEventListener("change", event => { state.days = event.target.value; render(); });
  $("#venue-filter").addEventListener("change", event => { state.venue = event.target.value; render(); });
  $("#export-csv").addEventListener("click", exportCsv);

  fetch(DATA_URL, {cache:"no-store"}).then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }).then(payload => {
    data = payload; $("#generated").textContent = `Updated ${new Date(data.meta.generated_at_utc).toLocaleString()}`;
    $("#loading").hidden = true; $("#benchmark-app").hidden = false; render();
  }).catch(error => { $("#loading").textContent = `Benchmark data is temporarily unavailable. ${error.message}`; });
})();
