// A failed request must never render as a clean pass.
// Findings C4/U-C2/U-C3: validate() did not check r.ok, so a
// {"detail": "..."} error body flowed through the filter as zero findings
// and the ledger announced "No findings — this message conforms".
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const ROOT = path.join(__dirname, '..', '..');
const { filteredResult } = require(path.join(ROOT, 'web/static/filter.js'));

// appendChild here is a light simulation (string concatenation, honouring
// document fragments) rather than a no-op, so tests can see what actually
// landed in #findings / #batch-summary -- not just that some assignment
// happened somewhere.
function makeApp(fetchStub) {
  const elems = {};
  const el = (id) => (elems[id] = elems[id] ||
    {value: '', innerHTML: '', textContent: '', hidden: false, disabled: false,
     className: '', files: [], setAttribute() {},
     appendChild(node) {
       if (!node) return;
       const kids = node._isFragment ? node._children : [node];
       for (const c of kids) this.innerHTML += `<li class="${c.className || ''}">${c.innerHTML || ''}</li>`;
     }});
  el('pack').value = 'SYOG26';
  el('xml').value = '<x/>';
  let mode = 'paste';
  const document = {
    getElementById: el,
    createDocumentFragment: () => ({_isFragment: true, _children: [],
                                     appendChild(n) { this._children.push(n); }}),
    querySelectorAll: (s) => {
      if (s === '.sevf:checked') return [{value: 'error'}];
      if (s === '.modef:checked') return [{value: mode}];
      return [{}];
    },
    createElement: () => ({className: '', innerHTML: '', appendChild() {},
                           href: '', download: '', click() {}}),
  };
  class FormDataStub { append() {} }
  class BlobStub { constructor(p) { this._text = p.join(''); } }
  const URLStub = {createObjectURL: () => 'blob:x'};
  const src = fs.readFileSync(path.join(ROOT, 'web/static/app.js'), 'utf8');
  const app = new Function('filteredResult', 'document', 'window', 'fetch',
                           'FormData', 'Blob', 'URL',
    src + '\nreturn {validate, exportJSON};')(
    filteredResult, document, {}, fetchStub, FormDataStub, BlobStub, URLStub);
  return {app, elems, setMode: (m) => { mode = m; }};
}

