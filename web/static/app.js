// ODF Validator — interaction layer.
//
// Kept deliberately DOM-light: every element is addressed by id or class and
// mutated through .textContent / .innerHTML / .hidden only. tests/js runs this
// file against a hand-rolled document stub, so avoid classList, dataset,
// addEventListener and element.style on anything reachable from validate().

let lastResult = null;

const ALL_SEVERITIES = ['error', 'warning', 'info'];

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function byId(id) { return document.getElementById(id); }

/* ---------------------------------------------------------------- rulesets */

async function loadPacks() {
  const r = await fetch('/packs');
  const packs = await r.json();
  const sel = byId('pack');
  // A scaffold sorts first alphabetically (SOLG28 before SYOG26) and would
  // otherwise be the default selection: an empty pack that answers every
  // message with CORE_XSD_INACTIVE and no explanation. Select the first
  // usable pack by index instead. If none are usable (a fresh checkout with
  // only a scaffold) firstUsableIndex is -1 and no option matches it, so
  // nothing is marked selected and the browser falls back to its own
  // default of the first option -- there is no usable pack to prefer
  // instead. An empty pack list maps to an empty option list either way;
  // neither case throws.
  const firstUsableIndex = packs.findIndex(p => p.usable !== false);
  sel.innerHTML = packs.map((p, i) => {
    const label = `${esc(p.name)} ${esc(p.version)}` +
      (p.usable === false ? ' — scaffold, not usable' : '');
    const selected = i === firstUsableIndex ? ' selected' : '';
    return `<option value="${esc(p.name)}"${selected}>${label}</option>`;
  }).join('');
  sel.onchange = showPackReport;
  window._packs = packs;
  showPackReport();
}

/* Two channels, two lines. `pack-report` is the alarm strip: only things a
   human must fix (load failures, id collisions). `pack-info` is neutral
   bookkeeping — chiefly the discipline rules merged into their broader GEN
   equivalents, which is normal and lossless. They shared one red strip once,
   so a healthy SYOG26 announced "405 rule conflict(s)". */
function showPackReport() {
  const packs = window._packs || [];
  const cur = packs.find(p => p.name === byId('pack').value);
  const el = byId('pack-report');
  const bits = [];
  if (cur && cur.errors && cur.errors.length) {
    bits.push(`${cur.errors.length} rule(s) failed to load — first: ${cur.errors[0]}`);
  }
  if (cur && cur.conflicts && cur.conflicts.length) {
    bits.push(`${cur.conflicts.length} rule conflict(s) in this ruleset`);
  }
  if (cur && cur.dd_unconvertible && cur.dd_unconvertible.length) {
    // Not cosmetic: a DD that cannot be read takes its discipline's
    // DD-over-XSD suppression offline, so XSD "required but missing" errors
    // come back as false positives. The old copy said "rules unaffected".
    bits.push(`${cur.dd_unconvertible.length} Data Dictionary/ies unreadable — ` +
              `expect false positives for those disciplines`);
  }
  if (cur && cur.converted_by_fallback && cur.converted_by_fallback.length) {
    // Not a load failure -- those DDs converted and their rules are active.
    // But the DD parser's line regexes are tuned to the primary converter's
    // Markdown shape, so obligations read out of fallback output can be
    // subtly wrong. Silence here would leave the operator trusting rules
    // nothing told them to check.
    bits.push(`${cur.converted_by_fallback.length} Data Dictionary/ies ` +
              `converted by the fallback converter — check obligations ` +
              `parsed from them`);
  }
  if (cur && cur.cache_warnings && cur.cache_warnings.length) {
    // A cache-integrity alarm, not a rule-load failure -- no rule failed to
    // load. Kept off the "rule(s) failed to load" wording above: that label
    // was untrue here, and for a cache whose keys can never match again (a
    // renamed DD) it alarmed permanently with a remedy that could not fix it.
    bits.push(`${cur.cache_warnings.length} obligation cache warning(s) — ` +
              `first: ${cur.cache_warnings[0]}`);
  }
  el.textContent = bits.join('  ·  ');
  el.hidden = bits.length === 0;

  const info = byId('pack-info');
  if (!info) return;
  const notes = [];
  if (cur && typeof cur.rule_count === 'number') {
    notes.push(`${cur.rule_count} rules active`);
  }
  if (cur && cur.deduped && cur.deduped.length) {
    notes.push(`${cur.deduped.length} duplicate discipline rules merged`);
  }
  if (cur && cur.specialised && cur.specialised.length) {
    notes.push(`${cur.specialised.length} generic rules superseded by discipline rules`);
  }
  info.textContent = notes.join('  ·  ');
  info.hidden = notes.length === 0;
}

/* ------------------------------------------------------------ input modes */

