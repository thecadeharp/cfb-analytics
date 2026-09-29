const assert = require('node:assert/strict');
const core = require('../playoff-projection.js');

function row(team, conference, projectedRank) {
  return { team, conference, projectedRank, selectionScore: 1 - projectedRank / 100 };
}

const ranked = [
  row('Notre Dame', 'FBS Independents', 1),
  row('Ohio State', 'Big Ten', 2),
  row('Georgia', 'SEC', 3),
  row('Clemson', 'ACC', 4),
  row('Texas Tech', 'Big 12', 5),
  row('Oregon', 'Big Ten', 6),
  row('Alabama', 'SEC', 7),
  row('Miami', 'ACC', 8),
  row('Texas', 'SEC', 9),
  row('LSU', 'SEC', 10),
  row('USC', 'Big Ten', 11),
  row('Penn State', 'Big Ten', 12),
  row('Boise State', 'Mountain West', 18),
  row('Michigan', 'Big Ten', 13),
  row('Utah', 'Big 12', 14),
];

const result = core.selectField(
  ranked,
  ['ACC', 'Big Ten', 'Big 12', 'SEC'],
  ['American Athletic', 'Conference USA', 'Mid-American', 'Mountain West', 'Pac-12', 'Sun Belt']
);

assert.equal(result.field.length, 12);
assert.deepEqual(result.field.map(team => team.seed), [1,2,3,4,5,6,7,8,9,10,11,12]);
assert.ok(result.field.some(team => team.team === 'Boise State' && team.autoBid === 'group'));
assert.ok(result.field.some(team => team.team === 'Notre Dame' && team.notreDameAuto));
assert.equal(result.field[11].team, 'Boise State');
assert.equal(result.firstOut.team, 'Penn State');
assert.equal(result.secondOut.team, 'Michigan');
console.log('playoff projection contract passed');
