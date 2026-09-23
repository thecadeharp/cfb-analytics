/* THI's independent research surface. Reads the existing display-only ratings. */
(() => {
  let search = "";
  let sort = "net";

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
    .thi-hub-table tr:last-child td { border-bottom:0; }
    .thi-hub-table tbody tr:hover { background:#f6f8f5; }
    .thi-hub-team { border:0; background:transparent; padding:0; color:var(--text); font-family:inherit; font-size:14px; font-weight:700; cursor:pointer; text-align:left; }
    .thi-hub-team:hover { text-decoration:underline; }
    .thi-hub-number { font:700 14px var(--mono); white-space:nowrap; }
    .thi-hub-muted { color:var(--muted); font-size:11px; white-space:nowrap; }
    .thi-hub-rank { color:var(--muted); font:600 11px var(--mono); }
    .thi-hub-badge { display:inline-block; border:1px solid var(--border); border-radius:40px; padding:4px 8px; font:600 10px var(--mono); }
    .thi-hub-badge.strong { color:#12694d; background:#e8f7ef; }
    .thi-hub-badge.limited { color:#815b08; background:#fff4d6; }
    .thi-hub-method { margin-top:18px; border:1px solid var(--border); border-radius:10px; padding:16px; color:var(--muted); font-size:13px; line-height:1.6; }
    .thi-hub-method summary { color:var(--text); font-weight:700; cursor:pointer; }
    @media (max-width:700px) {
      .thi-hub-table thead { display:none; }
      .thi-hub-table tbody tr { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); padding:14px; gap:10px 16px; border-bottom:1px solid var(--border); }
      .thi-hub-table td { padding:0; border:0; min-width:0; }
      .thi-hub-table td:first-child { grid-column:1/-1; }
      .thi-hub-table td[data-label]::before { content:attr(data-label); display:block; color:var(--muted); font:600 10px var(--mono); margin-bottom:3px; }
      .thi-hub-controls select { flex:1 1 150px; }
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

  function renderRows() {
    const target = document.getElementById("thi-ratings-rows");
    if (!target) return;
    const query = search.trim().toLocaleLowerCase();
    const data = Object.values(thiObservedRatingsData?.teams ?? {})
      .filter(profile => profile?.eligible && profile?.ratings &&
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
      <thead><tr><th>Team</th><th>Net</th><th>Offense</th><th>Defense ↓</th><th>Pace</th><th>Sample</th></tr></thead>
      <tbody>${data.map(profile => {
        const rating = profile.ratings;
        const reliability = profile.reliability ?? {};
        const band = reliability.games >= 2 ? "strong" : "limited";
        return `<tr>
          <td><span class="thi-hub-rank">#${rating[sort]?.rank ?? "—"}</span> &nbsp;
            <button type="button" class="thi-hub-team" data-thi-team="${escapeHtml(profile.team)}">${escapeHtml(profile.team)}</button></td>
          <td data-label="Net"><span class="thi-hub-number">${formatSigned(rating.net?.value, 2)}</span> <span class="thi-hub-rank">#${rating.net?.rank ?? "—"}</span></td>
          <td data-label="Offense"><span class="thi-hub-number">${formatNumber(rating.offense?.value, 2)}</span> <span class="thi-hub-rank">#${rating.offense?.rank ?? "—"}</span></td>
          <td data-label="Defense"><span class="thi-hub-number">${formatNumber(rating.defense?.value, 2)}</span> <span class="thi-hub-rank">#${rating.defense?.rank ?? "—"}</span></td>
          <td data-label="Pace"><span class="thi-hub-number">${formatNumber(rating.pace?.value, 2)}</span> <span class="thi-hub-rank">#${rating.pace?.rank ?? "—"}</span></td>
          <td data-label="Sample"><span class="thi-hub-badge ${band}">${escapeHtml(reliability.label ?? "LIMITED")}</span>
            <span class="thi-hub-muted">${formatNumber(reliability.games, 0)} games · ${formatNumber(reliability.qualifying_plays, 0)} plays</span></td>
        </tr>`;
      }).join("")}</tbody></table></div>` :
      `<div class="empty-state">No matching teams with a published THI rating.</div>`;
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
      </div>
      <p class="thi-hub-note">2026 data through Week ${escapeHtml(meta.through_week ?? "—")} · ${escapeHtml(meta.sample ?? "Completed FBS games")} · Beta. Net is offense minus defense; lower defense is better. Values describe performance and do not imply a neutral-field spread.</p>
      <div id="thi-ratings-rows"></div>
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
    renderRows();
  }

  view.addEventListener("click", event => {
    const team = event.target.closest("[data-thi-team]");
    if (team) openDossier(team.dataset.thiTeam);
  });
  document.addEventListener("hammer:data-ready", render);
})();
