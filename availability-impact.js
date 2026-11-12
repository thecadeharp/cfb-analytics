(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.THIAvailabilityImpact = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const POSITION_LEVERAGE = {
    QB: 1.00,
    OL: 0.72,
    DL: 0.64,
    LB: 0.61,
    DB: 0.61,
    RB: 0.56,
    WR: 0.56,
    TE: 0.52,
    ST: 0.36,
    OTHER: 0.42,
  };
  const POSITION_ORDER = ["QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "ST"];

  function number(value, fallback = 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function clamp(value, minimum = 0, maximum = 1) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  function normalizeName(value) {
    return String(value ?? "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  function positionGroup(value) {
    const position = String(value ?? "").trim().toUpperCase();
    if (["K", "P", "PK", "LS", "K/P"].includes(position)) return "ST";
    return POSITION_ORDER.includes(position) ? position : "OTHER";
  }

  function statusSeverity(status) {
    const value = String(status ?? "").trim().toLowerCase();
    if (/out|unavailable|suspend|inactive/.test(value)) return 1;
    if (/doubtful/.test(value)) return 0.8;
    if (/game.?time|questionable/.test(value)) return 0.5;
    if (/limited/.test(value)) return 0.3;
    if (/probable/.test(value)) return 0.14;
    if (/available|active|cleared/.test(value)) return 0;
    return 0.35;
  }

  function workloadValue(player) {
    const usage = player?.usage ?? {};
    const position = positionGroup(player?.position);
    if (position === "QB") {
      return number(usage.pass_attempts) + 0.45 * number(usage.rush_attempts);
    }
    if (position === "RB") {
      return number(usage.rush_attempts) + 0.8 * number(usage.targets)
        + 0.35 * number(usage.receptions);
    }
    if (["WR", "TE"].includes(position)) {
      return number(usage.targets) || (1.35 * number(usage.receptions));
    }
    if (["DL", "LB", "DB"].includes(position)) {
      return 0.45 * number(usage.total_tackles)
        + 1.5 * number(usage.tackles_for_loss)
        + 3 * number(usage.sacks)
        + 1.1 * number(usage.passes_defended)
        + 2.5 * number(usage.interceptions);
    }
    if (position === "ST") {
      return number(usage.field_goal_attempts) + number(usage.extra_point_attempts)
        + 0.35 * number(usage.punts);
    }
    return 0;
  }

  function teamPlayers(rosterData, teamName) {
    const players = rosterData?.teams?.[teamName]?.players;
    return Array.isArray(players) ? players : [];
  }

  function findPlayer(note, players) {
    const wanted = normalizeName(note?.player);
    if (!wanted) return null;
    const exact = players.find(player => normalizeName(player?.name) === wanted);
    if (exact) return exact;
    const jersey = String(note?.jersey_number ?? "").trim();
    const position = positionGroup(note?.position);
    if (!jersey) return null;
    return players.find(player => String(player?.jersey ?? "").trim() === jersey
      && positionGroup(player?.position) === position) ?? null;
  }

  function productionRating(player, playerIntelligence) {
    const profile = playerIntelligence?.players?.[String(player?.athlete_id ?? "")];
    const rating = Number(profile?.rating);
    if (!Number.isFinite(rating)) return null;
    const expected = positionGroup(player?.position);
    const actual = String(profile?.position_group ?? "").toUpperCase();
    if (["DL", "LB", "DB"].includes(expected) && actual !== "DEF") return null;
    if (!["DL", "LB", "DB"].includes(expected) && expected !== actual) return null;
    return clamp(rating / 100);
  }

  function impactTier(value) {
    if (value >= 50) return {key: "severe", label: "Severe"};
    if (value >= 30) return {key: "high", label: "High"};
    if (value >= 15) return {key: "moderate", label: "Moderate"};
    if (value > 0) return {key: "low", label: "Low"};
    return {key: "none", label: "None"};
  }

  function rateTeam(notes, teamName, rosterData, playerIntelligence) {
    const currentNotes = Array.isArray(notes) ? notes : [];
    const roster = teamPlayers(rosterData, teamName);
    const groupWorkload = roster.reduce((totals, player) => {
      const group = positionGroup(player?.position);
      totals[group] = number(totals[group]) + workloadValue(player);
      return totals;
    }, {});

    const players = currentNotes.map((note, noteIndex) => {
      const matchedPlayer = findPlayer(note, roster);
      const group = positionGroup(note?.position || matchedPlayer?.position);
      const workload = workloadValue(matchedPlayer);
      const groupTotal = number(groupWorkload[group]);
      const workloadShare = groupTotal > 0 ? clamp(workload / groupTotal) : null;
      const roleScore = workloadShare === null
        ? (matchedPlayer ? 0.25 : 0.15)
        : clamp(0.18 + 1.65 * Math.sqrt(workloadShare));
      const production = productionRating(matchedPlayer, playerIntelligence);
      const leverage = POSITION_LEVERAGE[group] ?? POSITION_LEVERAGE.OTHER;
      const roleValue = 0.52 * roleScore
        + 0.28 * (production === null ? 0.45 : production)
        + 0.20 * leverage;
      const severity = statusSeverity(note?.status);
      const score = Math.round(severity * 10 * clamp(roleValue) * 10) / 10;
      const confidence = matchedPlayer && workload > 0 && production !== null
        ? "high"
        : matchedPlayer ? "medium" : "low";
      return {
        noteIndex,
        score,
        group,
        severity,
        confidence,
        matchedPlayer: Boolean(matchedPlayer),
        workloadShare,
        productionRating: production === null ? null : Math.round(production * 1000) / 10,
      };
    });

    const byPosition = Object.fromEntries(POSITION_ORDER.map(group => [group, 0]));
    players.forEach(player => {
      if (Object.hasOwn(byPosition, player.group)) byPosition[player.group] += player.score;
    });
    Object.keys(byPosition).forEach(group => {
      byPosition[group] = Math.round(byPosition[group]);
    });
    const rawTotal = players.reduce((sum, player) => sum + player.score, 0);
    const total = Math.min(100, Math.round(rawTotal));
    const tier = impactTier(total);
    return {
      total,
      rawTotal: Math.round(rawTotal * 10) / 10,
      tier,
      byPosition,
      players,
      matchedPlayers: players.filter(player => player.matchedPlayer).length,
      ratedPlayers: players.filter(player => player.score > 0).length,
      noteCount: players.length,
      methodVersion: "thi-availability-impact-v1",
    };
  }

  return {
    POSITION_ORDER,
    impactTier,
    normalizeName,
    positionGroup,
    rateTeam,
    statusSeverity,
    workloadValue,
  };
});
