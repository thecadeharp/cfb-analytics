(() => {
  "use strict";

  const VIEW_SELECTOR = "#view-projections";
  const CONTAINER_SELECTOR = "#projections-container";
  const ROW_SELECTOR =
    "#projections-container .projection-table tbody tr.game-row";
  const SUMMARY_SELECTOR = "#projection-summary";

  const FILTER_ID = "hammer-game-status-filters";
  const STYLE_ID = "hammer-game-status-filter-styles";
  const EMPTY_ID = "hammer-game-status-empty";
  const DESKTOP_DAY_CLASS = "hammer-day-divider-row";
  const MOBILE_DAY_CLASS = "hammer-mobile-day-divider";
  const PROJECTIONS_URL = "./data/projections.json";
  const EASTERN_TZ = "America/New_York";

  const MONTHS = [
    "JAN.", "FEB.", "MAR.", "APR.", "MAY", "JUN.",
    "JUL.", "AUG.", "SEP.", "OCT.", "NOV.", "DEC."
  ];

  let activeStatus = "all";
  let updateQueued = false;
  let projectionObserver = null;
  let rowClickFallbackInstalled = false;
  let projectionsLoadStarted = false;
  let projectionByGameId = new Map();


  // ==========================================================================
  // STYLES
  // ==========================================================================

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;

    const style = document.createElement("style");
    style.id = STYLE_ID;

    style.textContent = `
      #projection-summary {
        display: none !important;
      }

      .hammer-status-filter-wrap {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 20px;
        margin: 4px 0 16px;
        padding: 15px 17px;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        position: relative;
        z-index: 50;
        pointer-events: auto;
      }

      .hammer-status-filter-title {
        flex: 0 0 auto;
        color: var(--muted);
        font-family: var(--mono);
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 1.2px;
        text-transform: uppercase;
        white-space: nowrap;
      }

      .hammer-status-filter-buttons {
        display: grid;
        grid-template-columns: repeat(4, minmax(110px, 1fr));
        gap: 9px;
        width: min(100%, 620px);
        position: relative;
        z-index: 51;
        pointer-events: auto;
      }

      .hammer-status-filter-button {
        appearance: none;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        min-height: 40px;
        padding: 9px 15px;
        border: 1px solid var(--border);
        border-radius: 999px;
        background: #fff;
        color: var(--muted);
        font-family: var(--mono);
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.3px;
        white-space: nowrap;
        cursor: pointer;
        position: relative;
        z-index: 52;
        pointer-events: auto;
        transition:
          background 0.15s ease,
          border-color 0.15s ease,
          color 0.15s ease,
          transform 0.15s ease;
      }

      .hammer-status-filter-button:hover {
        color: var(--text);
        border-color: var(--border-dark);
        transform: translateY(-1px);
      }

      .hammer-status-filter-button.is-active {
        background: var(--text);
        border-color: var(--text);
        color: #fff;
      }

      .hammer-status-filter-button[data-status="live"] {
        color: #b42318;
        border-color: #e6b7b3;
        background: #fffafa;
      }

      .hammer-status-filter-button[data-status="live"]:hover {
        border-color: #d87e77;
      }

      .hammer-status-filter-button[data-status="live"].is-active {
        background: #b42318;
        border-color: #b42318;
        color: #fff;
      }

      .hammer-status-live-dot {
        width: 7px;
        height: 7px;
        flex: 0 0 7px;
        border-radius: 50%;
        background: currentColor;
        pointer-events: none;
      }

      .hammer-status-count {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 20px;
        height: 20px;
        padding: 0 5px;
        border-radius: 999px;
        background: rgba(0, 0, 0, 0.055);
        font-size: 9px;
        line-height: 1;
        pointer-events: none;
      }

      .hammer-status-filter-button.is-active .hammer-status-count {
        background: rgba(255, 255, 255, 0.16);
      }

      .hammer-status-filter-button[data-status="live"] .hammer-status-count {
        background: rgba(180, 35, 24, 0.07);
      }

      .hammer-status-filter-button[data-status="live"].is-active .hammer-status-count {
        background: rgba(255, 255, 255, 0.17);
      }

      .hammer-status-empty {
        display: none;
        margin: 0 0 14px;
        padding: 28px 18px;
        text-align: center;
        color: var(--muted);
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        font-size: 12px;
      }

      /* ================================================================
         DAY SLATE DIVIDERS
         Full-width date bars inside the board. They are presentation only.
      ================================================================ */

      .${DESKTOP_DAY_CLASS} td {
        padding: 0 !important;
        border: 0 !important;
        background: var(--bg) !important;
      }

      .${DESKTOP_DAY_CLASS}:hover {
        background: transparent !important;
      }

      .hammer-day-divider-box {
        display: flex;
        align-items: center;
        min-height: 46px;
        margin: 12px 0 8px;
        padding: 0 16px;
        background: #fff8dc;
        border: 1px solid #e7c967;
        border-radius: 9px;
        color: #5f4900;
        font-family: var(--mono);
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 0.7px;
        line-height: 1.2;
        text-transform: uppercase;
      }

      .hammer-mobile-day-divider {
        display: none;
      }

      @media (max-width: 900px) {
        .hammer-status-filter-wrap {
          align-items: flex-start;
          flex-direction: column;
        }

        .hammer-status-filter-buttons {
          width: 100%;
        }
      }

      @media (max-width: 600px) {
        .hammer-status-filter-wrap {
          gap: 10px;
          margin-bottom: 14px;
          padding: 12px;
        }

        .hammer-status-filter-buttons {
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 8px;
        }

        .hammer-status-filter-button {
          width: 100%;
          min-height: 42px;
          padding: 9px 10px;
          font-size: 10px;
        }

        .hammer-mobile-day-divider {
          display: flex;
          align-items: center;
          min-height: 46px;
          padding: 0 14px;
          background: #fff8dc;
          border: 1px solid #e7c967;
          border-radius: 9px;
          color: #5f4900;
          font-family: var(--mono);
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0.55px;
          line-height: 1.25;
          text-transform: uppercase;
        }
      }
    `;

    document.head.appendChild(style);
  }


  // ==========================================================================
  // GAME HELPERS
  // ==========================================================================

  function projectionRows() {
    return Array.from(document.querySelectorAll(ROW_SELECTOR));
  }

  function gameIdFromRow(row) {
    if (!row) return "";
    if (row.dataset.gameId) return String(row.dataset.gameId);

    const onclick = String(row.getAttribute("onclick") || "");
    const match = onclick.match(/openMatchup\(\s*['"]([^'"]+)['"]\s*\)/);
    return match?.[1] ? String(match[1]) : "";
  }

  function rowStatus(row) {
    if (!row) return "upcoming";

    if (
      row.classList.contains("completed-row") ||
      row.classList.contains("hammer-final-untracked-row") ||
      row.dataset.hammerGameState === "final"
    ) {
      return "final";
    }

    if (
      row.classList.contains("hammer-live-row") ||
      row.dataset.hammerGameState === "live"
    ) {
      return "live";
    }

    return "upcoming";
  }

  function statusPriority(status) {
    if (status === "upcoming") return 0;
    if (status === "live") return 1;
    return 2;
  }

  function loadProjectionMetadata() {
    if (projectionsLoadStarted) return;
    projectionsLoadStarted = true;

    fetch(`${PROJECTIONS_URL}?v=${Date.now()}`, { cache: "no-store" })
      .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then(payload => {
        const games = Array.isArray(payload?.games) ? payload.games : [];
        projectionByGameId = new Map(
          games
            .filter(game => game?.game_id !== null && game?.game_id !== undefined)
            .map(game => [String(game.game_id), game])
        );
        scheduleUpdate();
      })
      .catch(error => {
        console.warn("Slate day metadata unavailable; using row date fallback.", error);
      });
  }

  function fallbackRowDate(row) {
    const cell = row?.querySelector(".matchup-cell");
    if (!cell) return null;

    const text = String(cell.textContent || "").replace(/\s+/g, " ");
    const match = text.match(
      /\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(\d{1,2}),\s+(\d{1,2}):(\d{2})\s*(AM|PM)\b/i
    );

    if (!match) return null;

    const monthNames = {
      jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5,
      jul: 6, aug: 7, sep: 8, sept: 8, oct: 9, nov: 10, dec: 11
    };

    const month = monthNames[match[1].toLowerCase()];
    let hour = Number(match[3]);
    const minute = Number(match[4]);
    const ampm = match[5].toUpperCase();

    if (ampm === "PM" && hour !== 12) hour += 12;
    if (ampm === "AM" && hour === 12) hour = 0;

    const year = new Date().getFullYear();
    return new Date(year, month, Number(match[2]), hour, minute);
  }

  function rowDate(row) {
    const gameId = gameIdFromRow(row);
    const startDate = projectionByGameId.get(gameId)?.start_date;

    if (startDate) {
      const date = new Date(startDate);
      if (!Number.isNaN(date.getTime())) return date;
    }

    return fallbackRowDate(row);
  }

  function rowTime(row) {
    const date = rowDate(row);
    return date ? date.getTime() : Number.MAX_SAFE_INTEGER;
  }

  function dayKey(row) {
    const date = rowDate(row);
    if (!date) return "unknown";

    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: EASTERN_TZ,
      year: "numeric",
      month: "2-digit",
      day: "2-digit"
    }).formatToParts(date);

    const values = Object.fromEntries(
      parts.filter(part => part.type !== "literal").map(part => [part.type, part.value])
    );

    return `${values.year}-${values.month}-${values.day}`;
  }

  function dayLabel(row) {
    const date = rowDate(row);
    if (!date) return "DATE TBD";

    const weekday = new Intl.DateTimeFormat("en-US", {
      timeZone: EASTERN_TZ,
      weekday: "long"
    }).format(date).toUpperCase();

    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: EASTERN_TZ,
      month: "numeric",
      day: "numeric"
    }).formatToParts(date);

    const month = Number(parts.find(part => part.type === "month")?.value) - 1;
    const day = Number(parts.find(part => part.type === "day")?.value);

    return `${weekday} — ${MONTHS[month] || ""} ${day}`.trim();
  }


  // ==========================================================================
  // STABLE PROJECTION ROW CLICK HANDLER
  //
  // Day grouping reparents rows inside the same tbody. The original inline
  // onclick remains in the markup, but this delegated handler guarantees that
  // the matchup interaction survives any presentation-layer row movement.
  // Team-name clicks are intentionally left alone so dossier navigation keeps
  // working exactly as before.
  // ==========================================================================

  function installProjectionRowClickFallback() {
    if (rowClickFallbackInstalled) return;

    const container = document.querySelector(CONTAINER_SELECTOR);
    if (!container) {
      setTimeout(installProjectionRowClickFallback, 100);
      return;
    }

    rowClickFallbackInstalled = true;

    container.addEventListener(
      "click",
      event => {
        const row = event.target.closest("tr.game-row");
        if (!row || !container.contains(row)) return;

        // Preserve team-name dossier clicks and any future interactive controls.
        if (
          event.target.closest(
            ".team-name, a, button, input, select, textarea, [role='button']"
          )
        ) {
          return;
        }

        const gameId = gameIdFromRow(row);
        if (!gameId) return;

        const opener =
          typeof window.openMatchup === "function"
            ? window.openMatchup
            : (typeof openMatchup === "function" ? openMatchup : null);

        if (!opener) return;

        // We handle the click here so the old inline onclick cannot double-fire.
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        opener(gameId);
      },
      true
    );
  }


  // ==========================================================================
  // FILTER COUNTS + UI
  // ==========================================================================

  function statusCounts() {
    const counts = { all: 0, upcoming: 0, live: 0, final: 0 };

    projectionRows().forEach(row => {
      const status = rowStatus(row);
      counts.all += 1;
      counts[status] += 1;
    });

    return counts;
  }

  function ensureFilterUI() {
    const tableCard = document.querySelector(`${VIEW_SELECTOR} .table-card`);
    if (!tableCard) return null;

    let wrapper = document.getElementById(FILTER_ID);
    if (wrapper) return wrapper;

    wrapper = document.createElement("div");
    wrapper.id = FILTER_ID;
    wrapper.className = "hammer-status-filter-wrap";

    wrapper.innerHTML = `
      <div class="hammer-status-filter-title">Game Status</div>
      <div class="hammer-status-filter-buttons">
        <button type="button" class="hammer-status-filter-button is-active" data-status="all" aria-pressed="true">
          <span>All Games</span>
          <span class="hammer-status-count" data-count-for="all">0</span>
        </button>
        <button type="button" class="hammer-status-filter-button" data-status="upcoming" aria-pressed="false">
          <span>Upcoming</span>
          <span class="hammer-status-count" data-count-for="upcoming">0</span>
        </button>
        <button type="button" class="hammer-status-filter-button" data-status="live" aria-pressed="false">
          <span class="hammer-status-live-dot" aria-hidden="true"></span>
          <span>Live</span>
          <span class="hammer-status-count" data-count-for="live">0</span>
        </button>
        <button type="button" class="hammer-status-filter-button" data-status="final" aria-pressed="false">
          <span>Final</span>
          <span class="hammer-status-count" data-count-for="final">0</span>
        </button>
      </div>
    `;

    tableCard.insertAdjacentElement("beforebegin", wrapper);

    wrapper.addEventListener("click", event => {
      const button = event.target.closest(".hammer-status-filter-button");
      if (!button) return;
      event.preventDefault();
      selectStatus(button.dataset.status);
    });

    return wrapper;
  }

  function updateFilterUI() {
    const wrapper = ensureFilterUI();
    if (!wrapper) return;

    const counts = statusCounts();

    ["all", "upcoming", "live", "final"].forEach(status => {
      const button = wrapper.querySelector(
        `.hammer-status-filter-button[data-status="${status}"]`
      );
      const count = wrapper.querySelector(`[data-count-for="${status}"]`);

      if (count) count.textContent = String(counts[status]);

      if (button) {
        const active = activeStatus === status;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      }
    });
  }

  function selectStatus(status) {
    if (!["all", "upcoming", "live", "final"].includes(status)) return;

    activeStatus = status;
    updateFilterUI();
    applyDesktopFilter();
    applyMobileFilter();
    syncDesktopDividerVisibility();
    syncMobileDayDividers();
    updateEmptyState();
  }


  // ==========================================================================
  // SLATE ORDER + DAY GROUPING
  // ==========================================================================

  function sortRowsForSlate(rows) {
    return [...rows].sort((a, b) => {
      const statusA = rowStatus(a);
      const statusB = rowStatus(b);
      const priorityDifference = statusPriority(statusA) - statusPriority(statusB);
      if (priorityDifference !== 0) return priorityDifference;

      const timeDifference = rowTime(a) - rowTime(b);
      if (timeDifference !== 0) return timeDifference;

      return gameIdFromRow(a).localeCompare(gameIdFromRow(b));
    });
  }

  function pauseObserver(callback) {
    const container = document.querySelector(CONTAINER_SELECTOR);

    if (projectionObserver) projectionObserver.disconnect();

    try {
      callback();
    } finally {
      if (projectionObserver && container) {
        projectionObserver.observe(container, {
          childList: true,
          subtree: true
        });
      }
    }
  }

  function rebuildDesktopDayGroups() {
    const tbody = document.querySelector(
      `${CONTAINER_SELECTOR} .projection-table tbody`
    );
    if (!tbody) return;

    const rows = projectionRows();
    if (!rows.length) return;

    const desired = sortRowsForSlate(rows);

    pauseObserver(() => {
      tbody.querySelectorAll(`.${DESKTOP_DAY_CLASS}`).forEach(divider => divider.remove());

      desired.forEach(row => tbody.appendChild(row));

      let previousGroupKey = null;

      desired.forEach(row => {
        const groupKey = `${rowStatus(row)}|${dayKey(row)}`;
        if (groupKey === previousGroupKey) return;
        previousGroupKey = groupKey;

        const divider = document.createElement("tr");
        divider.className = DESKTOP_DAY_CLASS;
        divider.dataset.hammerStatus = rowStatus(row);
        divider.dataset.hammerDayKey = dayKey(row);

        const cell = document.createElement("td");
        cell.colSpan = 7;

        const box = document.createElement("div");
        box.className = "hammer-day-divider-box";
        box.textContent = dayLabel(row);

        cell.appendChild(box);
        divider.appendChild(cell);
        tbody.insertBefore(divider, row);
      });
    });
  }

  function syncDesktopDividerVisibility() {
    document.querySelectorAll(`.${DESKTOP_DAY_CLASS}`).forEach(divider => {
      let sibling = divider.nextElementSibling;
      let hasVisibleGame = false;

      while (sibling && !sibling.classList.contains(DESKTOP_DAY_CLASS)) {
        if (
          sibling.classList.contains("game-row") &&
          sibling.style.display !== "none" &&
          !sibling.hidden
        ) {
          hasVisibleGame = true;
          break;
        }
        sibling = sibling.nextElementSibling;
      }

      divider.style.display = hasVisibleGame ? "" : "none";
    });
  }

  function syncMobileDayDividers() {
    const host = document.getElementById("mobile-projection-cards");
    if (!host) return;

    host.querySelectorAll(`.${MOBILE_DAY_CLASS}`).forEach(divider => divider.remove());

    const rows = projectionRows();
    const cards = Array.from(host.querySelectorAll(".mobile-projection-card"));
    if (!rows.length || rows.length !== cards.length) return;

    let previousGroupKey = null;

    rows.forEach((row, index) => {
      const card = cards[index];
      const groupKey = `${rowStatus(row)}|${dayKey(row)}`;

      if (groupKey !== previousGroupKey) {
        previousGroupKey = groupKey;

        const divider = document.createElement("div");
        divider.className = MOBILE_DAY_CLASS;
        divider.dataset.hammerStatus = rowStatus(row);
        divider.dataset.hammerDayKey = dayKey(row);
        divider.textContent = dayLabel(row);
        host.insertBefore(divider, card);
      }
    });

    host.querySelectorAll(`.${MOBILE_DAY_CLASS}`).forEach(divider => {
      let sibling = divider.nextElementSibling;
      let hasVisibleCard = false;

      while (sibling && !sibling.classList.contains(MOBILE_DAY_CLASS)) {
        if (
          sibling.classList.contains("mobile-projection-card") &&
          sibling.style.display !== "none" &&
          !sibling.hidden
        ) {
          hasVisibleCard = true;
          break;
        }
        sibling = sibling.nextElementSibling;
      }

      divider.style.display = hasVisibleCard ? "" : "none";
    });
  }


  // ==========================================================================
  // FILTER ROWS
  // ==========================================================================

  function applyDesktopFilter() {
    projectionRows().forEach(row => {
      const status = rowStatus(row);
      const visible = activeStatus === "all" || status === activeStatus;
      row.hidden = !visible;
      row.style.display = visible ? "" : "none";
    });
  }

  function applyMobileFilter() {
    const sourceRows = projectionRows();
    const cards = Array.from(document.querySelectorAll(".mobile-projection-card"));

    cards.forEach((card, index) => {
      const sourceRow = sourceRows[index];
      if (!sourceRow) return;

      const status = rowStatus(sourceRow);
      const visible = activeStatus === "all" || status === activeStatus;
      card.hidden = !visible;
      card.style.display = visible ? "" : "none";
    });
  }


  // ==========================================================================
  // BRAND TERMINOLOGY
  // ==========================================================================

  function replaceExactText(selector, replacements) {
    document.querySelectorAll(selector).forEach(element => {
      const current = String(element.textContent || "").trim();
      if (Object.prototype.hasOwnProperty.call(replacements, current)) {
        element.textContent = replacements[current];
      }
    });
  }

  function applyThiTerminology() {
    replaceExactText(
      "#projections-container .projection-table thead th",
      {
        "Our Line": "THI Spread",
        "Total": "THI Total"
      }
    );

    replaceExactText(
      "#view-projections .line-secondary",
      {
        "Model total": "THI Total",
        "Frozen public line": "Frozen THI spread"
      }
    );

    replaceExactText(
      "#mobile-projection-cards .mobile-card-label",
      {
        "FAIR LINE": "THI SPREAD",
        "FROZEN LINE": "FROZEN THI SPREAD",
        "PROJECTED TOTAL": "THI TOTAL"
      }
    );

    replaceExactText(
      "#view-matchup .analysis-label",
      {
        "Fair Line": "THI Spread",
        "Model Total": "THI Total"
      }
    );
  }


  // ==========================================================================
  // EMPTY STATE + OLD SUMMARY + ET LABELS
  // ==========================================================================

  function ensureEmptyState() {
    let empty = document.getElementById(EMPTY_ID);
    if (empty) return empty;

    const tableCard = document.querySelector(`${VIEW_SELECTOR} .table-card`);
    if (!tableCard) return null;

    empty = document.createElement("div");
    empty.id = EMPTY_ID;
    empty.className = "hammer-status-empty";
    tableCard.insertAdjacentElement("beforebegin", empty);
    return empty;
  }

  function updateEmptyState() {
    const empty = ensureEmptyState();
    if (!empty) return;

    const counts = statusCounts();
    if (activeStatus === "all" || counts[activeStatus] > 0) {
      empty.style.display = "none";
      return;
    }

    const labels = {
      upcoming: "upcoming games",
      live: "live games",
      final: "final games"
    };

    empty.textContent = `No ${labels[activeStatus]} are available in this week.`;
    empty.style.display = "block";
  }

  function hideOldSummary() {
    const summary = document.querySelector(SUMMARY_SELECTOR);
    if (summary) summary.style.display = "none";
  }

  function addEasternTimeLabels() {
    projectionRows().forEach(row => {
      const targets = row.querySelectorAll(".matchup-cell, .team-meta");

      targets.forEach(target => {
        const walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT);
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);

        nodes.forEach(node => {
          const original = String(node.nodeValue ?? "");
          const updated = original.replace(
            /(\b\d{1,2}:\d{2}\s*(?:AM|PM)\b)(?!\s*ET\b)/gi,
            "$1 ET"
          );
          if (updated !== original) node.nodeValue = updated;
        });
      });
    });
  }


  // ==========================================================================
  // UPDATE
  // ==========================================================================

  function updateEverything() {
    installStyles();
    hideOldSummary();
    ensureFilterUI();
    updateFilterUI();

    addEasternTimeLabels();
    rebuildDesktopDayGroups();
    applyThiTerminology();

    applyDesktopFilter();
    applyMobileFilter();
    syncDesktopDividerVisibility();
    syncMobileDayDividers();

    updateEmptyState();
  }

  function scheduleUpdate() {
    if (updateQueued) return;
    updateQueued = true;

    requestAnimationFrame(() => {
      updateQueued = false;
      updateEverything();
    });
  }


  // ==========================================================================
  // OBSERVER
  // ==========================================================================

  function installProjectionObserver() {
    const container = document.querySelector(CONTAINER_SELECTOR);

    if (!container) {
      setTimeout(installProjectionObserver, 100);
      return;
    }

    if (projectionObserver) return;

    projectionObserver = new MutationObserver(() => {
      scheduleUpdate();
    });

    projectionObserver.observe(container, {
      childList: true,
      subtree: true
    });
  }


  // ==========================================================================
  // START
  // ==========================================================================

  function start() {
    installStyles();
    hideOldSummary();
    ensureFilterUI();
    installProjectionRowClickFallback();
    loadProjectionMetadata();
    installProjectionObserver();
    updateEverything();

    window.addEventListener("hammer:data-ready", scheduleUpdate);
    window.addEventListener("resize", scheduleUpdate);

    [250, 750, 1500, 3000].forEach(delay => {
      setTimeout(scheduleUpdate, delay);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
