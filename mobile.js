(() => {
  "use strict";

  const mobileQuery =
    window.matchMedia("(max-width: 600px)");

  let buildTimer = null;
  let buildFrame = null;
  let lastSignature = "";


  // ==========================================================================
  // MOBILE-ONLY STYLES
  // ==========================================================================

  function installMobileStyles() {
    if (
      document.getElementById(
        "hammer-mobile-styles"
      )
    ) {
      return;
    }

    const style =
      document.createElement("style");

    style.id =
      "hammer-mobile-styles";

    style.textContent = `
      #mobile-projection-cards,
      .mobile-viewing-tip {
        display: none;
      }

      @media (max-width: 600px) {

        html,
        body {
          max-width: 100%;
          overflow-x: hidden;
        }

        body {
          -webkit-text-size-adjust: 100%;
        }

        .page {
          width: 100%;
          max-width: 100%;
          padding-left: 12px;
          padding-right: 12px;
        }


        /* ==============================================================
           MOBILE VIEWING NOTE
        ============================================================== */

        .mobile-viewing-tip {
          display: block;

          margin: 16px 0 18px;
          padding: 14px 15px;

          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: 10px;
        }

        .mobile-viewing-tip-title {
          margin-bottom: 5px;

          color: var(--text);

          font-family: var(--mono);
          font-size: 9px;
          font-weight: 700;
          letter-spacing: 0.08em;

          text-transform: uppercase;
        }

        .mobile-viewing-tip-copy {
          color: var(--muted);

          font-size: 11px;
          line-height: 1.55;
        }


        /* ==============================================================
           DESKTOP PROJECTION TABLE
        ============================================================== */

        #view-projections > .table-card {
          display: none !important;
        }


        /* ==============================================================
           MOBILE PROJECTION BOARD
        ============================================================== */

        #mobile-projection-cards {
          display: grid;

          gap: 12px;

          width: 100%;
          max-width: 100%;

          margin-top: 4px;
        }

        .mobile-projection-card {
          width: 100%;
          min-width: 0;
          max-width: 100%;

          overflow: hidden;

          background: var(--surface);

          border: 1px solid var(--border);
          border-radius: var(--radius);

          cursor: pointer;

          -webkit-tap-highlight-color: transparent;

          contain: layout paint;
        }

        .mobile-projection-card:active {
          transform: scale(0.997);
        }

        .mobile-projection-card * {
          min-width: 0;
        }


        /* ==============================================================
           MATCHUP
        ============================================================== */

        .mobile-card-matchup {
          padding: 16px;

          border-bottom: 1px solid #e9e9e5;
        }

        .mobile-card-matchup .team-line {
          display: flex;

          align-items: center;

          min-height: 28px;

          gap: 7px;
        }

        .mobile-card-matchup .team-name {
          font-size: 15px;

          cursor: pointer;
        }

        .mobile-card-matchup .team-meta {
          font-size: 10px;
        }

        .mobile-card-matchup .team-logo {
          flex: 0 0 auto;
        }

        .mobile-card-matchup .team-logo img {
          display: block;

          max-width: 100%;
          max-height: 100%;
        }


        /* ==============================================================
           MAIN STAT GRID
        ============================================================== */

        .mobile-card-grid {
          display: grid;

          grid-template-columns:
            repeat(2, minmax(0, 1fr));
        }

        .mobile-card-stat {
          padding: 13px 14px;

          border-bottom:
            1px solid #e9e9e5;
        }

        .mobile-card-stat:nth-child(odd) {
          border-right:
            1px solid #e9e9e5;
        }

        .mobile-card-label {
          margin-bottom: 7px;

          color: var(--muted);

          font-family: var(--mono);
          font-size: 8px;
          font-weight: 700;
          letter-spacing: 1px;
          line-height: 1.3;

          text-transform: uppercase;
        }

        .mobile-card-value {
          text-align: left;
        }

        .mobile-card-value .line-primary {
          font-size: 15px;
        }

        .mobile-card-value .line-secondary {
          line-height: 1.4;

          white-space: normal;
        }

        .mobile-card-value.disagreement {
          text-align: left;
        }

        .mobile-card-value .disagreement-note {
          white-space: normal;

          line-height: 1.35;
        }

        .mobile-card-value .total-signal {
          max-width: 100%;

          white-space: normal;

          line-height: 1.3;
        }


        /* ==============================================================
           MODEL SIGNAL / CONFIDENCE
        ============================================================== */

        .mobile-card-wide {
          display: grid;

          grid-template-columns:
            minmax(0, 1fr) auto;

          gap: 10px;

          align-items: center;

          padding: 13px 14px;

          border-bottom:
            1px solid #e9e9e5;
        }

        .mobile-card-wide:last-child {
          border-bottom: none;
        }

        .mobile-card-wide .mobile-card-label {
          margin: 0;
        }

        .mobile-card-wide .mobile-card-value {
          text-align: right;
        }

        .mobile-card-wide .status {
          max-width: 180px;

          white-space: normal;

          text-align: center;

          line-height: 1.25;
        }

        .mobile-card-confidence {
          grid-template-columns:
            minmax(0, 1fr) auto;
        }

        .mobile-card-confidence .signal-record {
          grid-column: 1 / -1;

          margin-top: 3px;

          color: var(--muted);

          font-family: var(--mono);
          font-size: 9px;
          line-height: 1.4;

          text-align: right;
        }


        /* ==============================================================
           DOSSIER / MATCHUP MOBILE HARDENING
        ============================================================== */

        #view-dossier,
        #view-matchup {
          width: 100%;
          max-width: 100%;

          overflow-x: hidden;
        }

        #view-dossier .panel-grid,
        #view-dossier .analysis-grid,
        #view-dossier .season-summary-grid,
        #view-matchup .panel-grid,
        #view-matchup .analysis-grid,
        #view-matchup .season-summary-grid {
          grid-template-columns:
            1fr !important;
        }

        #view-dossier .panel,
        #view-dossier .analysis-card,
        #view-dossier .season-summary-card,
        #view-matchup .panel,
        #view-matchup .analysis-card,
        #view-matchup .season-summary-card {
          min-width: 0;
          max-width: 100%;
        }

        #view-dossier .table-scroll,
        #view-matchup .table-scroll {
          max-width: 100%;

          overflow-x: auto;

          -webkit-overflow-scrolling:
            touch;
        }

        #view-dossier .metric-row,
        #view-matchup .metric-row {
          min-width: 0;
        }

        #view-dossier .metric-name,
        #view-matchup .metric-name {
          min-width: 0;

          overflow-wrap: anywhere;
        }

        #view-dossier .metric-value,
        #view-dossier .metric-rank,
        #view-matchup .metric-value,
        #view-matchup .metric-rank {
          white-space: nowrap;
        }


        /* ==============================================================
           EMPTY STATE
        ============================================================== */

        .mobile-projection-empty {
          padding: 40px 18px;

          text-align: center;

          color: var(--muted);

          background: var(--surface);

          border: 1px solid var(--border);
          border-radius: var(--radius);
        }
      }
    `;

    document.head.appendChild(style);
  }


  // ==========================================================================
  // HELPERS
  // ==========================================================================

  function createBlock(className) {
    const element =
      document.createElement("div");

    element.className =
      className;

    return element;
  }


  function copyCellContent(
    target,
    cell
  ) {
    if (
      !target ||
      !cell
    ) {
      return;
    }

    target.innerHTML =
      cell.innerHTML;
  }


  function addGridStat(
    grid,
    label,
    cell
  ) {
    const stat =
      createBlock(
        "mobile-card-stat"
      );

    const labelElement =
      createBlock(
        "mobile-card-label"
      );

    labelElement.textContent =
      label;

    const value =
      createBlock(
        "mobile-card-value"
      );

    copyCellContent(
      value,
      cell
    );

    stat.appendChild(
      labelElement
    );

    stat.appendChild(
      value
    );

    grid.appendChild(
      stat
    );
  }


  function addWideStat(
    card,
    label,
    cell,
    extraClass = ""
  ) {
    const row =
      createBlock(
        `mobile-card-wide ${extraClass}`.trim()
      );

    const labelElement =
      createBlock(
        "mobile-card-label"
      );

    labelElement.textContent =
      label;

    const value =
      createBlock(
        "mobile-card-value"
      );

    copyCellContent(
      value,
      cell
    );

    row.appendChild(
      labelElement
    );

    row.appendChild(
      value
    );

    const signalRecord =
      value.querySelector(
        ".signal-record"
      );

    if (signalRecord) {
      const recordClone =
        signalRecord.cloneNode(
          true
        );

      signalRecord.remove();

      row.appendChild(
        recordClone
      );
    }

    card.appendChild(
      row
    );
  }


  // ==========================================================================
  // GAME ID
  // ==========================================================================

  function gameIdFromRow(row) {
    if (!row) {
      return "";
    }

    if (
      row.dataset.gameId
    ) {
      return String(
        row.dataset.gameId
      );
    }

    const onclick =
      String(
        row.getAttribute(
          "onclick"
        ) || ""
      );

    const match =
      onclick.match(
        /openMatchup\(\s*['"]([^'"]+)['"]\s*\)/
      );

    if (
      match &&
      match[1]
    ) {
      return match[1];
    }

    return "";
  }


  // ==========================================================================
  // LOGO RESTORATION
  // ==========================================================================

  function restoreLogos(matchup) {
    if (!matchup) {
      return;
    }

    const teamLines =
      Array.from(
        matchup.querySelectorAll(
          ".team-line"
        )
      );

    teamLines.forEach(line => {
      if (
        line.querySelector(
          ".team-logo"
        )
      ) {
        return;
      }

      const teamName =
        line.querySelector(
          ".team-name"
        );

      if (!teamName) {
        return;
      }

      const name =
        String(
          teamName.textContent || ""
        ).trim();

      if (!name) {
        return;
      }

      if (
        typeof window.teamLogoMarkup !==
        "function"
      ) {
        return;
      }

      teamName.insertAdjacentHTML(
        "beforebegin",
        window.teamLogoMarkup(
          name,
          "projection"
        )
      );
    });
  }


  // ==========================================================================
  // CARD INTERACTION
  // ==========================================================================

  function attachCardInteraction(
    card,
    sourceRow
  ) {
    const gameId =
      gameIdFromRow(
        sourceRow
      );

    if (
      gameId &&
      typeof window.openMatchup ===
        "function"
    ) {
      card.dataset.gameId =
        gameId;

      card.setAttribute(
        "role",
        "button"
      );

      card.tabIndex = 0;

      const open =
        () => {
          window.openMatchup(
            gameId
          );
        };

      card.addEventListener(
        "click",
        event => {
          if (
            event.target.closest(
              ".team-name"
            )
          ) {
            return;
          }

          open();
        }
      );

      card.addEventListener(
        "keydown",
        event => {
          if (
            event.key !== "Enter" &&
            event.key !== " "
          ) {
            return;
          }

          event.preventDefault();

          open();
        }
      );
    }

    card
      .querySelectorAll(
        ".team-name"
      )
      .forEach(teamElement => {
        const teamName =
          String(
            teamElement.textContent || ""
          ).trim();

        if (!teamName) {
          return;
        }

        teamElement.addEventListener(
          "click",
          event => {
            event.preventDefault();
            event.stopPropagation();

            if (
              typeof window.openDossier ===
              "function"
            ) {
              window.openDossier(
                teamName
              );
            }
          }
        );
      });
  }


  // ==========================================================================
  // VIEWING NOTE
  // ==========================================================================

  function ensureViewingTip() {
    const projectionView =
      document.getElementById(
        "view-projections"
      );

    if (!projectionView) {
      return;
    }

    if (
      document.getElementById(
        "mobile-viewing-tip"
      )
    ) {
      return;
    }

    const subtitle =
      projectionView.querySelector(
        ".page-subtitle"
      );

    if (!subtitle) {
      return;
    }

    const tip =
      document.createElement(
        "div"
      );

    tip.id =
      "mobile-viewing-tip";

    tip.className =
      "mobile-viewing-tip";

    tip.innerHTML = `
      <div class="mobile-viewing-tip-title">
        Desktop Recommended
      </div>

      <div class="mobile-viewing-tip-copy">
        For the most complete analytics experience,
        The Hammer Index is best viewed on desktop.
        This mobile layout is optimized for quick access
        to projections, signals and matchup analysis.
      </div>
    `;

    subtitle.insertAdjacentElement(
      "afterend",
      tip
    );
  }


  // ==========================================================================
  // MOBILE HOST
  // ==========================================================================

  function ensureMobileHost() {
    const projectionView =
      document.getElementById(
        "view-projections"
      );

    if (!projectionView) {
      return null;
    }

    let host =
      document.getElementById(
        "mobile-projection-cards"
      );

    if (!host) {
      host =
        document.createElement(
          "div"
        );

      host.id =
        "mobile-projection-cards";

      host.setAttribute(
        "aria-live",
        "polite"
      );

      const tableCard =
        projectionView.querySelector(
          ".table-card"
        );

      if (tableCard) {
        tableCard.insertAdjacentElement(
          "afterend",
          host
        );
      }
    }

    return host;
  }


  // ==========================================================================
  // SOURCE SIGNATURE
  // ==========================================================================

  function sourceSignature(rows) {
    return rows
      .map(row => [
        gameIdFromRow(row),
        row.className,
        row.dataset.hammerGameState || "",
        row.hidden ? "1" : "0",
        row.innerHTML
      ].join("|"))
      .join("||");
  }


  // ==========================================================================
  // BUILD MOBILE CARDS
  // ==========================================================================

  function buildMobileCards() {
    buildTimer = null;
    buildFrame = null;

    const host =
      ensureMobileHost();

    const projectionContainer =
      document.getElementById(
        "projections-container"
      );

    if (
      !host ||
      !projectionContainer
    ) {
      return;
    }

    if (
      !mobileQuery.matches
    ) {
      lastSignature = "";

      host.replaceChildren();

      return;
    }

    const rows =
      Array.from(
        projectionContainer.querySelectorAll(
          ".projection-table tbody .game-row"
        )
      );

    if (!rows.length) {
      lastSignature = "";

      host.replaceChildren();

      const empty =
        projectionContainer.querySelector(
          ".empty-state"
        );

      if (empty) {
        const mobileEmpty =
          createBlock(
            "mobile-projection-empty"
          );

        mobileEmpty.innerHTML =
          empty.innerHTML;

        host.appendChild(
          mobileEmpty
        );
      }

      return;
    }

    /*
      Do not destroy/recreate the entire mobile board
      unless the source rows actually changed.

      This is especially important during LIVE Week 1
      status updates.
    */

    const signature =
      sourceSignature(
        rows
      );

    if (
      signature ===
      lastSignature
    ) {
      return;
    }

    lastSignature =
      signature;

    const fragment =
      document.createDocumentFragment();

    rows.forEach(sourceRow => {
      const cells =
        Array.from(
          sourceRow.querySelectorAll(
            ":scope > td"
          )
        );

      if (
        cells.length < 7
      ) {
        return;
      }

      const completed =
        sourceRow.classList.contains(
          "completed-row"
        );

      const live =
        sourceRow.classList.contains(
          "hammer-live-row"
        ) ||
        sourceRow.dataset.hammerGameState ===
          "live";

      const finalUntracked =
        sourceRow.classList.contains(
          "hammer-final-untracked-row"
        ) ||
        sourceRow.dataset.hammerGameState ===
          "final";

      const card =
        document.createElement(
          "article"
        );

      card.className =
        [
          "mobile-projection-card",
          completed
            ? "completed-row"
            : "",
          live
            ? "hammer-live-row"
            : "",
          finalUntracked
            ? "hammer-final-untracked-row"
            : ""
        ]
          .filter(Boolean)
          .join(" ");

      if (
        sourceRow.dataset.hammerGameState
      ) {
        card.dataset.hammerGameState =
          sourceRow.dataset.hammerGameState;
      }


      // ================================================================
      // MATCHUP
      // ================================================================

      const matchup =
        createBlock(
          "mobile-card-matchup"
        );

      copyCellContent(
        matchup,
        cells[0]
      );

      /*
        Week 1 live/final decorators can replace portions
        of the matchup cell.

        If that mutation removed logo HTML, put it back
        from teamLogoMarkup().
      */

      restoreLogos(
        matchup
      );

      card.appendChild(
        matchup
      );


      // ================================================================
      // MAIN STATS
      // ================================================================

      const grid =
        createBlock(
          "mobile-card-grid"
        );

      if (completed) {
        addGridStat(
          grid,
          "FROZEN LINE",
          cells[1]
        );

        addGridStat(
          grid,
          "CLOSING LINE",
          cells[2]
        );

        addGridStat(
          grid,
          "PROJECTED SCORE",
          cells[3]
        );

        addGridStat(
          grid,
          "ATS RESULT",
          cells[4]
        );
      } else {
        addGridStat(
          grid,
          "FAIR LINE",
          cells[1]
        );

        addGridStat(
          grid,
          "MARKET",
          cells[2]
        );

        addGridStat(
          grid,
          "PROJECTED TOTAL",
          cells[3]
        );

        addGridStat(
          grid,
          "MODEL EDGE",
          cells[4]
        );
      }

      card.appendChild(
        grid
      );


      // ================================================================
      // SIGNAL + CONFIDENCE
      // ================================================================

      addWideStat(
        card,
        "MODEL SIGNAL",
        cells[5]
      );

      addWideStat(
        card,
        "SIGNAL CONFIDENCE",
        cells[6],
        "mobile-card-confidence"
      );


      // ================================================================
      // REAL MOBILE CLICK HANDLERS
      // ================================================================

      attachCardInteraction(
        card,
        sourceRow
      );

      fragment.appendChild(
        card
      );
    });

    host.replaceChildren(
      fragment
    );
  }


  // ==========================================================================
  // STABLE / DEBOUNCED BUILD
  // ==========================================================================

  function scheduleBuild() {
    if (
      buildTimer !== null ||
      buildFrame !== null
    ) {
      return;
    }

    /*
      Give sort-tables / live-score decorators a moment
      to finish a complete DOM mutation burst before
      rebuilding the mobile cards.
    */

    buildTimer =
      window.setTimeout(
        () => {
          buildTimer = null;

          buildFrame =
            window.requestAnimationFrame(
              () => {
                buildFrame = null;

                buildMobileCards();
              }
            );
        },
        90
      );
  }


  // ==========================================================================
  // OBSERVER
  // ==========================================================================

  function installObserver() {
    const projectionContainer =
      document.getElementById(
        "projections-container"
      );

    if (!projectionContainer) {
      window.setTimeout(
        installObserver,
        100
      );

      return;
    }

    const observer =
      new MutationObserver(
        () => {
          scheduleBuild();
        }
      );

    observer.observe(
      projectionContainer,
      {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: [
          "class",
          "data-hammer-game-state"
        ]
      }
    );
  }


  // ==========================================================================
  // START
  // ==========================================================================

  function startMobileAdapter() {
    installMobileStyles();

    ensureViewingTip();

    ensureMobileHost();

    installObserver();

    scheduleBuild();

    window.setTimeout(
      scheduleBuild,
      300
    );

    window.setTimeout(
      scheduleBuild,
      900
    );

    window.setTimeout(
      scheduleBuild,
      1800
    );
  }


  document.addEventListener(
    "hammer:data-ready",
    scheduleBuild
  );


  if (
    typeof mobileQuery.addEventListener ===
    "function"
  ) {
    mobileQuery.addEventListener(
      "change",
      () => {
        lastSignature = "";

        scheduleBuild();
      }
    );
  } else {
    mobileQuery.addListener(
      () => {
        lastSignature = "";

        scheduleBuild();
      }
    );
  }


  window.addEventListener(
    "resize",
    scheduleBuild,
    {
      passive: true
    }
  );


  if (
    document.readyState ===
    "loading"
  ) {
    document.addEventListener(
      "DOMContentLoaded",
      startMobileAdapter,
      {
        once: true
      }
    );
  } else {
    startMobileAdapter();
  }
})();
