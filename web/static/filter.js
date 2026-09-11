// Pure helpers for filtering validation results by severity.
// Used by both the on-screen render and the JSON export so they always agree.
// Works in the browser (global functions) and under Node (module.exports).
function filterFindings(findings, active) {
  return (findings || []).filter(f => active.has(f.severity));
}

// Findings are grouped server-side: one entry can stand for many identical
// findings, with `occurrences` recording how many. Counts must therefore sum
// occurrences, not entries, so the true severity totals survive filtering and
// export. Legacy/ungrouped entries have no `occurrences` and count as one.
function _countsOf(findings) {
  const c = {error: 0, warning: 0, info: 0};
  for (const f of findings) if (f.severity in c) c[f.severity] += (f.occurrences || 1);
  return c;
}

function filteredResult(result, active) {
  if (!result) return result;
  if (result.files) {                       // batch result
    const files = {};
    const totals = {error: 0, warning: 0, info: 0};
    for (const [name, r] of Object.entries(result.files)) {
      const ff = filterFindings(r.findings, active);
      const counts = _countsOf(ff);
      files[name] = Object.assign({}, r, {findings: ff, counts});
      for (const k of ['error', 'warning', 'info']) totals[k] += counts[k];
    }
    return Object.assign({}, result, {files, totals});
  }
  const ff = filterFindings(result.findings, active);   // single-message result
  return Object.assign({}, result, {findings: ff, counts: _countsOf(ff)});
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {filterFindings, filteredResult};
}
