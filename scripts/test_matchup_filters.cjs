const assert = require("node:assert/strict");
const filters = require("../matchup-filters.js");

const game = (sport, filter, homeConference, awayConference, homeRank = null, awayRank = null) =>
  filters.matchesGameFilter({sport, filter, homeConference, awayConference, homeRank, awayRank});

assert.equal(game("CFB", "p4p4", "SEC", "Big Ten"), true);
assert.equal(game("CFB", "p4p4", "SEC", "Sun Belt"), false);
assert.equal(game("CFB", "g6g6", "American Athletic", "Pac-12"), true);
assert.equal(game("CFB", "g6g6", "Mountain West", "ACC"), false);
assert.equal(game("CBB", "p5p5", "Big East", "ACC"), true);
assert.equal(game("CBB", "p5p5", "Big East", "WCC"), false);
assert.equal(game("CBB", "midmajor", "WCC", "Mountain West"), true);
assert.equal(game("CBB", "midmajor", "Big East", "A-10"), false);
assert.equal(game("CBB", "thi25", "WCC", "Big East", 31, 12), true);
assert.equal(game("CFB", "thi25", "SEC", "ACC", 26, 40), false);
assert.equal(game("CFB", "all", "SEC", "ACC"), true);

console.log("matchup filter tests passed");
