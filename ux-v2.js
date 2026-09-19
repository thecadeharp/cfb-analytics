// ============================================================================
// CFB ANALYTICS — UX + WEATHER ENGINE v1
// Frontend/product layer only.
// Model A projection data remains untouched.
// ============================================================================

(() => {
  "use strict";

  const CONDITIONS_URL = "./data/game_conditions.json";
  const RESULTS_URL = "./data/reports/settled_results.json";

  let gameConditionsData = { games: {} };
  let settledResultsData = { rows: [] };
  let settledResultsByGame = new Map();
  let currentConferenceFilter = "";
  let currentSignalFilter = "";
  let currentConfidenceFilter = "";

  const CONFERENCE_OPTIONS = [
    ["", "All Conferences"],
    ["AAC", "AAC"],
    ["ACC", "ACC"],
    ["BIG TEN", "Big Ten"],
    ["BIG 12", "Big 12"],
    ["CUSA", "CUSA"],
    ["INDEPENDENT", "Independent"],
    ["MAC", "MAC"],
    ["MOUNTAIN WEST", "Mountain West"],
    ["PAC-12", "Pac-12"],
    ["SEC", "SEC"],
    ["SUN BELT", "Sun Belt"],
  ];

  const SIGNAL_OPTIONS = [
    ["", "All Signals"],
    ["ALIGNED", "Aligned"],
    ["SMALL EDGE", "Small Edge"],
    ["PLAY", "Play"],
    ["MATERIAL DISAGREEMENT", "Material Disagreement"],
    ["OUTLIER", "Outlier"],
  ];

  const CONFIDENCE_OPTIONS = [
    ["", "All Confidence"],
    ["DEVELOPING", "Developing"],
    ["VALIDATED", "Validated"],
    ["ESTABLISHED", "Established"],
  ];

  function normalizedConference(value) {
    const text = String(value || "").trim().toUpperCase();

    if (["AAC", "AMERICAN ATHLETIC", "AMERICAN ATHLETIC CONFERENCE"].includes(text)) return "AAC";
    if (["ACC", "ATLANTIC COAST CONFERENCE"].includes(text)) return "ACC";
    if (["BIG TEN", "BIG TEN CONFERENCE", "B1G"].includes(text)) return "BIG TEN";
    if (["BIG 12", "BIG 12 CONFERENCE", "B12"].includes(text)) return "BIG 12";
    if (["CONFERENCE USA", "C-USA", "CUSA"].includes(text)) return "CUSA";
    if (["FBS INDEPENDENTS", "INDEPENDENT", "INDEPENDENTS", "IND."].includes(text)) return "INDEPENDENT";
    if (["MAC", "MID-AMERICAN", "MID-AMERICAN CONFERENCE"].includes(text)) return "MAC";
    if (["MOUNTAIN WEST", "MOUNTAIN WEST CONFERENCE", "MWC"].includes(text)) return "MOUNTAIN WEST";
    if (["PAC-12", "PAC 12", "PAC-12 CONFERENCE"].includes(text)) return "PAC-12";
    if (["SEC", "SOUTHEASTERN CONFERENCE"].includes(text)) return "SEC";
    if (["SUN BELT", "SUN BELT CONFERENCE", "SBC"].includes(text)) return "SUN BELT";

    return text;
  }

  function uTeamLogo(teamName, size="projection") {
    return typeof window.teamLogoMarkup === "function"
      ? window.teamLogoMarkup(teamName, size)
      : "";
  }

  function conditionsForGame(game) {
    return gameConditionsData?.games?.[String(game?.game_id ?? "")] ?? null;
  }

  function indexSettledResults(payload) {
    const rows = Array.isArray(payload?.rows) ? payload.rows : [];
    const grouped = new Map();
    const indexed = new Map();

    rows
      .filter(row => row?.result_settled)
      .sort((a, b) => String(a?.captured_at_utc || "").localeCompare(String(b?.captured_at_utc || "")))
      .forEach(row => {
        const key = String(row?.game_key ?? row?.result_game_id ?? "");
        if (!key) return;
        if (!grouped.has(key)) grouped.set(key, []);
        grouped.get(key).push(row);
      });

    grouped.forEach(gameRows => {
      const official = { ...gameRows[0] };
      const weather = [...gameRows].reverse().find(row => row?.weather_applied);
