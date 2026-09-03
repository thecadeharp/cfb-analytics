(() => {
  "use strict";

  // ==========================================================================
  // THE HAMMER INDEX
  // status-controls.js
  //
  // Adds:
  //   - All Games / Upcoming / Live / Final filters
  //   - Upcoming / Live / Final counts to the existing projection summary
  //   - ET to scheduled kickoff times
  //
  // Presentation only.
  // Does NOT modify projection/model/odds/settlement data.
  // ==========================================================================

  const VIEW_SELECTOR =
    "#view-projections";

  const CONTAINER_SELECTOR =
    "#projections-container";

  const ROW_SELECTOR =
    "#projections-container .projection-table tbody tr.game-row";

  const SUMMARY_SELECTOR =
    "#projection-summary";

  const FILTER_ID =
    "hammer-game-status-filters";

  const STYLE_ID =
    "hammer-game-status-filter-styles";

  const EMPTY_ID =
    "hammer-game-status-empty";

  let activeStatus =
    "all";

  let updateQueued =
    false;

  let projectionObserver =
    null;

  let summaryObserver =
    null;

  let applyingSummary =
    false;


  // ==========================================================================
  // STYLES
  // ==========================================================================

  function installStyles() {
    if (
      document.getElementById(
        STYLE_ID
      )
    ) {
      return;
    }

    const style =
      document.createElement(
        "style"
      );

    style.id =
      STYLE_ID;

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

        flex: 0 0 6px;

        border-radius: 50%;
        background: currentColor;
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

    document.head.appendChild(
      style
    );
  }


  // ==========================================================================
  // GAME ROWS
  // ==========================================================================

  function projectionRows() {
    return Array.from(
      document.querySelectorAll(
        ROW_SELECTOR
      )
    );
  }


  function rowStatus(
    row
  ) {
    if (!row) {
      return "upcoming";
    }

    if (
      row.classList.contains(
        "completed-row"
      ) ||
      row.classList.contains(
        "hammer-final-untracked-row"
      ) ||
      row.dataset
        .hammerGameState ===
        "final"
    ) {
      return "final";
    }

    if (
      row.classList.contains(
        "hammer-live-row"
      ) ||
      row.dataset
        .hammerGameState ===
        "live"
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

    projectionRows()
      .forEach(
        row => {
          const status =
            rowStatus(
              row
            );

          counts.all += 1;

          if (
            Object.prototype
              .hasOwnProperty
              .call(
                counts,
                status
              )
          ) {
            counts[
              status
            ] += 1;
          }
        }
      );

    return counts;
  }


  // ==========================================================================
  // STATUS FILTER UI
  // ==========================================================================

  function buttonMarkup(
    status,
    label,
    count
  ) {
    const active =
      activeStatus ===
      status;

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

        <span>
          ${label}
        </span>

        <span class="hammer-status-count">
          ${count}
        </span>
      </button>
    `;
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

      tableCard
        .insertAdjacentElement(
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

          const status =
            button.dataset
              .status;

          if (
            ![
              "all",
              "upcoming",
              "live",
              "final"
            ].includes(
              status
            )
          ) {
            return;
          }

          activeStatus =
            status;

          updateEverything();
        }
      );
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
  }


  // ==========================================================================
  // DESKTOP FILTER
  // ==========================================================================

  function applyDesktopFilter() {
    projectionRows()
      .forEach(
        row => {
          const status =
            rowStatus(
              row
            );

          const visible =
            activeStatus ===
              "all" ||
            status ===
              activeStatus;

          row.style.display =
            visible
              ? ""
              : "none";
        }
      );
  }


  // ==========================================================================
  // MOBILE FILTER
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
      (
        card,
        index
      ) => {
        const sourceRow =
          sourceRows[
            index
          ];

        if (!sourceRow) {
          card.style.display =
            "";

          return;
        }

        const status =
          rowStatus(
            sourceRow
          );

        const visible =
          activeStatus ===
            "all" ||
          status ===
            activeStatus;

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

    tableCard
      .insertAdjacentElement(
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
      activeStatus ===
        "all" ||
      (
        counts[
          activeStatus
        ] ?? 0
      ) > 0
    ) {
      empty.style.display =
        "none";

      return;
    }

    const labels = {
      upcoming:
        "upcoming games",

      live:
        "live games",

      final:
        "final games"
    };

    empty.textContent =
      `No ${
        labels[
          activeStatus
        ] ?? "games"
      } are available in this week.`;

    empty.style.display =
      "block";
  }


  // ==========================================================================
  // SUMMARY
  //
  // IMPORTANT:
  //
  // We modify ONLY #projection-summary.
  //
  // We preserve the original HTML after the leading:
  //
  //   51 games · 0 final ·
  //
  // so existing colored PLAY / SMALL EDGE / MATERIAL / TOTAL markup survives.
  // ==========================================================================

  function updateSummary() {
    const summary =
      document.querySelector(
        SUMMARY_SELECTOR
      );

    if (!summary) {
      return;
    }

    const counts =
      statusCounts();

    const lifecycle =
      `${counts.all} games · ` +
      `${counts.upcoming} upcoming · ` +
      `${counts.live} live · ` +
      `${counts.final} final · `;

    let html =
      summary.innerHTML;

    if (!html) {
      return;
    }

    /*
      CASE 1:
      Already enhanced by this script.

      Replace only the lifecycle prefix.
    */

    const enhancedPattern =
      /^\s*\d+\s+games\s*·\s*\d+\s+upcoming\s*·\s*\d+\s+live\s*·\s*\d+\s+final\s*·\s*/i;

    if (
      enhancedPattern.test(
        html
      )
    ) {
      const updated =
        html.replace(
          enhancedPattern,
          lifecycle
        );

      if (
        updated !== html
      ) {
        applyingSummary =
          true;

        summary.innerHTML =
          updated;

        applyingSummary =
          false;
      }

      return;
    }

    /*
      CASE 2:
      Original app summary:

        51 games · 0 final · 41 lined · ...

      Replace ONLY:
        51 games · 0 final ·

      Everything from "41 lined" onward remains exactly as app.js rendered it.
    */

    const originalPattern =
      /^\s*\d+\s+games\s*·\s*\d+\s+final\s*·\s*/i;

    if (
      originalPattern.test(
        html
      )
    ) {
      applyingSummary =
        true;

      summary.innerHTML =
        html.replace(
          originalPattern,
          lifecycle
        );

      applyingSummary =
        false;

      return;
    }

    /*
      CASE 3:
      Defensive fallback if app.js ever drops "0 final":

        51 games · 41 lined · ...

      Replace only "51 games ·"
    */

    const gamesOnlyPattern =
      /^\s*\d+\s+games\s*·\s*/i;

    if (
      gamesOnlyPattern.test(
        html
      )
    ) {
      applyingSummary =
        true;

      summary.innerHTML =
        html.replace(
          gamesOnlyPattern,
          lifecycle
        );

      applyingSummary =
        false;
    }
  }


  // ==========================================================================
  // EASTERN TIME LABELS
  //
  // Only changes scheduled kickoff strings containing AM/PM.
  //
  // Examples:
  //
  //   Sep 5, 7:30 PM
  //       ->
  //   Sep 5, 7:30 PM ET
  //
  // Live clock:
  //
  //   04:39
  //
  // is untouched because it does not contain AM or PM.
  // ==========================================================================

  function addEasternTimeLabels() {
    const rows =
      projectionRows();

    rows.forEach(
      row => {
        /*
          Search the matchup cell and team-meta elements.

          Using both selectors protects us if app.js puts the
          kickoff metadata one level outside .matchup-cell.
        */

        const targets =
          row.querySelectorAll(
            ".matchup-cell, .team-meta"
          );

        targets.forEach(
          target => {
            const walker =
              document.createTreeWalker(
                target,
                NodeFilter.SHOW_TEXT
              );

            const nodes =
              [];

            while (
              walker.nextNode()
            ) {
              nodes.push(
                walker.currentNode
              );
            }

            nodes.forEach(
              node => {
                const original =
                  String(
                    node.nodeValue ?? ""
                  );

                if (
                  !/\b(?:AM|PM)\b/i
                    .test(
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
                  updated !==
                  original
                ) {
                  node.nodeValue =
                    updated;
                }
              }
            );
          }
        );
      }
    );
  }


  // ==========================================================================
  // MASTER UPDATE
  // ==========================================================================

  function updateEverything() {
    installStyles();

    ensureFilterUI();

    updateSummary();

    addEasternTimeLabels();

    applyDesktopFilter();

    applyMobileFilter();

    updateEmptyState();
  }


  function scheduleUpdate() {
    if (
      updateQueued
    ) {
      return;
    }

    updateQueued =
      true;

    requestAnimationFrame(
      () => {
        updateQueued =
          false;

        updateEverything();
      }
    );
  }


  // ==========================================================================
  // OBSERVERS
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

    if (
      projectionObserver
    ) {
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

          if (
            meaningful
          ) {
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


  function installSummaryObserver() {
    const summary =
      document.querySelector(
        SUMMARY_SELECTOR
      );

    if (!summary) {
      setTimeout(
        installSummaryObserver,
        100
      );

      return;
    }

    if (
      summaryObserver
    ) {
      return;
    }

    summaryObserver =
      new MutationObserver(
        () => {
          if (
            applyingSummary
          ) {
            return;
          }

          scheduleUpdate();
        }
      );

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
  // STARTUP
  // ==========================================================================

  function start() {
    installStyles();

    installProjectionObserver();

    installSummaryObserver();

    scheduleUpdate();

    /*
      Other Hammer Index scripts render asynchronously.

      These extra passes are intentional so this adapter runs
      after app.js, ux-v2.js, sort-tables.js and mobile.js settle.
    */

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
