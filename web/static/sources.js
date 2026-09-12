// ODF Validator — source-import actions on the Rulesets page.
//
// The fetch and apply buttons are plain <form> POSTs so they still work with
// no JavaScript. When this file loads it upgrades them: the POST is made with
// fetch(), the operator stays on the Rulesets page, and the server's answer is
// reported in a popup instead of replacing the page with raw JSON.
//
// Tone contract (tests/js/source_popup.test.js is the spec):
//   fail (red)    any non-2xx answer, or a request that never completed
//   warn (yellow) a 2xx that held stand-ins back, or that found staged files
//                 with no provenance record -- the import worked, but
//                 something on disk needs a human decision
//   ok   (green)  everything else, including "nothing was newer upstream"

function resultTone(status, body) {
  if (!(status >= 200 && status < 300)) return 'fail';
  const b = body || {};
  const held = (b.held_stand_ins || []).length;
  const unrecorded = (b.unrecorded || []).length;
  return (held || unrecorded) ? 'warn' : 'ok';
}

function prettyBody(body) {
  if (body == null) return '(no response body)';
  try {
    return JSON.stringify(body, null, 2);
  } catch (e) {
    return String(body);
  }
}

function popupTitle(tone, label, body) {
  if (tone === 'fail') return label + ' — failed';
  if (tone === 'warn') return label + ' — finished with warnings';
  // A clean run that moved nothing is still a success, so the tone stays
  // green -- but "done" is the word an import of 27 documents gets, and a
  // button that did nothing must not wear it. That was the whole shape of
  // the original bug: staged=[] reading as "checked, nothing newer" when the
  // truth was "asked the wrong pack". The payload says which button this
  // was: a fetch answers with `staged`, an apply with `applied`.
  const b = body || {};
  if (Array.isArray(b.staged) && b.staged.length === 0) {
    return label + ' — no updates to download';
  }
  if (Array.isArray(b.applied) && b.applied.length === 0) {
    return label + ' — nothing to apply';
  }
  return label + ' — done';
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderPopup(host, tone, label, body) {
  host.className = 'popup popup-' + tone;
  host.innerHTML =
    '<div class="popup-card" role="alertdialog" aria-modal="true" ' +
        'aria-labelledby="popup-title">' +
      '<h2 class="popup-title" id="popup-title">' +
        esc(popupTitle(tone, label, body)) + '</h2>' +
      '<pre class="popup-body">' + esc(prettyBody(body)) + '</pre>' +
      '<button type="button" class="btn" data-popup-close>Close</button>' +
    '</div>';
  host.hidden = false;
  const close = host.querySelector('[data-popup-close]');
  if (close) {
    close.addEventListener('click', function () {
      host.hidden = true;
      host.innerHTML = '';
    });
    close.focus();
  }
}

async function submitSourceForm(form, host) {
  const label = form.getAttribute('data-action-label') || 'Import';
  const buttons = form.querySelectorAll('button');
  for (const b of buttons) { b.disabled = true; b.setAttribute('aria-busy', 'true'); }
  let status = 0;
  let body = null;
  try {
    const response = await fetch(form.action,
                                 {method: 'POST', body: new FormData(form)});
    status = response.status;
    try {
      body = await response.json();
    } catch (e) {
      // A proxy error page, or an empty body. The status still decides the
      // tone; say plainly that the answer was not the JSON we expected
      // rather than rendering "null" and looking like a clean result.
      body = {error: 'The server did not return a JSON body.'};
    }
  } catch (e) {
    // The request never completed -- the server was stopped mid-import, or
    // the browser refused it. Left unhandled this was a button that did
    // nothing at all.
    status = 0;
    body = {error: String((e && e.message) || e)};
  }
  for (const b of buttons) { b.disabled = false; b.removeAttribute('aria-busy'); }

  const tone = resultTone(status, body);
  renderPopup(host, tone, label, body);
  // The pack list and the upstream status rows are now stale. Only on a
  // success: after a failure nothing moved, and a silent re-render would
  // suggest it had.
  if (tone !== 'fail' && typeof window !== 'undefined'
      && typeof window.refreshSourceRows === 'function') {
    window.refreshSourceRows();
  }
}

function wireSourceForms() {
  const host = document.getElementById('source-popup');
  if (!host) return;
  const forms = document.querySelectorAll('form[data-async-source]');
  for (const form of forms) {
    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      await submitSourceForm(form, host);
    });
  }
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !host.hidden) {
      host.hidden = true;
      host.innerHTML = '';
    }
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {resultTone, prettyBody, popupTitle};
} else if (typeof document !== 'undefined') {
  wireSourceForms();
}
