(() => {
  "use strict";

  // ==========================================================================
  // THE HAMMER INDEX — USER FEEDBACK UX POLISH
  //
  // 1) Matchup Analysis: after a valid Team A selection, focus Team B.
  // 2) Matchup Analysis: default Location to Team B home on first load.
  // 3) Projections: keep the column header visible while scrolling on desktop.
  //
  // Presentation/interaction only. No model calculations or data are changed.
  // ==========================================================================

  const TAPE_CONTAINER_ID = "tape-container";
  const TEAM_A_ID = "matchup-team-a";
  const TEAM_B_ID = "matchup-team-b";
  const VENUE_ID = "matchup-venue";

  const PROJECTION_VIEW_ID = "view-projections";
  const PROJECTION_CONTAINER_ID = "projections-container";
  const STICKY_ID = "hammer-sticky-projection-header";

  const MOBILE_BREAKPOINT = 600;

  let venueDefaultApplied = false;
  let lastFocusedTeamA = "";

  let stickyShell = null;
  let stickyTable = null;
  let stickySourceTable = null;
  let stickySourceScroll = null;
  let stickyVisible = false;
  let stickyFrame = null;


  // ==========================================================================
  // MATCHUP ANALYSIS — TEAM A -> TEAM B
  // ==========================================================================

  function validMatchupTeamNames() {
    return new Set(
      Array.from(
        document.querySelectorAll("#matchup-team-options option")
      )
        .map(option => String(option.value || "").trim())
        .filter(Boolean)
    );
  }

  function focusTeamBAfterValidTeamA() {
    const teamA = document.getElementById(TEAM_A_ID);
    const teamB = document.getElementById(TEAM_B_ID);

    if (!teamA || !teamB) return;

    const value = String(teamA.value || "").trim();
    if (!value) return;

    const validNames = validMatchupTeamNames();
    if (!validNames.has(value)) return;

    // Prevent repeated focus jumps if another DOM/input event fires
    // for the same already-selected Team A.
    if (value === lastFocusedTeamA) return;
    lastFocusedTeamA = value;

    window.requestAnimationFrame(() => {
      const currentTeamB = document.getElementById(TEAM_B_ID);
      if (!currentTeamB) return;

      currentTeamB.focus();

      // Highlight an existing value so typing immediately replaces it.
      if (currentTeamB.value && typeof currentTeamB.select === "function") {
        currentTeamB.select();
      }
    });
  }


  // ==========================================================================
  // MATCHUP ANALYSIS — DEFAULT TEAM B HOME
  // ==========================================================================

  function applyInitialVenueDefault() {
    if (venueDefaultApplied) return;

    const venue = document.getElementById(VENUE_ID);
    if (!venue) return;

    const teamBHome = Array.from(venue.options || []).some(
      option => option.value === "team_b_home"
    );

    if (!teamBHome) return;

    venue.value = "team_b_home";
    venueDefaultApplied = true;
  }

  function hardenMatchupControls() {
    applyInitialVenueDefault();
  }

  function installMatchupUx() {
    const container = document.getElementById(TAPE_CONTAINER_ID);

    if (!container) {
      window.setTimeout(installMatchupUx, 100);
      return;
    }

    container.addEventListener("input", event => {
      if (event.target?.id !== TEAM_A_ID) return;
      focusTeamBAfterValidTeamA();
    });

    container.addEventListener("change", event => {
      if (event.target?.id !== TEAM_A_ID) return;
      focusTeamBAfterValidTeamA();
    });

    const observer = new MutationObserver(() => {
      hardenMatchupControls();
    });

    observer.observe(container, {
      childList: true,
      subtree: true
    });

    hardenMatchupControls();
  }


  // ==========================================================================
  // PROJECTIONS — FLOATING/STICKY COLUMN HEADER
  //
  // A cloned header is used instead of relying on CSS position: sticky because
  // the projection table lives inside a horizontal overflow container.
  // This keeps desktop horizontal scrolling intact and does not modify rows.
  // ==========================================================================

  function projectionViewIsActive() {
    const view = document.getElementById(PROJECTION_VIEW_ID);
    return Boolean(view?.classList.contains("active"));
  }

  function desktopStickyEnabled() {
    return window.innerWidth > MOBILE_BREAKPOINT;
  }

  function buildStickyShell() {
    if (stickyShell) return;

    stickyShell = document.createElement("div");
    stickyShell.id = STICKY_ID;

    Object.assign(stickyShell.style, {
      display: "none",
      position: "fixed",
      overflow: "hidden",
      zIndex: "95",
      background: "#f7f7f5",
      borderTop: "1px solid var(--border)",
      borderBottom: "1px solid var(--border)",
      boxShadow: "0 2px 8px rgba(24, 33, 43, 0.08)",
      pointerEvents: "none"
    });

    stickyTable = document.createElement("table");

    Object.assign(stickyTable.style, {
      borderCollapse: "collapse",
      tableLayout: "fixed",
      margin: "0",
      background: "#f7f7f5"
    });

    stickyShell.appendChild(stickyTable);
    document.body.appendChild(stickyShell);
  }

  function hideStickyHeader() {
    if (!stickyShell) return;
    stickyShell.style.display = "none";
    stickyVisible = false;
  }

  function syncStickyHeaderContent(sourceTable) {
    const sourceHead = sourceTable?.tHead;
    if (!sourceHead || !stickyTable) return;

    stickyTable.innerHTML = "";
    stickyTable.appendChild(sourceHead.cloneNode(true));

    const sourceCells = Array.from(
      sourceHead.rows?.[0]?.cells || []
    );

    const cloneCells = Array.from(
      stickyTable.tHead?.rows?.[0]?.cells || []
    );

    sourceCells.forEach((cell, index) => {
      const width = cell.getBoundingClientRect().width;
      const clone = cloneCells[index];
      if (!clone) return;

      clone.style.width = `${width}px`;
      clone.style.minWidth = `${width}px`;
      clone.style.maxWidth = `${width}px`;
    });

    stickyTable.style.width = `${sourceTable.getBoundingClientRect().width}px`;
  }

  function locateProjectionTable() {
    const container = document.getElementById(PROJECTION_CONTAINER_ID);
    if (!container) return null;

    const table = container.querySelector(".projection-table");
    if (!table?.tHead) return null;

    const scroll = table.closest(".table-scroll");
    if (!scroll) return null;

    return { table, scroll };
  }

  function updateStickyHeaderNow() {
    stickyFrame = null;

    if (!desktopStickyEnabled() || !projectionViewIsActive()) {
      hideStickyHeader();
      return;
    }

    const located = locateProjectionTable();
    if (!located) {
      hideStickyHeader();
      return;
    }

    const { table, scroll } = located;
    const sourceHead = table.tHead;

    if (!sourceHead) {
      hideStickyHeader();
      return;
    }

    buildStickyShell();

    const siteHeader = document.querySelector(".site-header");
    const stickyTop = Math.max(
      0,
      siteHeader?.getBoundingClientRect().bottom || 0
    );

    const headRect = sourceHead.getBoundingClientRect();
    const tableRect = table.getBoundingClientRect();
    const scrollRect = scroll.getBoundingClientRect();

    const shouldShow =
      headRect.top < stickyTop &&
      tableRect.bottom > stickyTop + headRect.height;

    if (!shouldShow) {
      hideStickyHeader();
      return;
    }

    const sourceChanged = stickySourceTable !== table;

    if (sourceChanged || !stickyVisible) {
      stickySourceTable = table;
      stickySourceScroll = scroll;
      syncStickyHeaderContent(table);
    } else {
      // Keep widths/text current after THI terminology or responsive changes.
      syncStickyHeaderContent(table);
    }

    stickyShell.style.display = "block";
    stickyShell.style.top = `${stickyTop}px`;
    stickyShell.style.left = `${scrollRect.left}px`;
    stickyShell.style.width = `${scrollRect.width}px`;
    stickyShell.style.height = `${headRect.height}px`;

    stickyTable.style.transform =
      `translateX(${-Number(scroll.scrollLeft || 0)}px)`;

    stickyVisible = true;
  }

  function queueStickyHeaderUpdate() {
    if (stickyFrame !== null) return;

    stickyFrame = window.requestAnimationFrame(
      updateStickyHeaderNow
    );
  }

  function installStickyProjectionHeader() {
    buildStickyShell();

    window.addEventListener(
      "scroll",
      queueStickyHeaderUpdate,
      { passive: true }
    );

    window.addEventListener(
      "resize",
      queueStickyHeaderUpdate,
      { passive: true }
    );

    document.addEventListener(
      "hammer:data-ready",
      queueStickyHeaderUpdate
    );

    const projectionContainer =
      document.getElementById(PROJECTION_CONTAINER_ID);

    if (projectionContainer) {
      const observer = new MutationObserver(
        queueStickyHeaderUpdate
      );

      observer.observe(projectionContainer, {
        childList: true,
        subtree: true,
        characterData: true
      });

      projectionContainer.addEventListener(
        "scroll",
        queueStickyHeaderUpdate,
        true
      );
    }

    // Horizontal table scrolling happens on .table-scroll, which may not
    // exist yet when this script starts. Capture scroll events globally.
    document.addEventListener(
      "scroll",
      event => {
        if (
          event.target instanceof Element &&
          event.target.classList.contains("table-scroll")
        ) {
          queueStickyHeaderUpdate();
        }
      },
      true
    );

    queueStickyHeaderUpdate();
  }


  // ==========================================================================
  // STARTUP
  // ==========================================================================

  function start() {
    installMatchupUx();
    installStickyProjectionHeader();
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
