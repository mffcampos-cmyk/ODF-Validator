// Grouped findings: filteredResult must recompute counts from occurrences,
// not from the number of grouped entries, so the true severity totals survive
// filtering and export.
const assert = require('assert');
const { filteredResult } = require('../../web/static/filter.js');

const A = new Set(['error', 'warning', 'info']);

// One error group standing in for 18 folded findings, plus one lone warning.
const single = {
  doc_type: 'DT_RESULT', counts: {error: 18, warning: 1, info: 0},
  findings: [
    {severity: 'error', rule_id: 'R1', message: 'm', occurrences: 18,
     location: {line: 4, path: '/a'},
     locations: Array.from({length: 18}, (_, i) => ({line: i, path: '/a' + i}))},
    {severity: 'warning', rule_id: 'W1', message: 'm', occurrences: 1,
     location: {line: 2, path: '/b'}, locations: [{line: 2, path: '/b'}]},
  ],
};

const fs = filteredResult(single, A);
assert.deepStrictEqual(fs.counts, {error: 18, warning: 1, info: 0},
  'counts must sum occurrences, not group entries');

// Filtering to errors only keeps the 18 occurrences in the count.
const errOnly = filteredResult(single, new Set(['error']));
assert.strictEqual(errOnly.findings.length, 1);
assert.deepStrictEqual(errOnly.counts, {error: 18, warning: 0, info: 0});

// Legacy findings without an `occurrences` field count as one each.
const legacy = {counts: {error: 2, warning: 0, info: 0}, findings: [
  {severity: 'error', rule_id: 'E1'}, {severity: 'error', rule_id: 'E2'},
]};
assert.deepStrictEqual(filteredResult(legacy, A).counts, {error: 2, warning: 0, info: 0});

console.log('GROUP COUNTS TESTS PASSED');
