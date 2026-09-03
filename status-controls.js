(() => {
  "use strict";

  // ==========================================================================
  // THE HAMMER INDEX
  // status-controls.js
  //
  // Adds:
  //   1) All / Upcoming / Live / Final projection filters
  //   2) Live / Final / Upcoming counts to the projection summary
  //   3) "ET" to displayed kickoff times
  //
  // This is presentation-only.
  // It does NOT alter projections, odds, Model A, settlement, or live scores.
  // ==========================================================================

  const PROJECTION_VIEW =
    "#view-projections";

  const PROJECTION_CONTAINER =
    "#projections-container";

  const DESKTOP_ROW_SELECTOR =
    "#projections-container .projection-table tbody tr.game-row";

  const MOBILE_CARD_SELECTOR =
    "#mobile-projection-cards .mobile-projection-card";

  const FILTER_ID =
    "hammer-game-status-filters";

  const STYLE_ID =
    "hammer-game-status-filter-styles";

  let activeStatus =
    "all";

  let updateQueued =
    false;

  let observerInstalled =
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

        margin: 14px 0 16px;
        padding: 12px 14px;

        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius);
      }

      .hammer-status-filter-title {
        flex: 0 0 auto;

        color: var(--muted);

        font-family: var(--mono);
        font-size: 9px;
        font-weight: 800;
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

        background: #ffffff;
        color: var(--muted);

        font-family: var(--mono);
        font-size: 9px;
        font-weight: 800;
        letter-spacing: 0.35px;

        cursor: pointer;

        transition:
          background 0.15s ease,
          border-color 0.15s ease,
          color 0.15s ease,
          box-shadow 0.15s ease;
      }

      .hammer-status-filter-button:hover {
        color: var(--text);
        border-color: #b8b8b1;
      }

      .hammer-status-filter-button.is-active {
        background: var(--ink);
        border-color: var(--ink);
        color: #ffffff;
      }

      .hammer-status-filter-button[data-status="live"] {
        color: #b71c1c;
        border-color: #e4b1b1;
        background: #fffafa;
      }

      .hammer-status-filter-button[data-status="live"]:hover {
        border-color: #d77474;
        background: #fff4f4;
      }

      .hammer-status-filter-button[data-status="live"].is-active {
        background: #b71c1c;
        border-color: #b71c1c;
        color: #ffffff;
      }

      .hammer-filter-live-dot {
        width: 6px;
        height: 6px;

        border-radius: 999px;
        background: currentColor;
      }

      .hammer-status-filter-button[data-status="live"].is-active
      .hammer-filter-live-dot {
        background: #ffffff;
      }

      .hammer-status-count {
        opacity: 0.72;
      }

      .hammer-status-filter-empty {
        display: none;

        margin: 18px 0;
        padding: 30px 18px;

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

          margin-top: 12px;
          padding: 12px;
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
  // HELPERS
  // ==========================================================================

  function projectionRows() {
    return Array.from(
      document.querySelectorAll(
        DESKTOP_ROW_SELECTOR
      )
    );
  }


  function normalizeStatus(
    value
  ) {
    const status =
      String(
        value ?? ""
      )
        .trim()
        .toLowerCase();

    if (
      status === "live" ||
      status === "final"
    ) {
      return status;
    }

    return "upcoming";
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
      )
    ) {
      return "final";
    }

    if (
      row.classList.contains(
        "hammer-live-row"
      )
    ) {
      return "live";
    }

    if (
      row.classList.contains(
        "hammer-final-untracked-row"
      )
    ) {
      return "final";
    }

    return normalizeStatus(
      row.dataset
        ?.hammerGameState
    );
  }


  function statusCounts() {
    const rows =
      projectionRows();

    const counts = {
      all:
        rows.length,

      upcoming:
        0,

      live:
        0,

      final:
        0
    };

    rows.forEach(
      row => {
        const status =
          rowStatus(
            row
          );

        counts[
          status
        ] += 1;
      }
    );

    return counts;
  }


  // ==========================================================================
  // ET KICKOFF LABELS
  // ==========================================================================

  function addEasternTimeLabels() {
    const cells =
      document.querySelectorAll(
        `${PROJECTION_CONTAINER} .matchup-cell`
      );

    cells.forEach(
      cell => {
        const walker =
          document.createTreeWalker(
            cell,
            NodeFilter.SHOW_TEXT
          );

        const textNodes =
          [];

        while (
          walker.nextNode()
        ) {
          textNodes.push(
            walker.currentNode
          );
        }

        textNodes.forEach(
          node => {
            const original =
              node.nodeValue ?? "";

            /*
              Examples:
                12:00 PM
                3:30 PM
                7:00 PM

              Becomes:
                12:00 PM ET
                3:30 PM ET
                7:00 PM ET

              Does not touch live clocks like:
                04:39
            */

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
          }
        );
      }
    );
  }


  // ==========================================================================
  // FILTER UI
  // ==========================================================================

  function filterButtonMarkup(
    status,
    label,
    count,
    live = false
  ) {
    return `
      <button
        type="button"
        class="hammer-status-filter-button${
          activeStatus === status
            ? " is-active"
            : ""
        }"
        data-status="${status}"
        aria-pressed="${
          activeStatus === status
            ? "true"
            : "false"
        }"
      >
        ${
          live
            ? '<span class="hammer-filter-live-dot"></span>'
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
    const projectionView =
      document.querySelector(
        PROJECTION_VIEW
      );

    const projectionContainer =
      document.querySelector(
        PROJECTION_CONTAINER
      );

    if (
      !projectionView ||
      !projectionContainer
    ) {
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

      projectionContainer
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

        ${filterButtonMarkup(
          "all",
          "All Games",
          counts.all
        )}

        ${filterButtonMarkup(
          "upcoming",
          "Upcoming",
          counts.upcoming
        )}

        ${filterButtonMarkup(
          "live",
          "Live",
          counts.live,
          true
        )}

        ${filterButtonMarkup(
          "final",
          "Final",
          counts.final
        )}

      </div>
    `;
  }


  // ==========================================================================
  // DESKTOP FILTERING
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
  // MOBILE FILTERING
  // ==========================================================================

  function applyMobileFilter() {
    const rows =
      projectionRows();

    const cards =
      Array.from(
        document.querySelectorAll(
          MOBILE_CARD_SELECTOR
        )
      );

    cards.forEach(
      (
        card,
        index
      ) => {
        const sourceRow =
          rows[
            index
          ];

        if (!sourceRow) {
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
  // EMPTY FILTER MESSAGE
  // ==========================================================================

  function ensureEmptyMessage() {
    const projectionView =
      document.querySelector(
        PROJECTION_VIEW
      );

    if (!projectionView) {
      return null;
    }

    let empty =
      document.getElementById(
        "hammer-status-filter-empty"
      );

    if (!empty) {
      empty =
        document.createElement(
          "div"
        );

      empty.id =
        "hammer-status-filter-empty";

      empty.className =
        "hammer-status-filter-empty";

      const mobileHost =
        document.getElementById(
          "mobile-projection-cards"
        );

      if (mobileHost) {
        mobileHost
          .insertAdjacentElement(
            "afterend",
            empty
          );
      } else {
        const projectionContainer =
          document.querySelector(
            PROJECTION_CONTAINER
          );

        projectionContainer
          ?.insertAdjacentElement(
            "afterend",
            empty
          );
      }
    }

    return empty;
  }


  function updateEmptyMessage() {
    const empty =
      ensureEmptyMessage();

    if (!empty) {
      return;
    }

    const counts =
      statusCounts();

    const number =
      activeStatus ===
        "all"
        ? counts.all
        : counts[
            activeStatus
          ] ?? 0;

    if (
      activeStatus === "all" ||
      number > 0
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
      } are available in this view.`;

    empty.style.display =
      "block";
  }


  // ==========================================================================
  // PROJECTION SUMMARY
  // ==========================================================================

  function findSummaryElement() {
    const view =
      document.querySelector(
        PROJECTION_VIEW
      );

    if (!view) {
      return null;
    }

    const candidates =
      Array.from(
        view.querySelectorAll(
          "div, p, span"
        )
      );

    return (
      candidates.find(
        element => {
          const text =
            String(
              element.textContent ??
              ""
            )
              .replace(
                /\s+/g,
                " "
              )
              .trim();

          return (
            /\b\d+\s+games\b/i
              .test(text) &&
            /\b\d+\s+lined\b/i
              .test(text) &&
            text.includes("·")
          );
        }
      ) ?? null
    );
  }


  function updateSummary() {
    const summary =
      findSummaryElement();

    if (!summary) {
      return;
    }

    const counts =
      statusCounts();

    let text =
      String(
        summary.textContent ??
        ""
      )
        .replace(
          /\s+/g,
          " "
        )
        .trim();

    /*
      Current Hammer summary begins like:

      51 games · 0 final · 41 lined · ...

      Replace that lifecycle section with:

      51 games · 42 upcoming · 1 live · 8 final · 41 lined · ...
    */

    const lifecyclePrefix =
      `${counts.all} games · ` +
      `${counts.upcoming} upcoming · ` +
      `${counts.live} live · ` +
      `${counts.final} final · `;

    if (
      /^\d+\s+games\s*·\s*\d+\s+final\s*·\s*/i
        .test(text)
    ) {
      text =
        text.replace(
          /^\d+\s+games\s*·\s*\d+\s+final\s*·\s*/i,
          lifecyclePrefix
        );
    }

    else if (
      /^\d+\s+games\s*·\s*/i
        .test(text)
    ) {
      text =
        text.replace(
          /^\d+\s+games\s*·\s*/i,
          lifecyclePrefix
        );
    }

    summary.textContent =
      text;
  }


  // ==========================================================================
  // UPDATE LOOP
  // ==========================================================================

  function updateEverything() {
    installStyles();

    addEasternTimeLabels();

    ensureFilterUI();

    applyDesktopFilter();

    applyMobileFilter();

    updateSummary();

    updateEmptyMessage();
  }


  function queueUpdate() {
    if (
      updateQueued
    ) {
      return;
    }

    updateQueued =
      true;

    window
      .requestAnimationFrame(
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

  function installObservers() {
    if (
      observerInstalled
    ) {
      return;
    }

    const projectionContainer =
      document.querySelector(
        PROJECTION_CONTAINER
      );

    if (!projectionContainer) {
      return;
    }

    observerInstalled =
      true;

    const projectionObserver =
      new MutationObserver(
        queueUpdate
      );

    projectionObserver.observe(
      projectionContainer,
      {
        childList: true,
        subtree: true
      }
    );

    const mobileHost =
      document.getElementById(
        "mobile-projection-cards"
      );

    if (mobileHost) {
      const mobileObserver =
        new MutationObserver(
          queueUpdate
        );

      mobileObserver.observe(
        mobileHost,
        {
          childList: true,
          subtree: true
        }
      );
    }
  }


  // ==========================================================================
  // START
  // ==========================================================================

  function start() {
    installStyles();

    queueUpdate();

    /*
      sort-tables.js and mobile.js both modify the board after
      initial app rendering, so give each layer a chance to finish.
    */

    window.setTimeout(
      queueUpdate,
      150
    );

    window.setTimeout(
      queueUpdate,
      500
    );

    window.setTimeout(
      queueUpdate,
      1200
    );

    window.setTimeout(
      installObservers,
      1300
    );
  }


  document.addEventListener(
    "hammer:data-ready",
    queueUpdate
  );

  window.addEventListener(
    "resize",
    queueUpdate
  );

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
