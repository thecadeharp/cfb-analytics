const test = require("node:test");
const assert = require("node:assert/strict");
const engine = require("../cfb-game-script.js");

test("baseline preserves the published THI score, spread, and total", () => {
  const baseline = engine.buildBaseline({
    total: 51.5,
    homeSpread: -3.5,
    awayProfile: { drives: 44 },
    awayObservedRating: { reliability: { games: 4 } },
    homeProfile: { drives: 52 },
    homeObservedRating: { reliability: { games: 4 } },
  });
  const result = engine.simulate(baseline, baseline.drives, 16);
  assert.equal(baseline.drives, 12);
  assert.equal(result.total, 51.5);
  assert.equal(result.homeSpread, -3.5);
  assert.equal(result.homePoints, 27.5);
  assert.equal(result.awayPoints, 24);
});

test("faster scripts increase total and scale the margin without mutating the baseline", () => {
  const baseline = engine.buildBaseline({ total: 56, homeSpread: -7 });
  const initial = engine.simulate(baseline, baseline.drives, 16);
  const fast = engine.simulate(baseline, baseline.drives + 2, 16);
  assert.ok(fast.total > initial.total);
  assert.ok(Math.abs(fast.homeSpread) > Math.abs(initial.homeSpread));
  assert.equal(baseline.drives, engine.DEFAULT_DRIVES);
  assert.equal(initial.total, 56);
  assert.ok(Math.abs(initial.homeSpread - (-7)) < 1e-9);
});

test("scenario range is bounded and invalid projections are withheld", () => {
  assert.equal(engine.buildBaseline({ total: null, homeSpread: -3 }), null);
  const baseline = engine.buildBaseline({ total: 48, homeSpread: 2 });
  const result = engine.simulate(baseline, 99, 16);
  assert.equal(result.drives, baseline.maximumDrives);
  assert.ok(result.homeWinProbability >= 0 && result.homeWinProbability <= 100);
});
