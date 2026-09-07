(() => {
  "use strict";

  // ==========================================================================
  // THE HAMMER INDEX — STATUS CONTROLS
  //
  // Single owner for:
  //   • All / Upcoming / Live / Final filters
  //   • Upcoming → Live → Final ordering
  //   • Date dividers
  //
  // IMPORTANT:
  //   sort-tables.js owns score/final decoration only.
  //   This file owns board ordering/filtering only.
  //   No MutationObserver is used here, which prevents the prior flashing loop.
  // ==========================================================================

  const CONTAINER_ID = "projections-container";
  const VIEW_ID = "view-projections";
  const FILTER_ID = "hammer-game-status-filters";
  const STYLE_ID = "hammer-game-status-filter-styles";
  const EMPTY_ID = "hammer-game-status-empty";
  const DIVIDER_CLASS = "hammer-day-divider-row";
  const PROJECTIONS_URL = "./data/projections.json";
  const EASTERN_TZ = "America/New_York";

  const MONTHS = [
    "JAN.", "FEB.", "MAR.", "APR.", "MAY", "JUN.",
    "JUL.", "AUG.", "SEP.", "OCT.", "NOV.", "DEC."
  ];

  let activeStatus = "all";
  let projectionByGameId = new Map();
  let lastBoardSignature = "";
  let pollTimer = null;

  // --------------------------------------------------------------------------
  // BASIC HELPERS
  // --------------------------------------------------------------------------

  function container() {
    return document.getElementById(CONTAINER_ID);
  }

  function table() {
    return container()?.querySelector(".projection-table") ?? null;
  }

  function tbody() {
    return table()?.querySelector("tbody") ?? null;
  }

  function rows() {
    return Array.from(
      container()?.querySelectorAll(".projection-table tbody tr.game-row") ?? []
    );
  }

  function gameIdFromRow(row) {
    if (!row) return "";

    if (row.dataset.gameId) {
      return String(row.dataset.gameId);
    }

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

  function cleanText(value) {
    return String(value ?? "").replace(/\s+/g, " ").trim();
  }

  // --------------------------------------------------------------------------
  // DATE HELPERS
  // --------------------------------------------------------------------------

  function fallbackRowDate(row) {
    const cell = row?.querySelector(".matchup-cell");
    if (!cell) return null;

    const text = cleanText(cell.textContent);

    const match = text.match(
      /\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(\d{1,2}),\s+(\d{1,2}):(\d{2})\s*(AM|PM)\b/i
    );

    if (!match) return null;

    const monthMap = {
      jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5,
      jul: 6, aug: 7, sep: 8, sept: 8, oct: 9, nov: 10, dec: 11
    };

    const month = monthMap[match[1].toLowerCase()];
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
      if (!Number.isNaN(date.getTime())) {
        return date;
      }
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
      parts
        .filter(part => part.type !== "literal")
        .map(part => [part.type, part.value])
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

    const monthIndex =
      Number(parts.find(part => part.type === "month")?.value) - 1;

    const day =
      Number(parts.find(part => part.type === "day")?.value);

    return `${weekday} — ${MONTHS[monthIndex] || ""} ${day}`.trim();
  }

  // --------------------------------------------------------------------------
  // STYLES
  // --------------------------------------------------------------------------

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;

    const style = document.createElement("style");
    style.id = STYLE_ID;

    style.textContent = `
      #projection-summary {
        display: none !important;
      }

      .hammer-status-filter-wrap {
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:20px;
        margin:4px 0 16px;
        padding:15px 17px;
        background:var(--surface);
        border:1px solid var(--border);
        border-radius:var(--radius);
      }

      .hammer-status-filter-title {
        color:var(--muted);
        font-family:var(--mono);
        font-size:10px;
        font-weight:700;
        letter-spacing:1.2px;
        text-transform:uppercase;
        white-space:nowrap;
      }

      .hammer-status-filter-buttons {
        display:grid;
        grid-template-columns:repeat(4,minmax(110px,1fr));
        gap:9px;
        width:min(100%,620px);
      }

      .hammer-status-filter-button {
        appearance:none;
        display:inline-flex;
        align-items:center;
        justify-content:center;
        gap:8px;
        min-height:40px;
        padding:9px 15px;
        border:1px solid var(--border);
        border-radius:999px;
        background:#fff;
        color:var(--muted);
        font-family:var(--mono);
        font-size:10px;
        font-weight:700;
        cursor:pointer;
      }

      .hammer-status-filter-button:hover {
        color:var(--text);
        border-color:var(--border-dark);
      }

      .hammer-status-filter-button.is-active {
        background:var(--text);
        border-color:var(--text);
        color:#fff;
      }

      .hammer-status-filter-button[data-status="live"] {
        color:#b42318;
        border-color:#e6b7b3;
        background:#fffafa;
      }

      .hammer-status-filter-button[data-status="live"].is-active {
        background:#b42318;
        border-color:#b42318;
        color:#fff;
      }

      .hammer-status-live-dot {
        width:7px;
        height:7px;
        border-radius:50%;
        background:currentColor;
      }

      .hammer-status-count {
        display:inline-flex;
        align-items:center;
        justify-content:center;
        min-width:20px;
        height:20px;
        padding:0 5px;
        border-radius:999px;
        background:rgba(0,0,0,.055);
        font-size:9px;
        line-height:1;
      }

      .hammer-status-filter-button.is-active .hammer-status-count {
        background:rgba(255,255,255,.16);
      }

      .${DIVIDER_CLASS} td {
        padding:0 !important;
        border:0 !important;
        background:var(--bg) !important;
      }

      .${DIVIDER_CLASS}:hover {
        background:transparent !important;
      }

      .hammer-day-divider-box {
        display:flex;
        align-items:center;
        min-height:46px;
        margin:12px 0 8px;
        padding:0 16px;
        background:#fff8dc;
        border:1px solid #e7c967;
        border-radius:9px;
        color:#5f4900;
        font-family:var(--mono);
        font-size:13px;
        font-weight:700;
        letter-spacing:.7px;
        text-transform:uppercase;
      }

      .hammer-status-empty {
        display:none;
        margin:0 0 14px;
        padding:28px 18px;
        text-align:center;
        color:var(--muted);
        background:var(--surface);
        border:1px solid var(--border);
        border-radius:var(--radius);
        font-size:12px;
      }

      @media (max-width:900px) {
        .hammer-status-filter-wrap {
          align-items:flex-start;
          flex-direction:column;
        }

        .hammer-status-filter-buttons {
          width:100%;
        }
      }

      @media (max-width:600px) {
        .hammer-status-filter-buttons {
          grid-template-columns:repeat(2,minmax(0,1fr));
        }

        .hammer-status-filter-button {
          width:100%;
        }
      }
    `;

    document.head.appendChild(style);
  }

  // --------------------------------------------------------------------------
  // FILTER UI
  // --------------------------------------------------------------------------

  function ensureFilterUI() {
    const view = document.getElementById(VIEW_ID);
    const tableCard = view?.querySelector(".table-card");

    if (!tableCard) return null;

    let wrapper = document.getElementById(FILTER_ID);
    if (wrapper) return wrapper;

    wrapper = document.createElement("div");
    wrapper.id = FILTER_ID;
    wrapper.className = "hammer-status-filter-wrap";

    wrapper.innerHTML = `
      <div class="hammer-status-filter-title">Game Status</div>

      <div class="hammer-status-filter-buttons">
        <button type="button" class="hammer-status-filter-button is-active" data-status="all">
          <span>All Games</span>
          <span class="hammer-status-count" data-count-for="all">0</span>
        </button>

        <button type="button" class="hammer-status-filter-button" data-status="upcoming">
          <span>Upcoming</span>
          <span class="hammer-status-count" data-count-for="upcoming">0</span>
        </button>

        <button type="button" class="hammer-status-filter-button" data-status="live">
          <span class="hammer-status-live-dot"></span>
          <span>Live</span>
          <span class="hammer-status-count" data-count-for="live">0</span>
        </button>

        <button type="button" class="hammer-status-filter-button" data-status="final">
          <span>Final</span>
          <span class="hammer-status-count" data-count-for="final">0</span>
        </button>
      </div>
    `;

    tableCard.insertAdjacentElement("beforebegin", wrapper);

    wrapper.addEventListener("click", event => {
      const button = event.target.closest(".hammer-status-filter-button");
      if (!button) return;

      activeStatus = button.dataset.status || "all";
      applyFilterAndUI();
    });

    return wrapper;
  }

  function counts() {
    const result = {
      all: 0,
      upcoming: 0,
      live: 0,
      final: 0
    };

    rows().forEach(row => {
      const status = rowStatus(row);
      result.all += 1;
      result[status] += 1;
    });

    return result;
  }

  function updateFilterUI() {
    const wrapper = ensureFilterUI();
    if (!wrapper) return;

    const currentCounts = counts();

    ["all", "upcoming", "live", "final"].forEach(status => {
      const button = wrapper.querySelector(
        `.hammer-status-filter-button[data-status="${status}"]`
      );

      const count = wrapper.querySelector(
        `[data-count-for="${status}"]`
      );

      if (count) {
        count.textContent = String(currentCounts[status]);
      }

      if (button) {
        button.classList.toggle(
          "is-active",
          activeStatus === status
        );
      }
    });
  }

  // --------------------------------------------------------------------------
  // ORDERING + DIVIDERS
  // --------------------------------------------------------------------------

  function sortedRows() {
    return [...rows()].sort((a, b) => {
      const statusDiff =
        statusPriority(rowStatus(a)) -
        statusPriority(rowStatus(b));

      if (statusDiff !== 0) {
        return statusDiff;
      }

      const timeDiff = rowTime(a) - rowTime(b);

      if (timeDiff !== 0) {
        return timeDiff;
      }

      return gameIdFromRow(a).localeCompare(gameIdFromRow(b));
    });
  }

  function removeDividers() {
    tbody()?.querySelectorAll(`.${DIVIDER_CLASS}`)
      .forEach(node => node.remove());
  }

  function rebuildBoardOrderAndDividers() {
    const body = tbody();
    if (!body) return;

    const ordered = sortedRows();
    if (!ordered.length) return;

    removeDividers();

    // Reorder once per actual state/row change.
    const current = Array.from(
      body.querySelectorAll(":scope > tr.game-row")
    );

    const orderChanged =
      ordered.some((row, index) => row !== current[index]);

    if (orderChanged) {
      const fragment = document.createDocumentFragment();

      ordered.forEach(row => {
        fragment.appendChild(row);
      });

      body.appendChild(fragment);
    }

    let previousGroup = "";

    ordered.forEach(row => {
      const group = `${rowStatus(row)}|${dayKey(row)}`;

      if (group === previousGroup) return;
      previousGroup = group;

      const divider = document.createElement("tr");
      divider.className = DIVIDER_CLASS;
      divider.dataset.hammerStatus = rowStatus(row);

      const cell = document.createElement("td");
      cell.colSpan = 7;

      const box = document.createElement("div");
      box.className = "hammer-day-divider-box";
      box.textContent = dayLabel(row);

      cell.appendChild(box);
      divider.appendChild(cell);

      body.insertBefore(divider, row);
    });
  }

  // --------------------------------------------------------------------------
  // FILTERING
  // --------------------------------------------------------------------------

  function applyRowVisibility() {
    rows().forEach(row => {
      const visible =
        activeStatus === "all" ||
        rowStatus(row) === activeStatus;

      row.hidden = !visible;
      row.style.display = visible ? "" : "none";
    });
  }

  function syncDividerVisibility() {
    tbody()?.querySelectorAll(`.${DIVIDER_CLASS}`)
      .forEach(divider => {
        let node = divider.nextElementSibling;
        let visibleGameFound = false;

        while (
          node &&
          !node.classList.contains(DIVIDER_CLASS)
        ) {
          if (
            node.classList.contains("game-row") &&
            !node.hidden &&
            node.style.display !== "none"
          ) {
            visibleGameFound = true;
            break;
          }

          node = node.nextElementSibling;
        }

        divider.style.display =
          visibleGameFound ? "" : "none";
      });
  }

  function ensureEmptyState() {
    const view = document.getElementById(VIEW_ID);
    const tableCard = view?.querySelector(".table-card");

    if (!tableCard) return null;

    let empty = document.getElementById(EMPTY_ID);

    if (!empty) {
      empty = document.createElement("div");
      empty.id = EMPTY_ID;
      empty.className = "hammer-status-empty";
      tableCard.insertAdjacentElement("beforebegin", empty);
    }

    return empty;
  }

  function updateEmptyState() {
    const empty = ensureEmptyState();
    if (!empty) return;

    const visibleRows = rows().filter(row => !row.hidden);

    if (visibleRows.length) {
      empty.style.display = "none";
      return;
    }

    const labels = {
      upcoming: "upcoming games",
      live: "live games",
      final: "final games"
    };

    empty.textContent =
      activeStatus === "all"
        ? "No games are available."
        : `No ${labels[activeStatus] || "games"} are available.`;

    empty.style.display = "block";
  }

  function applyFilterAndUI() {
    updateFilterUI();
    applyRowVisibility();
    syncDividerVisibility();
    updateEmptyState();
  }

  // --------------------------------------------------------------------------
  // CHANGE DETECTION
  //
  // No MutationObserver.
  // We only rebuild when the actual set/order/status of game rows changes.
  // This avoids the old infinite feedback loop and date-bar flashing.
  // --------------------------------------------------------------------------

  function boardSignature() {
    return rows()
      .map(row => [
        gameIdFromRow(row),
        rowStatus(row),
        rowDate(row)?.getTime() ?? ""
      ].join(":"))
      .join("|");
  }

  function syncIfBoardChanged(force = false) {
    const signature = boardSignature();

    if (!force && signature === lastBoardSignature) {
      return;
    }

    lastBoardSignature = signature;

    rebuildBoardOrderAndDividers();
    applyFilterAndUI();
  }

  // --------------------------------------------------------------------------
  // DATA
  // --------------------------------------------------------------------------

  async function loadProjectionMetadata() {
    try {
      const response = await fetch(
        `${PROJECTIONS_URL}?v=${Date.now()}`,
        { cache: "no-store" }
      );

      if (!response.ok) return;

      const payload = await response.json();
      const games = Array.isArray(payload?.games)
        ? payload.games
        : [];

      projectionByGameId = new Map(
        games
          .filter(game =>
            game?.game_id !== null &&
            game?.game_id !== undefined
          )
          .map(game => [
            String(game.game_id),
            game
          ])
      );
    } catch (error) {
      console.warn(
        "Projection metadata unavailable for status controls:",
        error
      );
    }
  }

  // --------------------------------------------------------------------------
  // START
  // --------------------------------------------------------------------------

  async function start() {
    installStyles();
    ensureFilterUI();

    await loadProjectionMetadata();

    syncIfBoardChanged(true);

    document.addEventListener(
      "hammer:data-ready",
      () => {
        setTimeout(() => syncIfBoardChanged(true), 0);
      }
    );

    // Covers week-tab changes and score/final updates from sort-tables.js.
    // Because this only rebuilds when the row/status signature changes,
    // it does not create a flashing loop.
    pollTimer = window.setInterval(
      () => syncIfBoardChanged(false),
      1000
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      start,
      { once: true }
    );
  } else {
    start();
  }
})();
