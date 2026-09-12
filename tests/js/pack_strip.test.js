// The pack-report strip must mention a refused draft, and must not file it
// under "rule(s) failed to load" -- no rule exists to have failed.
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const ROOT = path.join(__dirname, '..', '..');
const { filteredResult } = require(path.join(ROOT, 'web/static/filter.js'));

function render(pack) {
  const elems = {};
  const el = (id) => (elems[id] = elems[id] ||
    {value: '', innerHTML: '', textContent: '', hidden: false, disabled: false,
     className: '', files: [], setAttribute() {}, appendChild() {}});
  el('pack').value = 'SYOG26';
  const document = {
    getElementById: el,
    createDocumentFragment: () => ({_isFragment: true, _children: [], appendChild() {}}),
    querySelectorAll: () => [{}],
    createElement: () => ({className: '', innerHTML: '', appendChild() {}, click() {}}),
  };
  const fetchStub = async () => ({ok: true, status: 200, json: async () => [pack]});
  const src = fs.readFileSync(path.join(ROOT, 'web/static/app.js'), 'utf8');
  const app = new Function('filteredResult', 'document', 'window', 'fetch',
                           'FormData', 'Blob', 'URL',
    src + '\nreturn {loadPacks};')(
    filteredResult, document, {}, fetchStub, class {}, class {}, {});
  return {app, elems};
}

(async () => {
  const pack = {name: 'SYOG26', version: '2026.09', errors: [], conflicts: [],
                deduped: [], specialised: [], dd_unconvertible: [],
                converted_by_fallback: [], cache_warnings: [],
                unmatched_codesets: [
                  "ODF_ATH_Data_Dictionary.pdf line 580: asks for codeset 'DISCIPLINECLASS', which the Common Codes do not provide under any spelling -- no draft rule was offered for @Class."],
                rule_count: 86, usable: true};
  const r = render(pack);
  await r.app.loadPacks();
  const strip = r.elems['pack-report'].textContent;
  assert.ok(/DISCIPLINECLASS/.test(strip),
    `the refusal must reach the strip: ${strip}`);
  assert.ok(!/failed to load/.test(strip),
    `a refused draft is not a failed rule load: ${strip}`);
  assert.strictEqual(r.elems['pack-report'].hidden, false);
  console.log('pack_strip.test.js: ok');
})().catch((e) => { console.error(e.message || e); process.exit(1); });