(async () => {
  // 1. An HTTP error body must not read as a pass.
  const errorFetch = async (u) => u === '/packs'
    ? {ok: true, status: 200, json: async () => [{name: 'SYOG26', version: '1', errors: [], conflicts: []}]}
    : {ok: false, status: 404, json: async () => ({detail: 'Unknown pack: SYOG26'})};
  const a = makeApp(errorFetch);
  await a.app.validate();
  const ledger = a.elems['empty'].innerHTML;
  assert.ok(!/conforms/i.test(ledger),
    `a 404 rendered as a clean pass: ${ledger}`);
  assert.ok(/couldn.t validate|404|unknown pack/i.test(ledger),
    `the failure was not reported to the user: ${ledger}`);
  assert.strictEqual(a.elems['export'].disabled, true,
    'Export must stay disabled after a failed request');

  // 2. A rejected fetch (server down) must say so, not fall silent.
  const deadFetch = async (u) => {
    if (u === '/packs') return {ok: true, status: 200, json: async () => []};
    throw new TypeError('Failed to fetch');
  };
  const b = makeApp(deadFetch);
  await b.app.validate();
  assert.ok(/reach|running|network/i.test(b.elems['empty'].innerHTML),
    `a network failure was silent: ${b.elems['empty'].innerHTML}`);
  assert.strictEqual(b.elems['validate'].disabled, false,
    'the Validate button must be re-enabled after a network failure');

  // 3. A real result still renders normally.
  const okFetch = async (u) => u === '/packs'
    ? {ok: true, status: 200, json: async () => [{name: 'SYOG26', version: '1', errors: [], conflicts: []}]}
    : {ok: true, status: 200,
       json: async () => ({doc_type: 'DT_RESULT', counts: {error: 0, warning: 0, info: 0}, findings: []})};
  const c = makeApp(okFetch);
  await c.app.validate();
  assert.ok(/conforms/i.test(c.elems['empty'].innerHTML),
    `a genuine clean pass no longer reports as clean: ${c.elems['empty'].innerHTML}`);
  assert.strictEqual(c.elems['export'].disabled, false,
    'Export must be enabled after a successful run');

  // 4. A failure after a prior good run must not leave the previous verdict
  // on screen. Whole-branch audit, Task 4 x Task 5 interaction: the failure
  // branches returned without touching #findings/#batch-summary/the tally,
  // and #empty sits below both in the DOM, so a stale tally and findings
  // table dominated the page with the error note as a footnote underneath.
  let call = 0;
  const flaky = async (u) => {
    if (u === '/packs') {
      return {ok: true, status: 200,
        json: async () => [{name: 'SYOG26', version: '1', errors: [], conflicts: []}]};
    }
    call++;
    if (call === 1) {
      return {ok: true, status: 200, json: async () => ({
        files: {
          'a.xml': {
            counts: {error: 2, warning: 0, info: 0},
            findings: [{severity: 'error', rule_id: 'X', message: 'bad', occurrences: 2,
                        locations: [{line: 1}, {line: 2}]}],
          },
        },
        totals: {error: 2, warning: 0, info: 0},
      })};
    }
    return {ok: false, status: 500, json: async () => ({detail: 'boom'})};
  };
  const d = makeApp(flaky);
  d.setMode('batch');
  d.elems['batch'] = {files: [{name: 'a.xml'}]};
  await d.app.validate();
  assert.ok(/a\.xml/.test(d.elems['batch-summary'].innerHTML),
    `setup: the first (good) batch run should have populated the batch summary: ${d.elems['batch-summary'].innerHTML}`);
  assert.ok(/bad/.test(d.elems['findings'].innerHTML),
    `setup: the first (good) batch run should have populated the findings list: ${d.elems['findings'].innerHTML}`);
  assert.strictEqual(d.elems['count-error'].textContent, 2,
    'setup: the first (good) batch run should have populated the tally');

  await d.app.validate();
  assert.strictEqual(d.elems['findings'].innerHTML, '',
    `a failed request left stale findings on screen: ${d.elems['findings'].innerHTML}`);
  assert.strictEqual(d.elems['batch-summary'].innerHTML, '',
    `a failed request left a stale batch summary on screen: ${d.elems['batch-summary'].innerHTML}`);
  assert.strictEqual(d.elems['count-error'].textContent, 0,
    `a failed request left the previous run's tally on screen: ${d.elems['count-error'].textContent}`);
  assert.ok(/couldn.t validate|500|boom/i.test(d.elems['empty'].innerHTML),
    `the failure was not reported to the user: ${d.elems['empty'].innerHTML}`);

  // 5. A pre-flight guard (no files chosen) after a prior good run must also
  // clear the stale verdict, not just post-fetch failures. validate() checks
  // batch/file/xml emptiness before ever calling fetch, so clearResultDisplay()
  // has to be called on those early-return paths too.
  const packsOnly = async (u) => u === '/packs'
    ? {ok: true, status: 200,
       json: async () => [{name: 'SYOG26', version: '1', errors: [], conflicts: []}]}
    : {ok: true, status: 200, json: async () => ({
        files: {
          'a.xml': {
            counts: {error: 2, warning: 0, info: 0},
            findings: [{severity: 'error', rule_id: 'X', message: 'bad', occurrences: 2,
                        locations: [{line: 1}, {line: 2}]}],
          },
        },
        totals: {error: 2, warning: 0, info: 0},
      })};
  const e = makeApp(packsOnly);
  e.setMode('batch');
  e.elems['batch'] = {files: [{name: 'a.xml'}]};
  await e.app.validate();
  assert.ok(/a\.xml/.test(e.elems['batch-summary'].innerHTML),
    `setup: the first (good) batch run should have populated the batch summary: ${e.elems['batch-summary'].innerHTML}`);
  assert.ok(/bad/.test(e.elems['findings'].innerHTML),
    `setup: the first (good) batch run should have populated the findings list: ${e.elems['findings'].innerHTML}`);
  assert.strictEqual(e.elems['count-error'].textContent, 2,
    'setup: the first (good) batch run should have populated the tally');
  assert.strictEqual(e.elems['export'].disabled, false,
    'setup: Export must be enabled after the first good run');

  e.elems['batch'] = {files: []};
  await e.app.validate();
  assert.strictEqual(e.elems['findings'].innerHTML, '',
    `the batch pre-flight guard left stale findings on screen: ${e.elems['findings'].innerHTML}`);
  assert.strictEqual(e.elems['batch-summary'].innerHTML, '',
    `the batch pre-flight guard left a stale batch summary on screen: ${e.elems['batch-summary'].innerHTML}`);
  assert.strictEqual(e.elems['count-error'].textContent, 0,
    `the batch pre-flight guard left the previous run's tally on screen: ${e.elems['count-error'].textContent}`);
  assert.ok(/choose \.xml files or a \.zip/i.test(e.elems['empty'].innerHTML),
    `the pre-flight guard message was not shown: ${e.elems['empty'].innerHTML}`);
  assert.strictEqual(e.elems['export'].disabled, false,
    'Export must remain enabled -- the prior good result is still exportable');

  console.log('error_states.test.js OK');
})();
