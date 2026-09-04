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
      padding: "28px"
    });

    modal.innerHTML = `
      <div style="font-size:32px; line-height:1; margin-bottom:14px;">🔨</div>
      <div style="font-family:var(--mono, monospace); font-size:12px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; color:#8a6a00; margin-bottom:8px;">
        Welcome to
      </div>
      <h2 id="thi-welcome-title" style="margin:0 0 12px; font-size:28px; line-height:1.08;">
        The Hammer Index
      </h2>
      <p style="margin:0 0 16px; line-height:1.6; color:#4b5563;">
        A college football analytics and projection platform built to create an independent view of every matchup.
      </p>
      <p style="margin:0 0 20px; line-height:1.6; color:#4b5563;">
        Explore <strong>THI Spreads</strong>, <strong>THI Totals</strong>, projected scores, win probabilities, team ratings, matchup analysis and how the model compares with the live betting market.
      </p>
      <div style="padding:13px 14px; margin-bottom:12px; border-radius:10px; background:#fff8dc; border:1px solid #e7c967; font-size:13px; line-height:1.5;">
        <strong>THI is independent of the sportsbook line.</strong> Market odds are used for comparison — not to create the model's projection.
      </div>
      <div style="padding:13px 14px; margin-bottom:22px; border-radius:10px; background:#f3f4f6; border:1px solid #d1d5db; font-size:13px; line-height:1.5; color:#4b5563;">
        <strong>Beta / Testing:</strong> The Hammer Index is actively being tested and refined. The site is available to use for analysis, research and entertainment, but projections and features may change as feedback and new data are incorporated. Nothing on THI should be considered financial or betting advice.
      </div>
      <button id="thi-welcome-enter" type="button" style="width:100%; border:0; border-radius:10px; padding:13px 16px; cursor:pointer; font:inherit; font-weight:800; background:#1f2937; color:#fff;">
        Explore The Hammer Index →
      </button>
    `;

    overlay.appendChild(modal);
    document.body.appendChild(overlay);
    document.body.style.overflow = "hidden";

    const button = modal.querySelector("#thi-welcome-enter");
    button?.addEventListener("click", closeWelcome);

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

  function start() {
    installMatchupUx();
    installStickyProjectionHeader();
    installTerminologyObserver();
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
