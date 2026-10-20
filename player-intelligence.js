(() => {
  const DATA_URL = "./data/player_intelligence.json?v=20261020-player-production-v21";
  const PROJECTION_URL = "./data/player_projections.json";
  let data = null;
  let dataPromise = null;
  let projectionData = null;
  let projectionPromise = null;
  let section = "ratings";
  let active = "QB";
  let search = "";
  let conference = "ALL";
  let projectionPosition = "ALL";
  let projectionSearch = "";
  let projectionConfidence = "ALL";
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
  const title = {QB:"Quarterbacks",RB:"Running Backs",WR:"Wide Receivers",TE:"Tight Ends",DEF:"Defensive Production",HEISMAN:"THI Heisman Board"};

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

  window.THIEnsurePlayerIntelligence = loadData;

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
    view.innerHTML = `<div class="eyebrow">THI Player Intelligence</div><h1 class="page-title">Player Intelligence</h1>
      <p class="page-subtitle">Position-specific production ratings and matchup-aware player stat projections in separate research layers. Neither layer affects Model A.</p>
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
    const query = String(search || "").trim().toLocaleLowerCase();
    if (active === "HEISMAN") return data.heisman_board || [];
    return (data.leaderboards?.[active] || []).map(id => data.players[id]).filter(Boolean)
      .filter(row => !query || `${row.name} ${row.team}`.trim().toLocaleLowerCase().includes(query))
      .filter(row => conference === "ALL" || teamConference(row) === conference);
  }

  function volume(row) {
    const s = row.traditional || {};
    if (row.position_group === "QB") return `${s.completions || 0}/${s.pass_attempts || 0}, ${s.pass_yards || 0} yds`;
    if (row.position_group === "RB") return `${s.rush_attempts || 0} car, ${s.rush_yards || 0} yds`;
    if (["WR","TE"].includes(row.position_group)) return `${s.receptions || 0}/${s.targets || 0}, ${s.receiving_yards || 0} yds`;
    return `${s.total_tackles || 0} tkl · ${s.tackles_for_loss || 0} TFL · ${s.passes_defended || s.pass_breakups || 0} PD`;
  }

  function sectionTabs() {
    return `<div class="thi-player-section-tabs" role="tablist" aria-label="Player intelligence view">
      <button type="button" role="tab" aria-selected="${section === "ratings"}" class="${section === "ratings" ? "active" : ""}" data-player-section="ratings">Player Ratings</button>
      <button type="button" role="tab" aria-selected="${section === "projections"}" class="${section === "projections" ? "active" : ""}" data-player-section="projections">Player Projections <span>Research</span></button>
    </div>`;
  }

  function bindSectionTabs(root) {
    root.querySelectorAll("[data-player-section]").forEach(button => button.addEventListener("click", () => {
      section = button.dataset.playerSection;
      if (section === "projections") loadProjectionData().catch(() => {});
      else render();
    }));
  }

  function render() {
    const root = document.getElementById("thi-player-root"); if (!root || !data) return;
    if (section === "projections") {
      if (projectionData) renderProjections();
      else root.innerHTML = `${sectionTabs()}<div class="loading-state"><div class="spinner"></div>Loading player projections…</div>`;
      bindSectionTabs(root);
      return;
    }
    const conferences = [...new Set(Object.values(data.players).map(teamConference).filter(Boolean))].sort();
    root.innerHTML = `${sectionTabs()}<div class="thi-player-mode-heading"><div><span>Current-season layer</span><strong>Player Production Ratings</strong></div><p>Who has produced efficiently within their position?</p></div>
      <div class="thi-player-tabs">${["QB","RB","WR","TE","DEF","HEISMAN"].map(key => `<button class="thi-player-tab ${active === key ? "active" : ""}" data-player-tab="${key}">${escape(title[key])}</button>`).join("")}</div>
      <div class="thi-player-controls"><div class="thi-player-control"><label for="thi-player-search">Player or team</label><input id="thi-player-search" type="search" value="${escape(search)}" placeholder="Search players"></div>
      <div class="thi-player-control"><label for="thi-player-conference">Conference</label><select id="thi-player-conference"><option value="ALL">All conferences</option>${conferences.map(name => `<option ${conference === name ? "selected" : ""}>${escape(name)}</option>`).join("")}</select></div></div>
      <div class="thi-player-beta">Through Week ${escape(data.meta?.through_week ?? "—")} · all percentiles compare players within position · observed roles are derived from recorded workload, not an official depth chart · production ratings are research beta, not scouting or award grades · Model A is unchanged.</div>
      <div id="thi-player-table"></div>`;
    bindSectionTabs(root);
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

  function loadProjectionData() {
    if (projectionData) { renderProjections(); return Promise.resolve(projectionData); }
    if (projectionPromise) return projectionPromise;
    const root = document.getElementById("thi-player-root");
    if (root) {
      root.innerHTML = `${sectionTabs()}<div class="loading-state"><div class="spinner"></div>Loading player projections…</div>`;
      bindSectionTabs(root);
    }
    projectionPromise = fetch(PROJECTION_URL)
      .then(response => { if (!response.ok) throw new Error(response.status); return response.json(); })
      .then(payload => {
        if (!Array.isArray(payload.projections)) throw new Error("Projection payload is incomplete.");
        projectionData = payload;
        renderProjections();
        return payload;
      })
      .catch(error => {
        projectionPromise = null;
        if (root) {
          root.innerHTML = `${sectionTabs()}<div class="empty-state">Player projections could not load. Ratings remain available.</div>`;
          bindSectionTabs(root);
        }
        throw error;
      });
    return projectionPromise;
  }

  const projectionMetricLabels = {
    pass_attempts:"Pass Att", completions:"Completions", pass_yards:"Pass Yds", pass_tds:"Pass TD", interceptions:"INT",
    rush_attempts:"Carries", rush_yards:"Rush Yds", targets:"Targets", receptions:"Receptions", receiving_yards:"Rec Yds"
  };

  function projectionMetrics(row) {
    const order = row.position_group === "QB"
      ? ["completions","pass_attempts","pass_yards","pass_tds","interceptions","rush_attempts","rush_yards"]
      : row.position_group === "RB"
        ? ["rush_attempts","rush_yards","targets","receptions","receiving_yards"]
        : ["targets","receptions","receiving_yards"];
    return order.filter(key => Number.isFinite(Number(row.projection?.[key]))).map(key => `<div class="thi-player-projection-metric"><span>${escape(projectionMetricLabels[key] || key)}</span><strong>${num(row.projection[key], ["pass_tds","interceptions"].includes(key) ? 2 : 1)}</strong></div>`).join("");
  }

  function projectionRows() {
    const query = projectionSearch.trim().toLocaleLowerCase();
    return (projectionData?.projections || []).filter(row => {
      const matchesQuery = !query || `${row.name} ${row.team} ${row.matchup?.opponent}`.toLocaleLowerCase().includes(query);
      const matchesPosition = projectionPosition === "ALL" || row.position_group === projectionPosition;
      const matchesConfidence = projectionConfidence === "ALL" || row.confidence === projectionConfidence;
      return matchesQuery && matchesPosition && matchesConfidence;
    });
  }

  function renderProjections() {
    const root = document.getElementById("thi-player-root"); if (!root || !projectionData) return;
    const meta = projectionData.meta || {};
    const rows = projectionRows();
    const visibleRows = rows.slice(0, 300);
    const countLabel = rows.length > visibleRows.length
      ? `Showing ${visibleRows.length} of ${rows.length} projected players · refine the filters to narrow the board`
      : `${rows.length} projected players shown`;
    root.innerHTML = `${sectionTabs()}
      <div class="thi-player-mode-heading"><div><span>Next-game layer</span><strong>Player Stat Projections</strong></div><p>What workload and production does the current matchup imply?</p></div>
      <div class="thi-player-projection-notice"><div><strong>Player performance forecasts · Research v0.1</strong><span>Matchup-aware statistical expectations for analysis, fantasy research, broadcast preparation and player evaluation.</span></div><small>Through Week ${escape(meta.through_week ?? "—")} · ${escape(meta.projection_count ?? 0)} players · Model A unchanged</small></div>
      <div class="thi-player-projection-policy"><strong>Forecasting only</strong><span>This board does not ingest, retain or display player market lines, odds, prices, picks or wager records.</span></div>
      <div class="thi-player-controls thi-player-projection-controls">
        <div class="thi-player-control"><label for="thi-projection-search">Player, team or opponent</label><input id="thi-projection-search" type="search" value="${escape(projectionSearch)}" placeholder="Search the next-game board"></div>
        <div class="thi-player-control"><label for="thi-projection-position">Position</label><select id="thi-projection-position"><option value="ALL">All positions</option>${["QB","RB","WR","TE"].map(position => `<option value="${position}" ${projectionPosition === position ? "selected" : ""}>${position}</option>`).join("")}</select></div>
        <div class="thi-player-control"><label for="thi-projection-confidence">Evidence state</label><select id="thi-projection-confidence"><option value="ALL">All evidence states</option><option value="established" ${projectionConfidence === "established" ? "selected" : ""}>Established role</option><option value="developing" ${projectionConfidence === "developing" ? "selected" : ""}>Developing role</option><option value="availability_watch" ${projectionConfidence === "availability_watch" ? "selected" : ""}>Availability watch</option></select></div>
      </div>
      <div class="thi-player-projection-count">${escape(countLabel)}</div>
      <div class="thi-player-projection-grid">${visibleRows.map(row => {
        const matchup = row.matchup || {};
        const start = matchup.start_date ? new Date(matchup.start_date).toLocaleString("en-US", {timeZone:"America/New_York",weekday:"short",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"}) : "Time TBD";
        const context = row.availability ? `<div class="thi-player-availability"><strong>${escape(row.availability.status || "Availability watch")}</strong><span>${escape(row.availability.note || "Current source-linked player status requires review.")}</span>${/^https:\/\//i.test(row.availability.source_url || "") ? `<a href="${escape(row.availability.source_url)}" target="_blank" rel="noopener noreferrer">Source ↗</a>` : ""}</div>` : "";
        return `<article class="thi-player-projection-card">
          <header><div><button type="button" class="thi-player-name" data-thi-player-id="${escape(row.athlete_id)}">${escape(row.name)}</button><p>${escape(row.team)} ${escape(matchup.home_away === "home" ? "vs" : "at")} ${escape(matchup.opponent)} · ${escape(start)}</p></div><span>${escape(row.position_group)}</span></header>
          <div class="thi-player-projection-context"><span>THI ${row.national_position_rank ? `#${escape(row.national_position_rank)} ${escape(row.position_group)}` : "N/R"}</span><span>${escape(row.confidence === "established" ? "Established role" : row.confidence === "availability_watch" ? "Availability watch" : "Developing role")}</span><span>${matchup.implied_team_points != null ? `${num(matchup.implied_team_points,1)} implied pts` : "No team total"}</span></div>
          <div class="thi-player-projection-metrics">${projectionMetrics(row)}</div>${context}
        </article>`;
      }).join("") || `<div class="empty-state">No projected players match these filters.</div>`}</div>
      <div class="thi-player-beta">Method: ${escape(meta.method || "Observed workload with matchup adjustments.")} A frozen player-game performance ledger will be used only to measure forecast accuracy and calibration.</div>`;
    bindSectionTabs(root);
    root.querySelector("#thi-projection-search").addEventListener("input", event => { projectionSearch = event.target.value; renderProjections(); const input=document.getElementById("thi-projection-search"); input?.focus(); input?.setSelectionRange(input.value.length,input.value.length); });
    root.querySelector("#thi-projection-position").addEventListener("change", event => { projectionPosition = event.target.value; renderProjections(); });
    root.querySelector("#thi-projection-confidence").addEventListener("change", event => { projectionConfidence = event.target.value; renderProjections(); });
  }

  function renderTable() {
    const target = document.getElementById("thi-player-table"); if (!target) return;
    let rows = eligibleRows();
    if (active === "HEISMAN") {
      const query = String(search || "").trim().toLocaleLowerCase();
      rows = rows.filter(row => !query || `${row.name} ${row.team}`.trim().toLocaleLowerCase().includes(query)).filter(row => conference === "ALL" || teamConference(data.players?.[row.athlete_id]) === conference);
      const validation = data.meta?.heisman_validation || {};
      const tested = Array.isArray(validation.seasons) && validation.seasons.length > 0;
      const note = tested && !validation.passed
        ? `This is a score-based watch list. A ${validation.seasons.length}-season leave-one-season-out backtest did not clear THI's publication gates, so finalist and winner probabilities are withheld.`
        : "This is a score-based watch list. Probabilities remain withheld until historical validation clears every THI publication gate.";
      rows = sortRows(rows.map(row => ({...data.players[row.athlete_id], ...row, rating:row.player_rating})), true);
      target.innerHTML = `<p class="thi-heisman-note">${escape(note)} The first five positions are THI's editorial watch tier, informed by production, team context and verified availability; the remaining order is score-based. The board is display-only and does not affect Model A.</p>${ratingBoard(rows, true)}`;
      installBoardSort();
      return;
    }
    rows = sortRows(rows, false);
    target.innerHTML = ratingBoard(rows, false);
    installBoardSort();
  }

  function installBoardSort() {
    const control = document.getElementById("thi-player-board-sort");
    if (!control) return;
    control.addEventListener("change", event => {
      [sortKey, sortDirection] = event.target.value.split("|");
      renderTable();
    });
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

  function ratingBoard(rows, heisman) {
    const visible = rows.slice(0, 250);
    const bands = Object.fromEntries(
      ["rating", "production", "adj_epa", "total_epa", "success", "reliability"]
        .map(key => [key, metricValues(rows, key, heisman)])
    );
    const currentSort = `${sortKey}|${sortDirection}`;
    const sortOptions = [
      ["rank|asc", heisman ? "Board order" : "Position rank"],
      ["rating|desc", heisman ? "Production context" : "THI Production"],
      ["adj_epa|desc", "Adjusted EPA / opportunity"],
      ["total_epa|desc", "Total EPA"],
      ["success|desc", "Success rate"],
      ["production|desc", "Workload"],
      ["reliability|desc", "Sample reliability"],
      ["player|asc", "Player name"],
      ["team|asc", "Team"],
    ];
    const metric = (label, display, rawValue, values) => {
      const band = metricBand(values, rawValue);
      return `<div class="thi-player-rating-metric thi-player-band-${band.name}"><span>${escape(label)}</span><strong>${escape(display)}</strong><small>${escape(band.label)}</small></div>`;
    };
    return `<div class="thi-player-board-toolbar"><div><strong>${escape(title[active])}</strong><span>${escape(visible.length)} of ${escape(rows.length)} qualifying players</span></div><label for="thi-player-board-sort">Sort board<select id="thi-player-board-sort">${sortOptions.map(([value,label]) => `<option value="${value}" ${currentSort === value ? "selected" : ""}>${escape(label)}</option>`).join("")}</select></label></div>
      <div class="thi-player-rating-grid">${visible.map((row,index) => {
        const rank = heisman ? row.rank : row.national_position_rank || index + 1;
        const score = heisman ? row.heisman_score : row.rating;
        const scoreBand = metricBand(bands.rating, score);
        return `<article class="thi-player-rating-card ${index < 3 && sortKey === "rank" ? "is-podium" : ""}">
          <div class="thi-player-rating-head"><div class="thi-player-rating-rank"><span>${heisman ? "Board" : `${escape(row.position_group || row.position || "POS")} rank`}</span><strong>#${escape(rank)}</strong></div><div class="thi-player-rating-identity"><button class="thi-player-name" data-thi-player-id="${escape(row.athlete_id)}">${escape(row.name)}</button><span>${escape(row.team || "—")} · ${escape(row.position || row.position_group || "—")} · ${escape(row.class_name || row.class || "—")}</span></div><div class="thi-player-rating-score thi-player-band-${scoreBand.name}"><span>${heisman ? "Production context" : "THI Production"}</span><strong>${num(score,1)}</strong><small>${heisman && row.board_basis === "editorial_top_tier" ? "Editorial watch tier" : escape(scoreBand.label)}</small></div></div>
          <div class="thi-player-rating-metrics">
            ${metric("Season production", volume(row), sortValue(row,"production",heisman), bands.production)}
            ${metric("Adj EPA / opp", num(row.advanced?.opponent_adjusted_epa_per_opportunity,3,true), sortValue(row,"adj_epa",heisman), bands.adj_epa)}
            ${metric("Total EPA", num(row.advanced?.epa_total,1,true), sortValue(row,"total_epa",heisman), bands.total_epa)}
            ${metric("Success rate", percent(row.advanced?.success_rate,1), sortValue(row,"success",heisman), bands.success)}
            ${metric("Sample", percent(row.reliability,0), sortValue(row,"reliability",heisman), bands.reliability)}
          </div>
        </article>`;
      }).join("") || `<div class="empty-state">No players match the current filters.</div>`}</div>`;
  }

  function table(rows, heisman) {
    const bands = Object.fromEntries(
      ["rating", "production", "adj_epa", "total_epa", "success", "reliability"]
        .map(key => [key, metricValues(rows, key, heisman)])
    );
    return `<div class="thi-player-table-wrap"><table class="thi-player-table"><thead><tr>${sortHeader("rank", heisman ? "Board" : "Pos Rank")}${sortHeader("player", "Player")}${sortHeader("team", "Team")}${sortHeader("class", "Class")}${sortHeader("rating", heisman ? "Production Context" : "THI Production")}${sortHeader("production", "Production")}${sortHeader("adj_epa", "Adj EPA/Opp")}${sortHeader("total_epa", "Total EPA")}${sortHeader("success", "Success")}${sortHeader("reliability", "Reliability")}</tr></thead><tbody>${rows.map((row,index) => `<tr>
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
    const components = row.rating_components || {};
    const componentLabel = key => ({adjusted_epa:"Adjusted EPA",success_rate:"Success rate",yards_per_attempt:"Yards / attempt",completion_rate:"Completion rate",touchdown_rate:"TD rate",turnover_avoidance:"Turnover avoidance",yards_per_game:"Yards / game",touchdowns_per_game:"TDs / game",yards_per_opportunity:"Yards / opportunity",workload_share:"Workload share",receiving_dominance:"Yards + TD production",yards_per_target:"Yards / target",target_share:"Target share",receiving_yards:"Receiving yards",receiving_touchdowns:"Receiving TDs",receptions:"Receptions",tackles:"Tackles",tackles_for_loss:"Tackles for loss",sacks:"Sacks",passes_defended:"Passes defended",interceptions:"Interceptions",forced_fumbles:"Forced fumbles",fumble_recoveries:"Fumble recoveries"}[key] || key.replaceAll("_", " "));
    const componentCards = Object.entries(components.weights || {}).map(([key, weight]) => `<div class="thi-player-component"><span>${escape(componentLabel(key))}</span><strong>${percent(components[key],1)}</strong><small>${percent(Number(weight) * 100,0)} weight · within position</small></div>`).join("");
    const labels = {pass_attempts:"Pass attempts",completions:"Completions",pass_yards:"Passing yards",pass_tds:"Passing TD",interceptions:"Interceptions",rush_attempts:"Carries",rush_yards:"Rushing yards",rush_tds:"Rushing TD",targets:"Targets",receptions:"Receptions",receiving_yards:"Receiving yards",receiving_tds:"Receiving TD",total_tackles:"Total tackles",solo_tackles:"Solo tackles",tackles_for_loss:"Tackles for loss",sacks:"Sacks",interceptions_def:"Defensive INT",pass_breakups:"Pass breakups",passes_defended:"Passes defended",qb_hurries:"QB hurries",forced_fumbles:"Forced fumbles",fumble_recoveries:"Fumble recoveries",defensive_disruptions:"Impact events",pass_attempt_share:"Pass-attempt share",rush_attempt_share:"Carry share",target_share:"Target share"};
    const drawer = document.getElementById("thi-player-drawer");
    document.getElementById("thi-player-drawer-content").innerHTML = `<div class="thi-player-identity">${row.headshot ? `<img class="thi-player-headshot" src="${escape(row.headshot)}" alt="">` : ""}<div><h2>${escape(row.name)}</h2><p>${escape(row.team)} · ${escape(row.position || "—")} · ${escape(row.class_name || row.class || "—")} · ${escape([row.height,row.weight].filter(Boolean).join(" · "))}</p></div></div>
      <div class="thi-player-card-grid"><div class="thi-player-card"><span>THI Production</span><strong>${num(row.rating,1)}</strong></div><div class="thi-player-card"><span>National position rank</span><strong>${row.national_position_rank ? `#${row.national_position_rank}` : "—"}</strong></div><div class="thi-player-card"><span>Adjusted EPA / opportunity</span><strong>${num(row.advanced?.opponent_adjusted_epa_per_opportunity,3,true)}</strong></div><div class="thi-player-card"><span>Success rate</span><strong>${num(row.advanced?.success_rate,1)}%</strong></div></div>
      <h3>Rating decomposition</h3><div class="thi-player-component-grid">${componentCards}<div class="thi-player-component reliability"><span>Sample reliability</span><strong>${percent(components.reliability_percent,0)}</strong><small>Regresses rating toward 50</small></div></div>
      <h3>Season production</h3><div class="thi-player-stat-list">${Object.entries(stats).map(([key,value]) => `<div class="thi-player-stat-line"><span>${escape(labels[key] || key)}</span><strong>${escape(value)}${key.endsWith("_share") ? "%" : ""}</strong></div>`).join("") || `<div class="thi-player-stat-line"><span>No qualifying production recorded</span></div>`}</div>
      <h3>Method</h3><p class="thi-heisman-note">THI Production is a current-season, within-position measure. Each position has its own transparent formula: quarterbacks include turnovers and passing efficiency; backs include scrimmage production; receivers emphasize yards and touchdowns with a distance scale that preserves separation between exceptional seasons; defenders use the complete box-score profile rather than disruption plays alone. Small samples regress toward 50. It is not a scouting grade, draft projection or Heisman probability and does not affect Model A.</p>`;
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
      const ratingText = Number.isFinite(Number(row.rating)) ? `Prod ${row.rating.toFixed(1)} · #${row.national_position_rank}` : "N/R";
      if (role && role.textContent !== roleText) role.textContent = roleText;
      if (rating && rating.textContent !== ratingText) rating.textContent = ratingText;
    });
  }
  window.openTHIPlayer = openPlayer;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install); else install();
})();
