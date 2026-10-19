/* THI-native cross-team charts. Uses only existing THI data contracts. */
(() => {
  const GROUPS = {
    P4: new Set(["ACC", "Big 12", "Big Ten", "SEC"]),
    G6: new Set(["American Athletic", "Conference USA", "Mid-American", "Mountain West", "Pac-12", "Sun Belt"]),
  };
  const state = { tab: "metrics", metric: "offense_identity", conference: "ALL", sample: "qualified", selectedTeam: "", historyTeam: "" };
  let snapshots = [];

  const metric = (label, unit, better, read, sample) => ({ label, unit, better, read, sample });
  const advanced = (team, side, field) => advancedMetricsData?.teams?.[team]?.non_garbage?.[side]?.[field];
  const live = (team, side, field) => teams?.[team]?.[side]?.live_2026?.[field] ?? teams?.[team]?.[side]?.[field];
  const indexRow = team => (cfbThiIndexData?.teams ?? []).find(row => row.team === team);
  const intelligence = team => teamIntelligenceData?.teams?.[team]?.splits?.all;
  const plays = team => Math.min(Number(advanced(team, "offense", "n_plays")) || 0, Number(advanced(team, "defense", "n_plays")) || 0);

  const METRICS = {
    offense_identity: {
      label: "Offense · Success vs Explosiveness",
      description: "How consistently an offense stays on schedule versus how often it creates explosive plays.",
      x: metric("Success rate", "%", "higher", team => advanced(team, "offense", "success_rate")),
      y: metric("Explosive-play rate", "%", "higher", team => advanced(team, "offense", "explosive_rate")),
    },
    defense_identity: {
      label: "Defense · Success vs Explosiveness Allowed",
      description: "Lower is better on both axes: sustained efficiency allowed and explosive-play exposure.",
      x: metric("Success rate allowed", "%", "lower", team => advanced(team, "defense", "success_rate")),
      y: metric("Explosive rate allowed", "%", "lower", team => advanced(team, "defense", "explosive_rate")),
    },
    rush_pass: {
      label: "Offense · Rush EPA vs Pass EPA",
      description: "Current-season EPA per play split by rushing and passing offense.",
      x: metric("Rush EPA / play", "EPA", "higher", team => live(team, "offense", "epa_rush")),
      y: metric("Pass EPA / play", "EPA", "higher", team => live(team, "offense", "epa_pass")),
    },
    down_profile: {
      label: "Offense · Early Downs vs Passing Downs",
      description: "Efficiency before obvious passing situations compared with performance after the offense falls behind schedule.",
      x: metric("Early-down EPA", "EPA", "higher", team => advanced(team, "offense", "early_down_epa")),
      y: metric("Passing-down EPA", "EPA", "higher", team => advanced(team, "offense", "passing_down_epa")),
    },
    havoc_profile: {
      label: "Defense · Front Seven vs Secondary Havoc",
      description: "Where disruption is created across the defense. Higher is better on both axes.",
      x: metric("Front-seven havoc", "%", "higher", team => advanced(team, "defense", "front_seven_havoc_rate")),
      y: metric("Secondary havoc", "%", "higher", team => advanced(team, "defense", "secondary_havoc_rate")),
    },
    line_play: {
      label: "Line Play · Offense vs Defense",
      description: "Offensive line yards created compared with line yards conceded by the defense.",
      x: metric("Offensive line yards / rush", "YDS", "higher", team => advanced(team, "offense", "line_yards_per_rush")),
      y: metric("Defensive line yards allowed", "YDS", "lower", team => advanced(team, "defense", "line_yards_per_rush")),
    },
    power_form: {
      label: "THI · Power vs Current Form",
      description: "Predictive neutral-field strength compared with opponent-adjusted current-season performance.",
      x: metric("THI Power rating", "PTS", "higher", team => indexRow(team)?.power_score),
      y: metric("Current Form percentile", "PCTL", "higher", team => indexRow(team)?.components?.observed_efficiency?.percentile),
    },
    resume_form: {
      label: "THI · Résumé vs Current Form",
      description: "Season accomplishment compared with how strongly the team is currently playing.",
      x: metric("Résumé percentile", "PCTL", "higher", team => indexRow(team)?.components?.resume?.percentile),
      y: metric("Current Form percentile", "PCTL", "higher", team => indexRow(team)?.components?.observed_efficiency?.percentile),
    },
    luck_quality: {
      label: "Underlying Quality · Net EPA vs Scoreboard Luck",
      description: "Observed efficiency compared with the gap between actual and underlying scoring margins.",
      x: metric("Net EPA / play", "EPA", "higher", team => intelligence(team)?.net_epa_per_play),
      y: metric("Scoreboard luck / game", "PTS", "neutral", team => intelligence(team)?.luck?.luck_per_game),
    },
    finishing_drives: {
      label: "Offense · Opportunity Rate vs Finishing",
      description: "How often an offense reaches scoring territory and how many points it produces per opportunity.",
      x: metric("Scoring-opportunity rate", "%", "higher", team => advanced(team, "offense", "opportunity_rate")),
      y: metric("Points / opportunity", "PTS", "higher", team => advanced(team, "offense", "points_per_opportunity")),
    },
  };

  const finite = value => Number.isFinite(Number(value));
  const esc = value => escapeHtml(String(value ?? ""));
  const conference = team => teams?.[team]?.conference || thiObservedRatingsData?.teams?.[team]?.conference || "FBS Independents";
  const qualifiesConference = team => state.conference === "ALL" || (GROUPS[state.conference] ? GROUPS[state.conference].has(conference(team)) : conference(team) === state.conference);
  const fmt = (value, unit) => {
    if (!finite(value)) return "—";
    const digits = unit === "%" || unit === "PCTL" || unit === "PTS" || unit === "YDS" ? 1 : 3;
    return `${Number(value).toFixed(digits)}${unit === "%" ? "%" : ""}`;
  };
  const median = values => {
    const sorted = values.slice().sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  };
  const extent = (values, unit) => {
    if (unit === "PCTL") return [0, 100];
    let min = Math.min(...values), max = Math.max(...values);
    const padding = Math.max((max - min) * .1, Math.abs(max || 1) * .025, .05);
    if (min === max) { min -= 1; max += 1; } else { min -= padding; max += padding; }
    return [min, max];
  };
  const logo = team => externalRatingsData?.teams?.[team]?.logo || externalRatingsData?.teams?.[team]?.logo_dark || "";
  const initials = team => String(team).split(/\s+/).map(word => word[0]).join("").slice(0, 3).toUpperCase();

  function rowsForMetric(config) {
    return Object.keys(teams ?? {}).map(team => ({
      team, conference: conference(team), x: Number(config.x.read(team)), y: Number(config.y.read(team)), plays: plays(team),
      reliability: thiObservedRatingsData?.teams?.[team]?.reliability?.label || "UNRATED",
    })).filter(row => finite(row.x) && finite(row.y) && qualifiesConference(row.team) && (state.sample !== "qualified" || row.plays >= 100));
  }

  function rankFor(rows, field, better, team) {
    if (better === "neutral") return "Context";
    const sorted = rows.slice().sort((a, b) => (better === "lower" ? a[field] - b[field] : b[field] - a[field]) || a.team.localeCompare(b.team));
    const rank = sorted.findIndex(row => row.team === team) + 1;
    return rank ? `#${rank} of ${sorted.length}` : "—";
  }

  function quadrantLabels(config, plot, xMid, yMid) {
    if (config.x.better === "neutral" || config.y.better === "neutral") return "";
    const xStrong = config.x.better === "higher" ? "right" : "left";
    const yStrong = config.y.better === "higher" ? "top" : "bottom";
    const position = (x, y) => ({
      x: x === "left" ? (plot.left + xMid) / 2 : (xMid + plot.right) / 2,
      y: y === "top" ? (plot.top + yMid) / 2 : (yMid + plot.bottom) / 2,
    });
    const opposite = value => value === "left" ? "right" : value === "right" ? "left" : value === "top" ? "bottom" : "top";
    const labels = [
      [xStrong, yStrong, "STRONG BOTH"],
      [xStrong, opposite(yStrong), "X STRENGTH"],
      [opposite(xStrong), yStrong, "Y STRENGTH"],
      [opposite(xStrong), opposite(yStrong), "DEVELOPING BOTH"],
    ];
    return labels.map(([x, y, label]) => { const p = position(x, y); return `<text x="${p.x}" y="${p.y}" text-anchor="middle" class="thi-explorer-quadrant">${label}</text>`; }).join("");
  }

  function renderMetric() {
    const target = document.getElementById("thi-metric-output");
    if (!target) return;
    const config = METRICS[state.metric];
    const rows = rowsForMetric(config);
    if (!rows.length) { target.innerHTML = `<div class="thi-visual-empty">No teams meet this view's data and sample requirements.</div>`; return; }
    if (!rows.some(row => row.team === state.selectedTeam)) state.selectedTeam = rows[0].team;
    const width = 1000, height = 590, plot = { left: 82, right: 972, top: 34, bottom: 510 };
    const [xMin, xMax] = extent(rows.map(row => row.x), config.x.unit);
    const [yMin, yMax] = extent(rows.map(row => row.y), config.y.unit);
    const sx = value => plot.left + (value - xMin) / (xMax - xMin) * (plot.right - plot.left);
    const sy = value => plot.bottom - (value - yMin) / (yMax - yMin) * (plot.bottom - plot.top);
    const xMedian = median(rows.map(row => row.x)), yMedian = median(rows.map(row => row.y));
    const xTicks = Array.from({ length: 6 }, (_, i) => xMin + (xMax - xMin) * i / 5);
    const yTicks = Array.from({ length: 6 }, (_, i) => yMin + (yMax - yMin) * i / 5);
    const selected = rows.find(row => row.team === state.selectedTeam) || rows[0];
    const points = rows.map(row => {
      const href = logo(row.team);
      const selectedClass = row.team === selected.team ? " selected" : "";
      return `<g class="thi-explorer-point${selectedClass}" data-explorer-team="${esc(row.team)}" tabindex="0" role="button" aria-label="${esc(`${row.team}: ${config.x.label} ${fmt(row.x, config.x.unit)}, ${config.y.label} ${fmt(row.y, config.y.unit)}`)}" transform="translate(${sx(row.x)} ${sy(row.y)})">
        <circle r="11"></circle>${href ? `<image href="${esc(href)}" x="-8" y="-8" width="16" height="16" preserveAspectRatio="xMidYMid meet"></image>` : `<text text-anchor="middle" y="3">${esc(initials(row.team))}</text>`}
        <title>${esc(row.team)} · ${esc(fmt(row.x, config.x.unit))} / ${esc(fmt(row.y, config.y.unit))}</title></g>`;
    }).join("");
    target.innerHTML = `<div class="thi-explorer-frame">
      <svg class="thi-explorer-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(config.label)} cross-team comparison">
        ${xTicks.map(value => `<line x1="${sx(value)}" y1="${plot.top}" x2="${sx(value)}" y2="${plot.bottom}" class="thi-explorer-grid"></line><text x="${sx(value)}" y="${plot.bottom + 24}" text-anchor="middle" class="thi-explorer-axis">${esc(fmt(value, config.x.unit))}</text>`).join("")}
        ${yTicks.map(value => `<line x1="${plot.left}" y1="${sy(value)}" x2="${plot.right}" y2="${sy(value)}" class="thi-explorer-grid"></line><text x="${plot.left - 12}" y="${sy(value) + 4}" text-anchor="end" class="thi-explorer-axis">${esc(fmt(value, config.y.unit))}</text>`).join("")}
        <line x1="${sx(xMedian)}" y1="${plot.top}" x2="${sx(xMedian)}" y2="${plot.bottom}" class="thi-explorer-median"></line>
        <line x1="${plot.left}" y1="${sy(yMedian)}" x2="${plot.right}" y2="${sy(yMedian)}" class="thi-explorer-median"></line>
        ${quadrantLabels(config, plot, sx(xMedian), sy(yMedian))}${points}
        <text x="${(plot.left + plot.right) / 2}" y="566" text-anchor="middle" class="thi-explorer-axis-title">${esc(config.x.label.toUpperCase())}</text>
        <text x="20" y="${(plot.top + plot.bottom) / 2}" text-anchor="middle" transform="rotate(-90 20 ${(plot.top + plot.bottom) / 2})" class="thi-explorer-axis-title">${esc(config.y.label.toUpperCase())}</text>
      </svg>
      <div class="thi-explorer-detail" aria-live="polite">
        <div><span>Selected team</span><strong>${esc(selected.team)} · ${esc(selected.conference)}</strong></div>
        <div><span>${esc(config.x.label)}</span><strong>${esc(fmt(selected.x, config.x.unit))} · ${esc(rankFor(rows, "x", config.x.better, selected.team))}</strong></div>
        <div><span>${esc(config.y.label)}</span><strong>${esc(fmt(selected.y, config.y.unit))} · ${esc(rankFor(rows, "y", config.y.better, selected.team))}</strong></div>
        <div><span>Sample reliability</span><strong>${esc(selected.reliability)} · ${selected.plays || "—"} plays</strong></div>
      </div></div>
      <p class="thi-explorer-method">${esc(config.description)} Median lines are calculated from the visible sample. This is a descriptive THI research view and does not alter Model A.</p>`;
  }

  function historyEntries(team) {
    const entries = snapshots.map(payload => {
      const profile = payload?.teams?.[team];
      const net = profile?.ratings?.net;
      return net && finite(net.value) ? { week: Number(payload.meta?.through_week), value: Number(net.value), rank: Number(net.rank), reliability: profile.reliability } : null;
    }).filter(Boolean).sort((a, b) => a.week - b.week);
    const current = thiObservedRatingsData?.teams?.[team];
    const net = current?.ratings?.net;
    const week = Number(thiObservedRatingsData?.meta?.through_week);
    if (net && finite(net.value) && !entries.some(row => row.week === week)) entries.push({ week, value: Number(net.value), rank: Number(net.rank), reliability: current.reliability });
    return entries;
  }

  function renderHistory() {
    const target = document.getElementById("thi-history-output");
    if (!target) return;
    const teamsAvailable = (thiPowerRatingsData?.teams ?? []).map(row => row.team).sort();
    if (!state.historyTeam || !teamsAvailable.includes(state.historyTeam)) state.historyTeam = thiPowerRatingsData?.teams?.[0]?.team || teamsAvailable[0];
    const entries = historyEntries(state.historyTeam);
    if (entries.length < 2) { target.innerHTML = `<div class="thi-visual-empty">Weekly history is still building for ${esc(state.historyTeam)}.</div>`; return; }
    const width = 760, height = 390, plot = { left: 60, right: 730, top: 34, bottom: 320 };
    const [yMin, yMax] = extent(entries.map(row => row.value));
    const minWeek = Math.min(...entries.map(row => row.week)), maxWeek = Math.max(...entries.map(row => row.week));
    const sx = week => plot.left + (week - minWeek) / Math.max(1, maxWeek - minWeek) * (plot.right - plot.left);
    const sy = value => plot.bottom - (value - yMin) / (yMax - yMin) * (plot.bottom - plot.top);
    const yTicks = Array.from({ length: 5 }, (_, i) => yMin + (yMax - yMin) * i / 4);
    const points = entries.map(row => `${sx(row.week)},${sy(row.value)}`).join(" ");
    const power = (thiPowerRatingsData?.teams ?? []).find(row => row.team === state.historyTeam) || {};
    const priorRankRows = (thiPowerRatingsData?.teams ?? []).filter(row => finite(row.previous_week_same_model_rating)).slice().sort((a,b) => b.previous_week_same_model_rating - a.previous_week_same_model_rating);
    const priorRank = priorRankRows.findIndex(row => row.team === state.historyTeam) + 1;
    const latest = entries.at(-1), first = entries[0];
    target.innerHTML = `<div class="thi-history-layout"><div class="thi-history-chart">
      <svg class="thi-history-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(state.historyTeam)} weekly current form history">
        ${yTicks.map(value => `<line x1="${plot.left}" y1="${sy(value)}" x2="${plot.right}" y2="${sy(value)}" class="thi-explorer-grid"></line><text x="${plot.left - 10}" y="${sy(value) + 4}" text-anchor="end" class="thi-explorer-axis">${value.toFixed(1)}</text>`).join("")}
        ${entries.map(row => `<text x="${sx(row.week)}" y="${plot.bottom + 24}" text-anchor="middle" class="thi-explorer-axis">W${row.week}</text>`).join("")}
        <polyline points="${points}" class="thi-history-line"></polyline>
        ${entries.map(row => `<circle cx="${sx(row.week)}" cy="${sy(row.value)}" r="6" class="thi-history-dot"><title>Week ${row.week}: ${row.value.toFixed(1)}, rank #${row.rank}</title></circle><text x="${sx(row.week)}" y="${sy(row.value) - 12}" text-anchor="middle" class="thi-history-rank">#${row.rank}</text>`).join("")}
        <text x="${(plot.left + plot.right) / 2}" y="374" text-anchor="middle" class="thi-explorer-axis-title">WEEKLY OPPONENT-ADJUSTED CURRENT FORM</text>
      </svg></div>
      <aside class="thi-history-side">
        <div class="thi-history-card"><span>Current Form</span><strong>${latest.value.toFixed(1)} · #${latest.rank}</strong><small>${esc(latest.reliability?.label || "—")} · ${esc(latest.reliability?.games ?? "—")} games</small></div>
        <div class="thi-history-card"><span>Since first snapshot</span><strong>${latest.value - first.value >= 0 ? "+" : ""}${(latest.value - first.value).toFixed(1)}</strong><small>Week ${first.week} to Week ${latest.week}</small></div>
        <div class="thi-history-card"><span>THI Power</span><strong>${finite(power.rating) ? Number(power.rating).toFixed(1) : "—"} · #${power.rank || "—"}</strong><small>Predictive neutral-field rating</small></div>
        <div class="thi-history-card"><span>Prior comparable Power</span><strong>${finite(power.previous_week_same_model_rating) ? Number(power.previous_week_same_model_rating).toFixed(1) : "—"} · #${priorRank || "—"}</strong><small>Recomputed with the same fitted model</small></div>
      </aside></div>
      <p class="thi-explorer-method">Current Form history uses immutable weekly THI Observed snapshots. THI Power shows the current rating and its same-model prior-week comparison; it is not presented as a longer frozen series.</p>`;
  }

  function renderPanel() {
    const metricPanel = document.getElementById("thi-metric-panel");
    const historyPanel = document.getElementById("thi-history-panel");
    if (!metricPanel || !historyPanel) return;
    metricPanel.hidden = state.tab !== "metrics";
    historyPanel.hidden = state.tab !== "history";
    document.querySelectorAll(".thi-visual-tab").forEach(button => button.classList.toggle("active", button.dataset.visualTab === state.tab));
    if (state.tab === "metrics") renderMetric(); else renderHistory();
  }

  async function loadSnapshots() {
    const through = Number(thiObservedRatingsData?.meta?.through_week) || 0;
    const version = String(thiObservedRatingsData?.meta?.version || "0.1.2").replaceAll(".", "_");
    const results = await Promise.allSettled(Array.from({ length: through }, (_, index) => loadJson(`./data/ratings_snapshots/2026_week_${index + 1}_v${version}.json`)));
    snapshots = results.filter(result => result.status === "fulfilled" && result.value?.teams).map(result => result.value);
    if (state.tab === "history") renderHistory();
  }

  function init() {
    const pulse = document.querySelector("#thi-ratings-container .thi-weekly-pulse");
    if (!pulse || document.getElementById("thi-visual-suite")) return;
    const conferences = [...new Set(Object.keys(teams ?? {}).map(conference))].sort((a,b) => a.localeCompare(b));
    const defaultTeam = thiPowerRatingsData?.teams?.[0]?.team || Object.keys(teams ?? {})[0] || "";
    state.selectedTeam = defaultTeam;
    state.historyTeam = defaultTeam;
    const section = document.createElement("section");
    section.id = "thi-visual-suite";
    section.className = "thi-visual-suite";
    section.innerHTML = `<header class="thi-visual-suite-head"><div><div class="eyebrow">THI Visual Research</div><h2>See how teams win</h2><p>Explore THI's own efficiency, style, rating and context data across the FBS. Every view keeps descriptive evidence separate from Model A.</p></div>
      <div class="thi-visual-tabs" role="tablist"><button class="thi-visual-tab active" type="button" data-visual-tab="metrics">Metric Explorer</button><button class="thi-visual-tab" type="button" data-visual-tab="history">Rating History</button></div></header>
      <div class="thi-visual-panel" id="thi-metric-panel"><div class="thi-visual-controls">
        <div class="thi-visual-control"><label for="thi-explorer-metric">Comparison</label><select id="thi-explorer-metric">${Object.entries(METRICS).map(([key,value]) => `<option value="${key}">${esc(value.label)}</option>`).join("")}</select></div>
        <div class="thi-visual-control"><label for="thi-explorer-conference">Conference</label><select id="thi-explorer-conference"><option value="ALL">All FBS</option><option value="P4">Power 4</option><option value="G6">Group of Six</option>${conferences.map(name => `<option value="${esc(name)}">${esc(name)}</option>`).join("")}</select></div>
        <div class="thi-visual-control"><label for="thi-explorer-sample">Sample</label><select id="thi-explorer-sample"><option value="qualified">100+ plays per side</option><option value="all">All available</option></select></div>
      </div><div id="thi-metric-output"></div></div>
      <div class="thi-visual-panel" id="thi-history-panel" hidden><div class="thi-visual-controls"><div class="thi-visual-control"><label for="thi-history-team">Team</label><select id="thi-history-team">${(thiPowerRatingsData?.teams ?? []).map(row => `<option value="${esc(row.team)}">#${row.rank} ${esc(row.team)}</option>`).join("")}</select></div></div><div id="thi-history-output"><div class="thi-visual-empty">Loading weekly rating history…</div></div></div>`;
    pulse.insertAdjacentElement("afterend", section);
    section.addEventListener("click", event => {
      const tab = event.target.closest("[data-visual-tab]");
      if (tab) { state.tab = tab.dataset.visualTab; renderPanel(); return; }
      const point = event.target.closest("[data-explorer-team]");
      if (point) { state.selectedTeam = point.dataset.explorerTeam; renderMetric(); }
    });
    section.addEventListener("keydown", event => {
      const point = event.target.closest("[data-explorer-team]");
      if (point && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); state.selectedTeam = point.dataset.explorerTeam; renderMetric(); }
    });
    section.querySelector("#thi-explorer-metric").addEventListener("change", event => { state.metric = event.target.value; renderMetric(); });
    section.querySelector("#thi-explorer-conference").addEventListener("change", event => { state.conference = event.target.value; renderMetric(); });
    section.querySelector("#thi-explorer-sample").addEventListener("change", event => { state.sample = event.target.value; renderMetric(); });
    section.querySelector("#thi-history-team").addEventListener("change", event => { state.historyTeam = event.target.value; renderHistory(); });
    renderMetric();
    loadSnapshots();
  }

  document.addEventListener("hammer:data-ready", () => requestAnimationFrame(init));
})();
