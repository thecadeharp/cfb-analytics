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

  function normalizedStatus(value) {
    return ["all", "upcoming", "live", "final"].includes(value)
      ? value
      : "all";
  }

  function announceStatusChange() {
    window.dispatchEvent(new CustomEvent(
      "hammer:status-filter-changed",
      { detail: { status: activeStatus } }
    ));
  }

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
