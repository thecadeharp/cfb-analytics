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
  let selectedTeam = "";

  const style = document.createElement("style");
  style.textContent = `
    .thi-hub-intro { max-width:850px; line-height:1.6; }
    .thi-hub-controls { display:flex; flex-wrap:wrap; gap:12px; align-items:center; margin:22px 0 12px; }
    .thi-hub-controls input, .thi-hub-controls select { font:inherit; min-height:42px; background:var(--surface); color:var(--text); border:1px solid var(--border); border-radius:8px; padding:8px 12px; }
    .thi-hub-controls input { flex:1 1 240px; min-width:0; }
    .thi-hub-note { font-size:12px; line-height:1.55; color:var(--muted); margin:0 0 18px; }
    .thi-hub-table-wrap { overflow-x:auto; border:1px solid var(--border); border-radius:12px; background:var(--surface); }
    .thi-hub-table { width:100%; border-collapse:collapse; }
    .thi-hub-table th, .thi-hub-table td { text-align:left; padding:14px 16px; border-bottom:1px solid var(--border); }
    .thi-hub-table th { font:600 11px var(--mono); letter-spacing:.05em; color:var(--muted); white-space:nowrap; }
    .thi-hub-sort-button { border:0; padding:0; background:transparent; color:inherit; font:inherit; letter-spacing:inherit; cursor:pointer; }
    .thi-hub-sort-button:hover, .thi-hub-sort-button:focus-visible { color:var(--text); text-decoration:underline; }
    .thi-hub-sort-arrow { display:inline-block; margin-left:4px; }
    .thi-hub-table tr:last-child td { border-bottom:0; }
    .thi-hub-table tbody tr:hover { background:#f6f8f5; }
    .thi-hub-team { border:0; background:transparent; padding:0; color:var(--text); font-family:inherit; font-size:14px; font-weight:700; cursor:pointer; text-align:left; }
    .thi-hub-team:hover { text-decoration:underline; }
    .thi-hub-team-wrap { display:inline-flex; align-items:center; gap:8px; vertical-align:middle; }
    .thi-hub-team-wrap .team-logo { flex:0 0 auto; }
    .thi-hub-number { font:700 14px var(--mono); white-space:nowrap; }
    .thi-hub-muted { color:var(--muted); font-size:11px; white-space:nowrap; }
    .thi-hub-rank { color:var(--muted); font:600 11px var(--mono); }
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
      .thi-hub-controls select { flex:1 1 150px; }
      .thi-situational-grid { grid-template-columns:1fr; }
    }
  `;
  document.head.appendChild(style);

  const nav = document.querySelector(".main-nav");
  const ratingsButton = nav?.querySelector('[data-view="ratings"]');
  const section = document.getElementById("view-ratings");
  if (!nav || !section || !ratingsButton) return;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "nav-item";
  button.dataset.view = "thi-ratings";
  button.textContent = "THI Ratings";
  button.addEventListener("click", () => switchView("thi-ratings"));
  ratingsButton.after(button);

  const view = document.createElement("section");
  view.id = "view-thi-ratings";
  view.className = "view";
  view.innerHTML = `
    <div class="eyebrow">Calculated by The Hammer Index</div>
    <h1 class="page-title">THI Ratings</h1>
    <p class="page-subtitle thi-hub-intro">Our opponent-adjusted view of on-field performance. Compare teams here; open a Team Dossier for the complete offensive and defensive breakdown.</p>
    <div id="thi-ratings-container" aria-live="polite"></div>`;
  section.after(view);

  function ratingValue(profile, key) {
    const raw = profile.ratings?.[key]?.value;
    if (raw === null || raw === undefined || raw === "") return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  }

  function sortHeader(key, label, defaultDirection = "desc") {
    const active = sort === key;
    const direction = active ? sortDirection : defaultDirection;
    const arrow = direction === "asc" ? "↑" : "↓";
    return `<th aria-sort="${active ? (direction === "asc" ? "ascending" : "descending") : "none"}">
      <button type="button" class="thi-hub-sort-button" data-thi-sort="${key}"
        data-thi-direction="${defaultDirection}" aria-label="Sort by ${label.toLowerCase()}">${label}${active ? `<span class="thi-hub-sort-arrow" aria-hidden="true">${arrow}</span>` : ""}</button>
    </th>`;
  }

  function renderRows() {
    const target = document.getElementById("thi-ratings-rows");
    if (!target) return;
    const query = search.trim().toLocaleLowerCase();
    const observed = thiObservedRatingsData?.teams ?? {};
    const data = (thiPowerRatingsData?.teams ?? []).map(power => {
      const profile = observed[power.team] ?? {};
      return { power, profile, team: power.team, conference: profile.conference || teams[power.team]?.conference || "FBS Independents" };
    }).filter(row => matchesRatingConference(row) && String(row.team).toLocaleLowerCase().includes(query));
    data.sort((a, b) => {
      const value = row => {
        if (sort === "team") return row.team;
        if (sort === "power_rank") return Number(row.power.rank);
        if (sort === "observed_rank") return Number(row.profile.ratings?.net?.rank);
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

    target.innerHTML = data.length ? `<div class="thi-hub-table-wrap"><table class="thi-hub-table">
      <thead><tr>${sortHeader("power_rank", "Rank", "asc")}${sortHeader("team", "Team", "asc")}${sortHeader("rating", "Rating")}${sortHeader("roster_contribution", "Roster")}${sortHeader("performance_contribution", "Performance")}${sortHeader("performance_only_weekly_change", "Weekly Δ")}${sortHeader("qualifying_games", "FBS Games")}${sortHeader("observed_rank", "Observed Rank", "asc")}${sortHeader("offense", "Off")}${sortHeader("defense", "Def", "asc")}${sortHeader("net", "Net")}${sortHeader("pace", "Pace")}</tr></thead>
      <tbody>${data.map(row => {
        const { power, profile } = row;
        const rating = profile.ratings ?? {};
        return `<tr>
          <td data-label="Rank"><span class="thi-hub-number">#${formatNumber(power.rank, 0)}</span></td>
          <td data-label="Team"><span class="thi-hub-team-wrap">${teamLogoMarkup(row.team, "projection")}
              <button type="button" class="thi-hub-team" data-thi-team="${escapeHtml(row.team)}">${escapeHtml(row.team)}</button></span></td>
          <td data-label="Rating"><span class="thi-hub-number">${formatSigned(power.rating, 2)}</span></td>
          <td data-label="Roster"><span class="thi-hub-number">${formatSigned(power.roster_contribution, 2)}</span></td>
          <td data-label="Performance"><span class="thi-hub-number">${formatSigned(power.performance_contribution, 2)}</span></td>
          <td data-label="Weekly Δ"><span class="thi-hub-number">${formatSigned(power.performance_only_weekly_change, 2)}</span></td>
          <td data-label="FBS Games"><span class="thi-hub-number">${formatNumber(power.qualifying_games, 0)}</span></td>
          <td data-label="Observed Rank"><span class="thi-hub-rank">#${formatNumber(rating.net?.rank, 0)}</span></td>
          <td data-label="Off"><span class="thi-hub-number">${formatNumber(rating.offense?.value, 2)}</span></td>
          <td data-label="Def"><span class="thi-hub-number">${formatNumber(rating.defense?.value, 2)}</span></td>
          <td data-label="Net"><span class="thi-hub-number">${formatSigned(rating.net?.value, 2)}</span></td>
          <td data-label="Pace"><span class="thi-hub-number">${formatNumber(rating.pace?.value, 2)}</span></td>
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
      <div class="thi-hub-controls">
        <input type="search" id="thi-ratings-search" aria-label="Search THI ratings by team" placeholder="Search teams">
        <select id="thi-ratings-conference" aria-label="Filter THI ratings by conference">
          <option value="ALL">All Conferences</option>
          <option value="P4">Power 4</option>
          <option value="G6">Group of Six</option>
          ${[...new Set(Object.values(teams).map(team => team.conference || "FBS Independents"))]
            .sort((a, b) => a.localeCompare(b)).map(name =>
              `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("")}
        </select>
        <select id="thi-situational-team" aria-label="Select team for situational EPA">
          <option value="">Situational profile · select team</option>
          ${Object.keys(thiObservedRatingsData.teams).sort().map(name =>
            `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("")}
        </select>
      </div>
      <div id="thi-situational-panel"></div>
      <p class="thi-hub-note">Predictive Power Rating through Week ${escapeHtml(powerMeta.through_week ?? "—")} · observed diagnostics through Week ${escapeHtml(meta.through_week ?? "—")}. Click any column header to sort; click again to reverse it. Roster is the talent and returning-production contribution. Performance is the opponent-adjusted rate contribution. Observed values remain descriptive context; lower defense is better.</p>
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
    const teamSelect = document.getElementById("thi-situational-team");
    teamSelect.value = selectedTeam;
    teamSelect.addEventListener("change", () => {
      selectedTeam = teamSelect.value;
      renderSituational();
    });
    renderSituational();
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
    loadJson("./data/thi_situational_profiles.json").then(data => {
      if (data?.meta?.status === "DESCRIPTIVE_BETA_NO_POINT_SCALE") {
        situationalData = data;
        renderSituational();
      }
    }).catch(() => { /* Profile generation has not run yet. */ });
  });
})();
