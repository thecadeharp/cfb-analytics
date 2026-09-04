(() => {
  "use strict";

  // ==========================================================================
  // THE HAMMER INDEX
  // status-controls.js
  //
  // Presentation-only game lifecycle controls:
  //   - All Games
  //   - Upcoming
  //   - Live
  //   - Final
  //   - ET kickoff labels
  //
  // The old projection-summary line is intentionally hidden.
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
  let updateQueued = false;
  let projectionObserver = null;


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

        pointer-events: auto;
        position: relative;
        z-index: 2;

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

      .hammer-status-live-dot {
        pointer-events: none;
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


      /* ==============================================================
         TABLET
      ============================================================== */

      @media (max-width: 900px) {
        .hammer-status-filter-wrap {
          align-items: flex-start;
          flex-direction: column;
        }

        .hammer-status-filter-buttons {
          width: 100%;
        }
      }


      /* ==============================================================
         MOBILE
      ============================================================== */

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
      }
    `;

    document.head.appendChild(style);
  }


  // ==========================================================================
  // GAME ROWS
  // ==========================================================================

  function projectionRows() {
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


  function statusCounts() {
    const counts = {
      all: 0,
      upcoming: 0,
      live: 0,
      final: 0
    };

    projectionRows().forEach(row => {
      const status = rowStatus(row);

      counts.all += 1;

      if (
        Object.prototype.hasOwnProperty.call(
          counts,
          status
        )
      ) {
        counts[status] += 1;
      }
    });

    return counts;
  }


  // ==========================================================================
  // STATUS BUTTONS
  // ==========================================================================

  function buttonMarkup(status, label, count) {
    const active =
      activeStatus === status;

    const live =
      status === "live";

    return `
      <button
        type="button"
        class="hammer-status-filter-button${active ? " is-active" : ""}"
        data-status="${status}"
        aria-pressed="${active ? "true" : "false"}"
      >
        ${
          live
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


  function selectStatus(status) {
    if (
      ![
        "all",
        "upcoming",
        "live",
        "final"
      ].includes(status)
    ) {
      return;
    }

    activeStatus = status;

    renderFilterUI();

    applyDesktopFilter();

    applyMobileFilter();

    updateEmptyState();
  }


  function bindFilterButtons(wrapper) {
    wrapper
      .querySelectorAll(
        ".hammer-status-filter-button"
      )
      .forEach(button => {
        button.addEventListener(
          "click",
          event => {
            event.preventDefault();
            event.stopPropagation();

            selectStatus(
              button.dataset.status
            );
          }
        );

        button.addEventListener(
          "keydown",
          event => {
            if (
              event.key !== "Enter" &&
              event.key !== " "
            ) {
              return;
            }

            event.preventDefault();
            event.stopPropagation();

            selectStatus(
              button.dataset.status
            );
          }
        );
      });
  }


  function renderFilterUI() {
    const wrapper =
      document.getElementById(FILTER_ID);

    if (!wrapper) {
      return;
    }

    const counts =
      statusCounts();

    wrapper.innerHTML = `
      <div class="hammer-status-filter-title">
        Game Status
      </div>

      <div class="hammer-status-filter-buttons">

        ${buttonMarkup(
          "all",
          "All Games",
          counts.all
        )}

        ${buttonMarkup(
          "upcoming",
          "Upcoming",
          counts.upcoming
        )}

        ${buttonMarkup(
          "live",
          "Live",
          counts.live
        )}

        ${buttonMarkup(
          "final",
          "Final",
          counts.final
        )}

      </div>
    `;

    bindFilterButtons(wrapper);
  }


  function ensureFilterUI() {
    const tableCard =
      document.querySelector(
        `${VIEW_SELECTOR} .table-card`
      );

    if (!tableCard) {
      return;
    }

    let wrapper =
      document.getElementById(
        FILTER_ID
      );

    if (!wrapper) {
      wrapper =
        document.createElement(
          "div"
        );

      wrapper.id =
        FILTER_ID;

      wrapper.className =
        "hammer-status-filter-wrap";

      tableCard.insertAdjacentElement(
        "beforebegin",
        wrapper
      );
    }

    renderFilterUI();
  }


  // ==========================================================================
  // DESKTOP FILTERING
  // ==========================================================================

  function applyDesktopFilter() {
    projectionRows().forEach(row => {
      const status =
        rowStatus(row);

      const visible =
        activeStatus === "all" ||
        status === activeStatus;

      row.style.display =
        visible
          ? ""
          : "none";
    });
  }


  // ==========================================================================
  // MOBILE FILTERING
  // ==========================================================================

  function applyMobileFilter() {
    const sourceRows =
      projectionRows();

    const cards =
      Array.from(
        document.querySelectorAll(
          ".mobile-projection-card"
        )
      );

    cards.forEach(
      (card, index) => {
        const sourceRow =
          sourceRows[index];

        if (!sourceRow) {
          card.style.display = "";
          return;
        }

        const status =
          rowStatus(
            sourceRow
          );

        const visible =
          activeStatus === "all" ||
          status === activeStatus;

        card.style.display =
          visible
            ? ""
            : "none";
      }
    );
  }


  // ==========================================================================
  // EMPTY STATE
  // ==========================================================================

  function ensureEmptyState() {
    let empty =
      document.getElementById(
        EMPTY_ID
      );

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

    empty =
      document.createElement(
        "div"
      );

    empty.id =
      EMPTY_ID;

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

    const counts =
      statusCounts();

    if (
      activeStatus === "all" ||
      (counts[activeStatus] ?? 0) > 0
    ) {
      empty.style.display =
        "none";

      return;
    }

    const labels = {
      upcoming: "upcoming games",
      live: "live games",
      final: "final games"
    };

    empty.textContent =
      `No ${
        labels[activeStatus] ??
        "games"
      } are available in this week.`;

    empty.style.display =
      "block";
  }


  // ==========================================================================
  // HIDE OLD SUMMARY
  // ==========================================================================

  function hideOldSummary() {
    const summary =
      document.querySelector(
        SUMMARY_SELECTOR
      );

    if (!summary) {
      return;
    }

    summary.style.display =
      "none";
  }


  // ==========================================================================
  // EASTERN TIME LABEL
  // ==========================================================================

  function addEasternTimeLabels() {
    projectionRows().forEach(row => {
      const targets =
        row.querySelectorAll(
          ".matchup-cell, .team-meta"
        );

      targets.forEach(target => {
        const walker =
          document.createTreeWalker(
            target,
            NodeFilter.SHOW_TEXT
          );

        const nodes = [];

        while (
          walker.nextNode()
        ) {
          nodes.push(
            walker.currentNode
          );
        }

        nodes.forEach(node => {
          const original =
            String(
              node.nodeValue ?? ""
            );

          if (
            !/\b(?:AM|PM)\b/i.test(
              original
            )
          ) {
            return;
          }

          const updated =
            original.replace(
              /(\b\d{1,2}:\d{2}\s*(?:AM|PM)\b)(?!\s*ET\b)/gi,
              "$1 ET"
            );

          if (
            updated !== original
          ) {
            node.nodeValue =
              updated;
          }
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

    addEasternTimeLabels();

    applyDesktopFilter();

    applyMobileFilter();

    updateEmptyState();
  }


  function scheduleUpdate() {
    if (updateQueued) {
      return;
    }

    updateQueued = true;

    requestAnimationFrame(
      () => {
        updateQueued = false;

        updateEverything();
      }
    );
  }


  // ==========================================================================
  // OBSERVER
  // ==========================================================================

  function installProjectionObserver() {
    const container =
      document.querySelector(
        CONTAINER_SELECTOR
      );

    if (!container) {
      setTimeout(
        installProjectionObserver,
        100
      );

      return;
    }

    if (projectionObserver) {
      return;
    }

    projectionObserver =
      new MutationObserver(
        mutations => {
          const meaningful =
            mutations.some(
              mutation =>
                mutation.type ===
                "childList"
            );

          if (meaningful) {
            scheduleUpdate();
          }
        }
      );

    projectionObserver.observe(
      container,
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

    hideOldSummary();

    installProjectionObserver();

    scheduleUpdate();

    setTimeout(
      scheduleUpdate,
      100
    );

    setTimeout(
      scheduleUpdate,
      300
    );

    setTimeout(
      scheduleUpdate,
      750
    );

    setTimeout(
      scheduleUpdate,
      1500
    );

    setTimeout(
      scheduleUpdate,
      3000
    );

    window.addEventListener(
      "hammer:data-ready",
      scheduleUpdate
    );
  }


  if (
    document.readyState ===
    "loading"
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
