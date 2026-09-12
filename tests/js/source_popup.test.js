// The Rulesets page posts fetch/apply with fetch() and reports the outcome in
// a popup, instead of navigating the operator to a page of raw JSON.
//
// Tone contract, decided with the operator:
//   fail (red)    any non-2xx answer, or a request that could not be made
//   warn (yellow) a 2xx answer that held stand-ins back or found unrecorded
//                 staged files -- it worked, but something needs reading
//   ok   (green)  anything else, including "nothing was newer"
const path = require('path');
const assert = require('assert');
const ROOT = path.join(__dirname, '..', '..');
const {resultTone, prettyBody, popupTitle} =
  require(path.join(ROOT, 'web/static/sources.js'));

// --- tone -------------------------------------------------------------------

assert.strictEqual(resultTone(200, {pack: 'SYOG26', staged: ['a.pdf']}), 'ok');
assert.strictEqual(resultTone(200, {pack: 'SYOG26', staged: []}), 'ok',
  'an up-to-date pack is a success, not a warning');
assert.strictEqual(resultTone(200, {applied: ['a.pdf'], unrecorded: [],
                                    held_stand_ins: []}), 'ok');

assert.strictEqual(
  resultTone(200, {applied: ['a.pdf'], held_stand_ins: ['x.md'],
                   unrecorded: []}), 'warn',
  'a held stand-in must not be reported as a clean import');
assert.strictEqual(
  resultTone(200, {applied: [], unrecorded: ['stray.pdf'],
                   held_stand_ins: []}), 'warn');

assert.strictEqual(resultTone(409, {detail: 'no publication page'}), 'fail');
assert.strictEqual(resultTone(502, {detail: 'could not read index'}), 'fail');
assert.strictEqual(resultTone(0, null), 'fail',
  'a request that never completed is a failure, not an empty success');
// A failure wins even when the body looks like a warning-free success.
assert.strictEqual(resultTone(500, {applied: [], held_stand_ins: []}), 'fail');

// --- pretty print -----------------------------------------------------------

const pretty = prettyBody({pack: 'SYOG26', staged: ['.incoming/a.pdf']});
assert.ok(pretty.includes('\n  "pack": "SYOG26"'),
  `body must be pretty-printed, got: ${pretty}`);
assert.ok(pretty.includes('.incoming/a.pdf'), 'the payload must be kept whole');
assert.strictEqual(typeof prettyBody(null), 'string',
  'a missing body must still render something');

// --- title ------------------------------------------------------------------
//
// An empty result is still a success, so it stays green -- but "done" is the
// same word an import of 27 documents gets, and a button that did nothing
// must not wear that face. The payload says which button it was: a fetch
// answers with `staged`, an apply with `applied`.

assert.ok(/fail/i.test(popupTitle('fail', 'Check and download updates', {})));
assert.ok(popupTitle('ok', 'Apply downloaded', {applied: ['a.pdf']})
            .includes('Apply downloaded'),
  'the title must say which action this was');
assert.ok(/warning/i.test(popupTitle('warn', 'Apply downloaded', {})));

assert.strictEqual(
  popupTitle('ok', 'Check and download updates', {pack: 'X', staged: []}),
  'Check and download updates \u2014 no updates to download');
assert.strictEqual(
  popupTitle('ok', 'Apply downloaded',
             {pack: 'X', applied: [], unrecorded: [], held_stand_ins: []}),
  'Apply downloaded \u2014 nothing to apply');

// Work actually done keeps the plain wording.
assert.strictEqual(
  popupTitle('ok', 'Check and download updates', {staged: ['.incoming/a.pdf']}),
  'Check and download updates \u2014 done');
assert.strictEqual(
  popupTitle('ok', 'Apply downloaded', {applied: ['a.pdf']}),
  'Apply downloaded \u2014 done');

// A tone that needs attention wins over the emptiness wording: an apply that
// applied nothing but held a stand-in back has something to read.
assert.ok(/warning/i.test(
  popupTitle('warn', 'Apply downloaded',
             {applied: [], held_stand_ins: ['ODF_ARC_Data_Dictionary.md']})));

console.log('source_popup.test.js: ok');
