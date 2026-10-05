(() => {
  "use strict";

  const PATHS = {
    profiles: "data/cbb/team_profiles.json",
    games: "data/cbb/game_board.json",
    foundation: "data/cbb/foundation_status.json",
    model: "data/cbb/model/model_card.json",
    priors: "data/cbb/model/current_priors.json",
    history: "data/cbb/history/manifest.json",
    projectionBoard: "data/cbb/projection_board.json"
  };
  const PLAYER_PATH = "data/cbb/player_ratings.json";

  const state = {
    sport: "cfb",
    cbbView: "cbb-projections",
    cfbView: "projections",
    loaded: false,
    loading: null,
    data: null,
    ratingSort: { key: "prior_net", direction: "desc" },
    playerSort: { key: "thi_player_rating", direction: "desc" },
    playerQuery: "",
    playerConference: "all",
    playerPosition: "all",
    playerReliability: 0,
    playerPage: 1,
    playerPageSize: 100,
    playerData: null,
    playerLoading: null,
    playerBandCache: {},
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
      <button class="nav-item active" type="button" data-cbb-view="cbb-projections">Projections</button>
      <button class="nav-item" type="button" data-cbb-view="cbb-tracking">Model Tracking</button>
      <button class="nav-item" type="button" data-cbb-view="cbb-team-data">Team Data</button>
      <button class="nav-item" type="button" data-cbb-view="cbb-ratings">THI Ratings</button>
      <button class="nav-item" type="button" data-cbb-view="cbb-player-ratings">Player Ratings</button>
      <button class="nav-item" type="button" data-cbb-view="cbb-bracketology">THI Bracketology</button>
      <button class="nav-item" type="button" data-cbb-view="cbb-portal">Transfer Portal</button>
      <button class="nav-item" type="button" data-cbb-view="cbb-market">Market Research</button>
    `;
    cfbNav.insertAdjacentElement("afterend", cbbNav);

    ["cbb-projections", "cbb-tracking", "cbb-team-data", "cbb-ratings", "cbb-player-ratings", "cbb-bracketology", "cbb-portal", "cbb-market"].forEach(id => {
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
      const playerButton = event.target.closest("[data-roster-player-id]");
      if (playerButton) openPlayerDetail(playerButton.dataset.rosterPlayerId);
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") closeTeamDetail();
    });

    window.thiSportHome = () => {
      if (state.sport === "cbb") showCbbView("cbb-projections");
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
    state.loading = Promise.all(Object.entries(PATHS).map(async ([key, path]) => {
      if (key === "projectionBoard") {
        try { return [key, await fetchJson(path)]; }
        catch (_error) { return [key, { meta: {}, games: [] }]; }
      }
      return [key, await fetchJson(path)];
    }))
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
    if (view === "cbb-player-ratings") loadPlayerRatings();
    if (scroll) window.scrollTo({ top: 0, behavior: "auto" });
  }

  function renderAll() {
    renderProjections();
    renderTracking();
    renderTeamData();
    renderRatings();
    renderPlayerRatings();
    renderBracketology();
    renderPortal();
    renderMarketResearch();
  }

  function renderError(error) {
    const message = escapeHtml(error?.message || "CBB data could not be loaded.");
    document.querySelectorAll(".cbb-view").forEach(section => {
      section.innerHTML = `<div class="cbb-error"><strong>College basketball data is temporarily unavailable.</strong><div>${message}</div></div>`;
    });
  }

  function renderProjections() {
    const { profiles, games, foundation, history, model, projectionBoard } = state.data;
    const meta = profiles.meta || {};
    const coverage = foundation.coverage || {};
    const projected = Array.isArray(projectionBoard?.games) ? projectionBoard.games : [];
    const scheduled = projected.length ? projected : (Array.isArray(games.games) ? games.games : []);
    const upcoming = scheduled
      .filter(game => String(game.status).toLowerCase() === "scheduled")
      .sort((a, b) => new Date(a.start_date) - new Date(b.start_date))
      .slice(0, 12);
    const trackedSignals = projected.filter(game => game.projection?.spread_signal_eligible).length;
    const modelVersion = model.meta?.model_version || "Research model";
    const view = document.getElementById("view-cbb-projections");
    view.innerHTML = `
      <div class="cbb-hero">
        <div>
          <div class="cbb-kicker">The Hammer Index · CBB Projections</div>
          <h1 class="cbb-title">The college basketball board.</h1>
          <p class="cbb-lede">Adjusted efficiency, tempo, Four Factors, personnel context and strict walk-forward testing—built as a separate basketball engine inside the same THI research platform.</p>
        </div>
        <div class="cbb-status-card">
          <span class="cbb-status-pill">Research projections</span>
          <div><strong>Sample-gated projection board</strong><p>Scores and win probabilities are visible from day one. Spread signals require six games for both teams and a five-point disagreement. Totals signals remain withheld.</p></div>
        </div>
      </div>

      <div class="cbb-stat-grid">
        ${statCard("D-I teams", integer(meta.team_count), "Full 2027 directory")}
        ${statCard("Historical games", integer(history.meta?.game_count), `${history.meta?.season_count || 0} walk-forward seasons`)}
        ${statCard("Projected games", integer(projected.length), "Current published window")}
        ${statCard("Tracked signals", integer(trackedSignals), "Six-game minimum · 5+ point edge")}
        ${statCard("Model state", "Sample-gated", escapeHtml(modelVersion))}
      </div>

      <section class="cbb-section">
        <div class="cbb-section-head"><div><div class="cbb-label">Projection board</div><h2 class="cbb-section-title">Upcoming games</h2></div><div class="cbb-section-note">Pregame score and win projections are research outputs. Only cards marked Tracked can carry a spread signal; totals remain projection context only.</div></div>
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
    const gameList = view.querySelector(".cbb-game-list");
    const openFromEvent = event => {
      const card = event.target.closest("[data-cbb-game-id]");
      if (card) openGameDetail(card.dataset.cbbGameId);
    };
    gameList?.addEventListener("click", openFromEvent);
    gameList?.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openFromEvent(event); }
    });
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
    const projection = game.projection;
    if (!projection) return `<article class="cbb-panel cbb-game-card"><div class="cbb-game-top"><span class="cbb-game-date">${escapeHtml(date)}</span>${game.neutral_site ? '<span class="cbb-chip">Neutral</span>' : ""}</div><div class="cbb-matchup">${escapeHtml(game.away?.team)} <span>vs.</span> ${escapeHtml(game.home?.team)}</div><div class="cbb-game-meta">${escapeHtml(venue)} · ${escapeHtml(network)}</div></article>`;
    const margin = Number(projection.home_margin);
    const favored = margin >= 0 ? game.home?.team : game.away?.team;
    const projectedLine = `${favored} -${Math.abs(margin).toFixed(1)}`;
    const stateLabel = projection.sample_state === "tracked_sample" ? "Tracked" : projection.sample_state === "developing_sample" ? "Developing" : projection.sample_state === "early_sample" ? "Early sample" : "Preseason";
    const signalTeam = Number(projection.spread_edge) >= 0 ? game.home?.team : game.away?.team;
    const signal = projection.spread_signal_eligible ? `<span class="cbb-projection-signal">${escapeHtml(signalTeam)} spread edge · ${number(Math.abs(Number(projection.spread_edge)),1)} pts</span>` : `<span class="cbb-projection-withheld">${stateLabel} · no spread signal</span>`;
    return `<article class="cbb-panel cbb-game-card" data-cbb-game-id="${escapeHtml(game.game_id)}" role="button" tabindex="0" aria-label="Open ${escapeHtml(game.away?.team)} at ${escapeHtml(game.home?.team)} matchup analysis"><div class="cbb-game-top"><span class="cbb-game-date">${escapeHtml(date)}</span><span class="cbb-chip">${escapeHtml(stateLabel)}</span></div><div class="cbb-matchup">${escapeHtml(game.away?.team)} <span>vs.</span> ${escapeHtml(game.home?.team)}</div><div class="cbb-projection-score"><strong>${number(projection.away_points,1)}–${number(projection.home_points,1)}</strong><span>${escapeHtml(projectedLine)} · ${pct(projection.home_win_probability)} home win</span></div><div class="cbb-projection-meta"><span>${number(projection.projected_possessions,1)} possessions</span><span>Projected total ${number(projection.total,1)} · totals signal withheld</span></div>${signal}<div class="cbb-game-meta">${escapeHtml(venue)} · ${escapeHtml(network)} · Open matchup analysis →</div></article>`;
  }

  function openGameDetail(gameId) {
    const game = state.data?.projectionBoard?.games?.find(row => String(row.game_id) === String(gameId));
    if (!game?.projection) return;
    const projection = game.projection;
    const context = projection.matchup_context || {};
    const home = context.home || {};
    const away = context.away || {};
    const market = game.market || {};
    const detail = document.getElementById("cbb-team-detail");
    const panel = detail.querySelector(".cbb-detail-panel");
    const start = new Date(game.start_date);
    const date = Number.isNaN(start.getTime()) ? "Date TBD" : new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", hour: game.start_time_tbd ? undefined : "numeric", minute: game.start_time_tbd ? undefined : "2-digit", timeZone: "America/New_York", timeZoneName: game.start_time_tbd ? undefined : "short" }).format(start);
    const stateLabel = humanize(projection.sample_state || "research");
    const spreadSide = Number(projection.home_margin) >= 0 ? game.home?.team : game.away?.team;
    const drivers = context.margin_drivers || [];
    panel.innerHTML = `
      <button class="cbb-detail-close" type="button" data-cbb-close>Close</button>
      <div class="cbb-kicker">THI CBB matchup analysis</div>
      <h2 class="cbb-detail-title" id="cbb-detail-title">${escapeHtml(game.away?.team)} at ${escapeHtml(game.home?.team)}</h2>
      <div class="cbb-detail-sub">${escapeHtml(date)} · ${escapeHtml(game.venue?.name || (game.neutral_site ? "Neutral site" : "Venue TBD"))} · ${escapeHtml(game.broadcasts?.map(item => item.network || item).filter(Boolean).join(", ") || "TV TBD")}</div>
      <div class="cbb-detail-grid">
        ${detailStat("Projected score", `${number(projection.away_points,1)}–${number(projection.home_points,1)}`)}
        ${detailStat("THI spread", `${spreadSide} -${number(Math.abs(Number(projection.home_margin)),1)}`)}
        ${detailStat("Home win probability", pct(projection.home_win_probability))}
        ${detailStat("Projected possessions", number(projection.projected_possessions,1))}
        ${detailStat("Projected total", number(projection.total,1))}
        ${detailStat("Sample state", stateLabel)}
      </div>
      <section class="cbb-detail-section"><h3>Team efficiency state</h3>
        <div class="cbb-panel cbb-table-wrap"><table class="cbb-table cbb-matchup-table"><thead><tr><th>Team</th><th>Adj offense</th><th>Adj defense</th><th>Tempo</th><th>Games</th><th>Source</th></tr></thead><tbody>
          <tr><td class="cbb-team-name">${escapeHtml(game.away?.team)}</td><td class="cbb-number">${number(away.offense,2)}</td><td class="cbb-number">${number(away.defense,2)}</td><td class="cbb-number">${number(away.tempo,2)}</td><td class="cbb-number">${integer(away.games)}</td><td>${escapeHtml(humanize(away.rating_source || "unknown"))}</td></tr>
          <tr><td class="cbb-team-name">${escapeHtml(game.home?.team)}</td><td class="cbb-number">${number(home.offense,2)}</td><td class="cbb-number">${number(home.defense,2)}</td><td class="cbb-number">${number(home.tempo,2)}</td><td class="cbb-number">${integer(home.games)}</td><td>${escapeHtml(humanize(home.rating_source || "unknown"))}</td></tr>
        </tbody></table></div>
      </section>
      <section class="cbb-detail-section"><h3>Largest margin drivers</h3>
        <div class="cbb-model-sub">Point contributions explain this projection relative to the model baseline. Positive values favor ${escapeHtml(game.home?.team)}; negative values favor ${escapeHtml(game.away?.team)}.</div>
        <div class="cbb-driver-list">${drivers.map(driver => {
          const points = Number(driver.margin_points);
          const side = points >= 0 ? game.home?.team : game.away?.team;
          return `<div class="cbb-detail-row"><span>${escapeHtml(humanize(driver.feature))}</span><strong class="${points >= 0 ? "cbb-driver-home" : "cbb-driver-away"}">${escapeHtml(side)} ${number(Math.abs(points),2)} pts</strong></div>`;
        }).join("")}</div>
      </section>
      <section class="cbb-detail-section"><h3>Market and signal state</h3>
        ${detailRow("Consensus home spread", market.consensus_home_spread == null ? "Not posted" : number(market.consensus_home_spread,1,true))}
        ${detailRow("Consensus total", market.consensus_total == null ? "Not posted" : number(market.consensus_total,1))}
        ${detailRow("Model spread edge", projection.spread_edge == null ? "Unavailable" : `${number(projection.spread_edge,1,true)} points`)}
        ${detailRow("Spread signal", projection.spread_signal_eligible ? "Eligible" : "Withheld")}
        ${detailRow("Totals signal", "Withheld")}
        <div class="cbb-model-sub">Spread signals require at least six games for both teams and a five-point model-versus-market disagreement. Projected totals remain informational while totals validation is below THI's promotion standard.</div>
      </section>`;
    detail.classList.add("is-open");
    detail.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    panel.scrollTop = 0;
    panel.querySelector("[data-cbb-close]")?.focus();
  }

  function renderTeamData() {
    const view = document.getElementById("view-cbb-team-data");
    const teams = [...(state.data.profiles.teams || [])].sort((a, b) => a.team.localeCompare(b.team));
    view.innerHTML = `
      <div class="cbb-kicker">Team directory and profiles</div>
      <h1 class="page-title">CBB Team Data</h1>
      <p class="page-subtitle">Every Division I program in the THI basketball warehouse. Open a team to inspect its efficiency baseline, recruiting class and incoming-transfer production.</p>
      <div class="cbb-controls cbb-controls-single"><input id="cbb-team-data-search" class="cbb-input" type="search" placeholder="Search 365 Division I teams"></div>
      <div class="cbb-panel cbb-table-wrap"><table class="cbb-table" aria-label="College basketball team directory"><thead><tr><th>Team</th><th>Conference</th><th>2026 source rank</th><th>2027 state</th></tr></thead><tbody id="cbb-team-data-body"></tbody></table></div>
    `;
    const paint = query => {
      const needle = String(query || "").trim().toLowerCase();
      const visible = teams.filter(team => !needle || `${team.team} ${team.display_name} ${team.conference?.name || ""}`.toLowerCase().includes(needle));
      view.querySelector("#cbb-team-data-body").innerHTML = visible.map(team => `<tr data-team-id="${team.team_id}"><td><div class="cbb-team-name">${escapeHtml(team.display_name || team.team)}</div><div class="cbb-team-meta">Open team profile →</div></td><td>${escapeHtml(team.conference?.abbreviation || "—")}</td><td class="cbb-number">${team.preseason_prior?.adjusted?.net_rank ? `#${integer(team.preseason_prior.adjusted.net_rank)}` : "—"}</td><td><span class="cbb-chip">Preseason prior</span></td></tr>`).join("");
    };
    paint("");
    view.querySelector("#cbb-team-data-search").addEventListener("input", event => paint(event.target.value));
    view.querySelector("#cbb-team-data-body").addEventListener("click", event => {
      const row = event.target.closest("[data-team-id]");
      if (row) openTeamDetail(Number(row.dataset.teamId));
    });
  }

  function renderPlayerRatings() {
    const view = document.getElementById("view-cbb-player-ratings");
    if (!state.playerData) {
      view.innerHTML = `
        <div class="cbb-kicker">Player-level basketball intelligence</div>
        <h1 class="page-title">CBB Player Ratings</h1>
        <p class="page-subtitle">THI's research layer grades production, efficiency, role and two-way possession value without feeding these ratings into public game projections.</p>
        <div class="cbb-readiness-banner"><span class="cbb-status-pill">Research v1.2</span><strong>${state.playerLoading ? "Loading the player board" : "Player board available"}</strong><p>${state.playerLoading ? "Reading the roster-verified player layer…" : "Open this tab to load active-roster players with qualified prior-season production. Ratings remain research-only until opponent and lineup adjustments are validated."}</p></div>
      `;
      return;
    }
    const payload = state.playerData;
    const meta = payload.meta || {};
    const players = payload.players || [];
    const conferences = [...new Set(players.map(player => player.conference).filter(Boolean))].sort();
    view.innerHTML = `
      <div class="cbb-kicker">Player-level basketball intelligence</div>
      <h1 class="page-title">CBB Player Ratings</h1>
      <p class="page-subtitle">Active ${escapeHtml(meta.roster_season || meta.season)} roster players with qualified ${escapeHtml(meta.source_season || "prior-season")} production, graded by THI efficiency, role and two-way possession value. This is a research reference layer and is not yet opponent-adjusted or lineup-adjusted.</p>
      <div class="cbb-stat-grid">
        ${statCard("Qualified players", integer(meta.player_count), `${integer(meta.team_count)} Division I teams`)}
        ${statCard("Minimum sample", `${integer(meta.minimum_minutes)} min`, `${integer(meta.minimum_games)} games`)}
        ${statCard("Roster state", "Verified active", `${integer(payload.coverage?.historical_players_withheld_unverified_current)} historical priors withheld`)}
        ${statCard("Projection use", "Research only", "No game-line adjustment")}
      </div>
      <div class="cbb-player-controls">
        <input id="cbb-player-search" class="cbb-input" type="search" placeholder="Search player, team or conference" value="${escapeHtml(state.playerQuery)}">
        <select id="cbb-player-position" class="cbb-select"><option value="all">All positions</option><option value="backcourt" ${state.playerPosition === "backcourt" ? "selected" : ""}>Backcourt</option><option value="wing" ${state.playerPosition === "wing" ? "selected" : ""}>Wings</option><option value="frontcourt" ${state.playerPosition === "frontcourt" ? "selected" : ""}>Frontcourt</option></select>
        <select id="cbb-player-conference" class="cbb-select"><option value="all">All conferences</option>${conferences.map(conf => `<option value="${escapeHtml(conf)}" ${state.playerConference === conf ? "selected" : ""}>${escapeHtml(conf)}</option>`).join("")}</select>
        <select id="cbb-player-reliability" class="cbb-select"><option value="0">Any reliability</option><option value="60" ${state.playerReliability === 60 ? "selected" : ""}>60%+ reliability</option><option value="80" ${state.playerReliability === 80 ? "selected" : ""}>80%+ reliability</option><option value="100" ${state.playerReliability === 100 ? "selected" : ""}>Full reliability</option></select>
      </div>
      <div class="cbb-panel cbb-table-wrap">
        <table class="cbb-table cbb-player-table" aria-label="THI college basketball player ratings"><thead><tr>
          <th>Rank</th>${playerHeader("name", "Player")}${playerHeader("team", "Team")}${playerHeader("position", "Pos")}${playerHeader("thi_player_rating", "THI")}${playerHeader("offense", "Off")}${playerHeader("defense", "Def")}${playerHeader("all_around", "All-around")}${playerHeader("points_per_40", "Pts/40")}${playerHeader("true_shooting_pct", "TS%")} ${playerHeader("porpag", "PORPAG")}${playerHeader("reliability", "Reliability")}
        </tr></thead><tbody id="cbb-player-body"></tbody></table>
      </div>
      <div class="cbb-player-pager"><button type="button" data-player-page="prev">Previous</button><span id="cbb-player-page-status"></span><button type="button" data-player-page="next">Next</button></div>
      <div class="cbb-stat-note">Only players verified on a ${escapeHtml(meta.roster_season || meta.season)} roster are shown. Displayed metrics use ${escapeHtml(meta.source_season || "prior-season")} production. Green is stronger, red is weaker. Rank numbers remain neutral.</div>
    `;
    bindPlayerControls();
    paintPlayerRows();
  }

  function loadPlayerRatings() {
    if (state.playerData || state.playerLoading) return state.playerLoading;
    state.playerLoading = fetchJson(PLAYER_PATH)
      .then(payload => {
        if (!Array.isArray(payload.players)) throw new Error("Player ratings payload is missing players.");
        if (payload.meta?.version !== "thi-cbb-player-research-v1.2" || !Array.isArray(payload.team_rosters) || payload.players.some(player => player.current_roster_verified !== true)) {
          throw new Error("The roster-verified player rebuild has not completed. Historical-only ratings are withheld.");
        }
        state.playerData = payload;
        state.playerBandCache = {};
        renderPlayerRatings();
        return payload;
      })
      .catch(error => {
        const view = document.getElementById("view-cbb-player-ratings");
        if (view) view.innerHTML = `<div class="cbb-error"><strong>CBB player ratings are temporarily unavailable.</strong><div>${escapeHtml(error.message)}</div></div>`;
      })
      .finally(() => { state.playerLoading = null; });
    renderPlayerRatings();
    return state.playerLoading;
  }

  function playerValue(player, key) {
    if (key === "name" || key === "team" || key === "position") return player[key] || "";
    if (key === "reliability") return player.data_quality?.reliability ?? -Infinity;
    if (["thi_player_rating", "offense", "defense", "all_around"].includes(key)) return player.research_scores?.[key] ?? -Infinity;
    return player.metrics?.[key] ?? -Infinity;
  }

  function playerRows() {
    const players = state.playerData?.players || [];
    const query = state.playerQuery.trim().toLowerCase();
    return players.filter(player => {
      const matchesQuery = !query || `${player.name} ${player.team} ${player.conference} ${player.position}`.toLowerCase().includes(query);
      const matchesConference = state.playerConference === "all" || player.conference === state.playerConference;
      const matchesPosition = state.playerPosition === "all" || player.position_group === state.playerPosition;
      const matchesReliability = Number(player.data_quality?.reliability || 0) >= state.playerReliability;
      return matchesQuery && matchesConference && matchesPosition && matchesReliability;
    }).sort((a, b) => {
      const av = playerValue(a, state.playerSort.key);
      const bv = playerValue(b, state.playerSort.key);
      const order = typeof av === "string" ? av.localeCompare(bv) : (Number(av) || 0) - (Number(bv) || 0);
      return state.playerSort.direction === "asc" ? order : -order;
    });
  }

  function playerHeader(key, label) {
    const active = state.playerSort.key === key;
    const arrow = active ? (state.playerSort.direction === "desc" ? " ↓" : " ↑") : " ↕";
    return `<th data-player-sort="${key}" class="${active ? "is-sorted" : ""}">${escapeHtml(label)}${arrow}</th>`;
  }

  function bindPlayerControls() {
    const view = document.getElementById("view-cbb-player-ratings");
    view.querySelector("#cbb-player-search").addEventListener("input", event => { state.playerQuery = event.target.value; state.playerPage = 1; paintPlayerRows(); });
    view.querySelector("#cbb-player-position").addEventListener("change", event => { state.playerPosition = event.target.value; state.playerPage = 1; paintPlayerRows(); });
    view.querySelector("#cbb-player-conference").addEventListener("change", event => { state.playerConference = event.target.value; state.playerPage = 1; paintPlayerRows(); });
    view.querySelector("#cbb-player-reliability").addEventListener("change", event => { state.playerReliability = Number(event.target.value); state.playerPage = 1; paintPlayerRows(); });
    view.querySelector("thead").addEventListener("click", event => {
      const header = event.target.closest("[data-player-sort]");
      if (!header) return;
      const key = header.dataset.playerSort;
      state.playerSort.direction = state.playerSort.key === key && state.playerSort.direction === "desc" ? "asc" : "desc";
      state.playerSort.key = key;
      state.playerPage = 1;
      renderPlayerRatings();
    });
    view.querySelector("#cbb-player-body").addEventListener("click", event => {
      const row = event.target.closest("[data-player-id]");
      if (row) openPlayerDetail(row.dataset.playerId);
    });
    view.querySelector(".cbb-player-pager").addEventListener("click", event => {
      const button = event.target.closest("[data-player-page]");
      if (!button || button.disabled) return;
      state.playerPage += button.dataset.playerPage === "next" ? 1 : -1;
      paintPlayerRows();
      view.querySelector(".cbb-table-wrap")?.scrollTo({ left: 0, top: 0, behavior: "auto" });
    });
  }

  function paintPlayerRows() {
    const body = document.getElementById("cbb-player-body");
    if (!body) return;
    const rows = playerRows();
    const pageCount = Math.max(1, Math.ceil(rows.length / state.playerPageSize));
    state.playerPage = Math.min(Math.max(1, state.playerPage), pageCount);
    const start = (state.playerPage - 1) * state.playerPageSize;
    const page = rows.slice(start, start + state.playerPageSize);
    const bands = Object.fromEntries(["thi_player_rating", "offense", "defense", "all_around", "points_per_40", "true_shooting_pct", "porpag", "reliability"].map(key => [key, cachedPlayerBands(key)]));
    body.innerHTML = page.length ? page.map(player => {
      const score = player.research_scores || {};
      const metrics = player.metrics || {};
      return `<tr data-player-id="${escapeHtml(player.player_season_id)}"><td class="cbb-rank">#${integer(player.ranks?.overall)}</td><td><div class="cbb-team-name">${escapeHtml(player.name)}</div><div class="cbb-team-meta">${escapeHtml(player.role)} · Open profile →</div></td><td>${escapeHtml(player.team)}</td><td>${escapeHtml(player.position || "—")}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.thi_player_rating(player)}">${number(score.thi_player_rating,1)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.offense(player)}">${number(score.offense,1)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.defense(player)}">${number(score.defense,1)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.all_around(player)}">${number(score.all_around,1)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.points_per_40(player)}">${number(metrics.points_per_40,1)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.true_shooting_pct(player)}">${shootingPct(metrics.true_shooting_pct)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.porpag(player)}">${number(metrics.porpag,2)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.reliability(player)}">${pct(player.data_quality?.reliability)}</td></tr>`;
    }).join("") : `<tr><td colspan="12" class="cbb-empty">No players match those filters.</td></tr>`;
    const status = document.getElementById("cbb-player-page-status");
    if (status) status.textContent = `${integer(rows.length)} players · page ${state.playerPage} of ${pageCount}`;
    const prev = document.querySelector('[data-player-page="prev"]');
    const next = document.querySelector('[data-player-page="next"]');
    if (prev) prev.disabled = state.playerPage <= 1;
    if (next) next.disabled = state.playerPage >= pageCount;
  }

  function playerQuantileBands(players, key, lowerIsBetter = false) {
    const values = players.map(player => Number(playerValue(player, key))).filter(Number.isFinite).sort((a, b) => a - b);
    return player => {
      const value = Number(playerValue(player, key));
      if (!Number.isFinite(value) || !values.length) return 3;
      let low = 0;
      let high = values.length;
      while (low < high) { const middle = (low + high) >>> 1; if (values[middle] < value) low = middle + 1; else high = middle; }
      const percentile = low / Math.max(1, values.length - 1);
      const score = lowerIsBetter ? 1 - percentile : percentile;
      return Math.max(1, Math.min(5, Math.ceil(score * 5)));
    };
  }

  function cachedPlayerBands(key, lowerIsBetter = false) {
    const cacheKey = `${key}:${lowerIsBetter ? "low" : "high"}`;
    if (!state.playerBandCache[cacheKey]) {
      state.playerBandCache[cacheKey] = playerQuantileBands(state.playerData?.players || [], key, lowerIsBetter);
    }
    return state.playerBandCache[cacheKey];
  }

  function shootingPct(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return "—";
    return `${(parsed <= 1.5 ? parsed * 100 : parsed).toFixed(1)}%`;
  }

  function openPlayerDetail(playerId) {
    const player = state.playerData?.players?.find(row => row.player_season_id === playerId);
    if (!player) return;
    const detail = document.getElementById("cbb-team-detail");
    const panel = detail.querySelector(".cbb-detail-panel");
    const score = player.research_scores || {};
    const metrics = player.metrics || {};
    panel.innerHTML = `
      <button class="cbb-detail-close" type="button" data-cbb-close>Close</button>
      <div class="cbb-kicker">THI CBB player profile</div>
      <h2 class="cbb-detail-title" id="cbb-detail-title">${escapeHtml(player.name)}</h2>
      <div class="cbb-detail-sub">${escapeHtml(player.team)} · ${escapeHtml(player.conference || "Independent")} · ${escapeHtml(player.position || "Position unavailable")} · ${escapeHtml(player.role)}</div>
      <div class="cbb-detail-grid">
        ${detailStat("THI rating", number(score.thi_player_rating,1))}
        ${detailStat("Overall rank", `#${integer(player.ranks?.overall)}`)}
        ${detailStat("Position rank", `#${integer(player.ranks?.position_group)}`)}
        ${detailStat("Offense", number(score.offense,1))}
        ${detailStat("Defense", number(score.defense,1))}
        ${detailStat("All-around", number(score.all_around,1))}
      </div>
      <section class="cbb-detail-section"><h3>Scoring and creation</h3>
        ${playerDetailRow("Points per 40", number(metrics.points_per_40,2), player, "points_per_40")}${playerDetailRow("Usage", pct(metrics.usage), player, "usage")}${playerDetailRow("True shooting", shootingPct(metrics.true_shooting_pct), player, "true_shooting_pct")}${playerDetailRow("Effective FG", pct(metrics.effective_field_goal_pct), player, "effective_field_goal_pct")}${playerDetailRow("PORPAG", number(metrics.porpag,3), player, "porpag")}${playerDetailRow("Offensive rating", number(metrics.offensive_rating,1), player, "offensive_rating")}${playerDetailRow("Assist / turnover", number(metrics.assist_turnover_ratio,2), player, "assist_turnover_ratio")}${playerDetailRow("Assists per 40", number(metrics.assists_per_40,2), player, "assists_per_40")}${playerDetailRow("Turnovers per 40", number(metrics.turnovers_per_40,2), player, "turnovers_per_40", true)}
      </section>
      <section class="cbb-detail-section"><h3>Defense and possession value</h3>
        ${playerDetailRow("Defensive rating", number(metrics.defensive_rating,1), player, "defensive_rating", true)}${playerDetailRow("Net rating", number(metrics.net_rating,1,true), player, "net_rating")}${playerDetailRow("Rebounds per 40", number(metrics.rebounds_per_40,2), player, "rebounds_per_40")}${playerDetailRow("Offensive rebounds per 40", number(metrics.offensive_rebounds_per_40,2), player, "offensive_rebounds_per_40")}${playerDetailRow("Steals per 40", number(metrics.steals_per_40,2), player, "steals_per_40")}${playerDetailRow("Blocks per 40", number(metrics.blocks_per_40,2), player, "blocks_per_40")}${playerDetailRow("Win shares per 40", number(metrics.total_win_shares_per_40,3), player, "total_win_shares_per_40")}
      </section>
      <section class="cbb-detail-section"><h3>Sample and rating state</h3>
        ${detailRow("Current roster", `${player.team} · ${state.playerData?.meta?.roster_season || state.playerData?.meta?.season}`)}${detailRow("Production source", `${player.source_team || player.team} · ${player.source_season || state.playerData?.meta?.source_season || "Prior season"}`)}${detailRow("Between-season transfer", player.transfer_between_seasons ? "Yes" : "No")}${detailRow("Games", integer(player.sample?.games))}${detailRow("Starts", integer(player.sample?.starts))}${detailRow("Minutes", integer(player.sample?.minutes))}${detailRow("Minutes per game", number(player.sample?.minutes_per_game,1))}${detailRow("Reliability", pct(player.data_quality?.reliability))}${detailRow("Projection use", "Research reference only")}
        <div class="cbb-model-sub">V1.2 displays only active-roster players and uses the prior completed season as the statistical input. Opponent and lineup adjustments are not active yet.</div>
      </section>`;
    detail.classList.add("is-open");
    detail.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    panel.scrollTop = 0;
    panel.querySelector("[data-cbb-close]")?.focus();
  }

  function playerDetailRow(label, value, player, key, lowerIsBetter = false) {
    const band = cachedPlayerBands(key, lowerIsBetter)(player);
    return `<div class="cbb-detail-row"><span>${escapeHtml(label)}</span><strong class="cbb-player-grade cbb-band-${band}">${escapeHtml(value)}</strong></div>`;
  }

  function renderBracketology() {
    const view = document.getElementById("view-cbb-bracketology");
    view.innerHTML = `
      <div class="cbb-kicker">NCAA tournament projection</div>
      <h1 class="page-title">THI Bracketology</h1>
      <p class="page-subtitle">A projected 68-team field built from THI team strength, résumé quality, conference races and selection-committee style inputs.</p>
      <div class="cbb-readiness-banner"><span class="cbb-status-pill">Preseason shell</span><strong>The field is not projected yet</strong><p>The bracket activates after schedules, current-season results and conference membership are complete enough to support automatic-bid and at-large modeling.</p></div>
      <section class="cbb-section"><div class="cbb-section-head"><div><div class="cbb-label">THI selection framework</div><h2 class="cbb-section-title">Four separate questions</h2></div></div>
        <div class="cbb-stat-grid">
          ${statCard("Team quality", "THI rating", "Opponent-adjusted possession strength")}
          ${statCard("Résumé", "Earned seed", "Results, location and opponent quality")}
          ${statCard("Auto bids", "Conference race", "Projected tournament champions")}
          ${statCard("Bubble", "In / out", "Bid probability with first four out")}
        </div>
      </section>
    `;
  }

  function renderPortal() {
    const view = document.getElementById("view-cbb-portal");
    const teams = [...(state.data.priors.teams || [])]
      .filter(team => Number(team.personnel?.transfers?.incoming_count) > 0)
      .sort((a, b) => Number(b.personnel?.transfers?.prior_minutes || 0) - Number(a.personnel?.transfers?.prior_minutes || 0));
    const totalIncoming = teams.reduce((sum, team) => sum + Number(team.personnel?.transfers?.incoming_count || 0), 0);
    const matched = teams.reduce((sum, team) => sum + Number(team.personnel?.transfers?.prior_production_match_count || 0), 0);
    view.innerHTML = `
      <div class="cbb-kicker">Roster movement and proven production</div>
      <h1 class="page-title">CBB Transfer Portal</h1>
      <p class="page-subtitle">Team-level incoming transfer context using ratings and prior college production. This board measures what arrives; it does not treat raw transfer count as automatic improvement.</p>
      <div class="cbb-stat-grid">
        ${statCard("Teams with additions", integer(teams.length), "2027 incoming transfer classes")}
        ${statCard("Incoming players", integer(totalIncoming), "Rated and unrated additions")}
        ${statCard("Production matches", integer(matched), "Incoming players matched to prior stats")}
        ${statCard("Primary sort", "Prior minutes", "Established college workload")}
      </div>
      <section class="cbb-section"><div class="cbb-section-head"><div><div class="cbb-label">Team portal board</div><h2 class="cbb-section-title">Incoming production</h2></div><div class="cbb-section-note">Click a team for its full personnel context.</div></div>
        <div class="cbb-panel cbb-table-wrap"><table class="cbb-table"><thead><tr><th>Team</th><th>Conf</th><th>Incoming</th><th>Matched</th><th>Prior minutes</th><th>Prior points</th><th>Mean rating</th></tr></thead><tbody>${teams.map(team => { const t=team.personnel.transfers; return `<tr data-team-id="${team.team_id}"><td class="cbb-team-name">${escapeHtml(team.team)}</td><td>${escapeHtml(team.conference?.abbreviation || "—")}</td><td class="cbb-number">${integer(t.incoming_count)}</td><td class="cbb-number">${integer(t.prior_production_match_count)}</td><td class="cbb-number">${integer(t.prior_minutes)}</td><td class="cbb-number">${integer(t.prior_points)}</td><td class="cbb-number">${number(t.mean_incoming_rating,3)}</td></tr>`; }).join("")}</tbody></table></div>
      </section>
    `;
    view.querySelector("tbody").addEventListener("click", event => {
      const row = event.target.closest("[data-team-id]");
      if (row) openTeamDetail(Number(row.dataset.teamId));
    });
  }

  function renderMarketResearch() {
    const view = document.getElementById("view-cbb-market");
    const coverage = state.data.foundation.coverage || {};
    const history = state.data.history.seasons || [];
    const test = state.data.model.evaluation?.out_of_time_test || {};
    const marketGames = history.reduce((sum, season) => sum + Number(season.games_with_market || 0), 0);
    view.innerHTML = `
      <div class="cbb-kicker">Price discovery and model accountability</div>
      <h1 class="page-title">CBB Market Research</h1>
      <p class="page-subtitle">Market lines remain evaluation context rather than model inputs. Current edges will stay hidden until the model clears its public-projection gate.</p>
      <div class="cbb-stat-grid">
        ${statCard("Historical market games", integer(marketGames), "2018–2026 evaluation inventory")}
        ${statCard("Current board lines", integer(coverage.games_with_market), `${integer(coverage.window_games)} scheduled games scanned`)}
        ${statCard("2026 market margin MAE", number(test.market_margin_mae,3), "Closing-market comparison")}
        ${statCard("2026 THI margin MAE", number(test.margin_mae,3), "Out-of-time research test")}
      </div>
      <section class="cbb-section"><div class="cbb-section-head"><div><div class="cbb-label">Research rules</div><h2 class="cbb-section-title">How prices are used</h2></div></div>
        <div class="cbb-method-grid">
          ${methodCard("Isolation", "Never a model feature", "Market spread and total are withheld from the predictive feature set.")}
          ${methodCard("Comparison", "Measure disagreement", "Frozen THI projections are compared with the available market and final result.")}
          ${methodCard("Accountability", "Track before promotion", "ATS, total, calibration and error results must generalize out of time before public signals appear.")}
        </div>
      </section>
    `;
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

  async function openTeamDetail(teamId) {
    const prior = state.data.priors.teams.find(team => Number(team.team_id) === Number(teamId));
    const profile = state.data.profiles.teams.find(team => Number(team.team_id) === Number(teamId));
    if (!prior) return;
    const detail = document.getElementById("cbb-team-detail");
    const panel = detail.querySelector(".cbb-detail-panel");
    if (!state.playerData) {
      panel.innerHTML = `<button class="cbb-detail-close" type="button" data-cbb-close>Close</button><div class="cbb-kicker">THI CBB team profile</div><h2 class="cbb-detail-title" id="cbb-detail-title">${escapeHtml(profile?.display_name || prior.team)}</h2><div class="cbb-readiness-banner"><strong>Loading verified roster…</strong></div>`;
      detail.classList.add("is-open");
      detail.setAttribute("aria-hidden", "false");
      document.body.style.overflow = "hidden";
      await loadPlayerRatings();
    }
    const recruiting = prior.personnel?.recruiting || {};
    const transfers = prior.personnel?.transfers || {};
    const preseason = profile?.preseason_prior || {};
    const roster = state.playerData?.team_rosters?.find(row => Number(row.team_id) === Number(teamId));
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
      <section class="cbb-detail-section"><h3>Verified roster and rotation outlook</h3>
        <div class="cbb-model-sub">Every listed player is verified on the current roster. THI grades appear only when the player has a qualifying prior-season sample; freshmen and limited samples stay explicitly unrated.</div>
        <div class="cbb-roster-summary">${detailRow("Active players", roster ? integer(roster.player_count) : "Unavailable")}${detailRow("Qualified returning production", roster ? integer(roster.rated_player_count) : "—")}${detailRow("Returning minutes", roster?.returning_minutes_pct != null ? pct(roster.returning_minutes_pct) : "Unavailable")}${detailRow("Identified transfers", roster ? integer(roster.transfer_count) : "—")}</div>
        <div class="cbb-roster-list">${roster?.players?.length ? roster.players.map(rosterPlayerRow).join("") : `<div class="cbb-empty">A verified current roster is not available for this team yet.</div>`}</div>
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

  function rosterPlayerRow(player) {
    const identity = [player.position, player.class, player.height].filter(Boolean).join(" · ") || "Roster verified";
    const prior = player.prior_state === "rated"
      ? `<button type="button" class="cbb-roster-rating" data-roster-player-id="${escapeHtml(player.player_season_id)}">${number(player.thi_player_rating,1)} THI · profile →</button>`
      : `<span class="cbb-roster-unrated">${player.prior_state === "below_sample" ? "Limited prior sample" : "No qualifying prior"}</span>`;
    const transfer = player.transfer_between_seasons ? `<span class="cbb-chip">Transfer · ${escapeHtml(player.prior_team || "prior team")}</span>` : "";
    return `<article class="cbb-roster-player"><div><strong>${player.jersey ? `#${escapeHtml(player.jersey)} ` : ""}${escapeHtml(player.name || "Unknown player")}</strong><div class="cbb-team-meta">${escapeHtml(identity)}</div></div><div class="cbb-roster-player-state">${transfer}${prior}</div></article>`;
  }

  function renderTracking() {
    const card = state.data.model;
    const validation = card.evaluation?.validation || {};
    const test = card.evaluation?.out_of_time_test || {};
    const checks = card.promotion_gate?.checks || {};
    const ats = test.ats_by_edge || [];
    const totals = test.totals_by_edge || [];
    const contexts = test.context_slices || {};
    const calibration = test.win_probability_calibration || [];
    const view = document.getElementById("view-cbb-tracking");
    view.innerHTML = `
      <div class="cbb-kicker">Transparent research and accountability</div>
      <h1 class="page-title">CBB Model Tracking</h1>
      <p class="page-subtitle">Strict walk-forward evaluation with market prices reserved for comparison. Current-season end ratings never initialize the same season.</p>
      <div class="cbb-model-grid">
        ${modelCard("2025 validation", "Margin MAE", number(validation.margin_mae,3), `${integer(validation.games)} games · ${pct(validation.winner_accuracy)} winner accuracy`)}
        ${modelCard("2026 out-of-time test", "Margin MAE", number(test.margin_mae,3), `${integer(test.games)} games · ${pct(test.winner_accuracy)} winner accuracy`)}
        ${modelCard("2026 market comparison", "Margin MAE gap", number(Number(test.margin_mae) - Number(test.market_margin_mae),3,true), `THI ${number(test.margin_mae,3)} · market ${number(test.market_margin_mae,3)}`)}
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
        <div class="cbb-section-head"><div><div class="cbb-label">2026 out-of-time test</div><h2 class="cbb-section-title">Totals disagreement audit</h2></div><div class="cbb-section-note">Totals remain a separate research problem and must clear their own validation gate.</div></div>
        <div class="cbb-panel cbb-table-wrap"><table class="cbb-table"><thead><tr><th>Minimum disagreement</th><th>Wins</th><th>Losses</th><th>Pushes</th><th>Hit rate</th></tr></thead><tbody>${totals.map(row => `<tr><td class="cbb-number">${row.minimum_edge}+ pts</td><td class="cbb-number">${integer(row.wins)}</td><td class="cbb-number">${integer(row.losses)}</td><td class="cbb-number">${integer(row.pushes)}</td><td class="cbb-number">${pct(row.hit_rate)}</td></tr>`).join("")}</tbody></table></div>
      </section>

      <section class="cbb-section">
        <div class="cbb-section-head"><div><div class="cbb-label">Error anatomy</div><h2 class="cbb-section-title">Performance by game context</h2></div><div class="cbb-section-note">This separates unstable opening samples from settled team states and campus games from neutral floors.</div></div>
        <div class="cbb-panel cbb-table-wrap"><table class="cbb-table"><thead><tr><th>Context</th><th>Games</th><th>THI margin MAE</th><th>Market margin MAE</th><th>THI total MAE</th><th>Market total MAE</th><th>Winner accuracy</th></tr></thead><tbody>${Object.entries(contexts).map(([key,row]) => `<tr><td>${escapeHtml(humanize(key))}</td><td class="cbb-number">${integer(row.games)}</td><td class="cbb-number">${number(row.margin_mae,3)}</td><td class="cbb-number">${number(row.market_margin_mae,3)}</td><td class="cbb-number">${number(row.total_mae,3)}</td><td class="cbb-number">${number(row.market_total_mae,3)}</td><td class="cbb-number">${pct(row.winner_accuracy)}</td></tr>`).join("")}</tbody></table></div>
      </section>

      <section class="cbb-section">
        <div class="cbb-section-head"><div><div class="cbb-label">Probability honesty</div><h2 class="cbb-section-title">Win-probability calibration</h2></div><div class="cbb-section-note">A calibrated 70% forecast should win about seven times in ten over a large sample.</div></div>
        <div class="cbb-panel cbb-table-wrap"><table class="cbb-table"><thead><tr><th>Forecast band</th><th>Games</th><th>Mean projection</th><th>Actual home win rate</th><th>Calibration gap</th></tr></thead><tbody>${calibration.map(row => `<tr><td class="cbb-number">${escapeHtml(row.range)}</td><td class="cbb-number">${integer(row.games)}</td><td class="cbb-number">${pct(row.mean_projected_probability)}</td><td class="cbb-number">${pct(row.actual_home_win_rate)}</td><td class="cbb-number">${number(Number(row.actual_home_win_rate) - Number(row.mean_projected_probability),2,true)} pts</td></tr>`).join("")}</tbody></table></div>
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
