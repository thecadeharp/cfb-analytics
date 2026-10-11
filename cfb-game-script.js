(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.THICfbGameScript = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const DEFAULT_DRIVES = 11.5;
  const MIN_DRIVES = 7;
  const MAX_DRIVES = 17;
  const DEFAULT_MARGIN_SIGMA = 16;

  function finite(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function clamp(value, low, high) {
    return Math.max(low, Math.min(high, value));
  }

  function erf(value) {
    const sign = value < 0 ? -1 : 1;
    const x = Math.abs(value);
    const a1 = 0.254829592;
    const a2 = -0.284496736;
    const a3 = 1.421413741;
    const a4 = -1.453152027;
    const a5 = 1.061405429;
    const p = 0.3275911;
    const t = 1 / (1 + p * x);
    const estimate = 1 - (((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t * Math.exp(-x * x));
    return sign * estimate;
  }

  function normalCdf(value) {
    return 0.5 * (1 + erf(value / Math.sqrt(2)));
  }

  function teamDrivesPerGame(profile, observedRating) {
    const drives = finite(profile?.drives);
    const games = finite(observedRating?.reliability?.games);
    if (drives === null || games === null || games < 2 || drives <= 0) return null;
    return clamp(drives / games, MIN_DRIVES, MAX_DRIVES);
  }

  function buildBaseline(input) {
    const total = finite(input?.total);
    const homeSpread = finite(input?.homeSpread);
    if (total === null || homeSpread === null || total <= 0) return null;

    const awayRate = teamDrivesPerGame(input?.awayProfile, input?.awayObservedRating);
    const homeRate = teamDrivesPerGame(input?.homeProfile, input?.homeObservedRating);
    const available = [awayRate, homeRate].filter(value => value !== null);
    const drives = available.length
      ? available.reduce((sum, value) => sum + value, 0) / available.length
      : DEFAULT_DRIVES;
    const roundedDrives = Math.round(clamp(drives, MIN_DRIVES, MAX_DRIVES) * 2) / 2;
    const homeMargin = -homeSpread;
    const homePoints = Math.max(0, (total + homeMargin) / 2);
    const awayPoints = Math.max(0, total - homePoints);

    return {
      drives: roundedDrives,
      minimumDrives: Math.max(MIN_DRIVES, roundedDrives - 2),
      maximumDrives: Math.min(MAX_DRIVES, roundedDrives + 2),
      awayPoints,
      homePoints,
      awayPointsPerDrive: awayPoints / roundedDrives,
      homePointsPerDrive: homePoints / roundedDrives,
      source: available.length === 2
        ? "both_teams_current_sample"
        : available.length === 1
          ? "one_team_current_sample"
          : "national_fallback",
    };
  }

  function simulate(baseline, selectedDrives, marginSigma) {
    if (!baseline) return null;
    const drives = clamp(
      finite(selectedDrives) ?? baseline.drives,
      baseline.minimumDrives,
      baseline.maximumDrives
    );
    const awayPoints = Math.max(0, drives * baseline.awayPointsPerDrive);
    const homePoints = Math.max(0, drives * baseline.homePointsPerDrive);
    const homeMargin = homePoints - awayPoints;
    const sigma = Math.max(1, finite(marginSigma) ?? DEFAULT_MARGIN_SIGMA);

    return {
      drives,
      awayPoints,
      homePoints,
      total: awayPoints + homePoints,
      homeSpread: -homeMargin,
      homeWinProbability: 100 * normalCdf(homeMargin / sigma),
      awayWinProbability: 100 * (1 - normalCdf(homeMargin / sigma)),
    };
  }

  return { DEFAULT_DRIVES, DEFAULT_MARGIN_SIGMA, buildBaseline, simulate };
});
