(() => {
  const DATA_URL = "./data/player_intelligence.json";
  let data = null;
  let dataPromise = null;
  let active = "QB";
  let search = "";
  let conference = "ALL";
  let sortKey = "rank";
  let sortDirection = "asc";
  let decorateQueued = false;

  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const num = (value, digits = 1, signed = false) => {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return `${signed && n > 0 ? "+" : ""}${n.toFixed(digits)}`;
  };
  const teamConference = row => row?.conference || "FBS Independents";
  const title = {QB:"Quarterbacks",RB:"Running Backs",WR:"Wide Receivers",TE:"Tight Ends",DEF:"Defensive Disruptors",HEISMAN:"THI Heisman Board"};

  function loadData() {
    if (data) return Promise.resolve(data);
    if (dataPromise) return dataPromise;
    const root = document.getElementById("thi-player-root");
    if (root) root.innerHTML = `<div class="loading-state"><div class="spinner"></div>Loading player intelligence…</div>`;
    dataPromise = fetch(DATA_URL)
      .then(response => { if (!response.ok) throw new Error(response.status); return response.json(); })
      .then(payload => {
        data = payload;
        window.THIPlayerIntelligence = payload;
        render();
        decorateRoster();
        return payload;
      })
      .catch(error => {
        dataPromise = null;
        if (root) root.innerHTML = `<div class="empty-state">Player intelligence could not load. Select Player Ratings to retry.</div>`;
        throw error;
      });
    return dataPromise;
  }

  function install() {
    const nav = document.querySelector(".main-nav");
    const ratings = document.getElementById("view-ratings");
    if (!nav || !ratings || document.getElementById("view-player-ratings")) return;
    const button = document.createElement("button");
    button.className = "nav-item"; button.dataset.view = "player-ratings"; button.textContent = "Player Ratings";
    button.addEventListener("click", () => {
      switchView("player-ratings");
      loadData().catch(() => {});
    });
    const anchor = nav.querySelector('[data-view="thi-ratings"]') || nav.querySelector('[data-view="ratings"]');
    anchor.after(button);
    const view = document.createElement("section");
    view.id = "view-player-ratings"; view.className = "view";
    view.innerHTML = `<div class="eyebrow">THI Player Intelligence</div><h1 class="page-title">Player Ratings</h1>
      <p class="page-subtitle">Position-specific production, opponent-adjusted efficiency and observed workload. Ratings are research and display tools and do not affect Model A.</p>
      <div id="thi-player-root"><div class="empty-state">Open Player Ratings to load the current player dataset.</div></div>`;
    ratings.after(view);
    const drawer = document.createElement("div"); drawer.id = "thi-player-drawer"; drawer.className = "thi-player-drawer"; drawer.hidden = true;
    drawer.innerHTML = `<aside class="thi-player-drawer-panel" role="dialog" aria-modal="true" aria-label="Player profile"><button class="thi-player-drawer-close" type="button">Close</button><div id="thi-player-drawer-content"></div></aside>`;
    document.body.appendChild(drawer);
    drawer.querySelector(".thi-player-drawer-close").addEventListener("click", closePlayer);
    drawer.addEventListener("click", event => { if (event.target === drawer) closePlayer(); });
    document.addEventListener("keydown", event => { if (event.key === "Escape") closePlayer(); });
    document.addEventListener("click", event => {
      const trigger = event.target.closest("[data-thi-player-id]");
      if (trigger) {
        event.preventDefault();
        loadData().then(() => openPlayer(trigger.dataset.thiPlayerId)).catch(() => {});
      }
    });
    const rosterRoot = document.getElementById("dossier-container") || document.body;
    new MutationObserver(queueDecorateRoster).observe(rosterRoot, {subtree:true, childList:true});
  }

  function eligibleRows() {
    if (!data) return [];
    if (active === "HEISMAN") return data.heisman_board || [];
    return (data.leaderboards?.[active] || []).map(id => data.players[id]).filter(Boolean)
      .filter(row => !search || `${row.name} ${row.team}`.toLowerCase().includes(search.toLowerCase()))
      .filter(row => conference === "ALL" || teamConference(row) === conference);
  }

  function volume(row) {
    const s = row.traditional || {};
    if (row.position_group === "QB") return `${s.completions || 0}/${s.pass_attempts || 0}, ${s.pass_yards || 0} yds`;
    if (row.position_group === "RB") return `${s.rush_attempts || 0} car, ${s.rush_yards || 0} yds`;
    if (["WR","TE"].includes(row.position_group)) return `${s.receptions || 0}/${s.targets || 0}, ${s.receiving_yards || 0} yds`;
    return `${s.defensive_disruptions || 0} disruptions`;
  }

  function render() {
    const root = document.getElementById("thi-player-root"); if (!root || !data) return;
    const conferences = [...new Set(Object.values(data.players).map(teamConference).filter(Boolean))].sort();
    root.innerHTML = `<div class="thi-player-tabs">${["QB","RB","WR","TE","DEF","HEISMAN"].map(key => `<button class="thi-player-tab ${active === key ? "active" : ""}" data-player-tab="${key}">${escape(title[key])}</button>`).join("")}</div>
      <div class="thi-player-controls"><div class="thi-player-control"><label for="thi-player-search">Player or team</label><input id="thi-player-search" type="search" value="${escape(search)}" placeholder="Search players"></div>
      <div class="thi-player-control"><label for="thi-player-conference">Conference</label><select id="thi-player-conference"><option value="ALL">All conferences</option>${conferences.map(name => `<option ${conference === name ? "selected" : ""}>${escape(name)}</option>`).join("")}</select></div></div>
      <div class="thi-player-beta">Through Week ${escape(data.meta?.through_week ?? "—")} · metric colors compare players within the current position and filter · observed roles are derived from recorded workload, not an official depth chart · position ratings are research beta · Model A is unchanged.</div>
      <div id="thi-player-table"></div>`;
    root.querySelectorAll("[data-player-tab]").forEach(button => button.addEventListener("click", () => {
      active = button.dataset.playerTab;
      sortKey = "rank";
      sortDirection = "asc";
      render();
    }));
    root.querySelector("#thi-player-search").addEventListener("input", event => { search = event.target.value; renderTable(); });
    root.querySelector("#thi-player-conference").addEventListener("change", event => { conference = event.target.value; renderTable(); });
    renderTable();
  }

  function renderTable() {
    const target = document.getElementById("thi-player-table"); if (!target) return;
    let rows = eligibleRows();
    if (active === "HEISMAN") {
      rows = rows.filter(row => !search || `${row.name} ${row.team}`.toLowerCase().includes(search.toLowerCase())).filter(row => conference === "ALL" || teamConference(data.players?.[row.athlete_id]) === conference);
      const validation = data.meta?.heisman_validation || {};
      const tested = Array.isArray(validation.seasons) && validation.seasons.length > 0;
      const note = tested && !validation.passed
        ? `This is a score-based watch list. A ${validation.seasons.length}-season leave-one-season-out backtest did not clear THI's publication gates, so finalist and winner probabilities are withheld.`
        : "This is a score-based watch list. Probabilities remain withheld until historical validation clears every THI publication gate.";
      rows = sortRows(rows.map(row => ({...data.players[row.athlete_id], ...row, rating:row.player_rating})), true);
      target.innerHTML = `<p class="thi-heisman-note">${escape(note)} The board is display-only and does not affect Model A.</p>${table(rows, true)}`;
      installSortListeners();
      return;
    }
    rows = sortRows(rows, false);
    target.innerHTML = table(rows.slice(0, 250), false);
    installSortListeners();
  }

  function sortValue(row, key, heisman) {
    if (key === "rank") return Number(heisman ? row.rank : row.national_position_rank);
    if (key === "player") return String(row.name || "").toLocaleLowerCase();
    if (key === "team") return String(row.team || "").toLocaleLowerCase();
    if (key === "class") return String(row.class || row.class_name || "").toLocaleLowerCase();
    if (key === "rating") return Number(heisman ? row.heisman_score : row.rating);
    if (key === "production") return Number(row.opportunities);
    if (key === "adj_epa") return Number(row.advanced?.opponent_adjusted_epa_per_opportunity);
    if (key === "total_epa") return Number(row.advanced?.epa_total);
    if (key === "success") return Number(row.advanced?.success_rate);
    if (key === "reliability") return Number(row.reliability);
    return null;
  }

  function sortRows(rows, heisman) {
    return rows.slice().sort((a, b) => {
      const av = sortValue(a, sortKey, heisman);
      const bv = sortValue(b, sortKey, heisman);
      const aMissing = av === null || av === undefined || (typeof av === "number" && !Number.isFinite(av));
      const bMissing = bv === null || bv === undefined || (typeof bv === "number" && !Number.isFinite(bv));
      if (aMissing !== bMissing) return aMissing ? 1 : -1;
      let comparison = typeof av === "string" ? av.localeCompare(bv) : Number(av) - Number(bv);
      if (comparison === 0) comparison = String(a.name || "").localeCompare(String(b.name || ""));
      return sortDirection === "asc" ? comparison : -comparison;
    });
  }

  function sortHeader(key, label) {
    const activeSort = sortKey === key;
    const arrow = activeSort ? (sortDirection === "asc" ? "↑" : "↓") : "↕";
    return `<th aria-sort="${activeSort ? (sortDirection === "asc" ? "ascending" : "descending") : "none"}"><button type="button" class="thi-player-sort ${activeSort ? "active" : ""}" data-player-sort="${key}">${label}<span aria-hidden="true">${arrow}</span></button></th>`;
  }

  function installSortListeners() {
    document.querySelectorAll("[data-player-sort]").forEach(button => button.addEventListener("click", () => {
      const next = button.dataset.playerSort;
      if (sortKey === next) sortDirection = sortDirection === "asc" ? "desc" : "asc";
      else {
        sortKey = next;
        sortDirection = ["rank", "player", "team", "class"].includes(next) ? "asc" : "desc";
      }
      renderTable();
    }));
  }

  function metricBand(values, rawValue) {
    const value = Number(rawValue);
    const valid = values.map(Number).filter(Number.isFinite).sort((a, b) => a - b);
    if (!Number.isFinite(value) || !valid.length) return {name:"missing", label:"N/A"};
    if (valid.length === 1) return {name:"average", label:"AVERAGE"};
    const below = valid.filter(item => item < value).length;
    const equal = valid.filter(item => item === value).length;
    const percentile = (below + Math.max(equal - 1, 0) / 2) / Math.max(valid.length - 1, 1);
    if (percentile >= .90) return {name:"elite", label:"ELITE"};
    if (percentile >= .70) return {name:"strong", label:"STRONG"};
    if (percentile >= .55) return {name:"above", label:"ABOVE AVG"};
    if (percentile >= .45) return {name:"average", label:"AVERAGE"};
    if (percentile >= .30) return {name:"below", label:"BELOW AVG"};
    if (percentile >= .10) return {name:"poor", label:"POOR"};
    return {name:"critical", label:"LOW"};
  }

  function gradedMetricCell(display, rawValue, values) {
    const band = metricBand(values, rawValue);
    return `<td class="thi-player-metric thi-player-band-${band.name}"><span class="thi-player-metric-value">${escape(display)}</span><span class="thi-player-metric-label">${band.label}</span></td>`;
  }

  function metricValues(rows, key, heisman) {
    return rows.map(row => sortValue(row, key, heisman)).filter(Number.isFinite);
  }

  function percent(value, digits = 1) {
    return Number.isFinite(Number(value)) ? `${num(value, digits)}%` : "—";
  }

  function table(rows, heisman) {
    const bands = Object.fromEntries(
      ["rating", "production", "adj_epa", "total_epa", "success", "reliability"]
        .map(key => [key, metricValues(rows, key, heisman)])
    );
    return `<div class="thi-player-table-wrap"><table class="thi-player-table"><thead><tr>${sortHeader("rank", heisman ? "Board" : "Pos Rank")}${sortHeader("player", "Player")}${sortHeader("team", "Team")}${sortHeader("class", "Class")}${sortHeader("rating", heisman ? "Heisman Score" : "THI Rating")}${sortHeader("production", "Production")}${sortHeader("adj_epa", "Adj EPA/Opp")}${sortHeader("total_epa", "Total EPA")}${sortHeader("success", "Success")}${sortHeader("reliability", "Reliability")}</tr></thead><tbody>${rows.map((row,index) => `<tr>
      <td class="thi-player-mono">#${escape(heisman ? row.rank : row.national_position_rank || index + 1)}</td>
      <td><button class="thi-player-name" data-thi-player-id="${escape(row.athlete_id)}">${escape(row.name)}</button><div class="thi-hub-muted">${escape(row.position || row.position_group || "—")}</div></td>
      <td>${escape(row.team || "—")}</td><td>${escape(row.class || "—")}</td>
      ${gradedMetricCell(num(heisman ? row.heisman_score : row.rating,1), sortValue(row,"rating",heisman), bands.rating)}
      ${gradedMetricCell(volume(row), sortValue(row,"production",heisman), bands.production)}
      ${gradedMetricCell(num(row.advanced?.opponent_adjusted_epa_per_opportunity,3,true), sortValue(row,"adj_epa",heisman), bands.adj_epa)}
      ${gradedMetricCell(num(row.advanced?.epa_total,1,true), sortValue(row,"total_epa",heisman), bands.total_epa)}
      ${gradedMetricCell(percent(row.advanced?.success_rate,1), sortValue(row,"success",heisman), bands.success)}
      ${gradedMetricCell(percent(row.reliability,0), sortValue(row,"reliability",heisman), bands.reliability)}
    </tr>`).join("")}</tbody></table></div>`;
  }

  function openPlayer(id) {
    const row = data?.players?.[String(id)]; if (!row) return;
    const stats = {...row.traditional, ...row.workload};
    const labels = {pass_attempts:"Pass attempts",completions:"Completions",pass_yards:"Passing yards",pass_tds:"Passing TD",interceptions:"Interceptions",rush_attempts:"Carries",rush_yards:"Rushing yards",rush_tds:"Rushing TD",targets:"Targets",receptions:"Receptions",receiving_yards:"Receiving yards",receiving_tds:"Receiving TD",sacks:"Sacks",interceptions_def:"Defensive INT",pass_breakups:"Pass breakups",forced_fumbles:"Forced fumbles",fumble_recoveries:"Fumble recoveries",defensive_disruptions:"Disruptions",pass_attempt_share:"Pass-attempt share",rush_attempt_share:"Carry share",target_share:"Target share"};
    const drawer = document.getElementById("thi-player-drawer");
    document.getElementById("thi-player-drawer-content").innerHTML = `<div class="thi-player-identity">${row.headshot ? `<img class="thi-player-headshot" src="${escape(row.headshot)}" alt="">` : ""}<div><h2>${escape(row.name)}</h2><p>${escape(row.team)} · ${escape(row.position || "—")} · ${escape(row.class_name || row.class || "—")} · ${escape([row.height,row.weight].filter(Boolean).join(" · "))}</p></div></div>
      <div class="thi-player-card-grid"><div class="thi-player-card"><span>THI rating</span><strong>${num(row.rating,1)}</strong></div><div class="thi-player-card"><span>National position rank</span><strong>${row.national_position_rank ? `#${row.national_position_rank}` : "—"}</strong></div><div class="thi-player-card"><span>Adjusted EPA / opportunity</span><strong>${num(row.advanced?.opponent_adjusted_epa_per_opportunity,3,true)}</strong></div><div class="thi-player-card"><span>Success rate</span><strong>${num(row.advanced?.success_rate,1)}%</strong></div></div>
      <h3>Season production</h3><div class="thi-player-stat-list">${Object.entries(stats).map(([key,value]) => `<div class="thi-player-stat-line"><span>${escape(labels[key] || key)}</span><strong>${escape(value)}${key.endsWith("_share") ? "%" : ""}</strong></div>`).join("") || `<div class="thi-player-stat-line"><span>No qualifying production recorded</span></div>`}</div>
      <h3>Method</h3><p class="thi-heisman-note">Position-specific rating combining opponent-adjusted EPA per opportunity, total value, workload and success rate. Observed workload is not an official depth designation and does not affect Model A.</p>`;
    drawer.hidden = false; document.body.style.overflow = "hidden";
  }
  function closePlayer() { const drawer = document.getElementById("thi-player-drawer"); if (drawer) drawer.hidden = true; document.body.style.overflow = ""; }
  function observedRole(row) {
    const share = Math.max(...Object.values(row.workload || {}).map(Number).filter(Number.isFinite), 0);
    if (share >= 60) return "Primary"; if (share >= 25) return "Rotation"; if (row.opportunities > 0) return "Contributor"; return "Roster";
  }
  function queueDecorateRoster() {
    if (!data || decorateQueued) return;
    decorateQueued = true;
    requestAnimationFrame(() => {
      decorateQueued = false;
      decorateRoster();
    });
  }
  function decorateRoster() {
    if (!data) return;
    document.querySelectorAll("[data-thi-player-row]").forEach(tr => {
      const row = data.players?.[tr.dataset.thiPlayerRow];
      if (!row) {
        const button = tr.querySelector(".thi-player-trigger");
        const url = button?.dataset.playerProfileUrl;
        if (button && /^https:\/\//i.test(url || "")) {
          const link = document.createElement("a"); link.className = "thi-roster-player-link"; link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = `${button.textContent} ↗`; button.replaceWith(link);
        }
        return;
      }
      const role = tr.querySelector("[data-thi-role]"); const rating = tr.querySelector("[data-thi-rating]");
      const roleText = `${observedRole(row)}${row.opportunities ? ` · ${row.opportunities} opp` : ""}`;
      const ratingText = Number.isFinite(Number(row.rating)) ? `${row.rating.toFixed(1)} · #${row.national_position_rank}` : "N/R";
      if (role && role.textContent !== roleText) role.textContent = roleText;
      if (rating && rating.textContent !== ratingText) rating.textContent = ratingText;
    });
  }
  window.openTHIPlayer = openPlayer;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install); else install();
})();
