(() => {
  "use strict";

  const PATHS = {
    profiles: "data/cbb/team_profiles.json",
    games: "data/cbb/game_board.json",
    foundation: "data/cbb/foundation_status.json",
    model: "data/cbb/model/model_card.json",
    priors: "data/cbb/model/current_priors.json",
    history: "data/cbb/history/manifest.json"
  };

  const state = {
    sport: "cfb",
    cbbView: "cbb-home",
    cfbView: "projections",
    loaded: false,
    loading: null,
    data: null,
    ratingSort: { key: "prior_net", direction: "desc" },
    query: "",
    conference: "all",
    statusText: ""
  };

  const escapeHtml = value => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const number = (value, digits = 1, sign = false) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return "—";
    const prefix = sign && parsed > 0 ? "+" : "";
    return `${prefix}${parsed.toFixed(digits)}`;
  };

  const integer = value => Number.isFinite(Number(value))
    ? Math.round(Number(value)).toLocaleString("en-US")
    : "—";

  const pct = value => Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}%` : "—";

  function activeCfbView() {
    return document.querySelector(".view.active:not(.cbb-view)")?.id?.replace(/^view-/, "") || state.cfbView;
  }

  function mount() {
    const header = document.querySelector(".header-inner");
    const cfbNav = document.querySelector(".main-nav");
    const main = document.querySelector("main.page");
    if (!header || !cfbNav || !main || document.querySelector(".thi-sport-switcher")) return;

    const switcher = document.createElement("div");
    switcher.className = "thi-sport-switcher";
    switcher.setAttribute("role", "group");
    switcher.setAttribute("aria-label", "Choose sport");
    switcher.innerHTML = `
      <button class="thi-sport-button is-active" type="button" data-sport="cfb" aria-pressed="true">College Football</button>
      <button class="thi-sport-button" type="button" data-sport="cbb" aria-pressed="false">College Basketball</button>
    `;
    header.insertBefore(switcher, cfbNav);

    const cbbNav = document.createElement("nav");
    cbbNav.className = "main-nav cbb-nav";
    cbbNav.setAttribute("aria-label", "College basketball sections");
    cbbNav.innerHTML = `
      <button class="nav-item active" type="button" data-cbb-view="cbb-home">Research Board</button>
      <button class="nav-item" type="button" data-cbb-view="cbb-ratings">Team Ratings</button>
      <button class="nav-item" type="button" data-cbb-view="cbb-model">Model Lab</button>
    `;
    cfbNav.insertAdjacentElement("afterend", cbbNav);

    ["cbb-home", "cbb-ratings", "cbb-model"].forEach(id => {
      const section = document.createElement("section");
      section.id = `view-${id}`;
      section.className = "view cbb-view cbb-shell";
      section.innerHTML = `<div class="cbb-panel cbb-empty">Loading THI College Basketball…</div>`;
      main.appendChild(section);
    });

    const detail = document.createElement("div");
    detail.id = "cbb-team-detail";
    detail.className = "cbb-detail";
    detail.setAttribute("aria-hidden", "true");
    detail.innerHTML = `<aside class="cbb-detail-panel" role="dialog" aria-modal="true" aria-labelledby="cbb-detail-title"></aside>`;
    document.body.appendChild(detail);

    switcher.addEventListener("click", event => {
      const button = event.target.closest("[data-sport]");
      if (button) setSport(button.dataset.sport);
    });
    cbbNav.addEventListener("click", event => {
      const button = event.target.closest("[data-cbb-view]");
      if (button) showCbbView(button.dataset.cbbView);
    });
    detail.addEventListener("click", event => {
      if (event.target === detail || event.target.closest("[data-cbb-close]")) closeTeamDetail();
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") closeTeamDetail();
    });

    window.thiSportHome = () => {
      if (state.sport === "cbb") showCbbView("cbb-home");
      else window.switchView?.("projections");
    };
    window.thiSetSport = setSport;
  }

  async function fetchJson(path) {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) throw new Error(`${path} returned ${response.status}`);
    return response.json();
  }

  async function loadData() {
    if (state.loaded) return state.data;
    if (state.loading) return state.loading;
    state.loading = Promise.all(Object.entries(PATHS).map(async ([key, path]) => [key, await fetchJson(path)]))
      .then(entries => {
        state.data = Object.fromEntries(entries);
        state.loaded = true;
        renderAll();
        return state.data;
      })
      .catch(error => {
        renderError(error);
        throw error;
      })
      .finally(() => { state.loading = null; });
    return state.loading;
  }

  function setSport(sport) {
    if (sport !== "cbb" && sport !== "cfb") return;
    if (sport === state.sport) return;
    const status = document.getElementById("data-updated");
    const logo = document.querySelector(".brand-sport-logo");
    state.sport = sport;

    document.querySelectorAll(".thi-sport-button").forEach(button => {
      const selected = button.dataset.sport === sport;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });

    if (sport === "cbb") {
      state.cfbView = activeCfbView();
      state.statusText = status?.textContent || state.statusText;
      document.body.classList.add("thi-sport-cbb");
      document.querySelectorAll(".view:not(.cbb-view)").forEach(view => view.classList.remove("active"));
      if (logo) logo.src = "assets/branding/thi-cbb-mark.png?v=2027-cbb-ui-v01";
      if (status) status.textContent = "CBB · 2027 PRESEASON";
      document.title = "THI College Basketball";
      showCbbView(state.cbbView, false);
      loadData().catch(() => {});
    } else {
      closeTeamDetail();
      document.body.classList.remove("thi-sport-cbb");
      document.querySelectorAll(".cbb-view").forEach(view => view.classList.remove("active"));
      if (logo) logo.src = "assets/branding/thi-cfb-mark.png?v=2026-brand-v01";
      if (status && state.statusText) status.textContent = state.statusText;
      document.title = "The Hammer Index";
      window.switchView?.(state.cfbView || "projections");
    }
  }

  function showCbbView(view, scroll = true) {
    state.cbbView = view;
    document.querySelectorAll(".cbb-view").forEach(section => section.classList.toggle("active", section.id === `view-${view}`));
    document.querySelectorAll("[data-cbb-view]").forEach(button => button.classList.toggle("active", button.dataset.cbbView === view));
    if (scroll) window.scrollTo({ top: 0, behavior: "auto" });
  }

  function renderAll() {
    renderHome();
    renderRatings();
    renderModel();
  }

  function renderError(error) {
    const message = escapeHtml(error?.message || "CBB data could not be loaded.");
    document.querySelectorAll(".cbb-view").forEach(section => {
      section.innerHTML = `<div class="cbb-error"><strong>College basketball data is temporarily unavailable.</strong><div>${message}</div></div>`;
    });
  }

  function renderHome() {
    const { profiles, games, foundation, history, model } = state.data;
    const meta = profiles.meta || {};
    const coverage = foundation.coverage || {};
    const scheduled = Array.isArray(games.games) ? games.games : [];
    const upcoming = scheduled
      .filter(game => String(game.status).toLowerCase() === "scheduled")
      .sort((a, b) => new Date(a.start_date) - new Date(b.start_date))
      .slice(0, 8);
    const modelVersion = model.meta?.model_version || "Research model";
    const view = document.getElementById("view-cbb-home");
    view.innerHTML = `
      <div class="cbb-hero">
        <div>
          <div class="cbb-kicker">The Hammer Index · College Basketball</div>
          <h1 class="cbb-title">Possession-based college hoops research.</h1>
          <p class="cbb-lede">Adjusted efficiency, tempo, Four Factors, personnel context and strict walk-forward testing—built as a separate basketball engine inside the same THI research platform.</p>
        </div>
        <div class="cbb-status-card">
          <span class="cbb-status-pill">Research preview</span>
          <div><strong>2027 preseason foundation</strong><p>The model is visible for accountability and evaluation. It has not cleared THI's promotion gate for public projections.</p></div>
        </div>
      </div>

      <div class="cbb-stat-grid">
        ${statCard("D-I teams", integer(meta.team_count), "Full 2027 directory")}
        ${statCard("Historical games", integer(history.meta?.game_count), `${history.meta?.season_count || 0} walk-forward seasons`)}
        ${statCard("Scheduled games", integer(coverage.window_games), "Current published window")}
        ${statCard("Model state", "Research", escapeHtml(modelVersion))}
      </div>

      <section class="cbb-section">
        <div class="cbb-section-head"><div><div class="cbb-label">Schedule</div><h2 class="cbb-section-title">Opening board</h2></div><div class="cbb-section-note">Schedule context only. THI projections remain withheld until the research model clears its validation gate.</div></div>
        <div class="cbb-game-list">${upcoming.length ? upcoming.map(gameCard).join("") : `<div class="cbb-panel cbb-empty">No scheduled games are currently published.</div>`}</div>
      </section>

      <section class="cbb-section">
        <div class="cbb-section-head"><div><div class="cbb-label">Model language</div><h2 class="cbb-section-title">How THI reads basketball</h2></div></div>
        <div class="cbb-method-grid">
          ${methodCard("01 · Efficiency", "Adjusted offense and defense", "Points per 100 possessions establish the scoring baseline after opponent and venue context.")}
          ${methodCard("02 · Possessions", "Tempo and game shape", "Projected pace translates per-possession strength into matchup-level scoring opportunities.")}
          ${methodCard("03 · Matchup causes", "Four Factors and personnel", "Shooting, turnovers, rebounding, free throws, recruiting and transfer production explain how an edge can appear.")}
        </div>
      </section>
    `;
  }

  function statCard(label, value, note) {
    return `<article class="cbb-stat-card"><div class="cbb-label">${escapeHtml(label)}</div><div class="cbb-stat-value">${escapeHtml(value)}</div><div class="cbb-stat-note">${escapeHtml(note)}</div></article>`;
  }

  function methodCard(label, title, copy) {
    return `<article class="cbb-panel cbb-method-card"><div class="cbb-label">${escapeHtml(label)}</div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(copy)}</p></article>`;
  }

  function gameCard(game) {
    const start = new Date(game.start_date);
    const date = Number.isNaN(start.getTime()) ? "Date TBD" : new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: game.start_time_tbd ? undefined : "numeric", minute: game.start_time_tbd ? undefined : "2-digit", timeZone: "America/New_York", timeZoneName: game.start_time_tbd ? undefined : "short" }).format(start);
    const venue = game.venue?.name || (game.neutral_site ? "Neutral site" : "Venue TBD");
    const network = game.broadcasts?.map(item => item.network || item).filter(Boolean).join(", ") || "TV TBD";
    return `<article class="cbb-panel cbb-game-card"><div class="cbb-game-top"><span class="cbb-game-date">${escapeHtml(date)}</span>${game.neutral_site ? '<span class="cbb-chip">Neutral</span>' : ""}</div><div class="cbb-matchup">${escapeHtml(game.away?.team)} <span>vs.</span> ${escapeHtml(game.home?.team)}</div><div class="cbb-game-meta">${escapeHtml(venue)} · ${escapeHtml(network)}</div></article>`;
  }

  function ratingsRows() {
    const priors = state.data.priors.teams || [];
    const filtered = priors.filter(team => {
      const query = state.query.trim().toLowerCase();
      const matchesQuery = !query || `${team.team} ${team.conference?.name || ""}`.toLowerCase().includes(query);
      const matchesConference = state.conference === "all" || (team.conference?.abbreviation || team.conference?.name) === state.conference;
      return matchesQuery && matchesConference;
    });
    const { key, direction } = state.ratingSort;
    return filtered.sort((a, b) => {
      const av = valueFor(a, key);
      const bv = valueFor(b, key);
      const order = typeof av === "string" ? av.localeCompare(bv) : (Number(av) || 0) - (Number(bv) || 0);
      return direction === "asc" ? order : -order;
    });
  }

  function valueFor(team, key) {
    if (key === "team") return team.team || "";
    if (key === "conference") return team.conference?.abbreviation || team.conference?.name || "";
    if (key === "recruiting") return team.personnel?.recruiting?.team_rating ?? -Infinity;
    if (key === "transfer_minutes") return team.personnel?.transfers?.prior_minutes ?? -Infinity;
    return team[key] ?? -Infinity;
  }

  function quantileBands(teams, key, lowerIsBetter = false) {
    const values = teams.map(team => Number(valueFor(team, key))).filter(Number.isFinite).sort((a, b) => a - b);
    return team => {
      const value = Number(valueFor(team, key));
      if (!Number.isFinite(value) || !values.length) return 3;
      const index = values.findIndex(candidate => candidate >= value);
      const percentile = (index < 0 ? values.length - 1 : index) / Math.max(1, values.length - 1);
      const score = lowerIsBetter ? 1 - percentile : percentile;
      return Math.max(1, Math.min(5, Math.ceil(score * 5)));
    };
  }

  function renderRatings() {
    const priors = state.data.priors.teams || [];
    const conferences = [...new Set(priors.map(team => team.conference?.abbreviation || team.conference?.name).filter(Boolean))].sort();
    const view = document.getElementById("view-cbb-ratings");
    view.innerHTML = `
      <div class="cbb-kicker">2027 preseason research</div>
      <h1 class="page-title">CBB Team Ratings</h1>
      <p class="page-subtitle">Regressed 2026 efficiency priors with recruiting and incoming-transfer context. These are preseason research ratings, not current-season adjusted ratings or public game projections.</p>
      <div class="cbb-controls">
        <input id="cbb-rating-search" class="cbb-input" type="search" placeholder="Search team or conference" value="${escapeHtml(state.query)}">
        <select id="cbb-conference-filter" class="cbb-select"><option value="all">All conferences</option>${conferences.map(conf => `<option value="${escapeHtml(conf)}" ${state.conference === conf ? "selected" : ""}>${escapeHtml(conf)}</option>`).join("")}</select>
      </div>
      <div class="cbb-panel cbb-table-wrap">
        <table class="cbb-table" aria-label="2027 THI college basketball preseason ratings">
          <thead><tr>
            <th>Rank</th>${ratingHeader("team", "Team")}${ratingHeader("conference", "Conf")}${ratingHeader("prior_net", "Net eff")}${ratingHeader("prior_offense", "Adj off")}${ratingHeader("prior_defense", "Adj def")}${ratingHeader("recruiting", "Recruiting")}${ratingHeader("transfer_minutes", "Transfer min")}
          </tr></thead>
          <tbody id="cbb-rating-body"></tbody>
        </table>
      </div>
      <div class="cbb-stat-note" style="margin-top:9px">Color bands compare each efficiency metric across all 365 teams. Lower defensive efficiency is better. Rank numbers remain uncolored.</div>
    `;

    view.querySelector("#cbb-rating-search").addEventListener("input", event => { state.query = event.target.value; paintRatingRows(); });
    view.querySelector("#cbb-conference-filter").addEventListener("change", event => { state.conference = event.target.value; paintRatingRows(); });
    view.querySelector("thead").addEventListener("click", event => {
      const header = event.target.closest("[data-sort]");
      if (!header) return;
      const key = header.dataset.sort;
      state.ratingSort.direction = state.ratingSort.key === key && state.ratingSort.direction === "desc" ? "asc" : "desc";
      state.ratingSort.key = key;
      renderRatings();
    });
    view.querySelector("#cbb-rating-body").addEventListener("click", event => {
      const row = event.target.closest("[data-team-id]");
      if (row) openTeamDetail(Number(row.dataset.teamId));
    });
    paintRatingRows();
  }

  function ratingHeader(key, label) {
    const active = state.ratingSort.key === key;
    const arrow = active ? (state.ratingSort.direction === "desc" ? " ↓" : " ↑") : " ↕";
    return `<th data-sort="${key}" class="${active ? "is-sorted" : ""}">${escapeHtml(label)}${arrow}</th>`;
  }

  function paintRatingRows() {
    const body = document.getElementById("cbb-rating-body");
    if (!body) return;
    const all = state.data.priors.teams || [];
    const rows = ratingsRows();
    const netBand = quantileBands(all, "prior_net");
    const offBand = quantileBands(all, "prior_offense");
    const defBand = quantileBands(all, "prior_defense", true);
    const globalRank = new Map([...all].sort((a,b) => b.prior_net - a.prior_net).map((team,index) => [team.team_id,index+1]));
    body.innerHTML = rows.length ? rows.map(team => {
      const recruiting = team.personnel?.recruiting || {};
      const transfers = team.personnel?.transfers || {};
      return `<tr data-team-id="${team.team_id}"><td class="cbb-rank">#${globalRank.get(team.team_id) || "—"}</td><td><div class="cbb-team-name">${escapeHtml(team.team)}</div><div class="cbb-team-meta">View team profile →</div></td><td>${escapeHtml(team.conference?.abbreviation || "—")}</td><td class="cbb-number cbb-metric-cell cbb-band-${netBand(team)}">${number(team.prior_net,2,true)}</td><td class="cbb-number cbb-metric-cell cbb-band-${offBand(team)}">${number(team.prior_offense,2)}</td><td class="cbb-number cbb-metric-cell cbb-band-${defBand(team)}">${number(team.prior_defense,2)}</td><td class="cbb-number">${number(recruiting.team_rating,2)}</td><td class="cbb-number">${integer(transfers.prior_minutes)}</td></tr>`;
    }).join("") : `<tr><td colspan="8" class="cbb-empty">No teams match those filters.</td></tr>`;
  }

  function openTeamDetail(teamId) {
    const prior = state.data.priors.teams.find(team => Number(team.team_id) === Number(teamId));
    const profile = state.data.profiles.teams.find(team => Number(team.team_id) === Number(teamId));
    if (!prior) return;
    const detail = document.getElementById("cbb-team-detail");
    const panel = detail.querySelector(".cbb-detail-panel");
    const recruiting = prior.personnel?.recruiting || {};
    const transfers = prior.personnel?.transfers || {};
    const preseason = profile?.preseason_prior || {};
    panel.innerHTML = `
      <button class="cbb-detail-close" type="button" data-cbb-close>Close</button>
      <div class="cbb-kicker">THI CBB team profile</div>
      <h2 class="cbb-detail-title" id="cbb-detail-title">${escapeHtml(profile?.display_name || prior.team)}</h2>
      <div class="cbb-detail-sub">${escapeHtml(prior.conference?.name || "Independent")} · 2027 preseason</div>
      <div class="cbb-detail-grid">
        ${detailStat("Net efficiency", number(prior.prior_net,2,true))}
        ${detailStat("Adjusted offense", number(prior.prior_offense,2))}
        ${detailStat("Adjusted defense", number(prior.prior_defense,2))}
      </div>
      <section class="cbb-detail-section"><h3>Personnel context</h3>
        ${detailRow("Recruiting team rank", recruiting.team_rank ? `#${integer(recruiting.team_rank)}` : "—")}
        ${detailRow("Recruiting team rating", number(recruiting.team_rating,2))}
        ${detailRow("Incoming transfers", integer(transfers.incoming_count))}
        ${detailRow("Transfers with prior production", integer(transfers.prior_production_match_count))}
        ${detailRow("Incoming prior minutes", integer(transfers.prior_minutes))}
        ${detailRow("Incoming prior points", integer(transfers.prior_points))}
      </section>
      <section class="cbb-detail-section"><h3>Rating provenance</h3>
        ${detailRow("Source season", integer(preseason.source_season || 2026))}
        ${detailRow("2026 source net", number(preseason.adjusted?.net,1,true))}
        ${detailRow("Current rating state", "Preseason prior")}
        ${detailRow("Returning-minutes signal", prior.returning_minutes_pct > 0 ? pct(prior.returning_minutes_pct) : "Unavailable in current feed")}
      </section>
      <section class="cbb-detail-section"><h3>Current-season Four Factors</h3><div class="cbb-model-sub">Four Factors and shot-profile grades activate after the 2027 season begins and a usable sample is available.</div></section>
    `;
    detail.classList.add("is-open");
    detail.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    panel.scrollTop = 0;
    panel.querySelector("[data-cbb-close]")?.focus();
  }

  function closeTeamDetail() {
    const detail = document.getElementById("cbb-team-detail");
    if (!detail?.classList.contains("is-open")) return;
    detail.classList.remove("is-open");
    detail.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  function detailStat(label, value) { return `<div class="cbb-detail-stat"><div class="cbb-label">${escapeHtml(label)}</div><strong>${escapeHtml(value)}</strong></div>`; }
  function detailRow(label, value) { return `<div class="cbb-detail-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`; }

  function renderModel() {
    const card = state.data.model;
    const validation = card.evaluation?.validation || {};
    const test = card.evaluation?.out_of_time_test || {};
    const checks = card.promotion_gate?.checks || {};
    const ats = test.ats_by_edge || [];
    const view = document.getElementById("view-cbb-model");
    view.innerHTML = `
      <div class="cbb-kicker">Transparent research and accountability</div>
      <h1 class="page-title">CBB Model Lab</h1>
      <p class="page-subtitle">Strict walk-forward evaluation with market prices reserved for comparison. Current-season end ratings never initialize the same season.</p>
      <div class="cbb-model-grid">
        ${modelCard("2025 validation", "Margin MAE", number(validation.margin_mae,3), `${integer(validation.games)} games · ${pct(validation.winner_accuracy)} winner accuracy`)}
        ${modelCard("2026 out-of-time test", "Margin MAE", number(test.margin_mae,3), `${integer(test.games)} games · ${pct(test.winner_accuracy)} winner accuracy`)}
        ${modelCard("Activation state", "Public engine", "Withheld", "Research-only until every required promotion check passes")}
      </div>

      <section class="cbb-section">
        <div class="cbb-section-head"><div><div class="cbb-label">Promotion standard</div><h2 class="cbb-section-title">Gate checks</h2></div><div class="cbb-section-note">A strong slice does not override failed generalization, totals or personnel-data checks.</div></div>
        <div class="cbb-panel cbb-gate-list">${Object.entries(checks).map(([key, pass]) => `<div class="cbb-gate-item ${pass ? "pass" : "fail"}"><span class="cbb-gate-icon">${pass ? "✓" : "×"}</span><span>${escapeHtml(humanize(key))}</span></div>`).join("")}</div>
      </section>

      <section class="cbb-section">
        <div class="cbb-section-head"><div><div class="cbb-label">2026 out-of-time test</div><h2 class="cbb-section-title">Spread disagreement audit</h2></div><div class="cbb-section-note">Retrospective research by absolute model-versus-market disagreement. Market prices were evaluation fields, never model inputs.</div></div>
        <div class="cbb-panel cbb-table-wrap"><table class="cbb-table"><thead><tr><th>Minimum disagreement</th><th>Wins</th><th>Losses</th><th>Pushes</th><th>Hit rate</th></tr></thead><tbody>${ats.map(row => `<tr><td class="cbb-number">${row.minimum_edge}+ pts</td><td class="cbb-number">${integer(row.wins)}</td><td class="cbb-number">${integer(row.losses)}</td><td class="cbb-number">${integer(row.pushes)}</td><td class="cbb-number">${pct(row.hit_rate)}</td></tr>`).join("")}</tbody></table></div>
      </section>

      <section class="cbb-section">
        <div class="cbb-section-head"><div><div class="cbb-label">Known limitations</div><h2 class="cbb-section-title">What is still missing</h2></div></div>
        <div class="cbb-panel cbb-gate-list">${(card.limitations || []).map(item => `<div class="cbb-gate-item"><span class="cbb-gate-icon">·</span><span>${escapeHtml(item)}</span></div>`).join("")}</div>
      </section>
    `;
  }

  function modelCard(kicker, label, value, note) {
    return `<article class="cbb-panel cbb-model-card"><div class="cbb-label">${escapeHtml(kicker)}</div><div class="cbb-model-sub">${escapeHtml(label)}</div><div class="cbb-model-value">${escapeHtml(value)}</div><div class="cbb-model-sub">${escapeHtml(note)}</div></article>`;
  }

  function humanize(value) {
    return value.replaceAll("_", " ").replace(/^./, letter => letter.toUpperCase()).replace("52 38 pct", "52.38% ");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount, { once: true });
  else mount();
})();
