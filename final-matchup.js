(() => {
  "use strict";

  // ==========================================================================
  // THE HAMMER INDEX — FINAL MATCHUP + CANONICAL POSTGAME UI
  //
  // Responsibilities:
  // 1) Preserve frozen pregame projection and replace headline score with FINAL.
  // 2) Read data/postgame_analytics.json.
  // 3) Render the exact canonical postgame metric package.
  // 4) Maintain exactly ONE projection-board postgame status pill:
  //      AVAILABLE -> one purple pill says POSTGAME ANALYSIS COMPLETE
  //      PENDING   -> one yellow pill says POSTGAME ANALYSIS PENDING
  //    This file NEVER creates a second yellow postgame badge.
  // 5) Never call a game "pending" merely because the JSON fetch failed.
  // ==========================================================================

  const RESULTS_URL = "./data/results.json";
  const POSTGAME_URL = "./data/postgame_analytics.json";
  const STYLE_ID = "hammer-final-matchup-styles-v3";
  const POSTGAME_SECTION_ID = "hammer-postgame-analysis";

  let finalGames = [];
  let postgameGames = [];
  let postgameDataLoaded = false;
  const postgameMetricDistributionCache = new Map();
  let observer = null;
  let applying = false;

  // ==========================================================================
  // NORMALIZATION
  // ==========================================================================

  function canonical(value) {
    return String(value || "")
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/&/g, "and")
      .replace(/[.'’(),_-]/g, " ")
      .replace(/\buniversity\b/g, "")
      .replace(/\bst\b/g, "state")
      .replace(/\bmich\b/g, "michigan")
      .replace(/\s+/g, " ")
      .trim();
  }

  function normalizedTeam(value) {
    const text = canonical(value);

    const aliases = {
      "umass": "massachusetts",
      "massachusetts": "massachusetts",

      "usc": "southern california",
      "southern cal": "southern california",
      "southern california": "southern california",

      "jacksonville state": "jacksonville state",
      "north dakota state": "north dakota state",
      "new mexico state": "new mexico state",
      "florida state": "florida state",
      "sacramento state": "sacramento state",
      "eastern michigan": "eastern michigan",
      "san jose state": "san jose state",

      "hawaii": "hawaii",
      "hawai i": "hawaii",

      "n c a and t": "north carolina a and t",
      "nc a and t": "north carolina a and t",
      "north carolina a and t": "north carolina a and t",

      "georgia state": "georgia state",

      "liu": "long island",
      "long island": "long island",
      "long island university": "long island"
    };

    return aliases[text] || text;
  }

  function sameTeam(a, b) {
    return normalizedTeam(a) === normalizedTeam(b);
  }

  function matchupFind(rows, away, home) {
    return (
      rows.find(game =>
        sameTeam(game?.away_team, away) &&
        sameTeam(game?.home_team, home)
      ) || null
    );
  }

  // ==========================================================================
  // FORMATTERS
  // ==========================================================================

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function numeric(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function fmt(value, digits = 1) {
    const number = numeric(value);
    return number === null
      ? "—"
      : number.toFixed(digits);
  }

  function fmtSigned(value, digits = 1) {
    const number = numeric(value);

    if (number === null) {
      return "—";
    }
