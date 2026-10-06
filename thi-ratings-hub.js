/* THI's independent research surface. Reads the existing display-only ratings. */
(() => {
  let search = "";
  let sort = "power_rank";
  let sortDirection = "asc";
  let conferenceFilter = "ALL";
  const RATING_CONFERENCE_GROUPS = {
    P4: new Set(["ACC", "Big 12", "Big Ten", "SEC"]),
    G6: new Set(["American Athletic", "Conference USA", "Mid-American", "Mountain West", "Pac-12", "Sun Belt"]),
  };

  function matchesRatingConference(profile) {
    const conference = profile.conference || teams[profile.team]?.conference || "FBS Independents";
    return conferenceFilter === "ALL" || (RATING_CONFERENCE_GROUPS[conferenceFilter]
      ? RATING_CONFERENCE_GROUPS[conferenceFilter].has(conference)
      : conference === conferenceFilter);
  }
  let situationalData = null;
  let teamIntelligenceData = null;
  let gameTypeSplit = "all";
  let selectedTeam = "";

  const style = document.createElement("style");
  style.textContent = `
    .thi-hub-intro { max-width:850px; line-height:1.6; }
    .thi-ratings-difference {
      display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px;
      max-width:980px; margin:16px 0 22px; padding:13px;
      border:1px solid var(--border); border-radius:11px; background:var(--surface-soft);
    }
    .thi-ratings-difference > div { display:grid; gap:4px; min-width:0; }
    .thi-ratings-difference strong { font-size:12px; }
    .thi-ratings-difference span { color:var(--muted); font-size:11px; line-height:1.5; }
    .thi-ratings-difference p {
      grid-column:1/-1; margin:2px 0 0; padding-top:10px; border-top:1px solid var(--border);
      color:var(--muted); font:700 9px/1.5 var(--mono); text-transform:uppercase;
    }
    .thi-hub-controls { flex-wrap:wrap; }
    .thi-hub-control-group { display:flex; align-items:center; gap:10px; }
    .thi-hub-search { min-width:210px; }
    .thi-hub-note { font-size:12px; line-height:1.55; color:var(--muted); margin:0 0 18px; }
    .thi-hub-table-wrap { overflow-x:auto; border:1px solid var(--border); border-radius:12px; background:var(--surface); }
    .thi-hub-table { width:100%; border-collapse:collapse; }
    .thi-hub-table th, .thi-hub-table td { text-align:left; padding:14px 16px; border-bottom:1px solid var(--border); }
    .thi-hub-table th { font:600 11px var(--mono); letter-spacing:.05em; color:var(--muted); white-space:nowrap; }
    .thi-hub-sort-button { display:inline-flex; align-items:center; gap:3px; border:0; padding:0; background:transparent; color:inherit; font:inherit; letter-spacing:inherit; cursor:pointer; }
    .thi-hub-sort-button:hover, .thi-hub-sort-button:focus-visible { color:var(--text); text-decoration:underline; }
    .thi-hub-sort-arrow { display:inline-flex; align-items:center; justify-content:center; width:9px; height:13px; margin-left:1px; color:var(--muted-light); font-family:var(--mono); font-size:9px; font-weight:700; opacity:.55; }
    .thi-hub-sort-button.active .thi-hub-sort-arrow { color:var(--green); opacity:1; }
    .thi-hub-table tr:last-child td { border-bottom:0; }
    .thi-hub-table tbody tr:hover { background:#f6f8f5; }
    .thi-hub-team { border:0; background:transparent; padding:0; color:var(--text); font-family:inherit; font-size:14px; font-weight:700; cursor:pointer; text-align:left; }
    .thi-hub-team:hover { text-decoration:underline; }
    .thi-hub-team-wrap { display:inline-flex; align-items:center; gap:8px; vertical-align:middle; }
    .thi-hub-team-wrap .team-logo { flex:0 0 auto; }
    .thi-hub-number { font:700 14px var(--mono); white-space:nowrap; }
    .thi-hub-muted { color:var(--muted); font-size:11px; white-space:nowrap; }
    .thi-hub-rank { color:var(--muted); font:600 11px var(--mono); }
    .thi-hub-heat { transition:background-color .18s ease; }
    .thi-hub-heat.positive { background:rgba(31,158,92,var(--heat-alpha,.10)); }
    .thi-hub-heat.negative { background:rgba(214,74,67,var(--heat-alpha,.10)); }
    .thi-hub-heat.context { background:rgba(61,126,176,var(--heat-alpha,.10)); }
    .thi-hub-rank-move { display:inline-flex; margin-left:6px; font:700 10px var(--mono); }
    .thi-hub-rank-move.up { color:#16734f; }
    .thi-hub-rank-move.down { color:#a44842; }
    .thi-weekly-pulse { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin:4px 0 16px; }
    .thi-weekly-pulse-card { min-width:0; border:1px solid var(--border); border-radius:11px; padding:14px 15px; background:var(--surface); }
    .thi-weekly-pulse-label { color:var(--muted); font:700 9px var(--mono); letter-spacing:.8px; text-transform:uppercase; }
    .thi-weekly-pulse-team { display:flex; align-items:center; gap:8px; margin-top:9px; font-size:15px; font-weight:800; }
    .thi-weekly-pulse-value { margin-top:6px; color:var(--muted); font:700 11px var(--mono); }
    .thi-weekly-pulse-card.riser .thi-weekly-pulse-value { color:#16734f; }
    .thi-weekly-pulse-card.faller .thi-weekly-pulse-value { color:#a44842; }
    .thi-decomposition { margin:4px 0 16px; padding:16px; border:1px solid var(--border); border-radius:12px; background:var(--surface); }
    .thi-decomposition-head { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; }
    .thi-decomposition-head h2 { margin:4px 0 0; font-size:20px; }
    .thi-decomposition-stamp { color:var(--muted); font:600 10px/1.5 var(--mono); text-align:right; }
    .thi-decomposition-lenses { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:9px; margin-top:14px; }
    .thi-decomposition-lens { border:1px solid var(--border); border-radius:9px; padding:12px; min-width:0; }
    .thi-decomposition-lens span { color:var(--muted); font:700 9px/1.4 var(--mono); letter-spacing:.7px; text-transform:uppercase; }
    .thi-decomposition-lens strong { display:block; margin:6px 0; font-size:13px; }
    .thi-decomposition-lens p { margin:0; color:var(--muted); font-size:11px; line-height:1.5; }
    .thi-conference-strength { display:flex; align-items:center; flex-wrap:wrap; gap:8px 14px; margin-top:12px; padding-top:12px; border-top:1px solid var(--border); color:var(--muted); font:600 10px/1.5 var(--mono); }
    .thi-conference-strength strong { color:var(--text); }
    .thi-conference-strength span { white-space:nowrap; }
    .thi-hub-badge { display:inline-block; border:1px solid var(--border); border-radius:40px; padding:4px 8px; font:600 10px var(--mono); }
    .thi-hub-badge.strong { color:#12694d; background:#e8f7ef; }
    .thi-hub-badge.limited { color:#815b08; background:#fff4d6; }
    .thi-hub-provisional { margin-top:18px; }
    .thi-hub-provisional summary { cursor:pointer; font-size:14px; font-weight:700; margin-bottom:10px; }
    .thi-hub-provisional p { color:var(--muted); font-size:12px; line-height:1.55; margin:0 0 12px; }
    .thi-hub-method { margin-top:18px; border:1px solid var(--border); border-radius:10px; padding:16px; color:var(--muted); font-size:13px; line-height:1.6; }
    .thi-hub-method summary { color:var(--text); font-weight:700; cursor:pointer; }
    .thi-situational-panel { border:1px solid var(--border); border-radius:12px; background:var(--surface); margin:8px 0 18px; padding:18px; }
    .thi-situational-header { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; align-items:baseline; }
    .thi-situational-header h2 { margin:0; font-size:19px; }
    .thi-situational-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin-top:14px; }
    .thi-situational-card { border:1px solid var(--border); border-radius:9px; padding:14px; min-width:0; }
    .thi-situational-card h3 { font-size:13px; margin:0 0 12px; }
    .thi-situational-line { display:flex; align-items:baseline; justify-content:space-between; gap:6px; padding:6px 0; border-top:1px solid var(--border); }
    .thi-situational-line strong { font:700 15px var(--mono); }
    .thi-situational-line span { color:var(--muted); font-size:12px; }
    .thi-situational-sample { color:var(--muted); font-size:11px; line-height:1.5; margin-top:4px; }
    .thi-situational-explainer { margin:12px 0 0; color:var(--muted); font-size:12px; line-height:1.55; }
    @media (max-width:700px) {
      .thi-hub-table thead { display:none; }
      .thi-hub-table tbody tr { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); padding:14px; gap:10px 16px; border-bottom:1px solid var(--border); }
      .thi-hub-table td { padding:0; border:0; min-width:0; }
      .thi-hub-table td:first-child { grid-column:1/-1; }
      .thi-hub-table td[data-label]::before { content:attr(data-label); display:block; color:var(--muted); font:600 10px var(--mono); margin-bottom:3px; }
      .thi-hub-controls { align-items:stretch; }
      .thi-hub-control-group { width:100%; }
      .thi-hub-control-group .conference-filter-select { flex:1 1 auto; min-width:0; }
      .thi-situational-grid { grid-template-columns:1fr; }
      .thi-weekly-pulse { grid-template-columns:1fr; }
      .thi-ratings-difference { grid-template-columns:1fr; }
      .thi-decomposition-head { display:block; }
      .thi-decomposition-stamp { margin-top:7px; text-align:left; }
      .thi-decomposition-lenses { grid-template-columns:1fr; }
    }
    @media (min-width:701px) and (max-width:1050px) { .thi-decomposition-lenses { grid-template-columns:repeat(2,minmax(0,1fr)); } }
  `;
  document.head.appendChild(style);

  const nav = document.querySelector(".main-nav");
  const ratingsButton = nav?.querySelector('[data-view="ratings"]');
  const section = document.getElementById("view-ratings");
  if (!nav || !section || !ratingsButton) return;

  ratingsButton.textContent = "Team Data";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "nav-item";
  button.textContent = "THI Ratings";
  button.dataset.view = "thi-ratings";
  button.addEventListener("click", () => switchView("thi-ratings"));
  ratingsButton.after(button);

  const view = document.createElement("section");
  view.id = "view-thi-ratings";
  view.className = "view";
  view.innerHTML = `
    <div class="eyebrow">Calculated by The Hammer Index</div>
    <h1 class="page-title">THI Ratings</h1>
    <p class="page-subtitle thi-hub-intro">An independent power rating combining roster strength, completed-game results and opponent-adjusted performance. Compare teams here or open a Team Dossier for the complete breakdown.</p>
    <div class="thi-ratings-difference" aria-label="Difference between Team Data and THI Ratings">
      <div><strong>Team Data</strong><span>Observed efficiency, schedule and resume context, market performance, and team dossiers.</span></div>
      <div><strong>THI Ratings</strong><span>THI's predictive weekly power order, blending roster foundation with opponent-adjusted performance and results.</span></div>
      <p>Both are independent research layers. Model A projections remain separately frozen.</p>
    </div>
    <div id="thi-ratings-container" aria-live="polite"></div>`;
  section.after(view);

  function ratingValue(profile, key) {
    const raw = profile.ratings?.[key]?.value;
    if (raw === null || raw === undefined || raw === "") return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  }

  function priorRankMap() {
    const rows = (thiPowerRatingsData?.teams ?? [])
      .filter(row => Number.isFinite(Number(row.previous_week_same_model_rating)))
      .slice()
      .sort((a, b) => Number(b.previous_week_same_model_rating) - Number(a.previous_week_same_model_rating) || a.team.localeCompare(b.team));
    return new Map(rows.map((row, index) => [row.team, index + 1]));
  }

  function weeklyPulseMarkup() {
    const power = thiPowerRatingsData?.teams ?? [];
    const previous = priorRankMap();
    const movement = power.map(row => ({
      ...row,
      priorRank: previous.get(row.team),
      spots: Number(previous.get(row.team)) - Number(row.rank),
    })).filter(row => Number.isFinite(row.spots));
    const riser = movement.slice().sort((a, b) => b.spots - a.spots || a.rank - b.rank)[0];
    const faller = movement.slice().sort((a, b) => a.spots - b.spots || a.rank - b.rank)[0];
    const schedule = power.map(row => ({
      ...row,
      sosRank: Number(externalRatingsData?.teams?.[row.team]?.sos_rank),
    })).filter(row => Number.isFinite(row.sosRank)).sort((a, b) => a.sosRank - b.sosRank || a.rank - b.rank)[0];
    const card = (kind, label, row, value) => `<article class="thi-weekly-pulse-card ${kind}">
      <div class="thi-weekly-pulse-label">${escapeHtml(label)}</div>
      <div class="thi-weekly-pulse-team">${row ? teamLogoMarkup(row.team, "projection") : ""}<span>${escapeHtml(row?.team ?? "Awaiting data")}</span></div>
      <div class="thi-weekly-pulse-value">${escapeHtml(value)}</div>
    </article>`;
    return `<div class="thi-weekly-pulse" aria-label="Weekly THI ratings movement">
      ${card("riser", "Biggest Riser", riser, riser ? `${riser.spots > 0 ? "+" : ""}${riser.spots} spots · now #${riser.rank}` : "—")}
      ${card("schedule", "Toughest Schedule", schedule, schedule ? `SOS #${schedule.sosRank} · THI #${schedule.rank}` : "—")}
      ${card("faller", "Biggest Faller", faller, faller ? `${faller.spots > 0 ? "+" : ""}${faller.spots} spots · now #${faller.rank}` : "—")}
    </div>`;
  }

  function heatStyle(values, value, direction = "higher") {
    const clean = values.map(Number).filter(Number.isFinite).sort((a, b) => a - b);
    const numeric = Number(value);
    if (!clean.length || !Number.isFinite(numeric)) return { className: "", style: "" };
    const below = clean.filter(item => item < numeric).length;
    const equal = clean.filter(item => item === numeric).length;
    let percentile = clean.length === 1 ? .5 : (below + Math.max(0, equal - 1) / 2) / (clean.length - 1);
    if (direction === "lower") percentile = 1 - percentile;
    if (direction === "context") {
      const alpha = (.06 + .18 * percentile).toFixed(3);
      return { className: "thi-hub-heat context", style: `--heat-alpha:${alpha}` };
    }
    const positive = percentile >= .5;
    const strength = Math.abs(percentile - .5) * 2;
    const alpha = (.035 + .22 * strength).toFixed(3);
    return { className: `thi-hub-heat ${positive ? "positive" : "negative"}`, style: `--heat-alpha:${alpha}` };
  }

  function metricCell(label, display, value, values, direction = "higher") {
    const heat = heatStyle(values, value, direction);
    return `<td data-label="${escapeHtml(label)}" class="${heat.className}" style="${heat.style}"><span class="thi-hub-number">${display}</span></td>`;
  }

  function modelARating(teamName) {
    const value = Number(teams?.[teamName]?.power_rating);
    return Number.isFinite(value) ? value : null;
  }

  function opponentQualityRecord(teamName, topRanks) {
    let wins = 0, losses = 0;
    (scheduleData?.games ?? []).forEach(game => {
      if (game.status !== "completed") return;
      const isHome = game.home_team === teamName;
      const isAway = game.away_team === teamName;
      if (!isHome && !isAway) return;
      const opponent = isHome ? game.away_team : game.home_team;
      if (!topRanks.has(opponent)) return;
      const own = Number(isHome ? game.home_points : game.away_points);
      const other = Number(isHome ? game.away_points : game.home_points);
      if (!Number.isFinite(own) || !Number.isFinite(other) || own === other) return;
      if (own > other) wins += 1; else losses += 1;
    });
    return `${wins}-${losses}`;
  }

  function ratingTimestamp() {
    const raw = thiPowerRatingsData?.meta?.generated_at;
    if (!raw) return "Timestamp unavailable";
    const parsed = new Date(raw);
    return Number.isNaN(parsed.getTime()) ? String(raw) : new Intl.DateTimeFormat("en-US", { dateStyle:"medium", timeStyle:"short" }).format(parsed);
  }

  function conferenceStrengthRows() {
    const groups = new Map();
    (thiPowerRatingsData?.teams ?? []).forEach(row => {
      const conference = teams?.[row.team]?.conference || "FBS Independents";
      if (!groups.has(conference)) groups.set(conference, []);
      if (Number.isFinite(Number(row.rating))) groups.get(conference).push(Number(row.rating));
    });
    return [...groups.entries()].map(([conference, values]) => {
      const ordered = values.slice().sort((a,b) => a-b);
      const trim = ordered.length >= 6 ? ordered.slice(1,-1) : ordered;
      return {
        conference,
        average: ordered.reduce((sum,value) => sum+value,0) / Math.max(1,ordered.length),
        robust: trim.reduce((sum,value) => sum+value,0) / Math.max(1,trim.length),
        win50: ordered[Math.floor(ordered.length/2)],
      };
    }).sort((a,b) => b.robust-a.robust);
  }

  function decompositionMarkup() {
    const conferences = conferenceStrengthRows().slice(0,6);
    const lens = (label, title, copy) => `<article class="thi-decomposition-lens"><span>${escapeHtml(label)}</span><strong>${escapeHtml(title)}</strong><p>${escapeHtml(copy)}</p></article>`;
    return `<section class="thi-decomposition" aria-label="THI rating decomposition">
      <div class="thi-decomposition-head"><div><div class="eyebrow">THI Rating Decomposition</div><h2>Five lenses, one transparent rating page</h2></div><div class="thi-decomposition-stamp">Through Week ${escapeHtml(thiPowerRatingsData?.meta?.through_week ?? "—")}<br>Rated ${escapeHtml(ratingTimestamp())}</div></div>
      <div class="thi-decomposition-lenses">
        ${lens("Overall", "THI blended rating", "Roster foundation, completed-game results and opponent-adjusted performance on a scoring-margin scale.")}
        ${lens("Predictive", "Model A power rating", "The production rating in CFB Metrics that currently powers published game projections.")}
        ${lens("Recent form", "Performance contribution", "Current-season opponent-adjusted performance within the research rating; compare it with Overall to spot disagreement.")}
        ${lens("Schedule", "SOS + quality record", "External schedule rank plus the team's completed record against the current THI top 25.")}
        ${lens("Home advantage", "Team-specific points", "The production home edge used by Model A; neutral-site games receive zero.")}
      </div>
      <div class="thi-conference-strength"><strong>Conference strength · neutral-field team benchmark</strong>${conferences.map(row => `<span>${escapeHtml(row.conference)} <b>${formatSigned(row.robust,1)}</b> robust · ${formatSigned(row.win50,1)} WIN50</span>`).join("")}</div>
    </section>`;
  }

  function numericCellValue(cell) {
    const match = String(cell?.textContent ?? "").replaceAll(",", "").match(/[+-]?\d+(?:\.\d+)?/);
    return match ? Number(match[0]) : null;
  }

  function formatAxisNumber(value, digits = 2) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits) : "—";
  }

  function applyTeamDataExperience() {
    const container = document.getElementById("ratings-container");
    if (!container || !thiPowerRatingsData?.teams?.length) return;
    if (!container.querySelector(".thi-weekly-pulse")) {
      container.insertAdjacentHTML("afterbegin", weeklyPulseMarkup());
    }
    container.querySelectorAll("table").forEach(table => {
      const headers = Array.from(table.querySelectorAll("thead th")).map(cell => cell.textContent.trim());
      const rows = Array.from(table.querySelectorAll("tbody tr"));
      headers.forEach((header, column) => {
        if (/rank|team|conference|record|read|status|home|away|favorite|underdog|tier|signal/i.test(header)) return;
        const cells = rows.map(row => row.children[column]).filter(Boolean);
        const values = cells.map(numericCellValue).filter(Number.isFinite);
        if (values.length < Math.max(3, Math.ceil(cells.length * .6))) return;
        const direction = /pace|plays|games|sample|schedule|sos/i.test(header)
          ? "context"
          : /defensive rating|def rating/i.test(header) ? "lower" : "higher";
        cells.forEach(cell => {
          const heat = heatStyle(values, numericCellValue(cell), direction);
          cell.classList.remove("thi-hub-heat", "positive", "negative", "context");
          if (heat.className) cell.classList.add(...heat.className.split(" "));
          if (heat.style) cell.style.setProperty("--heat-alpha", heat.style.split(":")[1]);
        });
      });
    });
  }

  const teamDataContainer = document.getElementById("ratings-container");
  if (teamDataContainer) {
    new MutationObserver(() => requestAnimationFrame(applyTeamDataExperience))
      .observe(teamDataContainer, { childList: true, subtree: true });
  }

  function sortHeader(key, label, defaultDirection = "desc") {
    const active = sort === key;
    const direction = active ? sortDirection : defaultDirection;
    const arrow = active ? (direction === "asc" ? "↑" : "↓") : "↕";
    return `<th aria-sort="${active ? (direction === "asc" ? "ascending" : "descending") : "none"}">
      <button type="button" class="thi-hub-sort-button ${active ? "active" : ""}" data-thi-sort="${key}"
        data-thi-direction="${defaultDirection}" aria-label="Sort by ${label.toLowerCase()}">${label}${active ? `<span class="thi-hub-sort-arrow" aria-hidden="true">${arrow}</span>` : ""}</button>
    </th>`;
  }

  function renderRows() {
    const target = document.getElementById("thi-ratings-rows");
    if (!target) return;
    const query = search.trim().toLocaleLowerCase();
    const observed = thiObservedRatingsData?.teams ?? {};
    const topRanks = new Set((thiPowerRatingsData?.teams ?? []).filter(row => Number(row.rank) <= 25).map(row => row.team));
    const sourceData = (thiPowerRatingsData?.teams ?? []).map(power => {
      const profile = observed[power.team] ?? {};
      const intelligence = teamIntelligenceData?.teams?.[power.team]?.splits?.[gameTypeSplit] ?? {};
      const sosRank = Number(externalRatingsData?.teams?.[power.team]?.sos_rank);
      const hfa = Number(hfaData?.teams?.[power.team] ?? hfaData?.meta?.default_hfa);
      return {
        power, profile, intelligence, team: power.team,
        conference: profile.conference || teams[power.team]?.conference || "FBS Independents",
        predictive: modelARating(power.team),
        sosRank: Number.isFinite(sosRank) ? sosRank : null,
        hfa: Number.isFinite(hfa) ? hfa : null,
        qualityRecord: opponentQualityRecord(power.team, topRanks),
      };
    });
    const data = sourceData.filter(row => matchesRatingConference(row) && String(row.team).toLocaleLowerCase().includes(query));
    data.sort((a, b) => {
      const value = row => {
        if (sort === "team") return row.team;
        if (sort === "power_rank") return Number(row.power.rank);
        if (sort === "predictive") return Number(row.predictive);
        if (sort === "recent") return Number(row.power.performance_contribution);
        if (sort === "sos") return Number(row.sosRank);
        if (sort === "hfa") return Number(row.hfa);
        if (sort === "split_games") return Number(row.intelligence?.games);
        if (sort === "split_net_epa") return Number(row.intelligence?.net_epa_per_play);
        if (sort === "luck") return Number(row.intelligence?.luck?.net_scoreboard_luck);
        if (sort === "left_on_field") return Number(row.intelligence?.luck?.points_left_on_field);
        if (["offense", "defense", "net", "pace"].includes(sort)) return ratingValue(row.profile, sort);
        return Number(row.power[sort]);
      };
      const av = value(a), bv = value(b);
      if (typeof av === "string" || typeof bv === "string") return String(av).localeCompare(String(bv)) * (sortDirection === "asc" ? 1 : -1);
      const aValid = Number.isFinite(av), bValid = Number.isFinite(bv);
      if (aValid !== bValid) return aValid ? -1 : 1;
      if (!aValid) return a.team.localeCompare(b.team);
      return (av - bv) * (sortDirection === "asc" ? 1 : -1) || a.team.localeCompare(b.team);
    });

    const allValues = key => sourceData.map(row => {
      if (key === "predictive") return row.predictive;
      if (key === "recent") return row.power.performance_contribution;
      if (key === "sos") return row.sosRank;
      if (key === "hfa") return row.hfa;
      if (["offense", "defense", "net", "pace"].includes(key)) return ratingValue(row.profile, key);
      if (key === "split_games") return row.intelligence?.games;
      if (key === "split_net_epa") return row.intelligence?.net_epa_per_play;
      if (key === "luck") return row.intelligence?.luck?.net_scoreboard_luck;
      if (key === "left_on_field") return row.intelligence?.luck?.points_left_on_field;
      return row.power[key];
    });
    const priorRanks = priorRankMap();

    target.innerHTML = data.length ? `<div class="thi-hub-table-wrap"><table class="thi-hub-table">
      <thead><tr>${sortHeader("power_rank", "Rank", "asc")}${sortHeader("team", "Team", "asc")}${sortHeader("rating", "Overall")}${sortHeader("predictive", "Predictive")}${sortHeader("recent", "Recent Form")}${sortHeader("performance_only_weekly_change", "Weekly Δ")}${sortHeader("sos", "SOS", "asc")}<th>vs THI Top 25</th>${sortHeader("hfa", "Home Edge")}</tr></thead>
      <tbody>${data.map(row => {
        const { power, profile } = row;
        const rating = profile.ratings ?? {};
        return `<tr>
          <td data-label="Rank"><span class="thi-hub-number">#${formatNumber(power.rank, 0)}</span>${(() => { const move = Number(priorRanks.get(row.team)) - Number(power.rank); return move ? `<span class="thi-hub-rank-move ${move > 0 ? "up" : "down"}">${move > 0 ? "▲" : "▼"}${Math.abs(move)}</span>` : ""; })()}</td>
          <td data-label="Team"><span class="thi-hub-team-wrap">${teamLogoMarkup(row.team, "projection")}
              <button type="button" class="thi-hub-team" data-thi-team="${escapeHtml(row.team)}">${escapeHtml(row.team)}</button></span></td>
          ${metricCell("Overall", formatAxisNumber(power.rating, 2), power.rating, allValues("rating"))}
          ${metricCell("Predictive", formatAxisNumber(row.predictive, 3), row.predictive, allValues("predictive"))}
          ${metricCell("Recent Form", formatAxisNumber(power.performance_contribution, 2), power.performance_contribution, allValues("recent"))}
          ${metricCell("Weekly Δ", formatAxisNumber(power.performance_only_weekly_change, 2), power.performance_only_weekly_change, allValues("performance_only_weekly_change"))}
          <td data-label="SOS"><span class="thi-hub-rank">${Number.isFinite(row.sosRank) ? `#${row.sosRank}` : "—"}</span></td>
          <td data-label="vs THI Top 25"><span class="thi-hub-number">${escapeHtml(row.qualityRecord)}</span></td>
          ${metricCell("Home Edge", formatAxisNumber(row.hfa, 1), row.hfa, allValues("hfa"), "context")}
        </tr>`;
      }).join("")}</tbody></table></div>` :
      `<div class="empty-state">No matching teams in the ranked sample.</div>`;
  }

  function renderSituational() {
    const target = document.getElementById("thi-situational-panel");
    if (!target) return;
    if (!selectedTeam) { target.innerHTML = ""; return; }
    const currentWeek = Number(thiObservedRatingsData?.meta?.through_week);
    const sourceWeek = Number(situationalData?.meta?.through_week);
    if (!situationalData || !Number.isFinite(currentWeek) || sourceWeek !== currentWeek) {
      target.innerHTML = `<div class="thi-situational-panel">Situational profiles are updating for this week.</div>`;
      return;
    }
    const team = situationalData.teams?.[selectedTeam];
    if (!team) { target.innerHTML = ""; return; }
    const labels = {
      script: "First-half early downs",
      leverage: "3rd/4th and 3+",
      red_zone: "Red-zone plays"
    };
    target.innerHTML = `<div class="thi-situational-panel">
      <div class="thi-situational-header"><h2>${escapeHtml(selectedTeam)} · Situational EPA</h2>
        <span class="thi-hub-muted">Through Week ${escapeHtml(sourceWeek)} · Regulation only</span></div>
      <div class="thi-situational-grid">${Object.entries(labels).map(([key, label]) => {
        const off = team.offense?.[key] ?? {};
        const def = team.defense?.[key] ?? {};
        const line = (name, entry) => `<div class="thi-situational-line"><span>${name}</span>
          <strong>${entry.epa_per_play === null || entry.epa_per_play === undefined ? "—" : formatSigned(entry.epa_per_play, 3)}</strong></div>
          <div class="thi-situational-sample">${escapeHtml(entry.sample_plays ?? 0)} plays · ${escapeHtml(entry.sample_status === "UNAVAILABLE" ? "Insufficient sample" : entry.sample_status === "MEASURED" ? "30+ play sample" : "Developing sample")}</div>`;
        return `<section class="thi-situational-card"><h3>${escapeHtml(label)}</h3>
          ${line("Offense", off)}${line("Defense allowed", def)}</section>`;
      }).join("")}</div>
      <p class="thi-situational-explainer">EPA per play; lower defense allowed is better. Small samples are pulled toward each team’s overall performance and the FBS average. These splits are descriptive, not opponent-adjusted, and are not first-half or full-game projected spreads. Red-zone and late-down samples can overlap.</p>
    </div>`;
  }

  function render() {
    const container = document.getElementById("thi-ratings-container");
    const meta = thiObservedRatingsData?.meta;
    const powerMeta = thiPowerRatingsData?.meta;
    if (!meta || !thiObservedRatingsData?.teams || !powerMeta || !Array.isArray(thiPowerRatingsData?.teams)) {
      container.innerHTML = `<div class="empty-state">THI power and observed ratings are awaiting their next matching refresh.</div>`;
      return;
    }
    container.innerHTML = `
      ${decompositionMarkup()}
      ${weeklyPulseMarkup()}
      <div class="conference-filter-bar thi-hub-controls">
        <div class="thi-hub-control-group">
          <label class="conference-filter-label" for="thi-ratings-search">Team</label>
          <input class="conference-filter-select thi-hub-search" type="search" id="thi-ratings-search" aria-label="Search THI ratings by team" placeholder="Search teams">
        </div>
        <div class="thi-hub-control-group">
          <label class="conference-filter-label" for="thi-ratings-conference">Conference</label>
          <select class="conference-filter-select" id="thi-ratings-conference" aria-label="Filter THI ratings by conference">
          <option value="ALL">All Conferences</option>
          <option value="P4">Power 4</option>
          <option value="G6">Group of Six</option>
          ${[...new Set(Object.values(teams).map(team => team.conference || "FBS Independents"))]
            .sort((a, b) => a.localeCompare(b)).map(name =>
              `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("")}
          </select>
        </div>
        <span class="conference-filter-count">${escapeHtml(thiPowerRatingsData.teams.length)} teams</span>
      </div>
      <p class="thi-hub-note">Overall research ratings are through Week ${escapeHtml(powerMeta.through_week ?? "—")}. Predictive is the production CFB power rating that feeds Model A. Recent Form is the independent rating's opponent-adjusted performance contribution; it does not silently alter Model A.</p>
      <div id="thi-ratings-rows"></div>
      <details class="thi-hub-method"><summary>How to read these ratings</summary>
        <p>Power Rating is a research scoring-margin scale that combines roster foundation, completed-game result Elo, and opponent-adjusted rate performance. It is separate from Model A and does not change any projection.</p>
        <p>${escapeHtml(meta.methodology?.description ?? "Observed ratings describe current on-field performance.")}</p>
        <p>Offense and defense use a scoring-scale index. Pace is indexed to the FBS average of 1.00. Observed Rank is the old net observed rank, retained for comparison.</p>
      </details>`;
    const input = document.getElementById("thi-ratings-search");
    input.value = search;
    input.addEventListener("input", () => { search = input.value; renderRows(); });
    const conferenceSelect = document.getElementById("thi-ratings-conference");
    conferenceSelect.value = conferenceFilter;
    conferenceSelect.addEventListener("change", () => {
      conferenceFilter = conferenceSelect.value;
      renderRows();
    });
    renderRows();
  }

  view.addEventListener("click", event => {
    const sortButton = event.target.closest("[data-thi-sort]");
    if (sortButton) {
      const nextSort = sortButton.dataset.thiSort;
      sortDirection = sort === nextSort ? (sortDirection === "asc" ? "desc" : "asc") : sortButton.dataset.thiDirection;
      sort = nextSort;
      renderRows();
      return;
    }
    const team = event.target.closest("[data-thi-team]");
    if (team) openDossier(team.dataset.thiTeam);
  });
  document.addEventListener("hammer:data-ready", () => {
    render();
    applyTeamDataExperience();
    loadJson("./data/thi_situational_profiles.json").then(data => {
      if (data?.meta?.status === "DESCRIPTIVE_BETA_NO_POINT_SCALE") {
        situationalData = data;
        renderSituational();
      }
    }).catch(() => { /* Profile generation has not run yet. */ });
    loadJson("./data/team_intelligence.json").then(data => {
      teamIntelligenceData = data;
      renderRows();
    }).catch(() => { /* Team intelligence build has not run yet. */ });
  });
})();