// The old page showed paste, file and batch at once but validate() honoured
// only one of them, silently. The mode is now explicit and drives the request.
function currentMode() {
  const on = document.querySelectorAll('.modef:checked')[0];
  return (on && on.value) || 'paste';
}

function setMode() {
  const mode = currentMode();
  byId('pane-paste').hidden = mode !== 'paste';
  byId('pane-file').hidden = mode !== 'file';
  byId('pane-batch').hidden = mode !== 'batch';
}

/* ----------------------------------------------------------------- gutter */

// Line numbers are the one numbering device this page earns: findings cite
// them. After a check, lines that produced a finding carry a signal tick.
let markedLines = {};

const SEVERITY_RANK = {info: 0, warning: 1, error: 2};

function collectMarks(findings) {
  const marks = {};
  for (const f of findings || []) {
    const locs = (f.locations && f.locations.length) ? f.locations
               : (f.location ? [f.location] : []);
    for (const l of locs) {
      if (!l || l.line == null) continue;
      const prev = marks[l.line];
      if (!prev || SEVERITY_RANK[f.severity] > SEVERITY_RANK[prev]) {
        marks[l.line] = f.severity;
      }
    }
  }
  return marks;
}

function renderGutter() {
  const g = byId('gutter');
  if (!g) return;
  const lines = String(byId('xml').value || '').split('\n').length;
  const out = [];
  for (let i = 1; i <= lines; i++) {
    const sev = markedLines[i];
    out.push(sev ? `<b class="mk mk-${sev}">${i}</b>` : String(i));
  }
  g.innerHTML = out.join('\n');
}

/* ------------------------------------------------------------- tally rail */

function activeSeverities() {
  return new Set([...document.querySelectorAll('.sevf:checked')].map(c => c.value));
}

function emptyCounts() { return {error: 0, warning: 0, info: 0}; }

function unfilteredCounts(result) {
  if (!result) return emptyCounts();
  const full = filteredResult(result, new Set(ALL_SEVERITIES));
  return full.files ? (full.totals || emptyCounts()) : (full.counts || emptyCounts());
}

// `total` drives the numerals (so you can see what you have muted); `shown`
// drives the bar (so the rail always describes the list underneath it).
function renderTally(total, shown, scope, fresh) {
  const bar = byId('tally-bar');
  const sum = shown.error + shown.warning + shown.info;
  const cls = fresh ? 'seg' : 'seg seg-static';
  bar.innerHTML = ALL_SEVERITIES
    .filter(k => shown[k] > 0)
    .map(k => `<span class="${cls} seg-${k}" style="flex-grow:${shown[k]}"></span>`)
    .join('');
  byId('tally-idle').hidden = sum > 0;
  for (const k of ALL_SEVERITIES) byId('count-' + k).textContent = total[k];
  byId('tally-scope').textContent = scope || '';
}

/* --------------------------------------------------------------- findings */

// How many locations to spell out inline for a single grouped finding before
// summarising the rest. Grouping already collapses repeats into one row; this
// just keeps one pathological row (a rule firing thousands of times) from
// building an enormous string.
const MAX_LOCATIONS_SHOWN = 200;

function formatLocation(l) {
  const line = (l && l.line != null) ? l.line : '?';
  return `<span class="ln">L${esc(line)}</span>` +
         (l && l.path ? esc(l.path) : '');
}

function findingRow(f, file) {
  const locs = (f.locations && f.locations.length) ? f.locations
             : (f.location ? [f.location] : []);
  const n = f.occurrences || locs.length || 1;
  const shown = (locs.length ? locs : [f.location]).slice(0, MAX_LOCATIONS_SHOWN)
                  .map(formatLocation);
  const extra = Math.max(locs.length - shown.length, 0);
  return `<span class="tag ${esc(f.severity)}">${esc(f.severity)}</span>` +
    `<span class="rule-id">${esc(f.rule_id)}` +
      (n > 1 ? `<span class="count">&times;${esc(n)}</span>` : '') +
    `</span>` +
    `<p class="msg">${esc(f.message)}</p>` +
    `<span class="loc">` +
      (file ? `<span class="file">${esc(file)}</span>` : '') +
      shown.join('<span class="sep">;</span>') +
      (extra > 0 ? `<span class="sep">+</span>${extra} more` : '') +
      (f.source_ref ? `<span class="sep">·</span><span class="ref">${esc(f.source_ref)}</span>` : '') +
    `</span>`;
}

// Hard cap on how many <li> nodes we'll ever insert in one go, independent of
// what the server sends. This is defense-in-depth alongside the server-side
// findings_omitted cap (odf_validator/model.py): a huge batch response
// rendered one appendChild() at a time is what froze the browser tab on
// large .zip uploads, so DOM writes are batched via a fragment and hard-capped.
// Each node is now a grouped finding, so this budget stretches much further.
const MAX_RENDERED_FINDINGS = 5000;

