// Integration test: validate() then exportJSON() must honor the Show: filters.
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const ROOT = path.join(__dirname, '..', '..');
const { filteredResult } = require(path.join(ROOT, 'web/static/filter.js'));

let captured = null;
const elems = {};
const el = (id) => (elems[id] = elems[id] ||
  {value: '', innerHTML: '', textContent: '', files: [], appendChild() {}});
el('pack').value = 'SYOG26';
el('xml').value = '<x/>';
const document = {
  getElementById: el,
  createDocumentFragment: () => ({appendChild() {}}),
  querySelectorAll: (s) => s === '.sevf:checked' ? [{value: 'error'}] : [{}],
  createElement: () => ({style: {}, set innerHTML(v) {}, set className(v) {},
                         appendChild() {}, href: '', download: '', click() {}}),
};
const SINGLE = {doc_type: 'DT_RESULT', counts: {error: 1, warning: 1, info: 0}, findings: [
  {severity: 'error', rule_id: 'E1', message: 'm', location: {line: 1, path: '/a'}, source_ref: ''},
  {severity: 'warning', rule_id: 'W1', message: 'm', location: {line: 2, path: '/b'}, source_ref: ''},
]};
const fetchStub = async (u) => u === '/packs'
  ? {ok: true, status: 200, json: async () => [{name: 'SYOG26', version: '1', errors: [], conflicts: []}]}
  : {ok: true, status: 200, json: async () => SINGLE};
class FormDataStub { append() {} }
class BlobStub { constructor(p) { this._text = p.join(''); } }
const URLStub = {createObjectURL: (b) => { captured = b; return 'blob:x'; }};

const src = fs.readFileSync(path.join(ROOT, 'web/static/app.js'), 'utf8');
const app = new Function('filteredResult', 'document', 'window', 'fetch', 'FormData', 'Blob', 'URL',
  src + '\nreturn {validate, exportJSON};')(
  filteredResult, document, {}, fetchStub, FormDataStub, BlobStub, URLStub);

(async () => {
  await app.validate();
  app.exportJSON();
  const out = JSON.parse(captured._text);
  assert.strictEqual(out.findings.length, 1, 'export must contain only the error finding');
  assert.deepStrictEqual(out.counts, {error: 1, warning: 0, info: 0});
  console.log('EXPORT RESPECTS FILTERS PASSED');
})().catch((e) => { console.error('FAIL:', e.message); process.exit(1); });
