(() => {
  "use strict";

  const mobileQuery = window.matchMedia("(max-width: 600px)");
  let scheduled = false;

  /* =========================================================
     MOBILE-ONLY STYLES
     Nothing in this block applies above 600px.
  ========================================================= */

  function installMobileStyles() {
    if (document.getElementById("hammer-mobile-styles")) return;

    const style = document.createElement("style");
    style.id = "hammer-mobile-styles";

    style.textContent = `
      #mobile-projection-cards,
      .mobile-viewing-tip {
        display: none;
      }

      @media (max-width: 600px) {

        /* =========================================
           MOBILE VIEWING RECOMMENDATION
        ========================================= */

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


        /* =========================================
           HIDE DESKTOP PROJECTION TABLE ON MOBILE
        ========================================= */

        #view-projections > .table-card {
          display: none !important;
        }


        /* =========================================
           MOBILE PROJECTION BOARD
        ========================================= */

        #mobile-projection-cards {
          display: grid;
          gap: 12px;
          width: 100%;
          margin-top: 4px;
        }

        .mobile-projection-card {
          width: 100%;
          min-width: 0;
          overflow: hidden;

          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: var(--radius);

          cursor: pointer;
        }

        .mobile-projection-card * {
          min-width: 0;
        }


        /* =========================================
           MATCHUP
        ========================================= */

        .mobile-card-matchup {
          padding: 16px;
          border-bottom: 1px solid #e9e9e5;
        }

        .mobile-card-matchup .team-line {
          min-height: 28px;
        }

        .mobile-card-matchup .team-name {
          font-size: 15px;
        }

        .mobile-card-matchup .team-meta {
          font-size: 10px;
        }


        /* =========================================
           FAIR LINE / MARKET / TOTAL / EDGE GRID
        ========================================= */

        .mobile-card-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .mobile-card-stat {
          padding: 13px 14px;
          border-bottom: 1px solid #e9e9e5;
        }

        .mobile-card-stat:nth-child(odd) {
          border-right: 1px solid #e9e9e5;
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


        /* =========================================
           MODEL SIGNAL / CONFIDENCE
        ========================================= */

        .mobile-card-wide {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          gap: 10px;
          align-items: center;

          padding: 13px 14px;
          border-bottom: 1px solid #e9e9e5;
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
          grid-template-columns: minmax(0, 1fr) auto;
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


        /* =========================================
           EMPTY STATE
        ========================================= */

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


  /* =========================================================
     HELPERS
  ========================================================= */

  function createBlock(className) {
    const element = document.createElement("div");
    element.className = className;
    return element;
  }

  function copyCellContent(target, cell) {
    if (!target || !cell) return;
    target.innerHTML = cell.innerHTML;
  }

  function addGridStat(grid, label, cell) {
    const stat = createBlock("mobile-card-stat");

    const labelElement = createBlock("mobile-card-label");
    labelElement.textContent = label;

    const value = createBlock("mobile-card-value");
    copyCellContent(value, cell);

    stat.appendChild(labelElement);
    stat.appendChild(value);

    grid.appendChild(stat);
  }

  function addWideStat(card, label, cell, extraClass = "") {
    const row = createBlock(
      `mobile-card-wide ${extraClass}`.trim()
    );

    const labelElement = createBlock("mobile-card-label");
    labelElement.textContent = label;

    const value = createBlock("mobile-card-value");
    copyCellContent(value, cell);

    row.appendChild(labelElement);
    row.appendChild(value);

    const signalRecord = value.querySelector(".signal-record");

    if (signalRecord) {
      const recordClone = signalRecord.cloneNode(true);

      signalRecord.remove();

      row.appendChild(recordClone);
    }

    card.appendChild(row);
  }


  /* =========================================================
     MOBILE VIEWING RECOMMENDATION
  ========================================================= */

  function ensureViewingTip() {
    const projectionView =
      document.getElementById("view-projections");

    if (!projectionView) return;

    if (document.getElementById("mobile-viewing-tip")) {
      return;
    }

    const subtitle =
      projectionView.querySelector(".page-subtitle");

    if (!subtitle) return;

    const tip = document.createElement("div");

    tip.id = "mobile-viewing-tip";
    tip.className = "mobile-viewing-tip";

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


  /* =========================================================
     MOBILE PROJECTION CARD HOST
  ========================================================= */

  function ensureMobileHost() {
    const projectionView =
      document.getElementById("view-projections");

    if (!projectionView) return null;

    let host =
      document.getElementById("mobile-projection-cards");

    if (!host) {
      host = document.createElement("div");

      host.id = "mobile-projection-cards";
      host.setAttribute("aria-live", "polite");

      const tableCard =
        projectionView.querySelector(".table-card");

      if (tableCard) {
        tableCard.insertAdjacentElement(
          "afterend",
          host
        );
      }
    }

    return host;
  }


  /* =========================================================
     BUILD MOBILE CARDS FROM FINAL UX TABLE
  ========================================================= */

  function buildMobileCards() {
    scheduled = false;

    const host = ensureMobileHost();

    const projectionContainer =
      document.getElementById("projections-container");

    if (!host || !projectionContainer) return;

    /*
      Desktop:
      remove generated mobile cards from memory/display,
      but leave the real desktop table completely untouched.
    */

    if (!mobileQuery.matches) {
      host.replaceChildren();
      return;
    }

    const rows = Array.from(
      projectionContainer.querySelectorAll(
        ".projection-table tbody .game-row"
      )
    );

    /*
      Handle loading / empty states.
    */

    if (!rows.length) {
      host.replaceChildren();

      const empty =
        projectionContainer.querySelector(".empty-state");

      if (empty) {
        const mobileEmpty =
          createBlock("mobile-projection-empty");

        mobileEmpty.innerHTML =
          empty.innerHTML;

        host.appendChild(mobileEmpty);
      }

      return;
    }

    const fragment =
      document.createDocumentFragment();

    rows.forEach((sourceRow) => {
      const cells = Array.from(
        sourceRow.querySelectorAll(":scope > td")
      );

      if (cells.length < 7) return;

      const completed =
        sourceRow.classList.contains(
          "completed-row"
        );

      const card =
        document.createElement("article");

      card.className = completed
        ? "mobile-projection-card completed-row"
        : "mobile-projection-card";

      /*
        Preserve the game's openMatchup() click behavior.
      */

      const rowClick =
        sourceRow.getAttribute("onclick");

      if (rowClick) {
        card.setAttribute(
          "onclick",
          rowClick
        );
      }


      /* =========================================
         MATCHUP
      ========================================= */

      const matchup =
        createBlock("mobile-card-matchup");

      copyCellContent(
        matchup,
        cells[0]
      );

      card.appendChild(matchup);


      /* =========================================
         MAIN STAT GRID
      ========================================= */

      const grid =
        createBlock("mobile-card-grid");

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

      card.appendChild(grid);


      /* =========================================
         SIGNAL + CONFIDENCE
      ========================================= */

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

      fragment.appendChild(card);
    });

    host.replaceChildren(fragment);
  }


  /* =========================================================
     SCHEDULING
  ========================================================= */

  function scheduleBuild() {
    if (scheduled) return;

    scheduled = true;

    window.requestAnimationFrame(
      buildMobileCards
    );
  }


  /* =========================================================
     WATCH THE FINAL PROJECTION RENDERER
  ========================================================= */

  function installObserver() {
    const projectionContainer =
      document.getElementById("projections-container");

    if (!projectionContainer) return;

    const observer =
      new MutationObserver(() => {
        scheduleBuild();
      });

    observer.observe(
      projectionContainer,
      {
        childList: true,
        subtree: true
      }
    );
  }


  /* =========================================================
     START
  ========================================================= */

  function startMobileAdapter() {
    installMobileStyles();
    ensureViewingTip();
    ensureMobileHost();
    installObserver();
    scheduleBuild();

    /*
      Extra passes account for app.js / ux-v2.js
      rendering asynchronously.
    */

    window.setTimeout(
      scheduleBuild,
      250
    );

    window.setTimeout(
      scheduleBuild,
      1000
    );
  }


  /*
    Rebuild whenever Hammer data finishes loading.
  */

  document.addEventListener(
    "hammer:data-ready",
    scheduleBuild
  );


  /*
    Rebuild if crossing the mobile/desktop breakpoint.
  */

  if (
    typeof mobileQuery.addEventListener ===
    "function"
  ) {
    mobileQuery.addEventListener(
      "change",
      scheduleBuild
    );
  } else {
    mobileQuery.addListener(
      scheduleBuild
    );
  }


  /*
    Resize fallback.
  */

  window.addEventListener(
    "resize",
    scheduleBuild
  );


  /*
    Initialize after HTML exists.
  */

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      startMobileAdapter,
      { once: true }
    );
  } else {
    startMobileAdapter();
  }

})();