function appendOmittedNotice(ul, count, context) {
  if (!count) return;
  const li = document.createElement('li');
  li.className = 'omitted';
  li.textContent = `${count} more finding(s)${context ? ' in ' + context : ''} not shown. ` +
                   `The response is capped so the page stays responsive.`;
  ul.appendChild(li);
}

// The ledger has four states: waiting, a clean pass, a note about what the run
// needs, or a list. A clean pass is a result too, and the old page never said
// so — it just showed an empty <ul>.
function setLedgerState(state, detail) {
  const el = byId('empty');
  if (state === 'list') { el.hidden = true; return; }
  el.hidden = false;
  if (state === 'clean') {
    el.className = 'empty clear';
    el.innerHTML = `<b>No findings</b>${esc(detail || '')}`;
  } else {
    el.className = 'empty';
    el.innerHTML = esc(detail || 'Paste an ODF message and validate it. Findings land here.');
  }
}

function renderSingle(view, total) {
  byId('batch-summary').innerHTML = '';
  const ul = byId('findings');
  ul.innerHTML = '';
  const frag = document.createDocumentFragment();
  const findings = view.findings || [];
  const shown = findings.slice(0, MAX_RENDERED_FINDINGS);
  for (const f of shown) {
    const li = document.createElement('li');
    li.className = 'sev-' + f.severity;
    li.innerHTML = findingRow(f, '');
    frag.appendChild(li);
  }
  ul.appendChild(frag);
  // Omission is measured in rows (grouped findings), matching what we render.
  const clientOmitted = findings.length - shown.length;
  appendOmittedNotice(ul, (view.findings_omitted || 0) + Math.max(clientOmitted, 0), '');

  const grand = total.error + total.warning + total.info;
  if (grand === 0) {
    setLedgerState('clean', ` — this message conforms to ${byId('pack').value}.`);
  } else if (findings.length === 0) {
    setLedgerState('clean', ' at the severities shown. Re-enable a key above to see the rest.');
  } else {
    setLedgerState('list');
  }
  // Rendered with textContent by renderTally, so it stays unescaped here.
  // The numerals are recomputed from the findings we were sent, so say so when
  // the server capped the response rather than quietly understating the count.
  return `${byId('pack').value}${view.doc_type ? ' · ' + view.doc_type : ''}` +
         (view.findings_omitted ? ` · ${view.findings_omitted} capped` : '');
}

function renderBatch(view, total) {
  const files = Object.entries(view.files);
  const worst = files.reduce((m, [, r]) =>
    Math.max(m, r.counts.error + r.counts.warning + r.counts.info), 0) || 1;
  const cell = (n, k) =>
    `<td class="num num-${k}${n ? '' : ' zero'}">${n}</td>`;
  const rows = files.map(([name, r]) => {
    const n = r.counts.error + r.counts.warning + r.counts.info;
    const bars = ALL_SEVERITIES.filter(k => r.counts[k] > 0).map(k =>
      `<span class="seg-${k}" style="flex-grow:${r.counts[k]}"></span>`).join('');
    // A clean file gets no bar at all — an empty stub would read as a finding.
    const mix = n === 0 ? '<span class="pass">clean</span>'
      : `<span class="microbar" style="max-width:${Math.max((n / worst) * 100, 6)}%">${bars}</span>`;
    return `<tr><td class="file">${esc(name)}</td>` +
      cell(r.counts.error, 'error') + cell(r.counts.warning, 'warning') +
      cell(r.counts.info, 'info') + `<td>${mix}</td></tr>`;
  }).join('');
  byId('batch-summary').innerHTML =
    `<caption class="sr-only">Findings per file</caption>` +
    `<tr><th scope="col">File</th><th scope="col" class="num">Err</th>` +
    `<th scope="col" class="num">Warn</th><th scope="col" class="num">Info</th>` +
    `<th scope="col">Mix</th></tr>${rows}`;

  const ul = byId('findings');
  ul.innerHTML = '';
  const frag = document.createDocumentFragment();
  let rendered = 0;
  let available = 0;        // grouped rows present in the response
  let serverOmitted = 0;    // grouped rows the server dropped at the cap
  for (const [name, r] of files) {
    serverOmitted += (r.findings_omitted || 0);
    for (const f of (r.findings || [])) {
      available++;
      if (rendered >= MAX_RENDERED_FINDINGS) continue;
      const li = document.createElement('li');
      li.className = 'sev-' + f.severity;
      li.innerHTML = findingRow(f, name);
      frag.appendChild(li);
      rendered++;
    }
  }
  ul.appendChild(frag);
  // Compare rows to rows: severity totals count occurrences, so they can't be
  // used here without over-counting grouped findings as omitted.
  const clientOmitted = Math.max(available - rendered, 0);
  appendOmittedNotice(ul, serverOmitted + clientOmitted, 'this batch');

  const grand = total.error + total.warning + total.info;
  if (grand === 0) {
    setLedgerState('clean', ` — all ${files.length} file(s) conform to ${byId('pack').value}.`);
  } else if (available === 0) {
    setLedgerState('clean', ' at the severities shown. Re-enable a key above to see the rest.');
  } else {
    setLedgerState('list');
  }
  return `${files.length} file(s) · ${byId('pack').value}` +
         (serverOmitted ? ` · ${serverOmitted} capped` : '');
}

