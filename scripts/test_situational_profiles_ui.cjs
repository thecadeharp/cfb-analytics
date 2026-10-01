const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const source = fs.readFileSync('situational-profiles.js', 'utf8');
const context = { window: {} };
vm.createContext(context);
vm.runInContext(source, context);
const ui = context.window.THISituationalProfilesUI;

assert(ui, 'UI helpers must be exposed');
assert.strictEqual(ui.teamKey('Miami (FL)'), 'miami');
assert.strictEqual(ui.teamKey('Miami (OH)'), 'miamioh');
assert.strictEqual(ui.teamKey('Appalachian State'), 'appstate');
assert.strictEqual(ui.teamKey("Hawai'i"), 'hawaii');

const index = ui.profileIndex([
  { team: 'Miami', net_possession_value: 1.2 },
  { team: 'Miami (OH)', net_possession_value: -0.3 },
  { team: 'App State', net_possession_value: 0.1 },
]);
assert.strictEqual(ui.findProfile(index, 'Miami (FL)').net_possession_value, 1.2);
assert.strictEqual(ui.findProfile(index, 'Miami Ohio').net_possession_value, -0.3);
assert.strictEqual(ui.findProfile(index, 'Appalachian State').net_possession_value, 0.1);
assert.strictEqual(ui.signed(0.125), '+0.125');
assert.strictEqual(ui.signed(-0.125), '-0.125');
assert.strictEqual(ui.percent(0.425), '42.5%');
assert.strictEqual(ui.number(null), '—');
assert(source.includes('Game Efficiency Log'));
assert(source.includes('THI Excitement Score'));
assert(source.includes("document.getElementById('thi-game-efficiency-log')"));

console.log('situational profile UI contract passed');
