(() => {
  "use strict";

  const RESULTS_URL = "./data/results.json";
  const BOARD_SELECTOR = "#projections-container";
  const ROW_SELECTOR = "#projections-container .projection-table tbody tr.game-row";
  const STYLE_ID = "thi-final-board-sync-styles";

  let resultIndex = null;
  let boardObserver = null;
  let applyQueued = false;

  const ALIASES = new Map(Object.entries({
    "army west point": "army",
    "army black knights": "army",
    "southern mississippi": "southern miss",
    "ga southern": "georgia southern",
    "georgia southern university": "georgia southern",
    "mississippi st": "mississippi state",
    "miss st": "mississippi state",
    "middle tennessee state": "middle tennessee",
    "middle tenn": "middle tennessee",
    "sam houston state": "sam houston",
    "sam houston st": "sam houston",
    "bowling green state": "bowling green",
    "nc state": "north carolina state",
    "north carolina st": "north carolina state",
    "miami fl": "miami",
    "miami florida": "miami",
    "connecticut": "uconn",
    "uconn huskies": "uconn",
    "utsa roadrunners": "utsa",
    "ucf knights": "ucf",
    "ole miss rebels": "ole miss",
    "lsu tigers": "lsu"
  }));

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;

    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      .hammer-final-untracked-row .hammer-final-score,
      .mobile-projection-card.hammer-final-untracked-card .hammer-final-score {
        margin-left:auto;
        padding-left:10px;
        color:var(--text);
        font-family:var(--mono);
        font-size:13px;
        font-weight:800;
        line-height:1;
      }

      .hammer-final-untracked-row .hammer-final-not-graded,
      .mobile-projection-card.hammer-final-untracked-card .hammer-final-not-graded {
        color:var(--muted);
        font-family:var(--mono);
        font-size:9px;
        font-weight:700;
        letter-spacing:.04em;
        text-transform:uppercase;
      }
    `;
    document.head.appendChild(style);
  }

  function normalizeName(value) {
    let text = String(value || "")
      .toLowerCase()
      .replace(/&/g, " and ")
      .replace(/\([^)]*\)\s*$/g, "")
      .replace(/\buniversity of\b/g, "")
      .replace(/\buniversity\b/g, "")
      .replace(/\bcollege\b/g, "")
      .replace(/\./g, "")
      .replace(/[^a-z0-9]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();

    if (ALIASES.has(text)) text = ALIASES.get(text);
    return text;
  }

  function teamPairKey(away, home) {
    return `${normalizeName(away)}|${normalizeName(home)}`;
  }

  function weekTeamPairKey(week, away, home) {
    const n = Number(week);
    const w = Number.isFinite(n) ? String(n) : "";
    return `${w}|${teamPairKey(away, home)}`;
  }

  function buildResultIndex(payload) {
    const byId = new Map();
    const byWeekTeams = new Map();
    const byTeams = new Map();

    (Array.isArray(payload?.games) ? payload.games : []).forEach(game => {
      if (!game) return;

      const isFinal =
        String(game.game_state || "").toLowerCase() === "final" ||
        String(game.status || "").toLowerCase() === "completed" ||
        String(game.final_message || "").toUpperCase().includes("FINAL");

      if (!isFinal) return;

      const id = String(game.game_id ?? "").trim();
      if (id) byId.set(id, game);

      const away = game.away_team ?? game.away?.team ?? game.away;
      const home = game.home_team ?? game.home?.team ?? game.home;
      if (!away || !home) return;

      byWeekTeams.set(weekTeamPairKey(game.week, away, home), game);

      const pair = teamPairKey(away, home);
      if (!byTeams.has(pair)) byTeams.set(pair, game);
    });

    return { byId, byWeekTeams, byTeams };
  }

  function projectionList() {
    try {
      if (typeof projections !== "undefined" && Array.isArray(projections)) {
        return projections;
      }
    } catch (_) {}

    try {
      if (
        typeof projectionsData !== "undefined" &&
        Array.isArray(projectionsData?.games)
      ) {
        return projectionsData.games;
      }
    } catch (_) {}

    return [];
  }

  function projectionForRow(row) {
    const onclick = row?.getAttribute("onclick") || "";
    const idMatch = onclick.match(/openMatchup\(['"]([^'"]+)['"]\)/);
    const id = idMatch?.[1] ? String(idMatch[1]) : "";
    const games = projectionList();

    if (id) {
      const found = games.find(game => String(game?.game_id ?? "") === id);
      if (found) return found;
    }

    const names = Array.from(
      row.querySelectorAll(".matchup-cell .team-name")
    ).map(el => String(el.textContent || "").trim());

    if (names.length < 2) return null;

    return games.find(game => {
      const away = game?.away?.team ?? game?.away_team;
      const home = game?.home?.team ?? game?.home_team;
      return (
        normalizeName(away) === normalizeName(names[0]) &&
        normalizeName(home) === normalizeName(names[1])
      );
    }) ?? null;
  }

  function resultForProjection(game) {
    if (!game || !resultIndex) return null;

    const id = String(game?.game_id ?? "").trim();
    if (id && resultIndex.byId.has(id)) return resultIndex.byId.get(id);

    const away = game?.away?.team ?? game?.away_team;
    const home = game?.home?.team ?? game?.home_team;

    const weekKey = weekTeamPairKey(game?.week, away, home);
    if (resultIndex.byWeekTeams.has(weekKey)) {
      return resultIndex.byWeekTeams.get(weekKey);
    }

    return resultIndex.byTeams.get(teamPairKey(away, home)) ?? null;
  }

  function scoreText(value) {
    const n = Number(value);
    return Number.isFinite(n) ? String(n) : "—";
  }

  function ensureScore(teamLine, value) {
    if (!teamLine) return;

    let score = teamLine.querySelector(":scope > .hammer-final-score");
    if (!score) {
      score = document.createElement("span");
      score.className = "hammer-final-score";
      teamLine.appendChild(score);
    }

    score.textContent = scoreText(value);
  }

  function markDesktopRow(row, result) {
    if (row.classList.contains("completed-row")) return false;

    const lines = row.querySelectorAll(".matchup-cell .team-line");
    if (lines.length < 2) return false;

    row.classList.add("hammer-final-untracked-row");
    row.dataset.hammerGameState = "final";
    row.dataset.hammerFinalSource = String(result?.source || "results");

    ensureScore(lines[0], result?.away_points);
    ensureScore(lines[1], result?.home_points);

    const cell = row.querySelector(".matchup-cell");
    if (!cell) return true;

    let meta = Array.from(
      cell.querySelectorAll(":scope > .team-meta")
    ).at(-1);

    if (!meta) {
      meta = document.createElement("div");
      meta.className = "team-meta";
      meta.style.marginTop = "5px";
      cell.appendChild(meta);
    }

    meta.classList.add("hammer-final-not-graded");
    meta.textContent = "FINAL · NOT GRADED";

    return true;
  }

  function syncMobileCards() {
    const cards = Array.from(
      document.querySelectorAll("#mobile-projection-cards .mobile-projection-card")
    );

    cards.forEach(card => {
      const names = Array.from(
        card.querySelectorAll(".mobile-card-matchup .team-name")
      ).map(el => String(el.textContent || "").trim());

      if (names.length < 2) return;

      const result = resultIndex?.byTeams.get(
        teamPairKey(names[0], names[1])
      );

      if (!result) return;

      card.classList.add("hammer-final-untracked-card");
      card.dataset.hammerGameState = "final";

      const lines = card.querySelectorAll(".mobile-card-matchup .team-line");
      if (lines.length >= 2) {
        ensureScore(lines[0], result.away_points);
        ensureScore(lines[1], result.home_points);
      }

      const matchup = card.querySelector(".mobile-card-matchup");
      if (!matchup) return;

      let note = matchup.querySelector(".hammer-final-not-graded");
      if (!note) {
        note = document.createElement("div");
        note.className = "hammer-final-not-graded";
        note.style.marginTop = "7px";
        matchup.appendChild(note);
      }
      note.textContent = "FINAL · NOT GRADED";
    });
  }

  function applyFinals() {
    if (!resultIndex) return;

    let changed = false;

    document.querySelectorAll(ROW_SELECTOR).forEach(row => {
      if (row.classList.contains("completed-row")) return;

      const projection = projectionForRow(row);
      const result = resultForProjection(projection);
      if (!result) return;

      if (markDesktopRow(row, result)) changed = true;
    });

    syncMobileCards();

    if (changed) {
      window.dispatchEvent(new CustomEvent("hammer:raw-finals-synced"));
    }
  }

  function scheduleApply() {
    if (applyQueued) return;
    applyQueued = true;

    requestAnimationFrame(() => {
      applyQueued = false;
      applyFinals();
    });
  }

  async function loadResults() {
    try {
      const response = await fetch(`${RESULTS_URL}?v=${Date.now()}`, {
        cache: "no-cache"
      });

      if (!response.ok) {
        throw new Error(`${RESULTS_URL} returned HTTP ${response.status}`);
      }

      const payload = await response.json();
      resultIndex = buildResultIndex(payload);
      scheduleApply();
    } catch (error) {
      console.warn("THI raw-final board sync could not refresh:", error);
    }
  }

  function installBoardObserver() {
    if (boardObserver) return;

    const container = document.querySelector(BOARD_SELECTOR);
    if (!container) {
      setTimeout(installBoardObserver, 150);
      return;
    }

    boardObserver = new MutationObserver(mutations => {
      const structureChanged = mutations.some(mutation =>
        Array.from(mutation.addedNodes || []).some(node => {
          if (!(node instanceof Element)) return false;
          if (node.matches?.("tr.game-row, .projection-table")) return true;
          return Boolean(node.querySelector?.("tr.game-row"));
        })
      );

      if (structureChanged) scheduleApply();
    });

    boardObserver.observe(container, {
      childList: true,
      subtree: true
    });
  }

  function start() {
    installStyles();
    installBoardObserver();
    loadResults();

    window.addEventListener("hammer:data-ready", loadResults);

    // Upstream settlement runs every five minutes. A two-minute browser refresh
    // is enough to surface late finals without adding heavy page work.
    window.setInterval(loadResults, 120000);

    [250, 750, 1500, 3000].forEach(delay => {
      setTimeout(scheduleApply, delay);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
