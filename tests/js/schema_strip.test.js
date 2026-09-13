// A ruleset with no usable XSD must say so on the strip, and must NOT be
// counted under "rule(s) failed to load" -- no rule failed, none had even
// been read. This is the banner a fresh clone of the public repository
// showed its operator: "1 rule(s) failed to load - first: pack.yaml
// root_xsd 'odf2.xsd' not found; falling back to heuristic."
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

const HEALTHY = {name: 'SYOG26', version: '2026.09', errors: [], conflicts: [],
                 deduped: [], specialised: [], dd_unconvertible: [],
                 converted_by_fallback: [], cache_warnings: [],
                 unmatched_codesets: [], schema_unavailable: [],
                 codes_unavailable: [], rule_count: 89, usable: true};

(async () => {
  const freshClone = Object.assign({}, HEALTHY, {
    schema_unavailable: ['This ruleset holds no XSD, so messages are not ' +
      'checked against the schema at all -- only the rules below run.'],
  });
  let r = render(freshClone);
  await r.app.loadPacks();
  let strip = r.elems['pack-report'].textContent;
  assert.ok(/no XSD/.test(strip), `the note must reach the strip: ${strip}`);
  assert.ok(!/failed to load/.test(strip),
    `a ruleset with no schema is not a ruleset whose rules failed: ${strip}`);
  assert.strictEqual(r.elems['pack-report'].hidden, false);

  // A healthy pack must stay silent, or this becomes another permanent
  // banner nobody reads.
  r = render(HEALTHY);
  await r.app.loadPacks();
  strip = r.elems['pack-report'].textContent;
  assert.strictEqual(strip, '', `healthy pack must be quiet, got: ${strip}`);
  assert.strictEqual(r.elems['pack-report'].hidden, true);

  // A freshly downloaded copy has neither the schema nor the workbook, and
  // this is the banner that sent an operator hunting for 53 broken rules:
  // "54 rule(s) failed to load", with 89 rules active in the same line.
  const firstLaunch = Object.assign({}, freshClone, {
    codes_unavailable: ['No code tables are loaded, so 52 code_membership ' +
      'rule(s) cannot fire. Import the Common Codes workbook from the ' +
      'publication page (Rulesets -> check and download updates -> apply), ' +
      'then reload.'],
  });
  r = render(firstLaunch);
  await r.app.loadPacks();
  strip = r.elems['pack-report'].textContent;
  assert.ok(/code tables/.test(strip), `the note must reach the strip: ${strip}`);
  assert.ok(!/failed to load/.test(strip),
    `a rule with no table to check against did not fail to load: ${strip}`);

  // The channel must survive an older /packs payload that predates it --
  // app.js is served to a browser that may still be holding a cached page.
  const legacy = Object.assign({}, HEALTHY);
  delete legacy.schema_unavailable;
  delete legacy.codes_unavailable;
  r = render(legacy);
  await r.app.loadPacks();
  assert.strictEqual(r.elems['pack-report'].textContent, '');

  console.log('schema_strip.test.js: ok');
})().catch((e) => { console.error(e.message || e); process.exit(1); });
