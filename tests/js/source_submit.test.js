// Submitting a source form must not navigate. The whole point of the change:
// clicking "Check and download updates" used to replace the Rulesets page
// with a page of raw JSON, so the operator lost the pack list, the status
// rows and their place.
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const ROOT = path.join(__dirname, '..', '..');

// A document stub thin enough to show what the page actually did: which
// listeners were attached, what landed in the popup host, whether the form
// was ever allowed to submit itself.
function makeHost() {
  return {hidden: true, className: '', innerHTML: '',
          querySelector(sel) { return this._close || null; },
          _close: {addEventListener(){}, focus(){}}};
}

function makePage({status, body, throws}) {
  const host = makeHost();
  let prevented = 0;
  let nativeSubmits = 0;
  let refreshed = 0;
  const form = {
    action: '/sources/fetch',
    getAttribute: (k) => (k === 'data-action-label' ? 'Check and download updates' : null),
    submit() { nativeSubmits += 1; },
    _handlers: {},
    addEventListener(type, fn) { this._handlers[type] = fn; },
    querySelectorAll: () => [{disabled: false, setAttribute(){}, removeAttribute(){}}],
  };
  const document = {
    getElementById: (id) => (id === 'source-popup' ? host : null),
    querySelectorAll: (sel) => (sel === 'form[data-async-source]' ? [form] : []),
    addEventListener() {},
  };
  const fetchStub = async () => {
    if (throws) throw new Error('simulated: connection refused');
    return {ok: status >= 200 && status < 300, status,
            json: async () => body};
  };
  const src = fs.readFileSync(path.join(ROOT, 'web/static/sources.js'), 'utf8');
  const mod = new Function('document', 'fetch', 'FormData', 'window',
    src + '\nreturn {wireSourceForms, submitSourceForm};')(
    document, fetchStub, class { constructor() {} append() {} },
    {refreshSourceRows: () => { refreshed += 1; }});
  return {mod, form, host,
          event: {preventDefault() { prevented += 1; }},
          counts: () => ({prevented, nativeSubmits, refreshed})};
}

(async () => {
  // 1. A successful fetch: no navigation, green popup, payload kept whole.
  let p = makePage({status: 200, body: {pack: 'SYOG26', staged: ['.incoming/a.pdf']}});
  p.mod.wireSourceForms();
  assert.ok(p.form._handlers.submit, 'the form must get a submit handler');
  await p.form._handlers.submit(p.event);
  assert.strictEqual(p.counts().prevented, 1,
    'the default form POST must be prevented, or the page navigates away');
  assert.strictEqual(p.counts().nativeSubmits, 0);
  assert.strictEqual(p.host.hidden, false, 'the popup must be shown');
  assert.ok(/popup-ok/.test(p.host.className), p.host.className);
  assert.ok(p.host.innerHTML.includes('.incoming/a.pdf'),
    `the response must be readable in the popup: ${p.host.innerHTML}`);
  assert.ok(p.host.innerHTML.includes('Check and download updates'),
    'the popup must name the action it is reporting');
  assert.strictEqual(p.counts().refreshed, 1,
    'the status rows must be refreshed after a successful import');

  // 2. A 409 from an unconfigured pack: red, and the server's message shown.
  p = makePage({status: 409, body: {detail: 'SOLG28 has no publication page configured'}});
  p.mod.wireSourceForms();
  await p.form._handlers.submit(p.event);
  assert.ok(/popup-fail/.test(p.host.className), p.host.className);
  assert.ok(p.host.innerHTML.includes('no publication page configured'),
    `the failure reason must reach the operator: ${p.host.innerHTML}`);
  assert.strictEqual(p.counts().refreshed, 0,
    'nothing changed, so nothing to refresh');

  // 3. An apply that held stand-ins back: yellow, not green.
  p = makePage({status: 200, body: {applied: ['a.pdf'], unrecorded: [],
                                    held_stand_ins: ['ODF_ARC_Data_Dictionary.md']}});
  p.mod.wireSourceForms();
  await p.form._handlers.submit(p.event);
  assert.ok(/popup-warn/.test(p.host.className), p.host.className);
  assert.ok(p.host.innerHTML.includes('ODF_ARC_Data_Dictionary.md'));

  // 3b. An empty result renders the honest wording, not "done". The helper
  //     knowing this is not enough: renderPopup has to pass the body through,
  //     which it did not when popupTitle first learned about emptiness.
  p = makePage({status: 200, body: {pack: 'SYOG26', staged: []}});
  p.mod.wireSourceForms();
  await p.form._handlers.submit(p.event);
  assert.ok(/popup-ok/.test(p.host.className), p.host.className);
  assert.ok(/no updates to download/.test(p.host.innerHTML),
    `an empty fetch must say so in the popup: ${p.host.innerHTML}`);
  assert.ok(!/&mdash; done|— done/.test(p.host.innerHTML),
    `"done" is the word a real import gets: ${p.host.innerHTML}`);

  // 4. The request itself fails (server stopped, connection refused). This
  //    must be a red popup, not an unhandled rejection that leaves the
  //    operator staring at a button that did nothing.
  p = makePage({throws: true});
  p.mod.wireSourceForms();
  await p.form._handlers.submit(p.event);
  assert.ok(/popup-fail/.test(p.host.className), p.host.className);
  assert.ok(/simulated: connection refused/.test(p.host.innerHTML),
    `the transport error must be shown: ${p.host.innerHTML}`);

  console.log('source_submit.test.js: ok');
})().catch((e) => { console.error(e); process.exit(1); });
