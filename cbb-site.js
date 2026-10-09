(() => {
  "use strict";

  const PATHS = {
    profiles: "data/cbb/team_profiles.json",
    games: "data/cbb/game_board.json",
    foundation: "data/cbb/foundation_status.json",
    model: "data/cbb/model/model_card.json",
    priors: "data/cbb/model/current_priors.json",
    homeCourt: "data/cbb/home_court_advantage.json",
    history: "data/cbb/history/manifest.json",
    projectionBoard: "data/cbb/projection_board.json",
    playStyle: "data/cbb/play_style.json",
    matchups: "data/cbb/matchup_engine.json",
    intelligence: "data/cbb/intelligence_suite.json",
    tracking: "data/cbb/model_tracking.json",
    bracketology: "data/cbb/bracketology.json",
    challenger: "data/cbb/research/model_v02_challenger.json",
    readiness: "data/cbb/game_day_readiness.json",
    operations: "data/cbb/operations_context.json",
    health: "data/cbb/platform_health.json",
    trends: "data/trends_lab.json",
    varianceTracker: "data/variance/prospective_tracker.json",
    rlmMonitor: "data/market/rlm_monitor.json",
    publicBacktest: "data/reports/public_backtest_scorecard.json",
    marketSnapshots: "data/cbb/market_snapshots.json"
  };
  const PLAYER_PATH = "data/cbb/player_ratings.json";
  const CORE_DATA_KEYS = new Set(["profiles", "foundation", "model", "priors", "homeCourt", "history", "projectionBoard", "tracking", "bracketology", "readiness", "health", "trends", "varianceTracker", "publicBacktest", "marketSnapshots"]);
  const DEFERRED_VIEW_KEYS = {
    "cbb-projections": ["intelligence", "matchups", "operations"],
    "cbb-team-data": ["intelligence"],
    "cbb-ratings": ["intelligence"],
    "cbb-market": ["intelligence", "rlmMonitor"],
    "cbb-variance": ["trends", "varianceTracker", "rlmMonitor"],
  };

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
    deferredLoads: {},
    projectionQuery: "",
    projectionConference: "all",
    projectionSignal: "all",
    projectionConfidence: "all",
    projectionSort: "time",
    projectionStatus: "all",
    projectionDate: "next",
    projectionLimit: 150,
    teamDataQuery: "",
    teamDataConference: "all",
    teamDataSort: { key: "team", direction: "asc" },
    portalQuery: "",
    portalConference: "all",
    portalSort: { key: "prior_minutes", direction: "desc" },
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
  const formatTimestamp = value => {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? "Awaiting refresh" : new Intl.DateTimeFormat("en-US", { month:"short", day:"numeric", hour:"numeric", minute:"2-digit", timeZone:"America/New_York", timeZoneName:"short" }).format(parsed);
  };

  const integer = value => Number.isFinite(Number(value))
    ? Math.round(Number(value)).toLocaleString("en-US")
    : "—";

  const pct = value => Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}%` : "—";
  const normalizeSearch = value => String(value ?? "").trim().toLocaleLowerCase();
  const matchupWord = row => row?.neutral_site ? "vs." : "at";

  function validMarketTotal(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0;
  }

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
      <button class="nav-item" type="button" data-cbb-view="cbb-variance">Variance Lab</button>
    `;
    cfbNav.insertAdjacentElement("afterend", cbbNav);

    ["cbb-projections", "cbb-tracking", "cbb-team-data", "cbb-ratings", "cbb-player-ratings", "cbb-bracketology", "cbb-portal", "cbb-market", "cbb-variance"].forEach(id => {
      const section = document.createElement("section");
      section.id = `view-${id}`;
      section.className = "view cbb-view cbb-shell";
      section.innerHTML = `<div class="cbb-panel cbb-empty">Loading THI College Basketball…</div>`;
      main.appendChild(section);
    });

    cfbNav.querySelector('[data-view="variance"]')?.addEventListener("click", () => loadData().catch(() => {}));

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
    state.loading = Promise.all(Object.entries(PATHS).filter(([key]) => CORE_DATA_KEYS.has(key)).map(async ([key, path]) => {
      if (["projectionBoard", "tracking", "bracketology", "playStyle", "matchups", "intelligence", "challenger", "readiness", "operations", "health", "trends", "varianceTracker", "rlmMonitor", "publicBacktest", "marketSnapshots"].includes(key)) {
        try { return [key, await fetchJson(path)]; }
        catch (_error) {
          if (key === "projectionBoard") return [key, { meta: {}, games: [] }];
          if (key === "tracking") return [key, { meta: {}, summary: {}, spread_decisions: [], total_decisions: [] }];
          if (key === "bracketology") return [key, { meta: {}, field: [], regions: {}, first_four: [], bubble: {}, conference_bids: [] }];
          if (key === "playStyle") return [key, { meta: {}, teams: [], games: [] }];
          if (key === "intelligence") return [key, { meta: {}, player_projections: [], team_dossiers: [], game_context: [], market_board: [], validation_registry: { gate_summary: {}, factors: [] } }];
          if (key === "challenger") return [key, { meta: {}, selected_candidate: {}, promotion: { checks: {} }, post_selection_comparison: {} }];
          if (key === "readiness") return [key, { meta: {}, checks: {}, coverage: {}, automation: {}, exceptions: [] }];
          if (key === "publicBacktest") return [key, { meta: {}, sports: {} }];
          if (key === "marketSnapshots") return [key, { meta: {}, games: {} }];
          return [key, { meta: {}, games: [] }];
        }
      }
      return [key, await fetchJson(path)];
    }))
      .then(entries => {
        state.data = { ...Object.fromEntries(Object.keys(PATHS).map(key => [key, {}])), ...Object.fromEntries(entries) };
        state.loaded = true;
        renderAll();
        loadDeferredForView(state.cbbView);
        return state.data;
      })
      .catch(error => {
        renderError(error);
        throw error;
      })
      .finally(() => { state.loading = null; });
    return state.loading;
  }

  function loadDeferred(keys = []) {
    if (!state.data) return Promise.resolve();
    const pending = keys.filter(key => PATHS[key] && !state.deferredLoads[key]);
    if (!pending.length) return Promise.resolve();
    return Promise.all(pending.map(key => {
      state.deferredLoads[key] = fetchJson(PATHS[key]).then(value => {
        state.data[key] = value;
        return value;
      }).catch(() => state.data[key] || {}).finally(() => { state.deferredLoads[key] = "loaded"; });
      return state.deferredLoads[key];
    })).then(() => renderAll());
  }

  function loadDeferredForView(view) {
    return loadDeferred(DEFERRED_VIEW_KEYS[view] || []);
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
    if (state.loaded) loadDeferredForView(view);
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
    renderTrendsLab();
  }

  function renderError(error) {
    const message = escapeHtml(error?.message || "CBB data could not be loaded.");
    document.querySelectorAll(".cbb-view").forEach(section => {
      section.innerHTML = `<div class="cbb-error"><strong>College basketball data is temporarily unavailable.</strong><div>${message}</div></div>`;
    });
  }

  function renderProjections() {
    const { profiles, foundation, history, model, projectionBoard } = state.data;
    const health = state.data.health || {};
    const readiness = state.data.readiness || {};
    const healthCoverage = health.coverage || {};
    const healthStatus = health.meta?.status === "healthy" && readiness.meta?.status === "ready" ? "Operational" : "Check required";
    const projected = Array.isArray(projectionBoard?.games) ? projectionBoard.games : [];
    const conferences = [...new Set(projected.flatMap(game => [game.home?.conference, game.away?.conference]).filter(Boolean))].sort();
    const trackedSignals = projected.filter(game => game.projection?.spread_signal_eligible).length;
    const view = document.getElementById("view-cbb-projections");
    view.innerHTML = `
      <div class="cbb-kicker">The Hammer Index · College Basketball</div>
      <h1 class="page-title">THI College Basketball Projection Center</h1>
      <p class="page-subtitle">A possession-based game intelligence board combining adjusted efficiency, pace, matchup drivers, market separation and transparent signal qualification.</p>

      <details class="cbb-signal-guide" aria-labelledby="cbb-signal-guide-title">
        <summary class="cbb-signal-guide-heading"><strong id="cbb-signal-guide-title">How CBB signals work</strong><small>Methodology + confidence key</small></summary>
        <div class="cbb-signal-guide-body">
          <p><strong>Model Signal</strong> measures the absolute difference between THI's fair spread and the consensus market. It measures disagreement, while <strong>Signal Confidence</strong> measures prospective evidence. A large disagreement is not automatically a qualified play.</p>
          <div class="cbb-signal-key">
            ${signalKey("Aligned", "0–2.5 pts", "aligned")}
            ${signalKey("Small edge", "2.6–5.0 pts", "small")}
            ${signalKey("Play", "5.1–7.0 pts", "play")}
            ${signalKey("Material disagreement", "7.1–10.0 pts", "material")}
            ${signalKey("Outlier", "10.1+ pts", "outlier")}
          </div>
          <div class="cbb-confidence-key">
            ${confidenceKey("Research only", "Opening state or no qualified market decision", "research")}
            ${confidenceKey("Developing", "Prospective evidence is accumulating", "developing")}
            ${confidenceKey("Validated", "No-vig exact test · Holm corrected · outlier robust · positive CLV", "validated")}
            ${confidenceKey("Established", "Validated edge also remains stable across rolling windows", "established")}
          </div>
          <p><strong>Totals key:</strong> 4.0–6.9 points from market is a Total Lean; 7.0+ is a Total Watch. No totals play is activated until the totals model clears its independent walk-forward and prospective gates.</p>
          <p><strong>Prior-based model</strong> means the projection still relies on regressed preseason team priors. It does not mean the matchup is an exhibition or preseason game.</p>
        </div>
      </details>

      <div class="cbb-research-banner"><strong>Projections · live testing</strong><span>THI scores and win probabilities publish from the opening slate. Spread signals require settled samples and market separation; totals remain research-only until their independent validation gate clears.</span></div>

      <section class="cbb-health-strip" aria-label="CBB data health">
        <div><small>Pipeline</small><strong class="${healthStatus === "Operational" ? "is-good" : "is-watch"}">${escapeHtml(healthStatus)}</strong></div>
        <div><small>Last coordinated refresh</small><strong>${escapeHtml(formatTimestamp(health.meta?.generated_at_utc || projectionBoard.meta?.generated_at_utc))}</strong></div>
        <div><small>Market coverage</small><strong>${integer(healthCoverage.games_with_market)} / ${integer(healthCoverage.games)} games</strong></div>
        <div><small>Neutral-site audit</small><strong class="${health.checks?.neutral_site_home_context_zero === false || health.checks?.neutral_venue_audit_ready === false ? "is-watch" : "is-good"}">${health.checks?.neutral_site_home_context_zero === false || health.checks?.neutral_venue_audit_ready === false ? "Attention" : `${integer(healthCoverage.neutral_site_games)} passed`}</strong></div>
        <div><small>Official venue corrections</small><strong>${integer(healthCoverage.neutral_site_official_overrides)} applied · ${integer(healthCoverage.neutral_site_unresolved_reviews)} unresolved</strong></div>
        <div><small>Opening-night rehearsal</small><strong class="${health.checks?.opening_night_rehearsal_passed === false ? "is-watch" : "is-good"}">${health.checks?.opening_night_rehearsal_passed === false ? "Attention" : "Passed"}</strong></div>
      </section>

      <div class="cbb-projection-controls">
        <input id="cbb-projection-search" class="cbb-input" type="search" placeholder="Search teams…" value="${escapeHtml(state.projectionQuery)}">
        <select id="cbb-projection-conference" class="cbb-select"><option value="all">All conferences</option>${conferences.map(conf => `<option value="${escapeHtml(conf)}" ${state.projectionConference === conf ? "selected" : ""}>${escapeHtml(conf)}</option>`).join("")}</select>
        <select id="cbb-projection-signal" class="cbb-select"><option value="all">All signals</option>${[['no_line','No line'],['aligned','Aligned'],['small','Small edge'],['play','Play'],['material','Material disagreement'],['outlier','Outlier']].map(([value,label]) => `<option value="${value}" ${state.projectionSignal === value ? "selected" : ""}>${label}</option>`).join("")}</select>
        <select id="cbb-projection-confidence" class="cbb-select"><option value="all">All confidence</option>${[['research','Research only'],['developing','Developing'],['validated','Validated'],['established','Established']].map(([value,label]) => `<option value="${value}" ${state.projectionConfidence === value ? "selected" : ""}>${label}</option>`).join("")}</select>
        <select id="cbb-projection-sort" class="cbb-select"><option value="time" ${state.projectionSort === "time" ? "selected" : ""}>Sort: Game time</option><option value="watch" ${state.projectionSort === "watch" ? "selected" : ""}>Sort: THI Watch</option><option value="top25" ${state.projectionSort === "top25" ? "selected" : ""}>Sort: THI Top 25 first</option></select>
        <button id="cbb-projection-clear" class="cbb-clear-button" type="button">Clear</button>
      </div>

      <div class="cbb-status-filter" role="group" aria-label="Game status">
        <span>Game status</span>
        <div>${statusButton("all", "All Games", projected)}${statusButton("upcoming", "Upcoming", projected)}${statusButton("live", "Live", projected)}${statusButton("final", "Final", projected)}</div>
      </div>

      <div class="cbb-date-navigator" aria-label="Choose game date">${projectionDateButtons()}</div>

      <div class="cbb-panel cbb-table-wrap cbb-projection-table-wrap">
        <table class="cbb-table cbb-projection-table" aria-label="THI college basketball game projections"><thead><tr>
          <th>Matchup</th><th>THI Watch</th><th>THI Spread</th><th>Market</th><th>Total</th><th>Model Edge</th><th>Model Signal</th><th>Signal Confidence</th>
        </tr></thead><tbody id="cbb-projection-body"></tbody></table>
      </div>
      <div class="cbb-projection-footer"><span id="cbb-projection-summary"></span><button id="cbb-projection-more" type="button">Show more games</button></div>

      <div class="cbb-stat-grid">
        ${statCard("D-I teams", integer(profiles.meta?.team_count), "Full Division I directory")}
        ${statCard("Historical games", integer(history.meta?.game_count), `${history.meta?.season_count || 0} walk-forward seasons`)}
        ${statCard("Projected games", integer(projected.length), "Current published window")}
        ${statCard("Qualified signals", integer(trackedSignals), "Settled sample · market threshold")}
      </div>
    `;
    bindProjectionControls();
    paintProjectionBoard();
  }

  function signalKey(label, range, tier) {
    return `<div class="cbb-signal-key-item"><strong class="cbb-signal-text cbb-signal-${tier}">${escapeHtml(label)}</strong><span>${escapeHtml(range)}</span></div>`;
  }

  function confidenceKey(label, copy, tier) {
    return `<div class="cbb-confidence-key-item"><span class="cbb-confidence cbb-confidence-${tier}">${escapeHtml(label)}</span><small>${escapeHtml(copy)}</small></div>`;
  }

  function gameStatus(game) {
    const raw = String(game.status || "scheduled").toLowerCase().replaceAll("_", "");
    if (["live", "inprogress", "halftime"].includes(raw)) return "live";
    if (["final", "completed", "complete"].includes(raw)) return "final";
    return "upcoming";
  }

  function gameDateKey(game) {
    const start = new Date(game.start_date);
    if (Number.isNaN(start.getTime())) return "tbd";
    return new Intl.DateTimeFormat("en-CA", { year:"numeric", month:"2-digit", day:"2-digit", timeZone:"America/New_York" }).format(start);
  }

  function projectionDateButtons() {
    const counts = new Map();
    for (const game of state.data?.projectionBoard?.games || []) {
      if (state.projectionStatus !== "all" && gameStatus(game) !== state.projectionStatus) continue;
      const key = gameDateKey(game); counts.set(key, (counts.get(key) || 0) + 1);
    }
    const dates = [...counts.keys()].filter(key => key !== "tbd").sort();
    const format = key => new Intl.DateTimeFormat("en-US", { weekday:"short", month:"short", day:"numeric", timeZone:"UTC" }).format(new Date(`${key}T12:00:00Z`));
    return `<button type="button" class="${state.projectionDate === "next" ? "is-active" : ""}" data-cbb-date="next">Next slate</button>${dates.map(key => `<button type="button" class="${state.projectionDate === key ? "is-active" : ""}" data-cbb-date="${key}">${escapeHtml(format(key))}<b>${integer(counts.get(key))}</b></button>`).join("")}<button type="button" class="${state.projectionDate === "all" ? "is-active" : ""}" data-cbb-date="all">All dates</button>`;
  }

  function statusButton(value, label, games) {
    const count = value === "all" ? games.length : games.filter(game => gameStatus(game) === value).length;
    return `<button type="button" class="cbb-status-button ${state.projectionStatus === value ? "is-active" : ""}" data-cbb-status="${value}">${escapeHtml(label)} <b>${integer(count)}</b></button>`;
  }

  function signalTier(game) {
    const raw = game.projection?.spread_edge;
    const edge = raw == null ? NaN : Number(raw);
    if (!Number.isFinite(edge)) return "no_line";
    const absolute = Math.abs(edge);
    if (absolute <= 2.5) return "aligned";
    if (absolute <= 5) return "small";
    if (absolute <= 7) return "play";
    if (absolute <= 10) return "material";
    return "outlier";
  }

  function signalLabel(tier) {
    return ({ no_line: "No line", aligned: "Aligned", small: "Small edge", play: "Play", material: "Material disagreement", outlier: "Outlier" })[tier] || "Research";
  }

  function confidenceTier(game) {
    return game.projection?.signal_confidence || (game.projection?.spread_signal_eligible ? "developing" : "research");
  }

  function modelInputLabel(game) {
    const sample = game.projection?.sample_state;
    return ({ preseason: "Prior-based model", early_sample: "Early sample", developing_sample: "Developing sample", tracked_sample: "Settled sample" })[sample] || "Research model";
  }

  function watchability(game) {
    if (Number.isFinite(Number(game.projection?.watchability_score))) return Number(game.projection.watchability_score);
    const margin = Math.abs(Number(game.projection?.home_margin || 0));
    const home = Number(game.projection?.matchup_context?.home?.offense || 100) - Number(game.projection?.matchup_context?.home?.defense || 100);
    const away = Number(game.projection?.matchup_context?.away?.offense || 100) - Number(game.projection?.matchup_context?.away?.defense || 100);
    return Math.round(Math.max(1, Math.min(99, 62 - margin * 2 + Math.max(0, (home + away) / 2))));
  }

  function cbbThiRank(teamId) {
    const teams = [...(state.data?.priors?.teams || [])].sort((a,b) => Number(b.prior_net || -Infinity) - Number(a.prior_net || -Infinity));
    const index = teams.findIndex(team => String(team.team_id) === String(teamId));
    return index >= 0 ? index + 1 : null;
  }

  function projectionValue(game, key) {
    if (key === "matchup") return `${game.away?.team || ""} ${game.home?.team || ""}`;
    if (key === "watch") return watchability(game);
    if (key === "spread") return Math.abs(Number(game.projection?.home_margin || 0));
    if (key === "market") { const value=game.market?.consensus_home_spread; return value == null ? -Infinity : Math.abs(Number(value)); }
    if (key === "total") return Number(game.projection?.total ?? -Infinity);
    if (key === "edge") { const value=game.projection?.spread_edge; return value == null ? -Infinity : Math.abs(Number(value)); }
    if (key === "signal") return ({no_line:0,aligned:1,small:2,play:3,material:4,outlier:5})[signalTier(game)];
    if (key === "confidence") return ({research:0,developing:1,validated:2,established:3})[confidenceTier(game)] || 0;
    return new Date(game.start_date).getTime() || 0;
  }

  function filteredProjectionGames() {
    const games = [...(state.data.projectionBoard?.games || [])];
    const query = state.projectionQuery.trim().toLowerCase();
    const filtered = games.filter(game => {
      const text = `${game.home?.team || ""} ${game.away?.team || ""} ${game.home?.conference || ""} ${game.away?.conference || ""}`.toLowerCase();
      const conference = state.projectionConference;
      return (!query || text.includes(query))
        && (conference === "all" || game.home?.conference === conference || game.away?.conference === conference)
        && (state.projectionSignal === "all" || signalTier(game) === state.projectionSignal)
        && (state.projectionConfidence === "all" || confidenceTier(game) === state.projectionConfidence)
        && (state.projectionStatus === "all" || gameStatus(game) === state.projectionStatus);
    }).sort((a, b) => {
      if (state.projectionSort === "watch") {
        const watchOrder = watchability(b) - watchability(a);
        if (watchOrder) return watchOrder;
      }
      if (state.projectionSort === "top25") {
        const aRank = Math.min(cbbThiRank(a.home?.team_id) || 999, cbbThiRank(a.away?.team_id) || 999);
        const bRank = Math.min(cbbThiRank(b.home?.team_id) || 999, cbbThiRank(b.away?.team_id) || 999);
        const top25Order = Number(bRank <= 25) - Number(aRank <= 25);
        if (top25Order) return top25Order;
        if (aRank !== bRank) return aRank - bRank;
      }
      const time = (new Date(a.start_date).getTime() || 0) - (new Date(b.start_date).getTime() || 0);
      return time || String(a.game_id || "").localeCompare(String(b.game_id || ""));
    });
    if (state.projectionDate === "all") return filtered;
    const selected = state.projectionDate === "next" ? filtered.map(gameDateKey).find(key => key !== "tbd") : state.projectionDate;
    return selected ? filtered.filter(game => gameDateKey(game) === selected) : filtered;
  }

  function bindProjectionControls() {
    const view = document.getElementById("view-cbb-projections");
    const resetLimit = () => { state.projectionLimit = 150; paintProjectionBoard(); };
    view.querySelector("#cbb-projection-search").addEventListener("input", event => { state.projectionQuery = event.target.value; resetLimit(); });
    view.querySelector("#cbb-projection-conference").addEventListener("change", event => { state.projectionConference = event.target.value; resetLimit(); });
    view.querySelector("#cbb-projection-signal").addEventListener("change", event => { state.projectionSignal = event.target.value; resetLimit(); });
    view.querySelector("#cbb-projection-confidence").addEventListener("change", event => { state.projectionConfidence = event.target.value; resetLimit(); });
    view.querySelector("#cbb-projection-sort").addEventListener("change", event => { state.projectionSort = event.target.value; resetLimit(); });
    view.querySelector("#cbb-projection-clear").addEventListener("click", () => {
      state.projectionQuery = ""; state.projectionConference = "all"; state.projectionSignal = "all"; state.projectionConfidence = "all"; state.projectionSort = "time"; state.projectionStatus = "all"; state.projectionDate = "next"; state.projectionLimit = 150; renderProjections();
    });
    view.querySelector(".cbb-status-filter").addEventListener("click", event => {
      const button = event.target.closest("[data-cbb-status]");
      if (!button) return;
      state.projectionStatus = button.dataset.cbbStatus;
      state.projectionLimit = 150;
      renderProjections();
    });
    view.querySelector(".cbb-date-navigator").addEventListener("click", event => {
      const button = event.target.closest("[data-cbb-date]");
      if (!button) return;
      state.projectionDate = button.dataset.cbbDate;
      state.projectionLimit = 150;
      renderProjections();
    });
    view.querySelector("#cbb-projection-body").addEventListener("click", async event => {
      const row = event.target.closest("[data-cbb-game-id]");
      if (row) {
        await loadDeferred(["matchups", "intelligence", "playStyle"]);
        openGameDetail(row.dataset.cbbGameId);
      }
    });
    view.querySelector("#cbb-projection-more").addEventListener("click", () => { state.projectionLimit += 150; paintProjectionBoard(); });
  }

  function paintProjectionBoard() {
    const body = document.getElementById("cbb-projection-body");
    if (!body) return;
    const all = filteredProjectionGames();
    const shown = all.slice(0, state.projectionLimit);
    const groups = new Map();
    for (const game of shown) {
      const start = new Date(game.start_date);
      const label = Number.isNaN(start.getTime()) ? "Date TBD" : new Intl.DateTimeFormat("en-US", { weekday: "long", month: "short", day: "numeric", timeZone: "America/New_York" }).format(start);
      if (!groups.has(label)) groups.set(label, []);
      groups.get(label).push(game);
    }
    body.innerHTML = shown.length ? [...groups.entries()].map(([date, games]) => `<tr class="cbb-date-row"><td colspan="8">${escapeHtml(date)}</td></tr>${games.map(projectionRow).join("")}`).join("") : `<tr><td colspan="8" class="cbb-empty">No games match those filters.</td></tr>`;
    const summary = document.getElementById("cbb-projection-summary");
    if (summary) summary.textContent = `Showing ${integer(shown.length)} of ${integer(all.length)} matching games`;
    const more = document.getElementById("cbb-projection-more");
    if (more) more.hidden = shown.length >= all.length;
  }

  function teamProfile(teamId) {
    return state.data?.profiles?.teams?.find(team => String(team.team_id) === String(teamId));
  }

  function teamLogo(team, size = "normal") {
    const profile = teamProfile(team?.team_id);
    const initials = String(profile?.abbreviation || team?.team || "?").split(/\s+/).map(word => word[0]).join("").slice(0,3);
    return `<span class="cbb-team-logo cbb-team-logo-${size}">${profile?.logo_url ? `<img src="${escapeHtml(profile.logo_url)}" alt="" loading="lazy">` : `<b>${escapeHtml(initials)}</b>`}</span>`;
  }

  function projectionRow(game) {
    const projection = game.projection || {};
    const start = new Date(game.start_date);
    const time = Number.isNaN(start.getTime()) ? "Time TBD" : (game.start_time_tbd ? "Time TBD" : new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" }).format(start) + " ET");
    const network = game.broadcasts?.map(item => item.network || item).filter(Boolean).join(", ") || "TV TBD";
    const gameType = game.conference_game ? "Conference" : "Nonconference";
    const margin = Number(projection.home_margin);
    const favoredTeam = margin >= 0 ? game.home : game.away;
    const projectedLine = `${favoredTeam?.team || "—"} -${number(Math.abs(margin),1)}`;
    const marketLine = game.market?.consensus_home_spread == null ? NaN : Number(game.market.consensus_home_spread);
    const marketTeam = Number.isFinite(marketLine) ? (marketLine <= 0 ? game.home : game.away) : null;
    const marketText = marketTeam ? `${marketTeam.team} -${number(Math.abs(marketLine),1)}` : "Not posted";
    const edge = projection.spread_edge == null ? NaN : Number(projection.spread_edge);
    const edgeTeam = Number.isFinite(edge) ? (edge >= 0 ? game.home : game.away) : null;
    const tier = signalTier(game);
    const edgeMarketNumber = edgeTeam && tier !== "aligned" && Number.isFinite(marketLine)
      ? (String(edgeTeam.team_id) === String(game.home?.team_id) ? marketLine : -marketLine)
      : NaN;
    const edgeMarketText = edgeTeam && Number.isFinite(edgeMarketNumber)
      ? `${edgeTeam.team} ${edgeMarketNumber > 0 ? "+" : ""}${number(edgeMarketNumber,1)}`
      : null;
    const confidence = confidenceTier(game);
    const totalMarket = validMarketTotal(game.market?.consensus_total) ? Number(game.market.consensus_total) : null;
    const projectedTotal = Number(projection.total);
    const totalEdge = totalMarket !== null && Number.isFinite(projectedTotal) && projectedTotal > 0 ? projectedTotal - totalMarket : null;
    const totalFlag = Number.isFinite(totalEdge) && Math.abs(totalEdge) >= 4 ? `<span class="cbb-total-flag">${totalEdge >= 0 ? "Over" : "Under"} ${number(totalMarket,1)} · ${Math.abs(totalEdge) >= 7 ? "Total Watch" : "Total Lean"}</span>` : "";
    const watch = watchability(game);
    const watchLabel = watch >= 75 ? "Prime window" : watch >= 60 ? "On the radar" : "Standard";
    const varianceRows = (state.data?.varianceTracker?.frozen || []).filter(row => row.sport === "cbb" && String(row.game_id) === String(game.game_id));
    const varianceCards = new Map((state.data?.trends?.sports?.cbb?.cards || []).map(card => [card.id, card]));
    const varianceMarkup = varianceRows.length ? `<div class="cbb-variance-context">${varianceRows.slice(0,2).map(row => { const card = varianceCards.get(row.system_id) || {}; const evidence = card.state === "failed_hypothesis" ? "did not validate" : humanize(card.state || "prospective"); return `<span title="Historical context only; does not affect the THI projection">${escapeHtml(card.name || humanize(row.system_id))} · ${escapeHtml(evidence)}</span>`; }).join("")}</div>` : "";
    const awayRank = cbbThiRank(game.away?.team_id);
    const homeRank = cbbThiRank(game.home?.team_id);
    return `<tr class="cbb-projection-row" data-cbb-game-id="${escapeHtml(game.game_id)}">
      <td><div class="cbb-matchup-team">${teamLogo(game.away,"small")}<div class="cbb-matchup-name"><strong>${escapeHtml(game.away?.team || "—")}</strong>${awayRank ? `<small>#${awayRank}</small>` : ""}</div><span>${gameStatus(game) === "final" ? integer(game.away?.score) : ""}</span></div><div class="cbb-matchup-team">${teamLogo(game.home,"small")}<div class="cbb-matchup-name"><strong>${escapeHtml(game.home?.team || "—")}</strong>${homeRank ? `<small>#${homeRank}</small>` : ""}</div><span>${gameStatus(game) === "final" ? integer(game.home?.score) : ""}</span></div><div class="cbb-team-meta">${escapeHtml(time)} · ${escapeHtml(network)} · ${gameType}</div>${varianceMarkup}</td>
      <td><span class="cbb-watch-score">${integer(watch)}</span><div class="cbb-team-meta">${watchLabel}</div></td>
      <td><strong class="cbb-number">${escapeHtml(edgeMarketText || projectedLine)}</strong><div class="cbb-team-meta">${edgeMarketText ? "THI preferred side at current market" : "THI projected spread"}</div></td>
      <td><strong class="cbb-number">${escapeHtml(marketText)}</strong><div class="cbb-team-meta">${game.market?.book_count ? `${integer(game.market.book_count)} books` : "No consensus line"}</div></td>
      <td><strong class="cbb-number">${Number.isFinite(projectedTotal) && projectedTotal > 0 ? number(projectedTotal,1) : "—"}</strong><div class="cbb-team-meta">Market ${totalMarket !== null ? number(totalMarket,1) : "—"}</div>${totalFlag}</td>
      <td><strong class="cbb-edge-value">${Number.isFinite(edge) ? `${number(Math.abs(edge),1)} pts` : "—"}</strong><div class="cbb-team-meta">${edgeTeam ? `Model favors ${escapeHtml(edgeTeam.team)}` : "No market comparison"}</div></td>
      <td><span class="cbb-signal cbb-signal-${tier}">${escapeHtml(signalLabel(tier))}</span></td>
      <td><span class="cbb-confidence cbb-confidence-${confidence}">${escapeHtml(confidence === "research" ? "Research only" : humanize(confidence))}</span><div class="cbb-team-meta">${projection.spread_signal_eligible ? "Qualified decision" : "Not in prospective record"}</div></td>
    </tr>`;
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
    if (!projection) return `<article class="cbb-panel cbb-game-card"><div class="cbb-game-top"><span class="cbb-game-date">${escapeHtml(date)}</span>${game.neutral_site ? '<span class="cbb-chip">Neutral</span>' : ""}</div><div class="cbb-matchup">${escapeHtml(game.away?.team)} <span>${matchupWord(game)}</span> ${escapeHtml(game.home?.team)}</div><div class="cbb-game-meta">${escapeHtml(venue)} · ${escapeHtml(network)}</div></article>`;
    const margin = Number(projection.home_margin);
    const favored = margin >= 0 ? game.home?.team : game.away?.team;
    const projectedLine = `${favored} -${Math.abs(margin).toFixed(1)}`;
    const stateLabel = projection.sample_state === "tracked_sample" ? "Tracked" : projection.sample_state === "developing_sample" ? "Developing" : projection.sample_state === "early_sample" ? "Early sample" : "Preseason";
    const signalTeam = Number(projection.spread_edge) >= 0 ? game.home?.team : game.away?.team;
    const signal = projection.spread_signal_eligible ? `<span class="cbb-projection-signal">${escapeHtml(signalTeam)} spread edge · ${number(Math.abs(Number(projection.spread_edge)),1)} pts</span>` : `<span class="cbb-projection-withheld">${stateLabel} · no spread signal</span>`;
    return `<article class="cbb-panel cbb-game-card" data-cbb-game-id="${escapeHtml(game.game_id)}" role="button" tabindex="0" aria-label="Open ${escapeHtml(game.away?.team)} ${matchupWord(game)} ${escapeHtml(game.home?.team)} matchup analysis"><div class="cbb-game-top"><span class="cbb-game-date">${escapeHtml(date)}</span><span class="cbb-chip">${escapeHtml(stateLabel)}</span></div><div class="cbb-matchup">${escapeHtml(game.away?.team)} <span>${matchupWord(game)}</span> ${escapeHtml(game.home?.team)}</div><div class="cbb-projection-score"><strong>${number(projection.away_points,1)}–${number(projection.home_points,1)}</strong><span>${escapeHtml(projectedLine)} · ${pct(projection.home_win_probability)} ${game.neutral_site ? escapeHtml(game.home?.team) : "home"} win</span></div><div class="cbb-projection-meta"><span>${number(projection.projected_possessions,1)} possessions</span><span>Projected total ${number(projection.total,1)} · totals signal withheld</span></div>${signal}<div class="cbb-game-meta">${escapeHtml(venue)} · ${escapeHtml(network)} · Open matchup analysis →</div></article>`;
  }

  function compareClass(value, opponent, higherIsBetter = true) {
    const a = Number(value), b = Number(opponent);
    if (!Number.isFinite(a) || !Number.isFinite(b) || Math.abs(a-b) < .05) return "cbb-compare-even";
    return ((a > b) === higherIsBetter) ? "cbb-compare-good" : "cbb-compare-bad";
  }

  function compareCell(value, opponent, higherIsBetter = true, digits = 1, suffix = "") {
    return `<td class="cbb-number ${compareClass(value, opponent, higherIsBetter)}">${number(value,digits)}${suffix}</td>`;
  }

  function contextFlags(teamContext) {
    const labels = {
      back_to_back: "Back-to-back", short_rest: "Short rest", neutral_site: "Neutral site",
      conference_game: "Conference game", lookahead_spot: "Lookahead watch",
      letdown_watch: "Letdown watch", bounce_back_watch: "Bounce-back watch"
    };
    const flags = (teamContext?.flags || []).map(flag => labels[flag] || humanize(flag));
    return flags.length ? flags.map(flag => `<span class="cbb-context-flag">${escapeHtml(flag)}</span>`).join("") : `<span class="cbb-context-clear">No schedule flag</span>`;
  }

  function cbbMarketMovement(game) {
    const stored = state.data?.marketSnapshots?.games?.[String(game.game_id)] || {};
    const snapshots = Array.isArray(stored.snapshots) ? stored.snapshots : [];
    const market = game.market || {};
    const firstSpread = stored.first_captured_home_spread ?? stored.open_home_spread ?? market.opening_home_spread;
    const currentSpread = stored.current_home_spread ?? market.consensus_home_spread;
    const firstTotal = stored.first_captured_total ?? stored.open_total ?? market.opening_total;
    const currentTotal = stored.current_total ?? market.consensus_total;
    const spreadMove = Number.isFinite(Number(firstSpread)) && Number.isFinite(Number(currentSpread)) ? Number(currentSpread) - Number(firstSpread) : null;
    const referenceMoneyline = market.reference_moneyline || {};
    const marketBooks = Array.isArray(market.book_lines) ? market.book_lines : [];
    const lineFor = value => {
      if (!Number.isFinite(Number(value))) return "—";
      const home = Number(value) <= 0;
      return `${home ? game.home?.team : game.away?.team} ${number(-Math.abs(Number(value)),1,true)}`;
    };
    const rows = snapshots.slice(-24).reverse().map((row,index) => `<tr><td>${index === 0 ? "Latest" : index === snapshots.slice(-24).length - 1 ? "First captured" : "Update"}</td><td>${escapeHtml(formatTimestamp(row.captured_at || row.captured_at_utc))}</td><td class="cbb-number">${lineFor(row.home_spread)}</td><td class="cbb-number">${Number.isFinite(Number(row.total)) ? number(row.total,1) : "—"}</td><td>${escapeHtml(row.bookmaker || row.source || "Consensus")}</td></tr>`).join("");
    return `<section class="cbb-detail-section"><h3>Odds &amp; line movement</h3>
      <div class="cbb-model-sub">Timestamped market observations for this game. Movement remains separate from the projection model.</div>
      <div class="cbb-detail-grid">
        ${detailStat("First captured spread", lineFor(firstSpread))}
        ${detailStat("Current spread", lineFor(currentSpread))}
        ${detailStat("Home-side move", spreadMove == null ? "—" : `${number(spreadMove,1,true)} pts`)}
        ${detailStat("First captured total", Number.isFinite(Number(firstTotal)) ? number(firstTotal,1) : "—")}
        ${detailStat("Current total", Number.isFinite(Number(currentTotal)) ? number(currentTotal,1) : "—")}
        ${detailStat("Captured updates", integer(snapshots.length))}
        ${detailStat("Reference moneyline", referenceMoneyline.provider ? `${referenceMoneyline.provider} · ${game.away?.team} ${number(referenceMoneyline.away_price,0,true)} / ${game.home?.team} ${number(referenceMoneyline.home_price,0,true)}` : "—")}
      </div>
      ${marketBooks.length ? `<div class="cbb-panel cbb-table-wrap"><table class="cbb-table" style="min-width:760px"><thead><tr><th>Sportsbook</th><th>${escapeHtml(game.away?.team)} ML</th><th>${escapeHtml(game.home?.team)} ML</th><th>Home spread</th><th>Total</th></tr></thead><tbody>${marketBooks.map(book => `<tr><td><strong>${escapeHtml(book.provider || "Sportsbook")}</strong></td><td class="cbb-number">${Number.isFinite(Number(book.away_moneyline)) ? number(book.away_moneyline,0,true) : "—"}</td><td class="cbb-number">${Number.isFinite(Number(book.home_moneyline)) ? number(book.home_moneyline,0,true) : "—"}</td><td class="cbb-number">${Number.isFinite(Number(book.spread)) ? number(book.spread,1,true) : "—"}</td><td class="cbb-number">${Number.isFinite(Number(book.total)) ? number(book.total,1) : "—"}</td></tr>`).join("")}</tbody></table></div>` : ""}
      ${rows ? `<div class="cbb-panel cbb-table-wrap"><table class="cbb-table"><thead><tr><th>Capture</th><th>Time</th><th>Spread</th><th>Total</th><th>Source</th></tr></thead><tbody>${rows}</tbody></table></div>` : `<div class="cbb-coverage-note">No market chronology is available yet. This panel will populate automatically as books release and move CBB lines.</div>`}
      <div class="cbb-model-sub">“First captured” means THI's first recorded observation; it is not presented as an official sportsbook opener.</div>
    </section>`;
  }

  function openGameDetail(gameId) {
    const game = state.data?.projectionBoard?.games?.find(row => String(row.game_id) === String(gameId));
    if (!game?.projection) return;
    const projection = game.projection;
    const context = projection.matchup_context || {};
    const home = context.home || {};
    const away = context.away || {};
    const factorMatchup = context.four_factor_matchup || {};
    const market = game.market || {};
    const detail = document.getElementById("cbb-team-detail");
    const panel = detail.querySelector(".cbb-detail-panel");
    detail.classList.remove("is-team-page");
    detail.classList.add("is-game-page");
    const start = new Date(game.start_date);
    const date = Number.isNaN(start.getTime()) ? "Date TBD" : new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", hour: game.start_time_tbd ? undefined : "numeric", minute: game.start_time_tbd ? undefined : "2-digit", timeZone: "America/New_York", timeZoneName: game.start_time_tbd ? undefined : "short" }).format(start);
    const stateLabel = modelInputLabel(game);
    const spreadSide = Number(projection.home_margin) >= 0 ? game.home?.team : game.away?.team;
    const drivers = context.margin_drivers || [];
    const matchup = state.data?.matchups?.games?.find(row => String(row.game_id) === String(gameId));
    const pace = matchup?.pace_environment || {};
    const advantages = matchup?.factor_advantages || [];
    const homeStyle = matchup?.shot_style?.home || {};
    const awayStyle = matchup?.shot_style?.away || {};
    const situational = state.data?.intelligence?.game_context?.find(row => String(row.game_id) === String(gameId)) || {};
    const awaySituation = situational.teams?.away || {};
    const homeSituation = situational.teams?.home || {};
    const operation = state.data?.operations?.games?.find(row => String(row.game_id) === String(gameId)) || {};
    const awayTravel = operation.teams?.away?.travel_miles;
    const homeTravel = operation.teams?.home?.travel_miles;
    const travelReady = Number.isFinite(Number(awayTravel)) || Number.isFinite(Number(homeTravel));
    const travelSummary = travelReady
      ? `${escapeHtml(game.away?.team)} ${Number.isFinite(Number(awayTravel)) ? `${integer(awayTravel)} mi` : "pending"} · ${escapeHtml(game.home?.team)} ${Number.isFinite(Number(homeTravel)) ? `${integer(homeTravel)} mi` : "pending"}`
      : "Mileage pending";
    const styleCell = value => value == null ? "Coverage unavailable" : pct(value);
    panel.innerHTML = `
      <button class="cbb-detail-close cbb-game-back" type="button" data-cbb-close>← Back to projections</button>
      <button class="thi-account-button" type="button" data-cbb-track-play>Track a Play</button>
      <div class="cbb-kicker">THI CBB matchup analysis</div>
      <div class="cbb-matchup-page-title"><div>${teamLogo(game.away,"large")}<span>${escapeHtml(game.away?.team)}</span></div><b>${matchupWord(game)}</b><div>${teamLogo(game.home,"large")}<span>${escapeHtml(game.home?.team)}</span></div></div>
      <div class="cbb-detail-sub">${escapeHtml(date)} · ${escapeHtml(game.venue?.name || (game.neutral_site ? "Neutral site" : "Venue TBD"))} · ${escapeHtml(game.broadcasts?.map(item => item.network || item).filter(Boolean).join(", ") || "TV TBD")}${game.neutral_site ? ' · <strong class="cbb-neutral-label">NEUTRAL FLOOR · NO HOME-COURT INPUT</strong>' : ""}</div>
      <div class="cbb-detail-grid">
        ${detailStat("Projected score", `${number(projection.away_points,1)}–${number(projection.home_points,1)}`)}
        ${detailStat("THI spread", `${spreadSide} -${number(Math.abs(Number(projection.home_margin)),1)}`)}
        ${detailStat("Home win probability", pct(projection.home_win_probability))}
        ${detailStat("Projected possessions", number(projection.projected_possessions,1))}
        ${detailStat("Projected total", number(projection.total,1))}
        ${detailStat("Model input", stateLabel)}
      </div>
      <section class="cbb-detail-section cbb-situational-section"><h3>Schedule, venue and availability context</h3>
        <div class="cbb-model-sub">These fields are shown separately from the published projection until each input clears historical out-of-sample testing.</div>
        <div class="cbb-situation-grid">
          <article><span>${escapeHtml(game.away?.team)}</span><strong>${awaySituation.rest_days == null ? "Rest unknown" : `${number(awaySituation.rest_days,1)} days rest`}</strong><div>${contextFlags(awaySituation)}</div><small>${awaySituation.next_opponent ? `Next: ${escapeHtml(awaySituation.next_opponent)} in ${number(awaySituation.next_game_days,1)} days` : "No next game in current window"}</small></article>
          <article><span>${game.neutral_site ? "Venue adjustment" : "Home-court input"}</span><strong>${game.neutral_site ? "0.00 pts" : situational.home_court_points == null ? "Awaiting estimate" : `${number(situational.home_court_points,2)} pts`}</strong><div>${game.neutral_site ? `<span class="cbb-context-clear">Neutral-floor override verified</span>` : `<span class="cbb-context-flag">Program-specific court</span>`}</div><small>${game.neutral_site ? "Home-court, early-home and nonconference-home effects are disabled." : "Five-season regularized value; thin samples shrink toward the national mean."}</small></article>
          <article><span>${escapeHtml(game.home?.team)}</span><strong>${homeSituation.rest_days == null ? "Rest unknown" : `${number(homeSituation.rest_days,1)} days rest`}</strong><div>${contextFlags(homeSituation)}</div><small>${homeSituation.next_opponent ? `Next: ${escapeHtml(homeSituation.next_opponent)} in ${number(homeSituation.next_game_days,1)} days` : "No next game in current window"}</small></article>
          <article><span>Injuries and availability</span><strong>Not yet sourced</strong><div><span class="cbb-context-pending">No model adjustment</span></div><small>THI will only publish availability effects from a verified, timestamped feed.</small></article>
          <article><span>Travel load</span><strong>${travelSummary}</strong><div><span class="${travelReady ? "cbb-context-clear" : "cbb-context-pending"}">${travelReady ? "Verified straight-line distance" : "No model adjustment"}</span></div><small>${travelReady ? "Derived from named OpenStreetMap venue objects; © OpenStreetMap contributors. Display-only research context." : "Requires verified team origin and venue coordinates."}</small></article>
          <article><span>Situational usage</span><strong>Research context</strong><div><span class="cbb-context-pending">Not priced into line</span></div><small>B2B, lookahead, letdown and bounce-back flags must pass validation first.</small></article>
        </div>
      </section>
      <div class="cbb-matchup-brain-grid">
      <section class="cbb-detail-section"><h3>Team efficiency state</h3>
        <div class="cbb-panel cbb-table-wrap"><table class="cbb-table cbb-matchup-table"><thead><tr><th>Team</th><th>Adj offense</th><th>Adj defense</th><th>Tempo</th><th>Games</th><th>Source</th></tr></thead><tbody>
          <tr><td class="cbb-team-name">${escapeHtml(game.away?.team)}</td>${compareCell(away.offense,home.offense,true,2)}${compareCell(away.defense,home.defense,false,2)}<td class="cbb-number cbb-compare-even">${number(away.tempo,2)}</td><td class="cbb-number">${integer(away.games)}</td><td>${escapeHtml(humanize(away.rating_source || "unknown"))}</td></tr>
          <tr><td class="cbb-team-name">${escapeHtml(game.home?.team)}</td>${compareCell(home.offense,away.offense,true,2)}${compareCell(home.defense,away.defense,false,2)}<td class="cbb-number cbb-compare-even">${number(home.tempo,2)}</td><td class="cbb-number">${integer(home.games)}</td><td>${escapeHtml(humanize(home.rating_source || "unknown"))}</td></tr>
        </tbody></table></div>
      </section>
      <section class="cbb-detail-section"><h3>Opponent-adjusted Four Factors matchup</h3>
        <div class="cbb-model-sub">Expected rates combine each offense with the opposing defense. Turnover rate is lower-is-better for the offense; the other displayed rates are higher-is-better.</div>
        <div class="cbb-panel cbb-table-wrap"><table class="cbb-table cbb-matchup-table"><thead><tr><th>Team</th><th>Expected eFG%</th><th>Expected TO%</th><th>Expected OR%</th><th>Expected FT rate</th></tr></thead><tbody>
          <tr><td class="cbb-team-name">${escapeHtml(game.away?.team)}</td>${compareCell(factorMatchup.away?.effective_fg_pct,factorMatchup.home?.effective_fg_pct,true,1,"%")}${compareCell(factorMatchup.away?.turnover_pct,factorMatchup.home?.turnover_pct,false,1,"%")}${compareCell(factorMatchup.away?.offensive_rebound_pct,factorMatchup.home?.offensive_rebound_pct,true,1,"%")}${compareCell(factorMatchup.away?.free_throw_rate,factorMatchup.home?.free_throw_rate,true,1,"%")}</tr>
          <tr><td class="cbb-team-name">${escapeHtml(game.home?.team)}</td>${compareCell(factorMatchup.home?.effective_fg_pct,factorMatchup.away?.effective_fg_pct,true,1,"%")}${compareCell(factorMatchup.home?.turnover_pct,factorMatchup.away?.turnover_pct,false,1,"%")}${compareCell(factorMatchup.home?.offensive_rebound_pct,factorMatchup.away?.offensive_rebound_pct,true,1,"%")}${compareCell(factorMatchup.home?.free_throw_rate,factorMatchup.away?.free_throw_rate,true,1,"%")}</tr>
        </tbody></table></div>
      </section>
      </div>
      <section class="cbb-detail-section"><h3>Possession and matchup engine</h3>
        <div class="cbb-model-sub">This research layer explains the matchup; it does not feed the published spread or total until it clears historical out-of-sample validation.</div>
        ${matchup ? `
          <div class="cbb-matchup-summary">
            ${detailStat("Pace environment", humanize(pace.band || "unavailable"))}
            ${detailStat("Tempo clash", pace.clash == null ? "Unavailable" : `${number(pace.clash,1)} possessions · ${humanize(pace.clash_label)}`)}
            ${detailStat("Component status", "Explanation only")}
          </div>
          <div class="cbb-advantage-grid">${advantages.map(item => `<div class="cbb-advantage-card"><span>${escapeHtml(humanize(item.dimension))}</span><strong>${escapeHtml(item.advantage_team || "Coverage unavailable")}</strong><small>${item.edge == null ? "No qualified input" : `${humanize(item.magnitude)} · ${number(Math.abs(item.edge),2)}-point rate edge`}</small></div>`).join("")}</div>
          <h4 class="cbb-detail-minor-title">Observed shot style</h4>
          <div class="cbb-panel cbb-table-wrap"><table class="cbb-table cbb-matchup-table"><thead><tr><th>Team</th><th>At rim</th><th>Midrange</th><th>Three-point</th><th>Assisted</th><th>Explicit transition</th><th>Sample</th></tr></thead><tbody>
            <tr><td class="cbb-team-name">${escapeHtml(game.away?.team)}</td><td>${styleCell(awayStyle.rim_rate)}</td><td>${styleCell(awayStyle.midrange_rate)}</td><td>${styleCell(awayStyle.three_rate)}</td><td>${styleCell(awayStyle.assisted_rate)}</td><td>${styleCell(awayStyle.explicit_transition_rate)}</td><td>${escapeHtml(humanize(awayStyle.sample_state || "unavailable"))}</td></tr>
            <tr><td class="cbb-team-name">${escapeHtml(game.home?.team)}</td><td>${styleCell(homeStyle.rim_rate)}</td><td>${styleCell(homeStyle.midrange_rate)}</td><td>${styleCell(homeStyle.three_rate)}</td><td>${styleCell(homeStyle.assisted_rate)}</td><td>${styleCell(homeStyle.explicit_transition_rate)}</td><td>${escapeHtml(humanize(homeStyle.sample_state || "unavailable"))}</td></tr>
          </tbody></table></div>
          <div class="cbb-model-sub">Transition rate uses explicit CBBD play-type labels only. THI does not infer transition from the period clock when shot-clock context is absent.</div>
        ` : `<div class="cbb-coverage-note">Matchup-engine data will appear after the next coordinated CBB refresh.</div>`}
      </section>
      <section class="cbb-detail-section"><h3>Largest margin drivers</h3>
        ${game.neutral_site ? '<div class="cbb-neutral-audit">Neutral-site audit passed · 0.00 home-court points · no home-context drivers</div>' : ""}
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
      </section>
      ${cbbMarketMovement(game)}`;
    detail.classList.add("is-open");
    detail.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    panel.scrollTop = 0;
    panel.querySelector("[data-cbb-track-play]")?.addEventListener("click", () => {
      const homeSpread=Number(game.market?.consensus_home_spread);
      const edge=Number(projection.spread_edge);
      const selection=Number.isFinite(edge) ? (edge > 0 ? "home" : "away") : null;
      const selectedLine=Number.isFinite(homeSpread)&&selection ? (selection==="home"?homeSpread:-homeSpread) : null;
      closeTeamDetail();
      window.THITrackPlay?.({game_id:String(game.game_id),sport:"cbb",market:"spread",selection,line:selectedLine});
    });
    panel.querySelector("[data-cbb-close]")?.focus();
  }

  function renderTeamData() {
    const view = document.getElementById("view-cbb-team-data");
    const source = state.data.profiles.teams || [];
    const conferences = [...new Set(source.map(team => team.conference?.abbreviation || team.conference?.name).filter(Boolean))].sort();
    const value = (team, key) => key === "team" ? team.team || "" : key === "conference" ? team.conference?.abbreviation || "" : key === "source_rank" ? Number(team.preseason_prior?.adjusted?.net_rank || 9999) : team.rating_state || "";
    const rows = source.filter(team => {
      const query = state.teamDataQuery.trim().toLowerCase();
      const conference = team.conference?.abbreviation || team.conference?.name;
      return (!query || `${team.team} ${team.display_name} ${team.conference?.name || ""}`.toLowerCase().includes(query)) && (state.teamDataConference === "all" || conference === state.teamDataConference);
    }).sort((a,b) => {
      const av=value(a,state.teamDataSort.key), bv=value(b,state.teamDataSort.key);
      const order=typeof av === "string" ? av.localeCompare(bv) : av-bv;
      return state.teamDataSort.direction === "asc" ? order : -order;
    });
    const header = (key,label) => { const active=state.teamDataSort.key===key; const arrow=active ? (state.teamDataSort.direction === "desc" ? "↓" : "↑") : "↕"; return `<th data-team-data-sort="${key}" class="${active ? "is-sorted" : ""}">${label}<span class="cbb-sort-icon" aria-hidden="true">${arrow}</span></th>`; };
    view.innerHTML = `
      <div class="cbb-kicker">Team directory and observed data</div>
      <h1 class="page-title">CBB Team Data</h1>
      <p class="page-subtitle">The factual team layer: identity, conference, records, observed efficiency, Four Factors, shot profile and roster context. THI Ratings is the separate modeled strength layer.</p>
      <div class="cbb-definition-banner"><strong>Team Data</strong><span>What has happened and who is on the roster.</span><strong>THI Ratings</strong><span>THI's opponent-adjusted estimate of underlying team strength.</span></div>
      <div class="cbb-controls"><input id="cbb-team-data-search" class="cbb-input" type="search" placeholder="Search 365 Division I teams" value="${escapeHtml(state.teamDataQuery)}"><select id="cbb-team-data-conference" class="cbb-select"><option value="all">All conferences</option>${conferences.map(conf => `<option value="${escapeHtml(conf)}" ${state.teamDataConference === conf ? "selected" : ""}>${escapeHtml(conf)}</option>`).join("")}</select></div>
      <div class="cbb-panel cbb-table-wrap"><table class="cbb-table" aria-label="College basketball team directory"><thead><tr>${header("team","Team")}${header("conference","Conference")}${header("source_rank","2026 source rank")}${header("state","2027 state")}</tr></thead><tbody id="cbb-team-data-body">${rows.map(team => `<tr data-team-id="${team.team_id}"><td><div class="cbb-team-cell">${teamLogo(team,"normal")}<div><div class="cbb-team-name">${escapeHtml(team.display_name || team.team)}</div><div class="cbb-team-meta">Open team profile →</div></div></div></td><td>${escapeHtml(team.conference?.abbreviation || "—")}</td><td class="cbb-number">${team.preseason_prior?.adjusted?.net_rank ? `#${integer(team.preseason_prior.adjusted.net_rank)}` : "—"}</td><td><span class="cbb-state-label">${team.rating_state === "current_adjusted" ? "Current adjusted" : "Prior-based rating"}</span></td></tr>`).join("")}</tbody></table></div>
      <div class="cbb-stat-note" style="margin-top:9px">${integer(rows.length)} teams shown. Rankings remain neutral; performance metrics inside each team profile use THI's green-to-red scale.</div>`;
    view.querySelector("#cbb-team-data-search").addEventListener("input", event => { state.teamDataQuery=event.target.value; renderTeamData(); const input=document.getElementById("cbb-team-data-search"); input?.focus(); input?.setSelectionRange(input.value.length,input.value.length); });
    view.querySelector("#cbb-team-data-conference").addEventListener("change", event => { state.teamDataConference=event.target.value; renderTeamData(); });
    view.querySelector("thead").addEventListener("click", event => { const cell=event.target.closest("[data-team-data-sort]"); if(!cell)return; const key=cell.dataset.teamDataSort; state.teamDataSort.direction=state.teamDataSort.key===key&&state.teamDataSort.direction==="asc"?"desc":"asc"; state.teamDataSort.key=key; renderTeamData(); });
    view.querySelector("#cbb-team-data-body").addEventListener("click", event => { const row=event.target.closest("[data-team-id]"); if(row)openTeamDetail(Number(row.dataset.teamId)); });
  }

  function renderPlayerRatings() {
    const view = document.getElementById("view-cbb-player-ratings");
    if (!state.playerData) {
      view.innerHTML = `
        <div class="cbb-kicker">Player-level basketball intelligence</div>
        <h1 class="page-title">CBB Player Ratings</h1>
        <p class="page-subtitle">THI's projected-impact layer translates prior production through competition, destination, role, pedigree and sample context without feeding these ratings into public game projections.</p>
        <div class="cbb-readiness-banner"><span class="cbb-status-pill">Research v1.3</span><strong>${state.playerLoading ? "Loading the player board" : "Player board available"}</strong><p>${state.playerLoading ? "Reading the roster-verified player layer…" : "Open this tab to load active-roster players with qualified prior-season production and THI's competition-adjusted projected-impact grade."}</p></div>
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
      <p class="page-subtitle">Active ${escapeHtml(meta.roster_season || meta.season)} roster players ranked by projected impact. THI adjusts qualified ${escapeHtml(meta.source_season || "prior-season")} production for competition, destination strength, role, recruiting or portal pedigree, and sample reliability.</p>
      <div class="cbb-stat-grid">
        ${statCard("Rated players", integer(meta.player_count), `${integer(meta.team_count)} Division I teams`)}
        ${statCard("Prior minimum", `${integer(meta.minimum_minutes)} min`, `${integer(meta.minimum_games)} games · newcomers use verified pedigree`)}
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
          <th>Rank</th>${playerHeader("name", "Player")}${playerHeader("team", "Team")}${playerHeader("position", "Pos")}${playerHeader("thi_player_rating", "Projected Impact")}${playerHeader("prior_production_rating", "Prior Production")}${playerHeader("offense", "Off")}${playerHeader("defense", "Def")}${playerHeader("all_around", "All-around")}${playerHeader("points_per_40", "Pts/40")}${playerHeader("true_shooting_pct", "TS%")} ${playerHeader("porpag", "PORPAG")}${playerHeader("reliability", "Reliability")}
        </tr></thead><tbody id="cbb-player-body"></tbody></table>
      </div>
      <div class="cbb-player-pager"><button type="button" data-player-page="prev">Previous</button><span id="cbb-player-page-status"></span><button type="button" data-player-page="next">Next</button></div>
      <div class="cbb-stat-note">Only players verified on a ${escapeHtml(meta.roster_season || meta.season)} roster are shown. Projected Impact is the default rank; Prior Production preserves the unadjusted statistical grade. Green is stronger, red is weaker. Rank numbers remain neutral.</div>
    `;
    bindPlayerControls();
    paintPlayerRows();
  }

  function loadPlayerRatings() {
    if (state.playerData || state.playerLoading) return state.playerLoading;
    state.playerLoading = fetchJson(PLAYER_PATH)
      .then(payload => {
        if (!Array.isArray(payload.players)) throw new Error("Player ratings payload is missing players.");
        if (payload.meta?.version !== "thi-cbb-player-research-v1.3" || !Array.isArray(payload.team_rosters) || payload.players.some(player => player.current_roster_verified !== true)) {
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
    if (["thi_player_rating", "projected_impact_rating", "prior_production_rating", "offense", "defense", "all_around"].includes(key)) return player.research_scores?.[key] ?? -Infinity;
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
    const bands = Object.fromEntries(["thi_player_rating", "prior_production_rating", "offense", "defense", "all_around", "points_per_40", "true_shooting_pct", "porpag", "reliability"].map(key => [key, cachedPlayerBands(key)]));
    body.innerHTML = page.length ? page.map(player => {
      const score = player.research_scores || {};
      const metrics = player.metrics || {};
      return `<tr data-player-id="${escapeHtml(player.player_season_id)}"><td class="cbb-rank">#${integer(player.ranks?.overall)}</td><td><div class="cbb-team-name">${escapeHtml(player.name)}</div><div class="cbb-team-meta">${escapeHtml(player.projection_context?.basis || player.role)} · Open profile →</div></td><td><div class="cbb-team-cell">${teamLogo(player,"small")}<span>${escapeHtml(player.team)}</span></div></td><td>${escapeHtml(player.position || "—")}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.thi_player_rating(player)}">${number(score.thi_player_rating,1)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.prior_production_rating(player)}">${number(score.prior_production_rating,1)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.offense(player)}">${number(score.offense,1)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.defense(player)}">${number(score.defense,1)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.all_around(player)}">${number(score.all_around,1)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.points_per_40(player)}">${number(metrics.points_per_40,1)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.true_shooting_pct(player)}">${shootingPct(metrics.true_shooting_pct)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.porpag(player)}">${number(metrics.porpag,2)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.reliability(player)}">${pct(player.data_quality?.reliability)}</td></tr>`;
    }).join("") : `<tr><td colspan="13" class="cbb-empty">No players match those filters.</td></tr>`;
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
    detail.classList.remove("is-game-page", "is-team-page");
    const panel = detail.querySelector(".cbb-detail-panel");
    const score = player.research_scores || {};
    const metrics = player.metrics || {};
    const forecast = state.data?.intelligence?.player_projections?.find(row => row.player_season_id === playerId) || {};
    panel.innerHTML = `
      <button class="cbb-detail-close" type="button" data-cbb-close>Close</button>
      <div class="cbb-kicker">THI CBB player profile</div>
      <h2 class="cbb-detail-title" id="cbb-detail-title">${escapeHtml(player.name)}</h2>
      <div class="cbb-detail-sub">${escapeHtml(player.team)} · ${escapeHtml(player.conference || "Independent")} · ${escapeHtml(player.position || "Position unavailable")} · ${escapeHtml(player.role)}</div>
      <div class="cbb-detail-grid">
        ${detailStat("Projected impact", number(score.thi_player_rating,1))}
        ${detailStat("Prior production", number(score.prior_production_rating,1))}
        ${detailStat("Overall rank", `#${integer(player.ranks?.overall)}`)}
        ${detailStat("Position rank", `#${integer(player.ranks?.position_group)}`)}
        ${detailStat("Offense", number(score.offense,1))}
        ${detailStat("Defense", number(score.defense,1))}
        ${detailStat("All-around", number(score.all_around,1))}
      </div>
      <section class="cbb-detail-section"><h3>Scoring and creation</h3>
        ${playerDetailRow("Points per 40", number(metrics.points_per_40,2), player, "points_per_40")}${playerDetailRow("Usage", pct(metrics.usage), player, "usage")}${playerDetailRow("True shooting", shootingPct(metrics.true_shooting_pct), player, "true_shooting_pct")}${playerDetailRow("Effective FG", pct(metrics.effective_field_goal_pct), player, "effective_field_goal_pct")}${playerDetailRow("PORPAG", number(metrics.porpag,3), player, "porpag")}${playerDetailRow("Offensive rating", number(metrics.offensive_rating,1), player, "offensive_rating")}${playerDetailRow("Assist / turnover", number(metrics.assist_turnover_ratio,2), player, "assist_turnover_ratio")}${playerDetailRow("Assists per 40", number(metrics.assists_per_40,2), player, "assists_per_40")}${playerDetailRow("Turnovers per 40", number(metrics.turnovers_per_40,2), player, "turnovers_per_40", true)}
      </section>
      <section class="cbb-detail-section"><h3>Projected per-game role</h3>
        ${detailRow("Projected minutes", number(forecast.projected_minutes,1))}${detailRow("Projected points", number(forecast.projected_points,1))}${detailRow("Projected rebounds", number(forecast.projected_rebounds,1))}${detailRow("Projected assists", number(forecast.projected_assists,1))}${detailRow("Projection state", humanize(forecast.projection_state || "not available"))}
        <div class="cbb-model-sub">Counting-stat forecasts publish only for players with qualified prior production. Role-only players retain impact context without fabricated box-score estimates.</div>
      </section>
      <section class="cbb-detail-section"><h3>Defense and possession value</h3>
        ${playerDetailRow("Defensive rating", number(metrics.defensive_rating,1), player, "defensive_rating", true)}${playerDetailRow("Net rating", number(metrics.net_rating,1,true), player, "net_rating")}${playerDetailRow("Rebounds per 40", number(metrics.rebounds_per_40,2), player, "rebounds_per_40")}${playerDetailRow("Offensive rebounds per 40", number(metrics.offensive_rebounds_per_40,2), player, "offensive_rebounds_per_40")}${playerDetailRow("Steals per 40", number(metrics.steals_per_40,2), player, "steals_per_40")}${playerDetailRow("Blocks per 40", number(metrics.blocks_per_40,2), player, "blocks_per_40")}${playerDetailRow("Win shares per 40", number(metrics.total_win_shares_per_40,3), player, "total_win_shares_per_40")}
      </section>
      <section class="cbb-detail-section"><h3>Sample and rating state</h3>
        ${detailRow("Current roster", `${player.team} · ${state.playerData?.meta?.roster_season || state.playerData?.meta?.season}`)}${detailRow("Production source", `${player.source_team || player.team} · ${player.source_season || state.playerData?.meta?.source_season || "Prior season"}`)}${detailRow("Between-season transfer", player.transfer_between_seasons ? "Yes" : "No")}${detailRow("Games", integer(player.sample?.games))}${detailRow("Starts", integer(player.sample?.starts))}${detailRow("Minutes", integer(player.sample?.minutes))}${detailRow("Minutes per game", number(player.sample?.minutes_per_game,1))}${detailRow("Reliability", pct(player.data_quality?.reliability))}${detailRow("Projection use", "Research reference only")}
        ${detailRow("Projection basis", player.projection_context?.basis || "Qualified prior production")}${detailRow("Competition adjustment", number(player.projection_context?.competition_adjustment,1,true))}${detailRow("Destination adjustment", number(player.projection_context?.destination_adjustment,1,true))}${detailRow("Pedigree adjustment", number(player.projection_context?.pedigree_adjustment,1,true))}
        <div class="cbb-model-sub">V1.3 ranks projected impact using active-roster status, prior production, team-strength translation, destination context, pedigree when matched, and sample reliability. It remains a research rating rather than a lineup-adjusted game projection.</div>
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
    const bracket = state.data.bracketology || {};
    const meta = bracket.meta || {};
    const field = bracket.field || [];
    if (!field.length) {
      view.innerHTML = `
        <div class="cbb-kicker">NCAA tournament projection</div>
        <h1 class="page-title">THI Bracketology</h1>
        <p class="page-subtitle">A projected 68-team field built from THI team strength, résumé quality, conference races and selection-committee style inputs.</p>
        <div class="cbb-readiness-banner"><span class="cbb-status-pill">Awaiting first build</span><strong>The forecast is ready to generate</strong><p>Run the CBB Bracketology workflow to publish the initial 68-team preseason field.</p></div>`;
      return;
    }
    const bubble = bracket.bubble || {};
    const regions = bracket.regions || {};
    const firstFour = bracket.first_four || [];
    const isPreseasonOutlook = meta.forecast_type === "preseason_strength_scenario";
    const atLargeCut = (bubble.last_four_in || []).reduce((minimum, team) => Math.min(minimum, Number(team.selection_score ?? team.prior_net)), Infinity);
    if (isPreseasonOutlook) {
      const nationalBoard = [...field].sort((a,b) => Number(a.overall_rank || 999) - Number(b.overall_rank || 999));
      const atLargePool = nationalBoard.filter(team => team.bid_type === "at_large");
      const conferenceFavorites = nationalBoard.filter(team => team.bid_type === "automatic").sort((a,b) => String(a.conference?.abbreviation || "").localeCompare(String(b.conference?.abbreviation || "")));
      view.innerHTML = `
        <div class="cbb-kicker">NCAA tournament outlook</div>
        <h1 class="page-title">THI Preseason Field Outlook</h1>
        <p class="page-subtitle">An opening strength board for the 2027 season. It identifies the teams THI rates most highly before results exist without pretending a committee-quality seed list or bubble can already be known.</p>
        <div class="cbb-readiness-banner"><span class="cbb-status-pill">Preseason scenario</span><strong>No seed lines or regions yet</strong><p>${escapeHtml(meta.limitations)}</p></div>
        <div class="cbb-stat-grid">
          ${statCard("Strength pool", integer(meta.field_size), `${integer(meta.automatic_bid_count)} conference favorites · ${integer(meta.at_large_count)} at-large candidates`)}
          ${statCard("No. 1 opening rating", escapeHtml(nationalBoard[0]?.team || "—"), `${number(nationalBoard[0]?.selection_score ?? nationalBoard[0]?.prior_net,1,true)} THI selection`)}
          ${statCard("2027 games included", integer(meta.current_game_count), "Résumé evidence has not begun")}
          ${statCard("Public forecast state", "Opening outlook", `2027 · ${escapeHtml(meta.version || "v0.3")}`)}
        </div>

        <section class="cbb-section"><div class="cbb-section-head"><div><div class="cbb-label">Opening national board</div><h2 class="cbb-section-title">Top 16 by THI strength</h2></div><div class="cbb-section-note">These are rating positions, not NCAA tournament seeds. Region placement begins only after the résumé gate clears.</div></div>
          <div class="cbb-bubble-grid">${[0,4,8,12].map(start => outlookColumn(`${start + 1}–${start + 4}`, nationalBoard.slice(start,start + 4), start)).join("")}</div>
        </section>

        <section class="cbb-section"><div class="cbb-section-head"><div><div class="cbb-label">Unseeded selection pool</div><h2 class="cbb-section-title">Preseason at-large candidates</h2></div><div class="cbb-section-note">The pool reflects predictive strength and qualified roster information. It is deliberately unseeded and has no “last four in” label.</div></div>
          <div class="cbb-bubble-grid">${[0,9,18,27].map(start => outlookColumn(`${start + 1}–${Math.min(start + 9, atLargePool.length)}`, atLargePool.slice(start,start + 9), start)).join("")}</div>
        </section>

        <section class="cbb-section"><div class="cbb-section-head"><div><div class="cbb-label">Automatic-bid baseline</div><h2 class="cbb-section-title">Preseason conference favorites</h2></div><div class="cbb-section-note">Each entry is the highest-rated current team in its league. These are conference forecasts, not awarded bids.</div></div>
          <div class="cbb-bubble-grid">${[0,8,16,24].map(start => outlookColumn(`${start + 1}–${Math.min(start + 8, conferenceFavorites.length)}`, conferenceFavorites.slice(start,start + 8), start, true)).join("")}</div>
        </section>

        <div class="cbb-methodology"><strong>When the bracket unlocks</strong><p>THI publishes regions, seed lines, First Four matchups and the live bubble after at least 300 teams have eight current-season games. That is when schedule strength, road performance and opponent-quality records can meaningfully separate résumés.</p><p>${escapeHtml(meta.methodology)}</p></div>`;
      view.querySelectorAll("[data-bracket-team-id]").forEach(button => button.addEventListener("click", () => openTeamDossier(button.dataset.bracketTeamId)));
      return;
    }
    view.innerHTML = `
      <div class="cbb-kicker">NCAA tournament projection</div>
      <h1 class="page-title">THI Bracketology</h1>
      <p class="page-subtitle">THI's 68-team field forecast, organized into four regions with automatic bids, at-large selections, the First Four and both sides of the cut line.</p>
      <div class="cbb-readiness-banner"><span class="cbb-status-pill">Strength + résumé forecast</span><strong>Predictive quality anchors the field; results phase in</strong><p>${escapeHtml(meta.limitations)}</p></div>
      <div class="cbb-stat-grid">
        ${statCard("Projected field", integer(meta.field_size), `${integer(meta.automatic_bid_count)} auto · ${integer(meta.at_large_count)} at-large`)}
        ${statCard("No. 1 overall", escapeHtml(field[0]?.team || "—"), `${number(field[0]?.prior_net,1,true)} THI net`)}
        ${statCard("At-large cut", Number.isFinite(atLargeCut) ? number(atLargeCut,1,true) : "—", "Lowest current selection score")}
        ${statCard("Forecast state", field.some(team => String(team.selection_state || "").includes("early_resume")) ? "Strength + roster + résumé" : "Strength + roster", `2027 · ${escapeHtml(meta.version || "v0.2")}`)}
      </div>

      <section class="cbb-section"><div class="cbb-section-head"><div><div class="cbb-label">Projected 68-team field</div><h2 class="cbb-section-title">Four regions</h2></div><div class="cbb-section-note">The slash identifies a First Four slot. Region placement uses an S-curve with conference separation where the field allows.</div></div>
        <div class="cbb-bracket-grid">${["East", "South", "Midwest", "West"].map(region => bracketRegion(region, regions[region] || [])).join("")}</div>
      </section>

      <section class="cbb-section"><div class="cbb-section-head"><div><div class="cbb-label">Dayton</div><h2 class="cbb-section-title">First Four</h2></div><div class="cbb-section-note">The last four at-larges and four lowest projected automatic bids play into the 64-team bracket.</div></div>
        <div class="cbb-first-four-grid">${firstFour.map(firstFourCard).join("")}</div>
      </section>

      <section class="cbb-section"><div class="cbb-section-head"><div><div class="cbb-label">Selection line</div><h2 class="cbb-section-title">Bubble board</h2></div><div class="cbb-section-note">This becomes résumé-driven as 2027 results, road performance and opponent quality accumulate.</div></div>
        <div class="cbb-bubble-grid">
          ${bubbleColumn("Last four in", bubble.last_four_in || [], true)}
          ${bubbleColumn("First four out", bubble.first_four_out || [])}
          ${bubbleColumn("Next four out", bubble.next_four_out || [])}
        </div>
      </section>

      <section class="cbb-section"><div class="cbb-section-head"><div><div class="cbb-label">League footprint</div><h2 class="cbb-section-title">Projected bids by conference</h2></div><div class="cbb-section-note">Every conference receives one projected automatic bid; additional bids reflect THI's current strength order.</div></div>
        <div class="cbb-panel cbb-table-wrap"><table class="cbb-table cbb-bid-table"><thead><tr><th>Conference</th><th>Total bids</th><th>Auto</th><th>At-large</th></tr></thead><tbody>${(bracket.conference_bids || []).map(row => `<tr><td class="cbb-team-name">${escapeHtml(row.conference)}</td><td class="cbb-number">${integer(row.bids)}</td><td class="cbb-number">${integer(row.automatic)}</td><td class="cbb-number">${integer(row.at_large)}</td></tr>`).join("")}</tbody></table></div>
      </section>
    `;
    view.querySelectorAll("[data-bracket-team-id]").forEach(button => button.addEventListener("click", () => openTeamDetail(button.dataset.bracketTeamId)));
  }

  function bracketRegion(region, rows) {
    return `<article class="cbb-panel cbb-region-card"><div class="cbb-region-head"><span>${escapeHtml(region)}</span><small>16 seeds</small></div><div class="cbb-seed-list">${rows.map(row => `<div class="cbb-seed-row ${row.first_four ? "is-first-four" : ""}"><strong>${integer(row.seed)}</strong>${row.first_four ? `<span>${escapeHtml(row.team)}</span>` : `<button type="button" data-bracket-team-id="${escapeHtml(row.team_id)}">${teamLogo({team_id:row.team_id,team:row.team},"tiny")}<span>${escapeHtml(row.team)}</span></button>`}<small>${escapeHtml(row.conference)}</small></div>`).join("")}</div></article>`;
  }

  function firstFourCard(game) {
    const label = game.bid_type === "automatic" ? "Automatic bid" : "At-large";
    return `<article class="cbb-panel cbb-first-four-card"><div class="cbb-label">${escapeHtml(game.region)} · ${integer(game.seed)} seed · ${label}</div>${(game.teams || []).map((team, index) => `<div class="cbb-first-four-team"><button type="button" data-bracket-team-id="${escapeHtml(team.team_id)}">${teamLogo(team,"tiny")}<span>${escapeHtml(team.team)}</span></button><span>${escapeHtml(team.conference?.abbreviation || "—")}</span></div>${index === 0 ? `<div class="cbb-first-four-vs">vs</div>` : ""}`).join("")}</article>`;
  }

  function bubbleColumn(title, rows, firstFour = false) {
    return `<article class="cbb-panel cbb-bubble-card"><h3>${escapeHtml(title)}</h3>${rows.map((team, index) => `<button type="button" class="cbb-bubble-team" data-bracket-team-id="${escapeHtml(team.team_id)}"><span><strong>${index + 1}</strong>${teamLogo(team,"tiny")}<b>${escapeHtml(team.team)}</b></span><small>${escapeHtml(team.conference?.abbreviation || "—")} · ${number(team.selection_score ?? team.prior_net,1,true)} selection</small></button>`).join("")} ${firstFour ? `<div class="cbb-model-sub">These four teams occupy the two at-large First Four games.</div>` : ""}</article>`;
  }

  function outlookColumn(title, rows, offset = 0, conferenceOrder = false) {
    return `<article class="cbb-panel cbb-bubble-card"><h3>${escapeHtml(title)}</h3>${rows.map((team, index) => `<button type="button" class="cbb-bubble-team" data-bracket-team-id="${escapeHtml(team.team_id)}"><span><strong>${conferenceOrder ? escapeHtml(team.conference?.abbreviation || "—") : offset + index + 1}</strong>${teamLogo(team,"tiny")}<b>${escapeHtml(team.team)}</b></span><small>${conferenceOrder ? `${number(team.selection_score ?? team.prior_net,1,true)} selection` : `${escapeHtml(team.conference?.abbreviation || "—")} · ${number(team.selection_score ?? team.prior_net,1,true)} rating`}</small></button>`).join("")}</article>`;
  }

  function renderPortal() {
    const view = document.getElementById("view-cbb-portal");
    const source = (state.data.priors.teams || []).filter(team => Number(team.personnel?.transfers?.incoming_count) > 0);
    const conferences = [...new Set(source.map(team => team.conference?.abbreviation || team.conference?.name).filter(Boolean))].sort();
    const portalValue = (team,key) => {
      if(key === "team") return team.team || "";
      if(key === "conference") return team.conference?.abbreviation || "";
      const transfers=team.personnel?.transfers || {};
      return transfers[key] ?? -Infinity;
    };
    const rows = source.filter(team => {
      const query=state.portalQuery.trim().toLowerCase(); const conference=team.conference?.abbreviation || team.conference?.name;
      return (!query || `${team.team} ${team.conference?.name || ""}`.toLowerCase().includes(query)) && (state.portalConference === "all" || conference === state.portalConference);
    }).sort((a,b) => { const av=portalValue(a,state.portalSort.key),bv=portalValue(b,state.portalSort.key); const order=typeof av === "string" ? av.localeCompare(bv) : Number(av)-Number(bv); return state.portalSort.direction === "asc" ? order : -order; });
    const totalIncoming = source.reduce((sum, team) => sum + Number(team.personnel?.transfers?.incoming_count || 0), 0);
    const matched = source.reduce((sum, team) => sum + Number(team.personnel?.transfers?.prior_production_match_count || 0), 0);
    const header=(key,label)=>{const active=state.portalSort.key===key;return `<th data-portal-sort="${key}" class="${active?"is-sorted":""}">${label}${active?(state.portalSort.direction==="desc"?" ↓":" ↑"):" ↕"}</th>`;};
    const bandFor=key=>{const values=source.map(team=>Number(portalValue(team,key))).filter(Number.isFinite).sort((a,b)=>a-b);return team=>{const v=Number(portalValue(team,key));let i=values.findIndex(x=>x>=v);if(i<0)i=values.length-1;return Math.max(1,Math.min(5,Math.ceil((i/Math.max(1,values.length-1))*5)));};};
    const bands={incoming_count:bandFor("incoming_count"),prior_production_match_count:bandFor("prior_production_match_count"),prior_minutes:bandFor("prior_minutes"),prior_points:bandFor("prior_points"),mean_incoming_rating:bandFor("mean_incoming_rating")};
    view.innerHTML = `
      <div class="cbb-kicker">Roster movement and proven production</div>
      <h1 class="page-title">CBB Transfer Portal</h1>
      <p class="page-subtitle">Team-level incoming transfer context using ratings and prior college production. THI measures what arrives instead of treating raw transfer count as automatic improvement.</p>
      <div class="cbb-stat-grid">${statCard("Teams with additions",integer(source.length),"2027 incoming transfer classes")}${statCard("Incoming players",integer(totalIncoming),"Rated and unrated additions")}${statCard("Production matches",integer(matched),"Players matched to prior stats")}${statCard("Primary lens","Proven workload","Minutes, points and efficiency")}</div>
      <div class="cbb-controls"><input id="cbb-portal-search" class="cbb-input" type="search" placeholder="Search team or conference" value="${escapeHtml(state.portalQuery)}"><select id="cbb-portal-conference" class="cbb-select"><option value="all">All conferences</option>${conferences.map(conf=>`<option value="${escapeHtml(conf)}" ${state.portalConference===conf?"selected":""}>${escapeHtml(conf)}</option>`).join("")}</select></div>
      <section class="cbb-section"><div class="cbb-section-head"><div><div class="cbb-label">Team portal board</div><h2 class="cbb-section-title">Incoming production</h2></div><div class="cbb-section-note">Every metric is sortable and graded relative to the current transfer pool. Click a team for its personnel profile.</div></div>
        <div class="cbb-panel cbb-table-wrap"><table class="cbb-table"><thead><tr>${header("team","Team")}${header("conference","Conf")}${header("incoming_count","Incoming")}${header("prior_production_match_count","Matched")}${header("prior_minutes","Prior minutes")}${header("prior_points","Prior points")}${header("mean_incoming_rating","Mean rating")}</tr></thead><tbody>${rows.map(team=>{const t=team.personnel.transfers;return `<tr data-team-id="${team.team_id}"><td><div class="cbb-team-cell">${teamLogo(team,"small")}<strong>${escapeHtml(team.team)}</strong></div></td><td>${escapeHtml(team.conference?.abbreviation||"—")}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.incoming_count(team)}">${integer(t.incoming_count)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.prior_production_match_count(team)}">${integer(t.prior_production_match_count)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.prior_minutes(team)}">${integer(t.prior_minutes)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.prior_points(team)}">${integer(t.prior_points)}</td><td class="cbb-number cbb-metric-cell cbb-band-${bands.mean_incoming_rating(team)}">${number(t.mean_incoming_rating,3)}</td></tr>`;}).join("")}</tbody></table></div>
      </section><div class="cbb-stat-note">${integer(rows.length)} teams shown. Green indicates a stronger incoming production profile relative to this portal class.</div>`;
    view.querySelector("#cbb-portal-search").addEventListener("input",event=>{state.portalQuery=event.target.value;renderPortal();const input=document.getElementById("cbb-portal-search");input?.focus();input?.setSelectionRange(input.value.length,input.value.length);});
    view.querySelector("#cbb-portal-conference").addEventListener("change",event=>{state.portalConference=event.target.value;renderPortal();});
    view.querySelector("thead").addEventListener("click",event=>{const cell=event.target.closest("[data-portal-sort]");if(!cell)return;const key=cell.dataset.portalSort;state.portalSort.direction=state.portalSort.key===key&&state.portalSort.direction==="desc"?"asc":"desc";state.portalSort.key=key;renderPortal();});
    view.querySelector("tbody").addEventListener("click",event=>{const row=event.target.closest("[data-team-id]");if(row)openTeamDetail(Number(row.dataset.teamId));});
  }

  function renderMarketResearch() {
    const view = document.getElementById("view-cbb-market");
    const coverage = state.data.foundation.coverage || {};
    const history = state.data.history.seasons || [];
    const test = state.data.model.evaluation?.out_of_time_test || {};
    const marketGames = history.reduce((sum, season) => sum + Number(season.games_with_market || 0), 0);
    const marketBoard = (state.data.intelligence?.market_board || []).filter(row =>
      [row.opening_spread, row.current_spread, row.opening_total, row.current_total].some(value => value !== null && value !== undefined && Number.isFinite(Number(value)))
    );
    const backtest = state.data.publicBacktest?.sports?.cbb || {};
    const backtestResult = backtest.actionable_over_5 || {};
    const backtestMeta = state.data.publicBacktest?.meta || {};
    const short = backtest.short_favorites || {};
    const marketRowsMarkup = rows => rows.length ? rows.slice(0,100).map(row => `<tr><td><strong>${escapeHtml(row.away_team)} ${matchupWord(row)} ${escapeHtml(row.home_team)}</strong></td><td class="cbb-number">${number(row.opening_spread,1,true)}</td><td class="cbb-number">${number(row.current_spread,1,true)}</td><td class="cbb-number">${number(row.spread_move,1,true)}</td><td class="cbb-number">${number(row.opening_total,1)}</td><td class="cbb-number">${number(row.current_total,1)}</td><td class="cbb-number">${number(row.total_move,1,true)}</td><td class="cbb-number">${number(row.model_edge,1,true)}</td></tr>`).join("") : `<tr><td colspan="8" class="cbb-empty">No sportsbook lines are posted yet. This board will populate automatically when usable spreads or totals arrive.</td></tr>`;
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
      <section class="cbb-section"><div class="cbb-section-head"><div><div class="cbb-label">2025–2026 · held-out research</div><h2 class="cbb-section-title">Historical Research Audit</h2></div><div class="cbb-section-note">Every game with a &gt;5-point model edge is shown. Flat −110 returns are hypothetical because per-play prices are unavailable.</div></div>
        <div class="cbb-stat-grid">
          ${statCard("ATS record", backtestResult.record || "—", `${integer(backtestResult.games)} historical decisions`)}
          ${statCard("Hit rate", pct(backtestResult.hit_rate), `95% CI ${(backtestResult.hit_rate_ci_95 || []).map(value=>number(value,1)).join("–")}%`)}
          ${statCard("Hypothetical return", `${number(backtestResult.hypothetical_return_pct,1,true)}%`, "Flat −110 arithmetic; not realized ROI")}
          ${statCard("Current status", "Not validated", `Exact p ${number(backtestResult.p_value_vs_flat_minus_110,3)} · Holm p ${number(backtestResult.holm_adjusted_p,3)}`)}
        </div>
        <div class="cbb-panel cbb-table-wrap"><table class="cbb-table"><thead><tr><th>Season</th><th>Record</th><th>ATS</th><th>Hypothetical return</th><th>THI margin MAE</th><th>Market margin MAE</th></tr></thead><tbody>${(backtest.yearly || []).map(row=>{const accuracy=(backtest.market_accuracy||[]).find(item=>item.season===row.season)||{};return `<tr><td><strong>${integer(row.season)}</strong></td><td>${escapeHtml(row.record)}</td><td class="cbb-number">${number(row.hit_rate,1)}%</td><td class="cbb-number">${number(row.hypothetical_return_pct,1,true)}%</td><td class="cbb-number">${number(accuracy.thi_margin_mae,2)}</td><td class="cbb-number">${number(accuracy.market_margin_mae,2)}</td></tr>`;}).join("")}</tbody></table></div>
        <div class="cbb-stat-grid">
          ${statCard("Short favorites SU", short.su_record || "—", `${number(short.su_win_rate,1)}% straight-up · −1 to −4.5`)}
          ${statCard("Short favorites ATS", short.ats_record || "—", `${number(short.ats_cover_rate,1)}% ATS · ${integer(short.games)} games`)}
        </div>
        <div class="cbb-stat-note">${escapeHtml(short.note || "Short-favorite research will publish with the next audit build.")}</div>
        <div class="cbb-stat-note"><strong>${escapeHtml(backtest.verdict || "Not validated")}.</strong> ${escapeHtml(backtest.validation_note || "Historical results are unavailable.")} ${escapeHtml(backtestMeta.price_policy || "")} ${escapeHtml(backtestMeta.promotion_rule || "")}</div>
      </section>
      <section class="cbb-section"><div class="cbb-section-head"><div><div class="cbb-label">Current market board</div><h2 class="cbb-section-title">Open-to-current movement</h2></div><div class="cbb-section-note">Movement is descriptive context. It never enters the projection model.</div></div>
        <div class="cbb-controls"><input id="cbb-market-search" class="cbb-input" type="search" placeholder="Search either team"><span id="cbb-market-count" class="cbb-stat-note">${integer(Math.min(marketBoard.length,100))} of ${integer(marketBoard.length)} lined games</span></div>
        <div class="cbb-panel cbb-table-wrap"><table class="cbb-table"><thead><tr><th>Matchup</th><th>Open spread</th><th>Current spread</th><th>Move</th><th>Open total</th><th>Current total</th><th>Total move</th><th>THI edge</th></tr></thead><tbody id="cbb-market-body">${marketRowsMarkup(marketBoard)}</tbody></table></div>
      </section>
    `;
    view.querySelector("#cbb-market-search")?.addEventListener("input", event => {
      const query = normalizeSearch(event.target.value);
      const rows = marketBoard.filter(row => !query || normalizeSearch(`${row.away_team} ${row.home_team}`).includes(query));
      view.querySelector("#cbb-market-body").innerHTML = marketRowsMarkup(rows);
      view.querySelector("#cbb-market-count").textContent = `${integer(Math.min(rows.length,100))} of ${integer(rows.length)} matching lined games`;
    });
  }

  function ratingsRows() {
    const priors = state.data.priors.teams || [];
    const filtered = priors.filter(team => {
      const query = normalizeSearch(state.query);
      const matchesQuery = !query || normalizeSearch(`${team.team} ${team.conference?.name || ""}`).includes(query);
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
      <h1 class="page-title">CBB THI Ratings</h1>
      <p class="page-subtitle">THI's modeled estimate of team strength, decomposed into the rating lenses and context that will update as the 2027 season develops.</p>
      ${cbbRatingDecomposition(priors)}
      <div class="cbb-definition-banner"><strong>THI Ratings</strong><span>How strong the model believes a team is beneath its record.</span><strong>Team Data</strong><span>Observed results, box-score performance and roster facts.</span></div>
      <div class="cbb-controls">
        <input id="cbb-rating-search" class="cbb-input" type="search" placeholder="Search team or conference" value="${escapeHtml(state.query)}">
        <select id="cbb-conference-filter" class="cbb-select"><option value="all">All conferences</option>${conferences.map(conf => `<option value="${escapeHtml(conf)}" ${state.conference === conf ? "selected" : ""}>${escapeHtml(conf)}</option>`).join("")}</select>
      </div>
      <div class="cbb-panel cbb-table-wrap">
        <table class="cbb-table" aria-label="2027 THI college basketball preseason ratings">
          <thead><tr>
            <th>Rank</th>${ratingHeader("team", "Team")}${ratingHeader("conference", "Conf")}${ratingHeader("prior_net", "Overall")}<th>Predictive</th><th>Recent form</th><th>SOS</th><th>vs THI Top 25</th>${ratingHeader("prior_offense", "Adj off")}${ratingHeader("prior_defense", "Adj def")}<th>Home edge</th>
          </tr></thead>
          <tbody id="cbb-rating-body"></tbody>
        </table>
      </div>
      <div class="cbb-stat-note" style="margin-top:9px">Overall and Predictive share the verified preseason prior until 2027 results create separate lenses. Recent form, schedule strength and quality records activate only after games are played. Lower defensive efficiency is better.</div>
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
    view.querySelector("#cbb-rating-body").addEventListener("click", async event => {
      const row = event.target.closest("[data-team-id]");
      if (row) { await loadDeferred(["intelligence"]); openTeamDetail(Number(row.dataset.teamId)); }
    });
    paintRatingRows();
  }

  function cbbRatingDecomposition(priors) {
    const generated = state.data?.profiles?.meta?.generated_at_utc || state.data?.model?.meta?.generated_at_utc;
    const stamp = generated ? new Intl.DateTimeFormat("en-US", { dateStyle:"medium", timeStyle:"short" }).format(new Date(generated)) : "Awaiting refresh";
    const home = cbbNationalHomeAdvantage();
    const conferenceRows = new Map();
    priors.forEach(team => {
      const name = team.conference?.abbreviation || team.conference?.name || "Independent";
      if (!conferenceRows.has(name)) conferenceRows.set(name, []);
      if (Number.isFinite(Number(team.prior_net))) conferenceRows.get(name).push(Number(team.prior_net));
    });
    const conferences = [...conferenceRows.entries()].map(([name, values]) => ({
      name,
      average: values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length),
      median: values.slice().sort((a,b) => a-b)[Math.floor(values.length / 2)],
    })).sort((a,b) => b.average-a.average).slice(0,6);
    return `<section class="cbb-rating-decomposition" aria-label="THI rating decomposition">
      <div class="cbb-rating-decomposition-head"><div><div class="cbb-label">THI Rating Decomposition</div><h2>What each rating means now</h2></div><span>Rated ${escapeHtml(stamp)}</span></div>
      <div class="cbb-rating-lenses">
        ${methodCard("Overall", "2027 preseason net efficiency", "The full prior blends last season's opponent-adjusted efficiency with verified continuity and personnel context.")}
        ${methodCard("Predictive", "Powers current projections", "The same preseason team state feeds the walk-forward score model now. It will separate from Overall after completed 2027 games update team state.")}
        ${methodCard("Recent form", "Awaiting 2027 games", "No recent-form rating is published before a qualified current-season sample exists.")}
        ${methodCard("Schedule + opponent quality", "Awaiting 2027 games", "Schedule strength and records against top-25 and top-50 THI teams begin only after games are played.")}
        ${methodCard("Dynamic home advantage", Number.isFinite(home) ? `${number(home,2)}-point national mean` : "Awaiting estimate", "Every program receives its own five-season regularized value; neutral courts receive zero.")}
      </div>
      <div class="cbb-conference-strip"><strong>Conference strength · neutral-floor team benchmark</strong>${conferences.map(row => `<span>${escapeHtml(row.name)} <b>${number(row.average,1,true)}</b> avg · ${number(row.median,1,true)} median</span>`).join("")}</div>
    </section>`;
  }

  function cbbNationalHomeAdvantage() {
    const published = Number(state.data?.homeCourt?.meta?.national_points);
    if (Number.isFinite(published)) return published;
    const marginModel = state.data?.model?.models?.margin || {};
    const homeIndex = (marginModel.feature_names || []).indexOf("home_court");
    const homeCoefficient = homeIndex >= 0 ? Number((marginModel.coefficients || [])[homeIndex + 1]) : NaN;
    const homeScale = Number(marginModel.scales?.home_court);
    const modelHome = Number.isFinite(homeCoefficient) && Number.isFinite(homeScale) && homeScale !== 0 ? homeCoefficient / homeScale : NaN;
    const suiteHome = Number(state.data?.intelligence?.home_court?.national_points);
    return Number.isFinite(suiteHome) ? suiteHome : modelHome;
  }

  function ratingHeader(key, label) {
    const active = state.ratingSort.key === key;
    const arrow = active ? (state.ratingSort.direction === "desc" ? "↓" : "↑") : "↕";
    return `<th data-sort="${key}" class="${active ? "is-sorted" : ""}">${escapeHtml(label)}<span class="cbb-sort-icon" aria-hidden="true">${arrow}</span></th>`;
  }

  function paintRatingRows() {
    const body = document.getElementById("cbb-rating-body");
    if (!body) return;
    const all = state.data.priors.teams || [];
    const rows = ratingsRows();
    const netBand = quantileBands(all, "prior_net");
    const offBand = quantileBands(all, "prior_offense");
    const defBand = quantileBands(all, "prior_defense", true);
    const home = cbbNationalHomeAdvantage();
    const homeByTeam = new Map((state.data?.homeCourt?.teams || []).map(row => [Number(row.team_id), row]));
    const globalRank = new Map([...all].sort((a,b) => b.prior_net - a.prior_net).map((team,index) => [team.team_id,index+1]));
    body.innerHTML = rows.length ? rows.map(team => {
      const programHome = homeByTeam.get(Number(team.team_id));
      return `<tr data-team-id="${team.team_id}"><td class="cbb-rank">#${globalRank.get(team.team_id) || "—"}</td><td><div class="cbb-team-cell">${teamLogo(team,"normal")}<div><div class="cbb-team-name">${escapeHtml(team.team)}</div><div class="cbb-team-meta">View team profile →</div></div></div></td><td>${escapeHtml(team.conference?.abbreviation || "—")}</td><td class="cbb-number cbb-metric-cell cbb-band-${netBand(team)}">${number(team.prior_net,2)}</td><td class="cbb-number cbb-metric-cell cbb-band-${netBand(team)}">${number(team.prior_net,2)}</td><td class="cbb-number cbb-rating-pending">Preseason</td><td class="cbb-number cbb-rating-pending">—</td><td class="cbb-number cbb-rating-pending">0–0</td><td class="cbb-number cbb-metric-cell cbb-band-${offBand(team)}">${number(team.prior_offense,2)}</td><td class="cbb-number cbb-metric-cell cbb-band-${defBand(team)}">${number(team.prior_defense,2)}</td><td class="cbb-number cbb-rating-context">${number(programHome?.home_court_points ?? home,2)}</td></tr>`;
    }).join("") : `<tr><td colspan="11" class="cbb-empty">No teams match those filters.</td></tr>`;
  }

  async function openTeamDetail(teamId) {
    const prior = state.data.priors.teams.find(team => Number(team.team_id) === Number(teamId));
    const profile = state.data.profiles.teams.find(team => Number(team.team_id) === Number(teamId));
    if (!prior) return;
    const detail = document.getElementById("cbb-team-detail");
    detail.classList.remove("is-game-page");
    detail.classList.add("is-team-page");
    const panel = detail.querySelector(".cbb-detail-panel");
    if (!state.playerData) {
      panel.innerHTML = `<button class="cbb-detail-close cbb-game-back" type="button" data-cbb-close>← Back to teams</button><div class="cbb-kicker">THI CBB team profile</div><h2 class="cbb-detail-title" id="cbb-detail-title">${escapeHtml(profile?.display_name || prior.team)}</h2><div class="cbb-readiness-banner"><strong>Loading verified roster…</strong></div>`;
      detail.classList.add("is-open");
      detail.setAttribute("aria-hidden", "false");
      document.body.style.overflow = "hidden";
      await loadPlayerRatings();
    }
    const recruiting = prior.personnel?.recruiting || {};
    const transfers = prior.personnel?.transfers || {};
    const preseason = profile?.preseason_prior || {};
    const factors = prior.prior_four_factors || {};
    const roster = state.playerData?.team_rosters?.find(row => Number(row.team_id) === Number(teamId));
    const dossier = state.data?.intelligence?.team_dossiers?.find(row => Number(row.team_id) === Number(teamId));
    const homeCourt = state.data?.intelligence?.home_court || {};
    const programCourt = (state.data?.homeCourt?.teams || []).find(row => Number(row.team_id) === Number(teamId)) || dossier?.home_court;
    const resume = dossier?.resume || {};
    const recordText = record => record ? `${integer(record.wins)}–${integer(record.losses)}` : "0–0";
    panel.innerHTML = `
      <button class="cbb-detail-close cbb-game-back" type="button" data-cbb-close>← Back to teams</button>
      <button class="thi-account-button" type="button" data-cbb-save-team>Save team</button>
      <div class="cbb-kicker">THI CBB team profile</div>
      <div class="cbb-detail-team-title">${teamLogo({team_id:prior.team_id,team:prior.team},"large")}<h2 class="cbb-detail-title" id="cbb-detail-title">${escapeHtml(profile?.display_name || prior.team)}</h2></div>
      <div class="cbb-detail-sub">${escapeHtml(prior.conference?.name || "Independent")} · 2027 THI team dossier</div>
      <div class="cbb-detail-grid">
        ${detailStat("Net efficiency", `${number(prior.prior_net,2,true)} · #${integer(dossier?.ratings?.ranks?.net)}`)}
        ${detailStat("Adjusted offense", `${number(prior.prior_offense,2)} · #${integer(dossier?.ratings?.ranks?.offense)}`)}
        ${detailStat("Adjusted defense", `${number(prior.prior_defense,2)} · #${integer(dossier?.ratings?.ranks?.defense)}`)}
        ${detailStat("Adjusted tempo", `${number(prior.prior_tempo,1)} · #${integer(dossier?.ratings?.ranks?.tempo)}`)}
        ${detailStat("Roster quality", dossier?.roster_quality?.top_eight_average == null ? "Awaiting ratings" : `${number(dossier.roster_quality.top_eight_average,1)} · #${integer(dossier.roster_quality.rank)}`)}
        ${detailStat("Expected wins", `${number(dossier?.forecast?.expected_wins_in_window,1)} / ${integer(dossier?.forecast?.games_in_window)}`)}
      </div>
      <nav class="cbb-dossier-jump-nav" aria-label="Team dossier sections">
        <a href="#cbb-dossier-ratings">Ratings</a><a href="#cbb-dossier-personnel">Personnel</a><a href="#cbb-dossier-schedule">Schedule</a><a href="#cbb-dossier-lineups">Lineups</a><a href="#cbb-dossier-methodology">Methodology</a>
      </nav>
      <div class="cbb-team-dossier-grid">
      <section class="cbb-detail-section" id="cbb-dossier-personnel"><h3>Personnel context</h3>
        ${detailRow("Recruiting team rank", recruiting.team_rank ? `#${integer(recruiting.team_rank)}` : "—")}
        ${detailRow("Recruiting team rating", number(recruiting.team_rating,2))}
        ${detailRow("Incoming transfers", integer(transfers.incoming_count))}
        ${detailRow("Transfers with prior production", integer(transfers.prior_production_match_count))}
        ${detailRow("Incoming prior minutes", integer(transfers.prior_minutes))}
        ${detailRow("Incoming prior points", integer(transfers.prior_points))}
      </section>
      <section class="cbb-detail-section" id="cbb-dossier-ratings"><h3>Rating provenance</h3>
        ${detailRow("Source season", integer(preseason.source_season || 2026))}
        ${detailRow("2026 source net", number(preseason.adjusted?.net,1,true))}
        ${detailRow("Current rating state", "Preseason prior")}
        ${detailRow("Returning-minutes signal", prior.returning_minutes_pct > 0 ? pct(prior.returning_minutes_pct) : "Unavailable in current feed")}
      </section>
      <section class="cbb-detail-section"><h3>Projection context</h3>
        ${detailRow("Program home-court value", programCourt?.home_court_points == null ? "Awaiting estimate" : `${number(programCourt.home_court_points,2)} points · ${escapeHtml(humanize(programCourt.tier || "standard"))}`)}
        ${detailRow("National home-court mean", homeCourt.national_points == null ? number(state.data?.homeCourt?.meta?.national_points,2) : `${number(homeCourt.national_points,2)} points`)}
        ${detailRow("Neutral-site adjustment", "0.00 points")}
        ${detailRow("Historical campus sample", programCourt?.sample?.campus_games == null ? "—" : `${integer(programCourt.sample.campus_games)} conference games`)}
        ${detailRow("Home eFG% shift", programCourt?.four_factor_home_road?.home_efg_delta_pct_points == null ? "—" : `${number(programCourt.four_factor_home_road.home_efg_delta_pct_points,2,true)} pct pts`)}
        ${detailRow("Home free-throw-rate shift", programCourt?.four_factor_home_road?.home_free_throw_rate_delta == null ? "—" : `${number(programCourt.four_factor_home_road.home_free_throw_rate_delta,2,true)}`)}
        ${detailRow("Opponent turnover shift", programCourt?.four_factor_home_road?.opponent_turnover_delta_pct_points == null ? "—" : `${number(programCourt.four_factor_home_road.opponent_turnover_delta_pct_points,2,true)} pct pts`)}
        <div class="cbb-model-sub">The point value comes from a five-season regularized margin model that separates team strength from site. Four Factor splits explain the observed profile and are not added again.</div>
        <div class="cbb-roster-list">${dossier?.schedule_window?.length ? dossier.schedule_window.slice(0,6).map(game => `<div class="cbb-detail-row"><span>${escapeHtml(humanize(game.site))} vs ${escapeHtml(game.opponent)}</span><strong>${number(game.projected_margin,1,true)} · ${pct(game.win_probability)}</strong></div>`).join("") : `<div class="cbb-empty">No games in the current projection window.</div>`}</div>
      </section>
      <section class="cbb-detail-section" id="cbb-dossier-schedule"><h3>Schedule and résumé outlook</h3>
        ${detailRow("Average opponent THI net", number(dossier?.schedule_strength?.average_opponent_thi_net,2,true))}
        ${detailRow("Nonconference opponent THI net", number(dossier?.schedule_strength?.nonconference_average_opponent_thi_net,2,true))}
        ${detailRow("Games in projection window", integer(dossier?.schedule_strength?.scheduled_games))}
        ${detailRow("Expected wins in window", number(dossier?.forecast?.expected_wins_in_window,2))}
        <div class="cbb-model-sub">Schedule strength uses THI opponent ratings from the published schedule window. Résumé outcomes and quadrant-style detail will phase in with current-season results.</div>
      </section>
      <section class="cbb-detail-section"><h3>Performance and résumé profile</h3>
        ${detailRow("Overall record", recordText(resume.overall_record))}
        ${detailRow("Home / away / neutral", `${recordText(resume.site_records?.home)} · ${recordText(resume.site_records?.away)} · ${recordText(resume.site_records?.neutral)}`)}
        ${detailRow("THI quadrant-style record", `Q1 ${recordText(resume.quadrant_records?.q1)} · Q2 ${recordText(resume.quadrant_records?.q2)} · Q3 ${recordText(resume.quadrant_records?.q3)} · Q4 ${recordText(resume.quadrant_records?.q4)}`)}
        ${detailRow("Top-25 / Top-50 opponents", `${recordText(resume.opponent_quality_records?.top_25)} · ${recordText(resume.opponent_quality_records?.top_50)}`)}
        ${detailRow("THI record quality", resume.record_quality == null ? "Awaiting finals" : number(resume.record_quality,3,true))}
        ${detailRow("Away-from-home performance", resume.away_from_home_performance == null ? "Awaiting road/neutral sample" : `${number(resume.away_from_home_performance,2,true)} pts vs projection`)}
        ${detailRow("Recent form", resume.recent_form_vs_projection == null ? "Awaiting finals" : `${number(resume.recent_form_vs_projection,2,true)} pts vs projection`)}
        ${detailRow("Rating movement", dossier?.ratings?.movement_since_preseason == null ? "Preseason baseline" : `${number(dossier.ratings.movement_since_preseason,2,true)} net · ${number(dossier.ratings.rank_movement_since_preseason,0,true)} ranks`)}
        <div class="cbb-model-sub">These are THI-calculated dossier fields. Quadrant-style records use THI opponent ranks and are separated from official NCAA NET quadrants.</div>
      </section>
      <section class="cbb-detail-section" id="cbb-dossier-lineups"><h3>Projected core lineup</h3>
        <div class="cbb-model-sub">This is a projected five-player rotation core based on minutes and player-impact priors. It is not represented as an observed lineup until possession-level lineup data exists.</div>
        <div class="cbb-lineup-list">${dossier?.projected_core_lineup?.players?.length ? dossier.projected_core_lineup.players.map((player,index) => `<div class="cbb-lineup-player"><strong>${index+1}</strong><span>${escapeHtml(player.name)}</span><small>${escapeHtml(player.position || "—")} · ${number(player.projected_minutes,1)} min · ${number(player.thi_impact,1)} impact</small></div>`).join("") : `<div class="cbb-empty">Projected lineup unavailable.</div>`}</div>
        ${detailRow("Combined projected impact", number(dossier?.projected_core_lineup?.combined_impact,1))}
      </section>
      <section class="cbb-detail-section"><h3>Verified roster and rotation outlook</h3>
        <div class="cbb-model-sub">Every listed player is verified on the current roster. THI grades appear only when the player has a qualifying prior-season sample; freshmen and limited samples stay explicitly unrated.</div>
        <div class="cbb-roster-summary">${detailRow("Active players", roster ? integer(roster.player_count) : "Unavailable")}${detailRow("Qualified returning production", roster ? integer(roster.rated_player_count) : "—")}${detailRow("Returning minutes", roster?.returning_minutes_pct != null ? pct(roster.returning_minutes_pct) : "Unavailable")}${detailRow("Identified transfers", roster ? integer(roster.transfer_count) : "—")}</div>
        <div class="cbb-roster-list">${roster?.players?.length ? roster.players.map(rosterPlayerRow).join("") : `<div class="cbb-empty">A verified current roster is not available for this team yet.</div>`}</div>
      </section>
      <section class="cbb-detail-section"><h3>Opponent-adjusted Four Factors</h3>
        <div class="cbb-model-sub">Preseason values carry the prior team's offensive and defensive factor profile toward the national average according to roster continuity. Current-season observations blend in as the sample grows.</div>
        <div class="cbb-panel cbb-table-wrap"><table class="cbb-table"><thead><tr><th>Unit</th><th>eFG%</th><th>TO%</th><th>OR%</th><th>FT rate</th></tr></thead><tbody>
          <tr><td>Offense</td><td class="cbb-number">${pct(factors.offense?.effective_fg_pct)}</td><td class="cbb-number">${pct(factors.offense?.turnover_pct)}</td><td class="cbb-number">${pct(factors.offense?.offensive_rebound_pct)}</td><td class="cbb-number">${pct(factors.offense?.free_throw_rate)}</td></tr>
          <tr><td>Defense allowed</td><td class="cbb-number">${pct(factors.defense?.effective_fg_pct)}</td><td class="cbb-number">${pct(factors.defense?.turnover_pct)}</td><td class="cbb-number">${pct(factors.defense?.offensive_rebound_pct)}</td><td class="cbb-number">${pct(factors.defense?.free_throw_rate)}</td></tr>
        </tbody></table></div>
      </section>
      <section class="cbb-detail-section"><h3>Recent games</h3>
        <div class="cbb-roster-list">${dossier?.recent_games?.length ? dossier.recent_games.map(game => `<div class="cbb-detail-row"><span>${escapeHtml(String(game.start_date || "").slice(0,10))} · ${escapeHtml(humanize(game.site))} vs ${escapeHtml(game.opponent)}</span><strong>${integer(game.team_score)}–${integer(game.opponent_score)}</strong></div>`).join("") : `<div class="cbb-empty">No current-season finals yet.</div>`}</div>
      </section>
      <section class="cbb-detail-section cbb-methodology-panel cbb-dossier-wide" id="cbb-dossier-methodology"><h3>How THI builds this rating</h3>
        <div class="cbb-methodology-flow"><span>Regressed prior</span><b>→</b><span>Roster + personnel</span><b>→</b><span>Opponent-adjusted possessions</span><b>→</b><span>Four Factors + pace</span><b>→</b><span>Walk-forward update</span></div>
        <p>${escapeHtml(state.data?.intelligence?.meta?.methodology || "THI combines predictive team strength, possession efficiency and verified roster context in a chronological walk-forward model.")}</p>
        <div class="cbb-model-sub">Concepts are informed by leading public basketball analytics, while THI publishes its own calculations, testing record and data-coverage limits.</div>
      </section>
      </div>
    `;
    detail.classList.add("is-open");
    detail.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    panel.scrollTop = 0;
    panel.querySelector("[data-cbb-save-team]")?.addEventListener("click", event => {
      window.THIAccount?.saveTeam({id:`cbb:${prior.team_id}`,team:profile?.display_name || prior.team,sport:"cbb",team_id:prior.team_id});
      event.currentTarget.textContent="Saved";
    });
    panel.querySelector("[data-cbb-close]")?.focus();
  }

  function closeTeamDetail() {
    const detail = document.getElementById("cbb-team-detail");
    if (!detail?.classList.contains("is-open")) return;
    detail.classList.remove("is-open", "is-game-page", "is-team-page");
    detail.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  function detailStat(label, value) { return `<div class="cbb-detail-stat"><div class="cbb-label">${escapeHtml(label)}</div><strong>${escapeHtml(value)}</strong></div>`; }
  function detailRow(label, value) { return `<div class="cbb-detail-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`; }

  function rosterPlayerRow(player) {
    const identity = [player.position, player.class, player.height].filter(Boolean).join(" · ") || "Roster verified";
    const prior = ["rated", "projected_newcomer"].includes(player.prior_state)
      ? `<button type="button" class="cbb-roster-rating" data-roster-player-id="${escapeHtml(player.player_season_id)}">${number(player.thi_player_rating,1)} THI · profile →</button>`
      : `<span class="cbb-roster-unrated">${player.prior_state === "below_sample" ? "Limited prior sample" : "No qualifying prior"}</span>`;
    const transfer = player.transfer_between_seasons ? `<span class="cbb-chip">Transfer · ${escapeHtml(player.prior_team || "prior team")}</span>` : "";
    return `<article class="cbb-roster-player"><div><strong>${player.jersey ? `#${escapeHtml(player.jersey)} ` : ""}${escapeHtml(player.name || "Unknown player")}</strong><div class="cbb-team-meta">${escapeHtml(identity)}</div></div><div class="cbb-roster-player-state">${transfer}${prior}</div></article>`;
  }

  function renderTracking() {
    const prospective = state.data.tracking || {};
    const prospectiveSummary = prospective.summary || {};
    const spreadYtd = prospectiveSummary.spread || {};
    const totalsYtd = prospectiveSummary.totals || {};
    const accuracyYtd = prospectiveSummary.projection_accuracy || {};
    const spreadSignals = prospective.spread_by_signal || {};
    const spreadMonths = prospective.spread_by_month || {};
    const record = row => Number(row?.games) ? `${integer(row.wins)}-${integer(row.losses)}-${integer(row.pushes)}` : "—";
    const confidence = row => {
      if (row?.validation?.passed !== true) return "DEVELOPING";
      const games = Number(row?.games || 0);
      const hit = Number(row?.hit_rate);
      const clv = Number(row?.average_clv);
      const beat = Number(row?.beat_close_pct);
      if (games >= 100 && hit >= 53 && clv > 0 && beat >= 55) return "ESTABLISHED";
      if (games >= 50 && hit >= 52.5 && clv > 0 && beat >= 52.5) return "VALIDATED";
      return "DEVELOPING";
    };
    const monthLabel = value => {
      const [year, month] = String(value).split("-").map(Number);
      if (!year || !month) return humanize(value);
      return new Intl.DateTimeFormat("en-US", { month:"long", year:"numeric", timeZone:"UTC" }).format(new Date(Date.UTC(year, month - 1, 1)));
    };
    const monthlyRows = Object.entries(spreadMonths).sort(([a],[b]) => a.localeCompare(b)).map(([month,row]) => `<tr>
      <td>${escapeHtml(monthLabel(month))}</td><td class="cbb-number">${integer(row.games)}</td><td class="cbb-number">${record(row)}</td>
      <td class="cbb-number">${row.hit_rate == null ? "—" : pct(row.hit_rate)}</td><td class="cbb-number">${row.average_clv == null ? "—" : number(row.average_clv,2,true)}</td>
      <td class="cbb-number">${row.beat_close_pct == null ? "—" : pct(row.beat_close_pct)}</td></tr>`).join("");
    const signalRows = Object.entries(spreadSignals).sort(([a],[b]) => a.localeCompare(b)).map(([signal,row]) => `<tr>
      <td>${escapeHtml(humanize(signal))}</td><td class="cbb-number">${integer(row.games)}</td><td class="cbb-number">${record(row)}</td>
      <td class="cbb-number">${row.hit_rate == null ? "—" : pct(row.hit_rate)}</td><td class="cbb-number">${row.average_clv == null ? "—" : number(row.average_clv,2,true)}</td>
      <td class="cbb-number">${row.beat_close_pct == null ? "—" : pct(row.beat_close_pct)}</td><td><span class="cbb-tracking-confidence">${confidence(row)}</span></td></tr>`).join("");
    const play = spreadSignals.play || spreadSignals.PLAY || {};
    const view = document.getElementById("view-cbb-tracking");
    view.innerHTML = `
      <div class="cbb-kicker">Prospective accountability</div>
      <h1 class="page-title">Model Tracking</h1>
      <p class="page-subtitle">Every frozen THI projection graded after the final: winner accuracy, ATS results, tracked totals, closing-line value and projection error.</p>
      <section class="cbb-panel cbb-tracking-shell">
        <header class="cbb-tracking-head"><div><div class="cbb-label">Transparent Model Tracking</div><h2>Season-to-Date Performance</h2></div><p>${escapeHtml(prospective.meta?.grading_policy || "The first coordinated refresh will initialize the frozen tracking ledger.")}</p></header>
        <div class="cbb-tracking-periods"><span>Season ${escapeHtml(prospective.meta?.season || "2027")}</span></div>
        <div class="cbb-tracking-section-label">Season to Date</div>
        <div class="cbb-tracking-grid">
          ${modelCard("Games final", "Frozen projections", integer(accuracyYtd.games), `${integer(prospectiveSummary.final_games_with_frozen_projection)} finals reconciled`)}
          ${modelCard("Straight up", "Winner accuracy", accuracyYtd.winner_accuracy == null ? "—" : pct(accuracyYtd.winner_accuracy), accuracyYtd.games ? `${integer(accuracyYtd.games)} graded games` : "No decisions")}
          ${modelCard("Overall ATS", "Spread record", record(spreadYtd), spreadYtd.games ? `${pct(spreadYtd.hit_rate)} ATS` : "No decisions")}
          ${modelCard("Tracked totals", "Totals record", record(totalsYtd), totalsYtd.games ? `${pct(totalsYtd.hit_rate)}` : "No decisions")}
          ${modelCard("Average margin error", "Projection accuracy", accuracyYtd.margin_mae == null ? "—" : `${number(accuracyYtd.margin_mae,1)} pts`, "Absolute THI projection error")}
          ${modelCard("Average CLV", "Preferred side", spreadYtd.average_clv == null ? "—" : number(spreadYtd.average_clv,1,true), `${integer(spreadYtd.closing_line_games)} decisions with a close`)}
          ${modelCard("Beat close", "Spread CLV", spreadYtd.beat_close_pct == null ? "—" : pct(spreadYtd.beat_close_pct), "Directional closing-line decisions")}
          ${modelCard("Play tier ATS", "Qualified plays", record(play), play.games ? `${pct(play.hit_rate)} ATS` : "No decisions")}
        </div>
        <div class="cbb-tracking-table-section"><div class="cbb-tracking-table-title">Monthly Ledger</div><div class="cbb-table-wrap"><table class="cbb-table"><thead><tr><th>Month</th><th>Games</th><th>ATS</th><th>Win %</th><th>Average CLV</th><th>Beat Close</th></tr></thead><tbody>${monthlyRows || `<tr><td colspan="6" class="cbb-empty">The ledger will populate after the first qualified CBB decision reaches final status.</td></tr>`}</tbody></table></div></div>
        <div class="cbb-tracking-table-section"><div class="cbb-tracking-table-title">Season-to-Date · Every Signal and Testing Key</div><div class="cbb-table-wrap"><table class="cbb-table"><thead><tr><th>Signal / Key</th><th>Games</th><th>Record</th><th>Win %</th><th>Average CLV</th><th>Beat Close</th><th>Confidence</th></tr></thead><tbody>${signalRows || `<tr><td colspan="7" class="cbb-empty">Signal records will populate prospectively as qualified games are graded.</td></tr>`}</tbody></table></div></div>
      </section>
    `;
  }

  function trendCard(card, sport) {
    const stateName = card.state || "developing";
    const live = state.data?.varianceTracker?.summary?.[sport]?.systems?.[card.id];
    return `<article class="cbb-panel cbb-trend-card is-${escapeHtml(stateName)}"><div class="cbb-label">${escapeHtml(card.market)} · ${escapeHtml(card.family || "situational")}</div><h3>${escapeHtml(card.name)}</h3><p>${escapeHtml(card.description)}</p><div class="cbb-trend-rate">${pct(card.hit_rate)}</div><strong>${integer(card.wins)}–${integer(card.losses)}${card.pushes ? `–${integer(card.pushes)}` : ""} · ${number(card.roi_pct_at_minus_110,1,true)}% ROI</strong><small>${integer(card.decisions)} historical decisions · ${escapeHtml(humanize(stateName))}</small>${live ? `<small><b>LIVE PROSPECTIVE</b> · ${integer(live.wins)}–${integer(live.losses)}–${integer(live.pushes)} · ${integer(live.pending)} pending</small>` : ""}<small>${escapeHtml(card.source_note || "THI historical warehouse")}</small></article>`;
  }

  function trendSection(title, note, cards, stateName, sport) {
    return `<section class="cbb-trend-section"><div class="cbb-section-head"><div><div class="cbb-label">Evidence registry</div><h2 class="cbb-section-title">${escapeHtml(title)}</h2></div><div class="cbb-section-note">${escapeHtml(note)}</div></div>${cards.length ? `<div class="cbb-trends-grid">${cards.map(card => trendCard(card, sport)).join("")}</div>` : `<div class="cbb-panel cbb-trend-empty">No ${escapeHtml(stateName)} systems currently qualify.</div>`}</section>`;
  }

  function trendsMarkup(sport) {
    const lab = state.data?.trends || {}; const data = lab.sports?.[sport] || { cards:[] };
    const groups = data.sections || { verified:[], developing:data.cards || [], failed_hypothesis:[], source_pending:[] };
    const tracker = state.data?.varianceTracker || { frozen:[] }; const tracked = (tracker.frozen || []).filter(row => row.sport === sport).sort((a,b) => Number(b.result === "pending") - Number(a.result === "pending") || String(a.start_date || "").localeCompare(String(b.start_date || "")));
    const rlm = state.data?.rlmMonitor || { meta:{ status:"source_pending" }, sharp_line_moves:[], alerts:[] };
    const lineMoves = (rlm.sharp_line_moves || []).filter(row => row.sport === sport);
    const alerts = (rlm.alerts || []).filter(row => row.sport === sport);
    return `<div class="cbb-kicker">The Hammer Index · ${sport.toUpperCase()}</div><h1 class="page-title">THI Variance Lab</h1><p class="page-subtitle">Reproducible situational systems, frozen prospective tracking and synchronized market intelligence. Losing hypotheses remain visible.</p><div class="cbb-research-banner"><strong>Systems discipline</strong><span>${escapeHtml(lab.meta?.policy || "Historical research only.")}</span></div><div class="cbb-trends-summary"><strong>${integer(data.settled_games)}</strong><span>settled historical games examined</span></div>
      ${trendSection("Verified", "Large, profitable historical samples that clear THI's published evidence gate.", groups.verified || [], "verified", sport)}
      ${trendSection("Developing", "Promising or limited samples remain research observations.", groups.developing || [], "developing", sport)}
      ${trendSection("Failed hypotheses", "Popular angles that did not survive THI's own closing-line test.", groups.failed_hypothesis || [], "failed", sport)}
      <section class="cbb-trend-section"><div class="cbb-section-head"><div><div class="cbb-label">Forward evidence</div><h2 class="cbb-section-title">Prospective tracker</h2></div><div class="cbb-section-note">The first eligible pregame line is frozen and final scores automatically grade it.</div></div><div class="cbb-panel cbb-variance-ledger"><strong>${integer(tracked.length)} frozen qualifiers</strong>${tracked.slice(0,16).map(row => `<div><span>${escapeHtml(row.away_team)} ${matchupWord(row)} ${escapeHtml(row.home_team)}</span><b>${escapeHtml(humanize(row.system_id))}</b><small>${escapeHtml(row.result)}</small></div>`).join("")}${!tracked.length ? `<p>Qualifiers will appear automatically as markets become available.</p>` : ""}</div></section>
      <section class="cbb-trend-section"><div class="cbb-section-head"><div><div class="cbb-label">Free market intelligence</div><h2 class="cbb-section-title">Sharp Line Movement</h2></div><div class="cbb-section-note">Pinnacle spread movement from THI's first captured number. This is market context only and does not affect Model A.</div></div><div class="cbb-panel cbb-rlm-monitor"><div class="cbb-rlm-status is-${escapeHtml(rlm.meta?.sharp_line_status || "api_key_pending")}">${escapeHtml(humanize(rlm.meta?.sharp_line_status || "api_key_pending"))}</div>${lineMoves.map(row => `<div class="cbb-rlm-alert"><strong>${escapeHtml(row.away_team)} at ${escapeHtml(row.home_team)}</strong><span>Home spread ${number(row.opening_home_spread,1,true)} → ${number(row.current_home_spread,1,true)} · toward ${escapeHtml(row.movement_toward_team || humanize(row.movement_toward || "unknown"))}</span><b>${escapeHtml(row.key_number_crossed ? `Crossed ${row.key_number_crossed}` : humanize(row.severity || "move"))}</b></div>`).join("")}${!lineMoves.length ? `<p>${rlm.meta?.sharp_line_status === "monitoring" ? "No Pinnacle moves of 0.5 points or more are active." : "The free Pinnacle collector is ready and begins after the ODDS_API_KEY repository secret is configured."}</p>` : ""}</div></section>
      <section class="cbb-trend-section"><div class="cbb-section-head"><div><div class="cbb-label">Public splits contract</div><h2 class="cbb-section-title">Reverse Line Movement</h2></div><div class="cbb-section-note">RLM requires verified ticket percentages synchronized with a sharp-book move. Line movement alone is never labeled sharp money.</div></div><div class="cbb-panel cbb-rlm-monitor"><div class="cbb-rlm-status is-${escapeHtml(rlm.meta?.rlm_status || "public_splits_pending")}">${escapeHtml(humanize(rlm.meta?.rlm_status || "public_splits_pending"))}</div>${alerts.map(row => `<div class="cbb-rlm-alert"><strong>${escapeHtml(row.away_team)} at ${escapeHtml(row.home_team)}</strong><span>${pct(row.public_ticket_pct)} tickets on ${escapeHtml(row.public_side)} · ${number(row.line_delta,1,true)} toward ${escapeHtml(row.sharp_team)}</span><b>${escapeHtml(humanize(row.severity))}</b></div>`).join("")}${!alerts.length ? `<p>No RLM alerts. A verified public-splits source is still required, so THI is making no public-money claim.</p>` : ""}</div></section>
      <section class="cbb-trend-section"><div class="cbb-section-head"><div><div class="cbb-label">Data contracts</div><h2 class="cbb-section-title">Source pending</h2></div><div class="cbb-section-note">A missing feed is shown plainly and never converted into a synthetic signal.</div></div><div class="cbb-panel cbb-planned-trends">${(lab.source_backlog || []).map(row => `<div><strong>${escapeHtml(row.name)} <em>${escapeHtml(humanize(row.status || "source_pending"))}</em></strong><span>${escapeHtml(row.path)}</span></div>`).join("")}</div></section>`;
  }

  function renderTrendsLab() {
    const cbb = document.getElementById("view-cbb-variance");
    if (cbb) cbb.innerHTML = trendsMarkup("cbb");
  }

  function modelCard(kicker, label, value, note) {
    return `<article class="cbb-panel cbb-model-card"><div class="cbb-label">${escapeHtml(kicker)}</div><div class="cbb-model-sub">${escapeHtml(label)}</div><div class="cbb-model-value">${escapeHtml(value)}</div><div class="cbb-model-sub">${escapeHtml(note)}</div></article>`;
  }

  function trackingDecisionRow(row) {
    const start = new Date(row.start_date);
    const date = Number.isNaN(start.getTime()) ? "—" : new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "America/New_York" }).format(start);
    const result = String(row.result || "").toLowerCase();
    return `<tr><td class="cbb-number">${escapeHtml(date)}</td><td><strong>${escapeHtml(row.away_team)} ${matchupWord(row)} ${escapeHtml(row.home_team)}</strong></td><td class="cbb-team-name">${escapeHtml(row.pick_team)}</td><td class="cbb-number">${number(row.pregame_line,1,true)}</td><td class="cbb-number">${row.closing_line == null ? "—" : number(row.closing_line,1,true)}</td><td class="cbb-number">${row.clv == null ? "—" : number(row.clv,2,true)}</td><td class="cbb-number">${number(row.model_edge,1)} pts</td><td><span class="cbb-result cbb-result-${escapeHtml(result)}">${escapeHtml(result || "—")}</span></td><td class="cbb-number">${escapeHtml(row.final_score || "—")}</td></tr>`;
  }

  function humanize(value) {
    return value.replaceAll("_", " ").replace(/^./, letter => letter.toUpperCase()).replace("52 38 pct", "52.38% ");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount, { once: true });
  else mount();
})();
