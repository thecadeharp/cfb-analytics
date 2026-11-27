const assert = require('node:assert/strict');
const core = require('../playoff-projection.js');

const liberty = { team: 'Liberty', powerRating: 12.648 };
const notreDame = { team: 'Notre Dame', powerRating: 28.238 };

const neutral = core.projectRatingMatchup(liberty, notreDame, 'neutral', 0, 52.5);
assert.equal(neutral.ratingSource, 'thi_power_ratings');
assert.ok(neutral.teamAWin < 50, 'lower-rated Liberty must not advance over Notre Dame');
assert.ok(neutral.homeSpread > 0, 'Liberty must be an underdog on the neutral-site line');

const campus = core.projectRatingMatchup(
  { team: 'Higher Rated', powerRating: 20 },
  { team: 'Lower Rated', powerRating: 18 },
  'team_a_home',
  3,
  50,
);
assert.ok(campus.teamAWin > 50);
assert.equal(campus.homeSpread, -5);

console.log('playoff projection tests passed');
