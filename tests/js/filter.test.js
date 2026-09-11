const assert = require('assert');
const { filterFindings, filteredResult } = require('../../web/static/filter.js');

const A = new Set(['error']);                 // show only errors

// single-message result
const single = {
  doc_type: 'DT_RESULT', counts: {error:1, warning:2, info:0},
  findings: [
    {severity:'error', rule_id:'E1'},
    {severity:'warning', rule_id:'W1'},
    {severity:'warning', rule_id:'W2'},
  ],
};

// 1) filterFindings keeps only active severities
assert.strictEqual(filterFindings(single.findings, A).length, 1);

// 2) filteredResult (single) filters findings AND recomputes counts
const fs = filteredResult(single, A);
assert.strictEqual(fs.findings.length, 1);
assert.deepStrictEqual(fs.counts, {error:1, warning:0, info:0});

// 3) filteredResult (batch) filters each file's findings and recomputes totals
const batch = {
  totals: {error:1, warning:1, info:0},
  files: {
    'a.xml': {counts:{error:1,warning:0,info:0}, findings:[{severity:'error',rule_id:'E1'}]},
    'b.xml': {counts:{error:0,warning:1,info:0}, findings:[{severity:'warning',rule_id:'W1'}]},
  },
};
const fb = filteredResult(batch, A);
assert.strictEqual(fb.files['a.xml'].findings.length, 1);
assert.strictEqual(fb.files['b.xml'].findings.length, 0);
assert.deepStrictEqual(fb.totals, {error:1, warning:0, info:0});

console.log('ALL FILTER TESTS PASSED');
