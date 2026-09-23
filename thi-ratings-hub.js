/* THI's independent research surface. Reads the existing display-only ratings. */
(() => {
  let search = "";
  let sort = "net";
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
    const value = Number(profile.ratings?.[key]?.value);
    return Number.isFinite(value) ? value : null;
  }

  function sortHeader(key, label) {
    const active = sort === key;
    const direction = key === "defense" ? "ascending" : "descending";
    const arrow = key === "defense" ? "↑" : "↓";
    return `<th aria-sort="${active ? direction : "none"}">
      <button type="button" class="thi-hub-sort-button" data-thi-sort="${key}"
        aria-label="Sort by ${label.toLowerCase()} (${key === "defense" ? "lowest" : "highest"} first)">${label}${active ? `<span class="thi-hub-sort-arrow" aria-hidden="true">${arrow}</span>` : ""}</button>
    </th>`;
  }

  function renderRows() {
    const target = document.getElementById("thi-ratings-rows");
    const provisionalTarget = document.getElementById("thi-ratings-provisional");
    if (!target) return;
    const query = search.trim().toLocaleLowerCase();
    const data = Object.values(thiObservedRatingsData?.teams ?? {})
      .filter(profile => profile?.eligible && profile?.ratings && matchesRatingConference(profile) &&
        String(profile.team || "").toLocaleLowerCase().includes(query));
    data.sort((a, b) => {
      const av = ratingValue(a, sort);
      const bv = ratingValue(b, sort);
      if (av === null) return 1;
      if (bv === null) return -1;
      return (sort === "defense" ? av - bv : bv - av) ||
        String(a.team).localeCompare(String(b.team));
    });

    target.innerHTML = data.length ? `<div class="thi-hub-table-wrap"><table class="thi-hub-table">
      <thead><tr><th>Team</th>${sortHeader("net", "Net")}${sortHeader("offense", "Offense")}${sortHeader("defense", "Defense")}${sortHeader("pace", "Pace")}<th>Sample</th></tr></thead>
      <tbody>${data.map(profile => {
        const rating = profile.ratings;
        const reliability = profile.reliability ?? {};
        const band = reliability.games >= 2 ? "strong" : "limited";
        return `<tr>
          <td><span class="thi-hub-rank">#${rating[sort]?.rank ?? "—"}</span> &nbsp;
            <span class="thi-hub-team-wrap">${teamLogoMarkup(profile.team, "projection")}
              <button type="button" class="thi-hub-team" data-thi-team="${escapeHtml(profile.team)}">${escapeHtml(profile.team)}</button></span></td>
          <td data-label="Net"><span class="thi-hub-number">${formatSigned(rating.net?.value, 2)}</span> <span class="thi-hub-rank">#${rating.net?.rank ?? "—"}</span></td>
          <td data-label="Offense"><span class="thi-hub-number">${formatNumber(rating.offense?.value, 2)}</span> <span class="thi-hub-rank">#${rating.offense?.rank ?? "—"}</span></td>
          <td data-label="Defense"><span class="thi-hub-number">${formatNumber(rating.defense?.value, 2)}</span> <span class="thi-hub-rank">#${rating.defense?.rank ?? "—"}</span></td>
          <td data-label="Pace"><span class="thi-hub-number">${formatNumber(rating.pace?.value, 2)}</span> <span class="thi-hub-rank">#${rating.pace?.rank ?? "—"}</span></td>
          <td data-label="Sample"><span class="thi-hub-badge ${band}">${escapeHtml(reliability.label ?? "LIMITED")}</span>
            <span class="thi-hub-muted">${formatNumber(reliability.games, 0)} games · ${formatNumber(reliability.qualifying_plays, 0)} plays</span></td>
        </tr>`;
      }).join("")}</tbody></table></div>` :
      `<div class="empty-state">No matching teams in the ranked sample.</div>`;

    if (provisionalTarget) {
      const provisional = Object.values(thiObservedRatingsData?.teams ?? {})
        .filter(profile => profile?.provisional && profile?.provisional_ratings && matchesRatingConference(profile) &&
          String(profile.team || "").toLocaleLowerCase().includes(query))
        .sort((a, b) => {
          const av = Number(a.provisional_ratings?.[sort]);
          const bv = Number(b.provisional_ratings?.[sort]);
          return (sort === "defense" ? av - bv : bv - av) ||
            String(a.team).localeCompare(String(b.team));
        });
      provisionalTarget.hidden = provisional.length === 0;
      provisionalTarget.innerHTML = provisional.length ? `
        <details class="thi-hub-provisional"${query ? " open" : ""}>
          <summary>Provisional · ${provisional.length} team${provisional.length === 1 ? "" : "s"} (unranked)</summary>
          <p>One qualifying FBS game. Values are displayed for context and receive no FBS ranks until the second qualifying game.</p>
          <div class="thi-hub-table-wrap"><table class="thi-hub-table">
            <thead><tr><th>Team</th>${sortHeader("net", "Net")}${sortHeader("offense", "Offense")}${sortHeader("defense", "Defense")}${sortHeader("pace", "Pace")}<th>Sample</th></tr></thead>
            <tbody>${provisional.map(profile => {
              const rating = profile.provisional_ratings;
              const sample = profile.reliability ?? {};
              return `<tr>
                <td><span class="thi-hub-team-wrap">${teamLogoMarkup(profile.team, "projection")}
                  <button type="button" class="thi-hub-team" data-thi-team="${escapeHtml(profile.team)}">${escapeHtml(profile.team)}</button></span></td>
                <td data-label="Net"><span class="thi-hub-number">${formatSigned(rating.net, 2)}</span></td>
                <td data-label="Offense"><span class="thi-hub-number">${formatNumber(rating.offense, 2)}</span></td>
                <td data-label="Defense"><span class="thi-hub-number">${formatNumber(rating.defense, 2)}</span></td>
                <td data-label="Pace"><span class="thi-hub-number">${formatNumber(rating.pace, 2)}</span></td>
                <td data-label="Sample"><span class="thi-hub-badge limited">PROVISIONAL</span>
                  <span class="thi-hub-muted">${formatNumber(sample.games, 0)} game · ${formatNumber(sample.qualifying_plays, 0)} plays</span></td>
              </tr>`;
            }).join("")}</tbody></table></div>
        </details>` : "";
    }
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
    if (!meta || !thiObservedRatingsData?.teams) {
      container.innerHTML = `<div class="empty-state">THI Observed Ratings are awaiting their next data refresh.</div>`;
      return;
    }
    container.innerHTML = `
      <div class="thi-hub-controls">
        <input type="search" id="thi-ratings-search" aria-label="Search THI ratings by team" placeholder="Search teams">
        <select id="thi-ratings-sort" aria-label="Order THI ratings">
          <option value="net">Rank by net</option><option value="offense">Rank by offense</option>
          <option value="defense">Rank by defense</option><option value="pace">Rank by pace</option>
        </select>
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
      <p class="thi-hub-note">2026 data through Week ${escapeHtml(meta.through_week ?? "—")} · ${escapeHtml(meta.sample ?? "Completed FBS games")} · Beta. Net is offense minus defense; lower defense is better. Values describe performance and do not imply a neutral-field spread.</p>
      <div id="thi-ratings-rows"></div>
      <div id="thi-ratings-provisional"></div>
      <details class="thi-hub-method"><summary>How to read these ratings</summary>
        <p>${escapeHtml(meta.methodology?.description ?? "Opponent-adjusted current-season performance.")}</p>
        <p>Offense and defense use a scoring-scale index, not projected points for the next game. Pace is indexed to the FBS average of 1.00. The sample badge shows how much game evidence is available. These ratings are separate from Model A.</p>
      </details>`;
    const input = document.getElementById("thi-ratings-search");
    input.value = search;
    input.addEventListener("input", () => { search = input.value; renderRows(); });
    const select = document.getElementById("thi-ratings-sort");
    select.value = sort;
    select.addEventListener("change", () => { sort = select.value; renderRows(); });
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
      sort = sortButton.dataset.thiSort;
      const select = document.getElementById("thi-ratings-sort");
      if (select) select.value = sort;
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
