'use strict';
const assert = require('node:assert/strict');
const core = require('../thi-intelligence.js');

assert.deepEqual(core.probabilityDistribution([0.5, 0.5]), [0.25, 0.5, 0.25]);
assert.deepEqual(core.probabilityDistribution([1, 0]), [0, 1, 0]);
console.log('THI intelligence core tests passed');
