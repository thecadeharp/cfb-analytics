(() => {
  "use strict";

  // ==========================================================================
  // THE HAMMER INDEX
  // status-controls.js
  //
  // Presentation-only:
  //   - Adds All Games / Upcoming / Live / Final filters
  //   - Adds lifecycle counts to #projection-summary
  //   - Adds ET to kickoff times
  //
  // DOES NOT alter:
  //   - projections
  //   - odds
  //   - Model A
  //   - settlement
  //   - live-score data
  //   - existing conference / signal / confidence filters
  // ==========================================================================

  const VIEW_SELECTOR = "#view-projections";
  const CONTAINER_SELECTOR = "#projections-container";
  const ROW_SELECTOR =
    "#projections-container .projection-table tbody tr.game-row";

  const SUMMARY_SELECTOR = "#projection-summary";
  const FILTER_ID = "hammer-game-status-filters";
  const STYLE_ID = "hammer-game-status-filter-styles";
  const EMPTY_ID = "hammer-game-status-empty";

  let activeStatus = "all";
  let updateTimer = null;
  let observer = null;
  let summaryBaseText = "";


  // ==========================================================================
  // STYLES
  // ==========================================================================

  function installStyles() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }

    const style = document.createElement("style");
    style.id = STYLE_ID;

    style.textContent = `
      .hammer-status-filter-wrap {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 14px;

        margin: 0 0 14px;
        padding: 11px 13px;

        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius);
      }

      .hammer-status-filter-title {
        flex: 0 0 auto;

        color: var(--muted);

        font-family: var(--mono);
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 1px;
        text-transform: uppercase;
        white-space: nowrap;
      }

      .hammer-status-filter-buttons {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        flex-wrap: wrap;
        gap: 7px;
      }

      .hammer-status-filter-button {
        appearance: none;

        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 6px;

        min-height: 30px;
        padding: 6px 10px;

        border: 1px solid var(--border);
        border-radius: 999px;

        background: #fff;
        color: var(--muted);

        font-family: var(--mono);
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 0.25px;

        cursor: pointer;

        transition:
          background 0.15s ease,
          border-color 0.15s ease,
          color 0.15s ease;
      }

      .hammer-status-filter-button:hover {
        color: var(--text);
        border-color: var(--border-dark);
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
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: currentColor;
        flex: 0 0 6px;
      }

      .hammer-status-count {
        opacity: 0.72;
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

      @media (max-width: 600px) {
        .hammer-status-filter-wrap {
          align-items: flex-start;
          flex-direction: column;
          padding: 11px;
        }

        .hammer-status-filter-buttons {
          justify-content: flex-start;
          width: 100%;
        }

        .hammer-status-filter-button {
          min-height: 34px;
          padding: 7px 10px;
        }
      }
    `;

    document.head.appendChild(style);
  }


  // ==========================================================================
  // ROW HELPERS
  // ==========================================================================

  function rows() {
    return Array.from(
      document.querySelectorAll(ROW_SELECTOR)
    );
  }


  function rowStatus(row) {
    if (!row) {
      return "upcoming";
    }

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


  // ==========================================================================
  // FILTER UI
  // ==========================================================================

  function buttonMarkup(status, label, count) {
    const isLive = status === "live";
    const active = activeStatus === status;

    return `
      <button
        type="button"
        class="hammer-status-filter-button${active ? " is-active" : ""}"
        data-status="${status}"
        aria-pressed="${active ? "true" : "false"}"
      >
        ${
          isLive
            ? '<span class="hammer-status-live-dot" aria-hidden="true"></span>'
            : ""
        }

        <span>${label}</span>

        <span class="hammer-status-count">
          ${count}
        </span>
      </button>
    `;
  }


  function ensureFilterUI() {
    const projectionControls =
      document.querySelector(
        `${VIEW_SELECTOR} .projection-controls`
      );

    const tableCard =
      document.querySelector(
        `${VIEW_SELECTOR} .table-card`
      );

    if (!projectionControls || !tableCard) {
      return;
    }

    let wrapper =
      document.getElementById(FILTER_ID);

    if (!wrapper) {
      wrapper = document.createElement("div");

      wrapper.id = FILTER_ID;
      wrapper.className =
        "hammer-status-filter-wrap";

      tableCard.insertAdjacentElement(
        "beforebegin",
        wrapper
      );

      wrapper.addEventListener(
        "click",
        event => {
          const button =
            event.target.closest(
              ".hammer-status-filter-button"
            );

          if (!button) {
            return;
          }

          const nextStatus =
            button.dataset.status;

          if (
            ![
              "all",
              "upcoming",
              "live",
              "final"
            ].includes(nextStatus)
          ) {
            return;
          }

          activeStatus = nextStatus;

          renderStatusControls();
          applyFilters();
        }
      );
    }

    const currentCounts = counts();

    wrapper.innerHTML = `
      <div class="hammer-status-filter-title">
        Game Status
      </div>

      <div class="hammer-status-filter-buttons">
        ${buttonMarkup(
          "all",
          "All Games",
          currentCounts.all
        )}

        ${buttonMarkup(
          "upcoming",
          "Upcoming",
          currentCounts.upcoming
        )}

        ${buttonMarkup(
          "live",
          "Live",
          currentCounts.live
        )}

        ${buttonMarkup(
          "final",
          "Final",
          currentCounts.final
        )}
      </div>
    `;
  }


  // ==========================================================================
  // DESKTOP FILTERING
  // ==========================================================================

  function applyDesktopFilter() {
    rows().forEach(row => {
      const status = rowStatus(row);

      const show =
        activeStatus === "all" ||
        status === activeStatus;

      row.style.display =
        show ? "" : "none";
    });
  }


  // ==========================================================================
  // MOBILE FILTERING
  // ==========================================================================

  function applyMobileFilter() {
    const sourceRows = rows();

    const cards = Array.from(
      document.querySelectorAll(
        ".mobile-projection-card"
      )
    );

    cards.forEach((card, index) => {
      const sourceRow =
        sourceRows[index];

      if (!sourceRow) {
        card.style.display = "";
        return;
      }

      const status =
        rowStatus(sourceRow);

      const show =
        activeStatus === "all" ||
        status === activeStatus;

      card.style.display =
        show ? "" : "none";
    });
  }


  // ==========================================================================
  // EMPTY STATE
  // ==========================================================================

  function ensureEmptyState() {
    let empty =
      document.getElementById(EMPTY_ID);

    if (empty) {
      return empty;
    }

    const tableCard =
      document.querySelector(
        `${VIEW_SELECTOR} .table-card`
      );

    if (!tableCard) {
      return null;
    }

    empty = document.createElement("div");

    empty.id = EMPTY_ID;
    empty.className =
      "hammer-status-empty";

    tableCard.insertAdjacentElement(
      "beforebegin",
      empty
    );

    return empty;
  }


  function updateEmptyState() {
    const empty =
      ensureEmptyState();

    if (!empty) {
      return;
    }

    const currentCounts = counts();

    if (
      activeStatus === "all" ||
      currentCounts[activeStatus] > 0
    ) {
      empty.style.display = "none";
      return;
    }

    const labels = {
      upcoming: "upcoming games",
      live: "live games",
      final: "final games"
    };

    empty.textContent =
      `No ${labels[activeStatus] || "games"} are available in this week.`;

    empty.style.display = "block";
  }


  // ==========================================================================
  // PROJECTION SUMMARY
  //
  // IMPORTANT:
  // We ONLY touch #projection-summary.
  // We never search parent divs or overwrite existing controls.
  // ==========================================================================

  function updateSummary() {
    const summary =
      document.querySelector(
        SUMMARY_SELECTOR
      );

    if (!summary) {
      return;
    }

    const visibleText =
      String(summary.textContent || "")
        .replace(/\s+/g, " ")
        .trim();

    /*
      app.js owns this element.

      Whenever app.js writes a fresh summary,
      save that as the base text.

      Never store our own lifecycle-enhanced version
      as the base.
    */

    if (
      visibleText &&
      !summary.dataset.hammerStatusEnhanced
    ) {
      summaryBaseText = visibleText;
    }

    if (!summaryBaseText) {
      summaryBaseText = visibleText;
    }

    if (!summaryBaseText) {
      return;
    }

    const currentCounts = counts();

    let remainder = summaryBaseText;

    /*
      Remove the original leading lifecycle section only.

      Handles examples such as:

      51 games · 0 final · 41 lined ...
      51 games · 41 lined ...
    */

    remainder = remainder.replace(
      /^\s*\d+\s+games\s*·\s*(?:\d+\s+final\s*·\s*)?/i,
      ""
    );

    summary.textContent =
      `${currentCounts.all} games · ` +
      `${currentCounts.upcoming} upcoming · ` +
      `${currentCounts.live} live · ` +
      `${currentCounts.final} final · ` +
      remainder;

    summary.dataset.hammerStatusEnhanced =
      "1";
  }


  function watchSummaryForAppUpdates() {
    const summary =
      document.querySelector(
        SUMMARY_SELECTOR
      );

    if (!summary) {
      return;
    }

    if (
      summary.dataset
        .hammerSummaryObserverInstalled === "1"
    ) {
      return;
    }

    summary.dataset
      .hammerSummaryObserverInstalled = "1";

    const summaryObserver =
      new MutationObserver(() => {
        const text =
          String(summary.textContent || "")
            .replace(/\s+/g, " ")
            .trim();

        /*
          If another script writes into the summary,
          MutationObserver fires.

          If it no longer contains our lifecycle format,
          treat it as fresh app.js text.
        */

        if (
          text &&
          !/\bupcoming\b/i.test(text)
        ) {
          summaryBaseText = text;

          delete summary.dataset
            .hammerStatusEnhanced;

          scheduleUpdate();
        }
      });

    summaryObserver.observe(
      summary,
      {
        childList: true,
        characterData: true,
        subtree: true
      }
    );
  }


  // ==========================================================================
  // EASTERN TIME LABELS
  // ==========================================================================

  function addEasternTimeLabels() {
    const matchupCells =
      document.querySelectorAll(
        `${CONTAINER_SELECTOR} .matchup-cell`
      );

    matchupCells.forEach(cell => {
      const walker =
        document.createTreeWalker(
          cell,
          NodeFilter.SHOW_TEXT
        );

      const textNodes = [];

      while (walker.nextNode()) {
        textNodes.push(
          walker.currentNode
        );
      }

      textNodes.forEach(node => {
        const original =
          node.nodeValue || "";

        const updated =
          original.replace(
            /(\b\d{1,2}:\d{2}\s*(?:AM|PM)\b)(?!\s*ET\b)/gi,
            "$1 ET"
          );

        if (updated !== original) {
          node.nodeValue = updated;
        }
      });
    });
  }


  // ==========================================================================
  // UPDATE CYCLE
  // ==========================================================================

  function renderStatusControls() {
    ensureFilterUI();
    updateSummary();
  }


  function applyFilters() {
    applyDesktopFilter();
    applyMobileFilter();
    updateEmptyState();
  }


  function updateEverything() {
    installStyles();

    addEasternTimeLabels();

    renderStatusControls();

    applyFilters();

    watchSummaryForAppUpdates();
  }


  function scheduleUpdate() {
    if (updateTimer) {
      clearTimeout(updateTimer);
    }

    updateTimer = setTimeout(() => {
      updateTimer = null;
      updateEverything();
    }, 80);
  }


  // ==========================================================================
  // OBSERVER
  // ==========================================================================

  function installObserver() {
    const projectionContainer =
      document.querySelector(
        CONTAINER_SELECTOR
      );

    if (!projectionContainer) {
      setTimeout(
        installObserver,
        150
      );

      return;
    }

    if (observer) {
      return;
    }

    observer =
      new MutationObserver(() => {
        scheduleUpdate();
      });

    observer.observe(
      projectionContainer,
      {
        childList: true,
        subtree: true
      }
    );
  }


  // ==========================================================================
  // START
  // ==========================================================================

  function start() {
    installStyles();

    installObserver();

    scheduleUpdate();

    /*
      app.js / ux-v2 / sort-tables.js / mobile.js
      do not all finish at exactly the same moment.

      These are harmless presentation refreshes
      after their initial rendering settles.
    */

    setTimeout(
      scheduleUpdate,
      250
    );

    setTimeout(
      scheduleUpdate,
      700
    );

    setTimeout(
      scheduleUpdate,
      1500
    );

    window.addEventListener(
      "hammer:data-ready",
      scheduleUpdate
    );
  }


  if (
    document.readyState === "loading"
  ) {
    document.addEventListener(
      "DOMContentLoaded",
      start,
      {
        once: true
      }
    );
  } else {
    start();
  }
})();