// A failure must stop asserting a verdict: clear the findings list and the
// batch summary, and drop the tally back to its idle state. lastResult is
// deliberately left untouched by callers -- Export must still offer the
// last *good* run -- this only clears what's on screen.
function clearResultDisplay() {
  byId('findings').innerHTML = '';
  byId('batch-summary').innerHTML = '';
  renderTally(emptyCounts(), emptyCounts(), '', false);
}

function refresh(fresh) {
  if (!lastResult) return;
  const view = filteredResult(lastResult, activeSeverities());
  const total = unfilteredCounts(lastResult);
  const shown = view.files ? (view.totals || emptyCounts()) : (view.counts || emptyCounts());
  const scope = view.files ? renderBatch(view, total) : renderSingle(view, total);
  renderTally(total, shown, scope, !!fresh);
  if (fresh) {
    markedLines = view.files ? {} : collectMarks(unfilteredFindings(lastResult));
    renderGutter();
  }
}

function unfilteredFindings(result) {
  return (result && !result.files && result.findings) ? result.findings : [];
}

/* --------------------------------------------------------------- requests */

function setBusy(on) {
  const b = byId('validate');
  b.disabled = !!on;
  if (b.setAttribute) b.setAttribute('aria-busy', on ? 'true' : 'false');
  b.textContent = on ? 'Checking…' : 'Validate';
}

async function validate() {
  const mode = currentMode();
  const fd = new FormData();
  fd.append('pack', byId('pack').value);
  let url = '/validate';

  if (mode === 'batch') {
    const batch = byId('batch').files;
    if (!batch.length) {
      clearResultDisplay();
      return setLedgerState('note', 'Choose .xml files or a .zip, then validate.');
    }
    url = '/validate/batch';
    for (const f of batch) fd.append('files', f);
  } else if (mode === 'file') {
    const file = byId('file').files[0];
    if (!file) {
      clearResultDisplay();
      return setLedgerState('note', 'Choose an .xml file, then validate.');
    }
    fd.append('file', file);
  } else {
    const xml = byId('xml').value;
    if (!String(xml).trim()) {
      clearResultDisplay();
      return setLedgerState('note', 'Paste an ODF message, then validate.');
    }
    fd.append('xml', xml);
  }

  setBusy(true);
  try {
    const r = await fetch(url, {method: 'POST', body: fd});
    if (!r.ok) {
      // An error body is {"detail": "..."} — no findings, no files. Passed to
      // the filter it yields zero counts, and the ledger used to announce
      // "this message conforms" for a request that never validated anything.
      let detail = '';
      try { detail = (await r.json()).detail || ''; } catch (e) { detail = ''; }
      clearResultDisplay();
      return setLedgerState('note',
        `Couldn't validate — the server returned ${r.status}` +
        (detail ? `: ${detail}` : '.'));
    }
    const body = await r.json();
    // Shape check: a validation result is either a single message (findings)
    // or a batch (files). Anything else is not a result and must not be
    // rendered as one, whatever the status code said.
    if (!body || (!body.findings && !body.files)) {
      clearResultDisplay();
      return setLedgerState('note',
        "Couldn't validate — the server sent a response that isn't a result.");
    }
    lastResult = body;
    byId('export').disabled = false;
    refresh(true);
  } catch (e) {
    // fetch() rejects when the server isn't running or the connection drops.
    clearResultDisplay();
    return setLedgerState('note',
      "Couldn't reach the validator — is it still running?");
  } finally {
    setBusy(false);
  }
}

function exportJSON() {
  if (!lastResult) return;
  const view = filteredResult(lastResult, activeSeverities());
  const blob = new Blob([JSON.stringify(view, null, 2)], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'odf-validation.json';
  a.click();
}

/* ------------------------------------------------------------------ wiring */

byId('validate').onclick = validate;
byId('export').onclick = exportJSON;
byId('export').disabled = true;
byId('xml').oninput = renderGutter;
byId('xml').onscroll = function () { byId('gutter').scrollTop = byId('xml').scrollTop; };
document.querySelectorAll('.modef').forEach(r => { r.onchange = setMode; });
document.querySelectorAll('.sevf').forEach(c => { c.onchange = function () { refresh(false); }; });
loadPacks();
