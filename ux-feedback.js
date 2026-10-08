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
    stickyShell.className = "hammer-sticky-projection-header";

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
    stickyTable.className = "projection-table hammer-sticky-projection-table";

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
  // PUBLIC TERMINOLOGY — THI NAMING
  //
  // Keep the public product vocabulary consistent:
  //   THI Spread = our projected/fair spread
  //   THI Total  = our projected total
  //
  // Backend/model field names are intentionally untouched.
  // ==========================================================================

  const TERMINOLOGY_MAP = new Map([
    ["Our Line", "THI Spread"],
    ["Fair Line", "THI Spread"],
    ["Model Line", "THI Spread"],
    ["Model Total", "THI Total"],
    ["Projected Total", "THI Total"],
    ["Final fair line", "THI Spread"],
    ["Model-implied spread", "THI projected spread"],
    ["Pregame Hammer fair line", "Pregame THI spread"],
    ["Pregame model fair line", "Pregame THI spread"],
    ["Historical model fair line", "Historical THI spread"],
    ["Frozen public line", "Frozen THI spread"],
    ["Model total", "THI Total"],
    ["Pregame projected total", "Pregame THI total"],
    ["Historical projected total", "Historical THI total"]
  ]);

  function applyThiTerminology(root = document) {
    const selectors = [
      "#view-projections th",
      "#view-projections .line-secondary",
      "#view-projections .mobile-card-label",
      "#view-matchup .analysis-label",
      "#view-matchup .analysis-row-label",
      "#view-matchup .line-secondary",
      "#view-tape .tape-summary-label",
      "#view-tape .metric-name",
      "#view-tape .analysis-label",
      "#view-tape .analysis-row-label"
    ].join(", ");

    root.querySelectorAll(selectors).forEach(element => {
      const current = String(element.textContent || "").trim();
      const replacement = TERMINOLOGY_MAP.get(current);

      if (replacement && replacement !== current) {
        element.textContent = replacement;
      }
    });
  }

  function installTerminologyObserver() {
    applyThiTerminology();

    const targets = [
      document.getElementById("projections-container"),
      document.getElementById("matchup-container"),
      document.getElementById("tape-container"),
      document.getElementById("mobile-projection-cards")
    ].filter(Boolean);

    targets.forEach(target => {
      const observer = new MutationObserver(() => {
        applyThiTerminology(target);
        queueStickyHeaderUpdate();
      });

      observer.observe(target, {
        childList: true,
        subtree: true,
        characterData: true
      });
    });

    document.addEventListener("hammer:data-ready", () => {
      window.requestAnimationFrame(() => {
        applyThiTerminology();
        queueStickyHeaderUpdate();
      });
    });

    window.setTimeout(() => {
      applyThiTerminology();
      queueStickyHeaderUpdate();
    }, 250);

    window.setTimeout(() => {
      applyThiTerminology();
      queueStickyHeaderUpdate();
    }, 1000);
  }



  // ==========================================================================

  // ==========================================================================
  // PROJECTIONS — COLLAPSIBLE METHODOLOGY PANEL
  // ==========================================================================

  function makeSignalGuidePersistent() {
    const guide = document.querySelector("#view-projections details.signal-guide");
    if (!guide || guide.dataset.hammerPersistentGuide === "1") return;

    guide.dataset.hammerPersistentGuide = "1";
    guide.open = false;

    const summary = guide.querySelector(":scope > summary");
    if (summary) {
      summary.style.cursor = "pointer";
      summary.style.pointerEvents = "auto";
      summary.removeAttribute("aria-disabled");
    }
  }


  // FIRST-VISIT WELCOME
  // ==========================================================================

  const WELCOME_STORAGE_KEY = "thi-welcome-v1-seen";
  const WELCOME_ID = "thi-welcome-overlay";

  function welcomeAlreadySeen() {
    try {
      return window.localStorage.getItem(WELCOME_STORAGE_KEY) === "1";
    } catch {
      return false;
    }
  }

  function markWelcomeSeen() {
    try {
      window.localStorage.setItem(WELCOME_STORAGE_KEY, "1");
    } catch {
      // If storage is unavailable, simply allow the site to continue normally.
    }
  }

  function closeWelcome() {
    const overlay = document.getElementById(WELCOME_ID);
    if (!overlay) return;

    markWelcomeSeen();
    overlay.remove();
    document.body.style.overflow = "";
  }

  function installWelcomeModal() {
    if (welcomeAlreadySeen() || document.getElementById(WELCOME_ID)) return;

    const overlay = document.createElement("div");
    overlay.id = WELCOME_ID;
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "thi-welcome-title");

    Object.assign(overlay.style, {
      position: "fixed",
      inset: "0",
      zIndex: "10000",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "20px",
      background: "rgba(15, 23, 32, 0.72)",
      backdropFilter: "blur(5px)"
    });

    const modal = document.createElement("div");
    Object.assign(modal.style, {
      width: "min(520px, 100%)",
      maxHeight: "calc(100vh - 40px)",
      overflowY: "auto",
      background: "#fff",
      border: "1px solid var(--border, #d8d8d4)",
      borderRadius: "16px",
      boxShadow: "0 24px 70px rgba(0, 0, 0, 0.28)",
      padding: "28px",
      color: "#17212b"
    });

    modal.innerHTML = `
      <div style="font-size:32px; line-height:1; margin-bottom:14px;">🔨</div>
      <div style="font-family:var(--mono, monospace); font-size:12px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; color:#8a6a00; margin-bottom:8px;">
        Welcome to
      </div>
      <h2 id="thi-welcome-title" style="margin:0 0 12px; font-size:28px; line-height:1.08; color:#111827;">
        The Hammer Index
      </h2>
      <p style="margin:0 0 16px; line-height:1.6; color:#4b5563;">
        A college football and college basketball analytics platform built to create an independent view of every matchup.
      </p>
      <p style="margin:0 0 20px; line-height:1.6; color:#4b5563;">
        Explore <strong>THI Spreads</strong>, <strong>THI Totals</strong>, projected scores, win probabilities, team and player ratings, matchup analysis and transparent model tracking.
      </p>
      <div style="padding:13px 14px; margin-bottom:12px; border-radius:10px; background:#fff8dc; border:1px solid #e7c967; font-size:13px; line-height:1.5;">
        <strong>THI is independent of the sportsbook line.</strong> Market odds are used for comparison — not to create the model's projection.
      </div>
      <div style="padding:13px 14px; margin-bottom:22px; border-radius:10px; background:#f3f4f6; border:1px solid #d1d5db; font-size:13px; line-height:1.5; color:#4b5563;">
        <strong>Beta / Testing:</strong> The Hammer Index is actively being tested and refined. The site is available to use for analysis, research and entertainment, but projections and features may change as feedback and new data are incorporated. Nothing on THI should be considered financial or betting advice.
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <button id="thi-welcome-account" type="button" style="border:0; border-radius:10px; padding:13px 16px; cursor:pointer; font:inherit; font-weight:800; background:#b99726; color:#111827;">Create free account</button>
        <button id="thi-welcome-enter" type="button" style="border:0; border-radius:10px; padding:13px 16px; cursor:pointer; font:inherit; font-weight:800; background:#1f2937; color:#fff;">Continue exploring →</button>
      </div>
    `;

    overlay.appendChild(modal);
    document.body.appendChild(overlay);
    document.body.style.overflow = "hidden";

    const button = modal.querySelector("#thi-welcome-enter");
    button?.addEventListener("click", closeWelcome);
    modal.querySelector("#thi-welcome-account")?.addEventListener("click", () => {
      closeWelcome();
      window.THIAccount?.open?.();
    });

    overlay.addEventListener("click", event => {
      if (event.target === overlay) closeWelcome();
    });

    document.addEventListener("keydown", function escapeWelcome(event) {
      if (event.key !== "Escape") return;
      if (!document.getElementById(WELCOME_ID)) return;
      closeWelcome();
      document.removeEventListener("keydown", escapeWelcome);
    });

    window.requestAnimationFrame(() => button?.focus());
  }


  // ==========================================================================
  // STARTUP
  // ==========================================================================


  // ==========================================================================
  // RATINGS + TRANSFER PORTAL TABLE READABILITY
  //
  // Ratings Advanced mode has many columns. Give it a real horizontal-scroll
  // surface and enough intrinsic width so headers/values do not get crushed.
  //
  // Transfer Portal class rankings had mixed header/cell alignment, which made
  // values look like they belonged to the wrong columns. Normalize widths and
  // numeric alignment without changing any data or sorting.
  // ==========================================================================

  function installWideTableFixes() {
    if (document.getElementById("hammer-wide-table-fixes")) return;

    const style = document.createElement("style");
    style.id = "hammer-wide-table-fixes";
    style.textContent = `
      /* -------------------------
         TEAM RATINGS
      -------------------------- */

      /* Overview/conference tables keep their normal responsive behavior. */
      #view-ratings .table-scroll {
        width: 100%;
        max-width: 100%;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
      }

      /* Only the 15-column Advanced Ratings table becomes a true wide table. */
      #view-ratings .table-scroll.hammer-advanced-ratings-scroll {
        overflow-x: auto !important;
        overflow-y: hidden;
        overscroll-behavior-x: contain;
        scrollbar-gutter: stable;
      }

      #view-ratings .table-scroll.hammer-advanced-ratings-scroll .projection-table {
        width: 1780px !important;
        min-width: 1780px !important;
      }

      #view-ratings .table-scroll.hammer-advanced-ratings-scroll th,
      #view-ratings .table-scroll.hammer-advanced-ratings-scroll td {
        white-space: nowrap;
      }

      /* Always-visible scrollbar above Advanced Ratings. */
      #view-ratings .hammer-ratings-top-scroll {
        width: 100%;
        max-width: 100%;
        overflow-x: auto;
        overflow-y: hidden;
        height: 16px;
        background: #f7f7f5;
        border-top: 1px solid var(--border);
        border-bottom: 1px solid var(--border);
        scrollbar-gutter: stable;
      }

      #view-ratings .hammer-ratings-top-scroll-inner {
        height: 1px;
        width: 1780px;
      }

      #view-ratings .hammer-ratings-top-scroll::-webkit-scrollbar,
      #view-ratings .table-scroll.hammer-advanced-ratings-scroll::-webkit-scrollbar {
        height: 12px;
      }

      #view-ratings .hammer-ratings-top-scroll::-webkit-scrollbar-track,
      #view-ratings .table-scroll.hammer-advanced-ratings-scroll::-webkit-scrollbar-track {
        background: #f1f1ee;
      }

      #view-ratings .hammer-ratings-top-scroll::-webkit-scrollbar-thumb,
      #view-ratings .table-scroll.hammer-advanced-ratings-scroll::-webkit-scrollbar-thumb {
        background: #aaa9a3;
        border-radius: 999px;
        border: 2px solid #f1f1ee;
      }

      /* -------------------------
         TRANSFER PORTAL
      -------------------------- */
      #view-portal .pv-table-wrap {
        width: 100%;
        max-width: 100%;
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch;
        overscroll-behavior-x: contain;
        scrollbar-gutter: stable;
      }

      #view-portal .pv-table {
        width: 100%;
        min-width: 1040px;
        table-layout: fixed;
      }

      #view-portal .pv-table th,
      #view-portal .pv-table td {
        box-sizing: border-box;
        vertical-align: middle;
      }

      #view-portal .pv-table th:nth-child(1),
      #view-portal .pv-table td:nth-child(1) {
        width: 6%;
        text-align: left;
      }

      #view-portal .pv-table th:nth-child(2),
      #view-portal .pv-table td:nth-child(2) {
        width: 20%;
        text-align: left;
      }

      #view-portal .pv-table th:nth-child(3),
      #view-portal .pv-table td:nth-child(3),
      #view-portal .pv-table th:nth-child(4),
      #view-portal .pv-table td:nth-child(4) {
        width: 7%;
        text-align: right;
      }

      #view-portal .pv-table th:nth-child(5),
      #view-portal .pv-table td:nth-child(5) {
        width: 10%;
        text-align: right;
      }

      #view-portal .pv-table th:nth-child(6),
      #view-portal .pv-table td:nth-child(6),
      #view-portal .pv-table th:nth-child(7),
      #view-portal .pv-table td:nth-child(7) {
        width: 10%;
        text-align: right;
      }

      #view-portal .pv-table th:nth-child(8),
      #view-portal .pv-table td:nth-child(8) {
        width: 12%;
        text-align: right;
      }

      #view-portal .pv-table th:nth-child(9),
      #view-portal .pv-table td:nth-child(9) {
        width: 8%;
        text-align: right;
      }

      #view-portal .pv-table td:nth-child(n+3) {
        font-variant-numeric: tabular-nums;
      }

      #view-portal .pv-table th:nth-child(n+3) {
        text-align: right !important;
      }

      #view-portal .pv-table-wrap::-webkit-scrollbar {
        height: 10px;
      }

      #view-portal .pv-table-wrap::-webkit-scrollbar-track {
        background: #f1f1ee;
      }

      #view-portal .pv-table-wrap::-webkit-scrollbar-thumb {
        background: #c9c9c3;
        border-radius: 999px;
        border: 2px solid #f1f1ee;
      }

      @media (max-width: 600px) {
        #view-ratings .table-scroll.hammer-advanced-ratings-scroll .projection-table {
          width: 1600px !important;
          min-width: 1600px !important;
        }

        #view-ratings .hammer-ratings-top-scroll-inner {
          width: 1600px;
        }

        #view-portal .pv-table {
          min-width: 900px;
        }
      }
    `;

    document.head.appendChild(style);

    const ratingsContainer = document.getElementById("ratings-container");
    if (!ratingsContainer) return;

    let syncingRatingsScroll = false;

    function wireAdvancedRatingsScroll() {
      const scrolls = Array.from(
        ratingsContainer.querySelectorAll(".table-scroll")
      );

      // app.js renders Advanced Ratings with 15 headers. Overview has 8 and
      // Conference Standings has 11, so this targets Advanced only.
      const advancedScroll = scrolls.find(scroll => {
        const table = scroll.querySelector(".projection-table");
        return (table?.querySelectorAll("thead th").length || 0) >= 15;
      });

      // Remove a stale top bar when the user switches away from Advanced.
      ratingsContainer
        .querySelectorAll(".hammer-ratings-top-scroll")
        .forEach(bar => {
          if (!advancedScroll || bar.nextElementSibling !== advancedScroll) {
            bar.remove();
          }
        });

      scrolls.forEach(scroll => {
        scroll.classList.toggle(
          "hammer-advanced-ratings-scroll",
          scroll === advancedScroll
        );
      });

      if (!advancedScroll) return;

      let topBar = advancedScroll.previousElementSibling;
      if (!topBar?.classList.contains("hammer-ratings-top-scroll")) {
        topBar = document.createElement("div");
        topBar.className = "hammer-ratings-top-scroll";
        topBar.setAttribute(
          "aria-label",
          "Scroll Advanced Ratings horizontally"
        );

        const inner = document.createElement("div");
        inner.className = "hammer-ratings-top-scroll-inner";
        topBar.appendChild(inner);

        advancedScroll.parentNode.insertBefore(topBar, advancedScroll);
      }

      const table = advancedScroll.querySelector(".projection-table");
      const inner = topBar.querySelector(".hammer-ratings-top-scroll-inner");

      function syncWidth() {
        if (!table || !inner) return;
        const width = Math.max(
          table.scrollWidth,
          table.getBoundingClientRect().width
        );
        inner.style.width = `${width}px`;
      }

      syncWidth();

      if (topBar.dataset.hammerScrollWired !== "1") {
        topBar.dataset.hammerScrollWired = "1";

        topBar.addEventListener("scroll", () => {
          if (syncingRatingsScroll) return;
          syncingRatingsScroll = true;
          advancedScroll.scrollLeft = topBar.scrollLeft;
          syncingRatingsScroll = false;
        });

        advancedScroll.addEventListener("scroll", () => {
          if (syncingRatingsScroll) return;
          syncingRatingsScroll = true;
          topBar.scrollLeft = advancedScroll.scrollLeft;
          syncingRatingsScroll = false;
        });
      }

      topBar.scrollLeft = advancedScroll.scrollLeft;
    }

    const ratingsObserver = new MutationObserver(() => {
      window.requestAnimationFrame(wireAdvancedRatingsScroll);
    });

    ratingsObserver.observe(ratingsContainer, {
      childList: true,
      subtree: true
    });

    window.addEventListener("resize", () => {
      window.requestAnimationFrame(wireAdvancedRatingsScroll);
    }, { passive: true });

    wireAdvancedRatingsScroll();
  }

  // ========================================================================
  // STATIC BUILD RESILIENCE + TABLE POLISH
  // ========================================================================

  function installTableContainment() {
    if (document.getElementById("thi-table-containment")) return;
    const style = document.createElement("style");
    style.id = "thi-table-containment";
    style.textContent = `
      :is(.table-scroll,.perf-table-wrap,.cbb-table-wrap,.thi-hub-table-wrap,.thi-player-table-wrap,.pv-table-wrap) {
        width:100%; max-width:100%; overflow-x:auto; overscroll-behavior-x:contain;
        -webkit-overflow-scrolling:touch;
      }
      :is(.table-scroll,.perf-table-wrap,.cbb-table-wrap,.thi-hub-table-wrap,.thi-player-table-wrap,.pv-table-wrap)
        table:has(th:nth-child(5)) { min-width:max(100%,760px); }
      :is(.table-scroll,.perf-table-wrap,.cbb-table-wrap,.thi-hub-table-wrap,.thi-player-table-wrap,.pv-table-wrap)
        table:has(th:nth-child(8)) { min-width:max(100%,980px); }
      :is(.table-scroll,.perf-table-wrap,.cbb-table-wrap,.thi-hub-table-wrap,.thi-player-table-wrap,.pv-table-wrap)
        :is(th,td) { font-variant-numeric:tabular-nums; }
      :is(.table-scroll,.perf-table-wrap,.cbb-table-wrap,.thi-hub-table-wrap,.thi-player-table-wrap,.pv-table-wrap)
        :is(th,.cbb-number,.metric-value,.perf-value) { white-space:nowrap; }
      .cbb-view > .cbb-panel.cbb-empty:first-child { min-height:420px; display:grid; place-content:center; box-sizing:border-box; }
      tbody .loading-state { min-height:420px; }
      .thi-positive-sign { display:inline-block; width:.72ch; color:var(--muted); opacity:.42; text-align:left; }
      #thi-loader-status {
        position:fixed; right:14px; bottom:14px; z-index:9998; display:none; align-items:center; gap:10px;
        max-width:min(390px,calc(100vw - 28px)); padding:10px 12px; border:1px solid var(--border);
        border-radius:9px; background:var(--surface); color:var(--muted); box-shadow:0 8px 26px rgba(0,0,0,.16);
        font:700 10px/1.4 var(--mono);
      }
      html[data-thi-load-state="stalled"] #thi-loader-status { display:flex; }
      #thi-loader-status button { border:1px solid var(--border); border-radius:7px; padding:6px 9px; background:var(--surface-2); color:var(--text); font:inherit; cursor:pointer; }
      @media (max-width:640px) {
        :is(.table-scroll,.perf-table-wrap,.cbb-table-wrap,.thi-hub-table-wrap,.thi-player-table-wrap,.pv-table-wrap)
          table:has(th:nth-child(5)) { min-width:760px; }
      }
    `;
    document.head.appendChild(style);
  }

  function sanitizePositiveSigns(root = document) {
    const cells = root.matches?.("td") ? [root] : root.querySelectorAll?.("td") || [];
    cells.forEach(cell => {
      const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
      const matches = [];
      while (walker.nextNode()) {
        const node = walker.currentNode;
        if (node.parentElement?.closest(".thi-positive-sign")) continue;
        if (/^\s*\+(?=\d)/.test(node.nodeValue || "")) matches.push(node);
      }
      matches.forEach(node => {
        const match = (node.nodeValue || "").match(/^(\s*)\+(.*)$/s);
        if (!match) return;
        const fragment = document.createDocumentFragment();
        if (match[1]) fragment.append(document.createTextNode(match[1]));
        const sign = document.createElement("span");
        sign.className = "thi-positive-sign";
        sign.textContent = "+";
        fragment.append(sign, document.createTextNode(match[2]));
        node.replaceWith(fragment);
      });
    });
  }

  function installStaticLoaderState() {
    const root = document.documentElement;
    root.dataset.thiBuild = "static";
    const status = document.createElement("div");
    status.id = "thi-loader-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.innerHTML = `<span>Data is taking longer than expected.</span><button type="button">Retry</button>`;
    status.querySelector("button")?.addEventListener("click", () => window.location.reload());
    document.body.appendChild(status);

    const visibleLoadingStates = () => [...document.querySelectorAll(".loading-state")].filter(node => {
      const view = node.closest(".view");
      return (!view || view.classList.contains("active")) && getComputedStyle(node).display !== "none";
    });
    let stallTimer = null;
    const update = () => {
      const loading = visibleLoadingStates().length > 0;
      if (!loading) {
        root.dataset.thiLoadState = "ready";
        if (stallTimer) window.clearTimeout(stallTimer);
        stallTimer = null;
      } else if (root.dataset.thiLoadState !== "stalled") {
        root.dataset.thiLoadState = "loading";
        if (!stallTimer) stallTimer = window.setTimeout(() => {
          stallTimer = null;
          update();
          if (root.dataset.thiLoadState === "loading") root.dataset.thiLoadState = "stalled";
        }, 15000);
      }
    };
    const observer = new MutationObserver(records => {
      records.forEach(record => record.addedNodes.forEach(node => {
        if (node.nodeType === Node.ELEMENT_NODE) sanitizePositiveSigns(node);
      }));
      records.filter(record => record.type === "characterData").forEach(record => {
        const cell = record.target.parentElement?.closest("td");
        if (cell) sanitizePositiveSigns(cell);
      });
      window.requestAnimationFrame(update);
    });
    observer.observe(document.body, { childList:true, characterData:true, attributes:true, attributeFilter:["class","style"], subtree:true });
    sanitizePositiveSigns();
    update();
    window.addEventListener("load", () => window.requestAnimationFrame(update), { once:true });
  }

  function start() {
    installMatchupUx();
    installStickyProjectionHeader();
    installTerminologyObserver();
    makeSignalGuidePersistent();
    installWideTableFixes();
    installTableContainment();
    installStaticLoaderState();
    installWelcomeModal();
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
