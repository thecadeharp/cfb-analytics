(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.THIMatchupFilters = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const CFB_P4 = new Set(["ACC", "BIG TEN", "BIG 12", "SEC"]);
  const CFB_G6 = new Set(["AAC", "CUSA", "MAC", "MOUNTAIN WEST", "PAC-12", "SUN BELT"]);
  const CBB_P5 = new Set(["ACC", "BIG TEN", "BIG 12", "SEC", "BIG EAST"]);

  function normalizeConference(value) {
    const text = String(value || "").trim().toUpperCase();
    if (["AAC", "AMERICAN", "AMERICAN ATHLETIC", "AMERICAN ATHLETIC CONFERENCE"].includes(text)) return "AAC";
    if (["ACC", "ATLANTIC COAST CONFERENCE"].includes(text)) return "ACC";
    if (["BIG TEN", "BIG TEN CONFERENCE", "B1G"].includes(text)) return "BIG TEN";
    if (["BIG 12", "BIG 12 CONFERENCE", "B12"].includes(text)) return "BIG 12";
    if (["BIG EAST", "BIG EAST CONFERENCE"].includes(text)) return "BIG EAST";
    if (["CONFERENCE USA", "C-USA", "CUSA"].includes(text)) return "CUSA";
    if (["MAC", "MID-AMERICAN", "MID-AMERICAN CONFERENCE"].includes(text)) return "MAC";
    if (["MOUNTAIN WEST", "MOUNTAIN WEST CONFERENCE", "MWC"].includes(text)) return "MOUNTAIN WEST";
    if (["PAC-12", "PAC 12", "PAC-12 CONFERENCE"].includes(text)) return "PAC-12";
    if (["SEC", "SOUTHEASTERN CONFERENCE"].includes(text)) return "SEC";
    if (["SUN BELT", "SUN BELT CONFERENCE", "SBC"].includes(text)) return "SUN BELT";
    return text;
  }

  function matchesGameFilter({
    sport,
    filter,
    homeConference,
    awayConference,
    homeRank,
    awayRank,
  } = {}) {
    const selected = String(filter || "").toLowerCase();
    if (!selected || selected === "all") return true;
    if (selected === "thi25") {
      return [homeRank, awayRank].some(rank => Number.isFinite(Number(rank)) && Number(rank) <= 25);
    }

    const home = normalizeConference(homeConference);
    const away = normalizeConference(awayConference);
    if (!home || !away) return false;

    if (String(sport || "").toUpperCase() === "CBB") {
      if (selected === "p5p5") return CBB_P5.has(home) && CBB_P5.has(away);
      if (selected === "midmajor") return !CBB_P5.has(home) && !CBB_P5.has(away);
      return true;
    }

    if (selected === "p4p4") return CFB_P4.has(home) && CFB_P4.has(away);
    if (selected === "g6g6") return CFB_G6.has(home) && CFB_G6.has(away);
    return true;
  }

  return {
    CBB_P5,
    CFB_G6,
    CFB_P4,
    matchesGameFilter,
    normalizeConference,
  };
});
