from __future__ import annotations
import io
import logging
import os
import secrets
import threading
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, File, UploadFile, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.ingestion import draft_store
from odf_validator.loader.pack import ruleset_summary
from odf_validator.pipeline.orchestrator import Pipeline
from odf_validator.context import ValidationContext
from odf_validator.model import BatchResult, MAX_SINGLE_FINDINGS
from odf_validator.sources.sync import (SyncReport, apply_targets,
                                        fetch_targets, orphaned_staged_files,
                                        read_source_config, staged_entries,
                                        superseded_stand_ins, verify_targets)
from odf_validator.sources.sync import check as source_check
from .browser import schedule_open

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RULES_ROOT = PROJECT_ROOT / "Rules"
PACKS: dict = {}

# Upstream source status, keyed by pack name. Populated in the background at
# startup; empty until the first check lands, and empty forever on a machine
# with no network. Nothing else depends on it.
SOURCE_REPORTS: dict = {}

# The operator's stated realistic ceiling. Applies to a single upload,
# to each zip member after decompression, and to a zip's cumulative expanded
# size -- so it also bounds a compression bomb, which needs no special case.
MAX_UPLOAD_BYTES = 150 * 1024 * 1024
# A zip holding more messages than this is a mistake, not a feed.
MAX_ZIP_MEMBERS = 5000


def _unique_key(results: dict, name: str) -> str:
    """Batch results are keyed by filename, and ODF feeds legitimately ship
    the same name from different units (a DT_RESULT.xml per unit). Colliding
    keys silently discarded the earlier file's findings."""
    if name not in results:
        return name
    n = 2
    while f"{name} ({n})" in results:
        n += 1
    return f"{name} ({n})"


def _nothing_to_validate(display_name: str, entries: list[str]) -> str:
    """Why an uploaded archive yielded no messages, in the operator's terms.

    A zip whose members are all zips used to be a silent pass: the member
    filter kept only names ending .xml, matched nothing, and the empty batch
    rendered as {"totals": {0,0,0}, "files": {}} -- indistinguishable from a
    genuinely clean run. A real IOC delivery is shaped exactly like that, and
    on 2026-09-13 one was read as "all 0 file(s) conform to SYOG26" when not a
    byte of it had been parsed. Counting what IS in the archive is the whole
    point: "holds 3 zip archives" tells the operator to unpack it, where a
    bare "no messages found" would read as a bug in the validator.
    """
    files = [n for n in entries if not n.endswith("/")]
    zips = [n for n in files if n.lower().endswith(".zip")]
    if zips:
        found = (f"{len(zips)} zip archive{'s' if len(zips) != 1 else ''} and "
                 f"no .xml messages -- unpack it and upload the messages, or "
                 f"the inner archive")
    elif files:
        found = (f"{len(files)} file{'s' if len(files) != 1 else ''}, none of "
                 f"them .xml messages")
    else:
        found = "no files"
    return f"{display_name} holds {found}. Nothing was validated."


def discover_packs(root: Path = None) -> None:
    root = root or RULES_ROOT
    PACKS.clear()
    if not root.exists():
        return
    for ruleset_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        pack = build_ruleset_pack(ruleset_dir)
        PACKS[pack.name] = pack


def refresh_source_reports(root: Path = None) -> None:
    """Check each configured pack against its upstream index page.

    Every failure is swallowed to a log line. This runs on startup, where an
    exception would turn 'the laptop is offline' into 'the validator will not
    start'.
    """
    log = logging.getLogger(__name__)
    root = root or RULES_ROOT

    # Enumerating the rulesets is itself I/O: pathlib's exists()/is_dir()/
    # iterdir() propagate PermissionError for a directory the process cannot
    # traverse (they only swallow ENOENT/ENOTDIR/EBADF/ELOOP). An unreadable
    # Rules/ must not take the startup thread down with it.
    try:
        if not root.exists():
            return
        ruleset_dirs = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError as e:
        log.info("Could not enumerate rulesets under %s: %s", root, e)
        return

    for ruleset_dir in ruleset_dirs:
        # The whole per-pack body is inside the try, not just source_check.
        # read_source_config happens not to raise today, but that is a
        # contract owned by another module: if it ever did, an uncaught
        # exception here would kill the background thread and silently skip
        # every remaining pack, reported only by Python's default thread
        # excepthook rather than this logger.
        try:
            config = read_source_config(ruleset_dir)
            if not config.get("index_url"):
                continue
            if config.get("check_on_start") is False:
                continue
            SOURCE_REPORTS[ruleset_dir.name] = source_check(ruleset_dir)
        except Exception as e:                      # noqa: BLE001
            # WARNING, not INFO: uvicorn configures only its own loggers, so
            # the root logger stays at WARNING and an info() here is discarded
            # before it reaches a handler. That is not theoretical -- the
            # feature's first release could not reach the site at all, and
            # this line printed nothing, on every start, for days.
            log.warning("Upstream source check for %s did not complete: %s",
                        ruleset_dir.name, e)
            # Store the failure too. Leaving SOURCE_REPORTS empty made a
            # crashed check indistinguishable from one that has not run yet,
            # and /sources then manufactured a healthy-looking empty report.
            SOURCE_REPORTS[ruleset_dir.name] = SyncReport(
                pack=ruleset_dir.name, configured=True,
                error=f"The check did not complete: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    discover_packs()
    # In a thread, so a slow or hanging index page cannot delay the port
    # binding. The page is one HTML request; the documents are never fetched
    # here.
    threading.Thread(target=refresh_source_reports, daemon=True,
                     name="odf-source-check").start()
    schedule_open()   # open the validator page in the browser (set ODF_NO_BROWSER to disable)
    yield


# --------------------------------------------------------------------------- #
# Local-only trust boundary
#
# This app has no login, because it is a single-operator desktop tool bound to
# 127.0.0.1. That is a reasonable design, but "bound to loopback" is not by
# itself an access control: a page the operator happens to be browsing can
# still reach the server from their own machine. Two ways in, closed here.
#
#   1. DNS rebinding. An attacker-controlled name whose A record flips to
#      127.0.0.1 makes the victim's browser treat this server as same-origin.
#      The Host header still carries the attacker's name, so checking it shuts
#      the door -- see enforce_local_host below.
#
#   2. Cross-site form POST. /drafts/approve, /approve_all and /reject change
#      which rules are live. A plain form POST needs no preflight, so any page
#      could submit one; approve_all needs no parameters at all, so an attacker
#      needed to know nothing about the install. A security review raised this as F-01.
#
# The token below is the load-bearing part: it is per-process and only ever
# rendered into this app's own pages, so an off-origin page cannot obtain it
# even if it can guess every other field. The Origin/Sec-Fetch-Site check in
# front of it is defence in depth, not the primary control.
# --------------------------------------------------------------------------- #

CSRF_TOKEN = secrets.token_urlsafe(32)

# Mutable and read per-request (not frozen into middleware at import time), so
# tests and unusual local setups can adjust it without rebuilding the app.
ALLOWED_HOSTS = {
    h.strip().lower()
    for h in os.environ.get("ODF_ALLOWED_HOSTS", "127.0.0.1,localhost,[::1]").split(",")
    if h.strip()
}


def _hostname(value: str) -> str:
    """Bare hostname from a Host header or an Origin URL, port stripped.

    Handles the bracketed IPv6 literal form ('[::1]:8000'), where a naive
    rsplit on ':' would return '[::1' and never match the allowlist.
    """
    value = (value or "").strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[:end + 1] if end != -1 else value
    return value.rsplit(":", 1)[0] if ":" in value else value


class RevalidatingStaticFiles(StaticFiles):
    """Serve assets with `Cache-Control: no-cache`.

    StaticFiles sends ETag and Last-Modified but no Cache-Control, and with no
    Cache-Control a browser may apply heuristic freshness -- about a tenth of
    the file's age when it was cached. styles.css had been unchanged for
    weeks, so the copy Chrome took then stayed "fresh" for days: the import
    popup shipped, the server served the new stylesheet, and the browser never
    asked for it. The popup rendered as unstyled text in the page flow.

    Worse than plainly not working: the same reload picked up rulesets.html
    (rendered per request) and sources.js (a new URL, never cached), so the
    feature half-arrived and looked broken rather than stale.

    `no-cache` means revalidate, not re-download. The ETag above turns each
    check into a 304 on loopback, for a single operator. Nothing here is worth
    the risk of a stale asset.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app = FastAPI(title="ODF Validator", lifespan=lifespan)
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "web" / "templates"))
app.mount("/static",
          RevalidatingStaticFiles(directory=str(PROJECT_ROOT / "web" / "static")),
          name="static")


@app.middleware("http")
async def enforce_local_host(request: Request, call_next):
    """Refuse any request whose Host header is not a loopback name.

    Closes the DNS-rebinding read path to /packs and /validate, whose responses
    quote attribute values out of the submitted XML. Raised as F-02.
    """
    if _hostname(request.headers.get("host", "")) not in ALLOWED_HOSTS:
        return PlainTextResponse(
            "This server only accepts requests addressed to localhost.",
            status_code=400)
    return await call_next(request)


def _is_same_origin(request: Request) -> bool:
    # Sec-Fetch-Site is the reliable signal in current browsers and is not
    # forgeable by page script. 'none' means the user typed the URL or used a
    # bookmark; 'same-origin' is our own page submitting its own form.
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site in ("same-origin", "none")
    origin = request.headers.get("origin")
    if origin is None:
        # No Origin at all means a non-browser client (curl, the test client).
        # Those cannot be driven by a malicious web page, and the token check
        # below still applies to them, so this is not a hole.
        return True
    return _hostname(urlsplit(origin).netloc) in ALLOWED_HOSTS


def guard_state_change(request: Request, csrf_token: str = Form(...)) -> None:
    """Dependency for every route that changes which rules are live."""
    if not _is_same_origin(request):
        raise HTTPException(403, "Cross-origin request refused.")
    if not secrets.compare_digest(csrf_token.encode("utf-8"),
                                  CSRF_TOKEN.encode("utf-8")):
        raise HTTPException(
            403, "This form is stale (the server restarted). "
                 "Reload /drafts and try again.")

# Populate at import as well, so a TestClient created without the context-manager
# form (which would otherwise skip lifespan startup) still has packs available.
discover_packs()


@app.get("/packs")
def list_packs():
    # `usable`: a pack with no compiled schema and no rules is a scaffold
    # (SOLG28), and validating against it yields CORE_XSD_INACTIVE plus
    # envelope noise. It sorts first, so it used to be the default selection.
    return [{"name": p.name, "version": p.version,
             "errors": p.report.errors, "conflicts": p.report.conflicts,
             "deduped": p.report.deduped,
             "specialised": p.report.specialised,
             "dd_unconvertible": p.report.dd_unconvertible,
             "converted_by_fallback": p.report.converted_by_fallback,
             "cache_warnings": p.report.cache_warnings,
             "unmatched_codesets": p.report.unmatched_codesets,
             "schema_unavailable": p.report.schema_unavailable,
             "codes_unavailable": p.report.codes_unavailable,
             "rule_count": len(p.rules),
             "usable": bool(p.schema) or bool(p.rules)}
            for p in PACKS.values()]


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # Starlette's modern signature is TemplateResponse(request, name, context=...).
    return templates.TemplateResponse(request=request, name="index.html")


# `def`, not `async def`: Pipeline().run is synchronous and CPU-bound, so an
# async handler runs it on the event loop and blocks every other request --
# including the page's own static assets, which is why a large batch looked
# like a hang. FastAPI runs a sync handler in its threadpool instead.
@app.post("/validate")
def validate(pack: str = Form(...),
             xml: Optional[str] = Form(None),
             file: Optional[UploadFile] = File(None)):
    if pack not in PACKS:
        raise HTTPException(404, f"Unknown pack: {pack}")
    if file is not None:
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                413, f"That file is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit.")
    elif xml is not None:
        # No explicit size check here: Starlette's multipart parser caps any
        # non-file form field (this one included) at max_part_size, 1MB by
        # default. That bound comes from the framework, not this code -- if
        # it's ever reconfigured, this path is no longer bounded by anything
        # of ours.
        data = xml.encode("utf-8")
    else:
        raise HTTPException(400, "Provide xml text or a file.")
    return Pipeline().run(data, PACKS[pack]).to_dict(max_findings=MAX_SINGLE_FINDINGS)


@app.get("/rulesets", response_class=HTMLResponse)
def rulesets_page(request: Request):
    # One fetch/apply pair per pack that has a publication page. This used to
    # be a single pair bound to sorted(PACKS)[0], which is SOLG28 (no
    # index_url) as soon as it sits beside SYOG26 -- so the button answered
    # staged=[] and the configured pack was unreachable from the UI.
    source_packs = [name for name in sorted(PACKS)
                    if read_source_config(RULES_ROOT / name).get("index_url")]
    return templates.TemplateResponse(
        request=request, name="rulesets.html",
        context={"rulesets": ruleset_summary(PACKS),
                 "csrf_token": CSRF_TOKEN,
                 "source_packs": source_packs})


def _report_json(report) -> dict:
    return {
        "pack": report.pack,
        "configured": report.configured,
        "error": report.error,
        "last_checked": report.last_checked,
        "entries": [{
            "reference": s.entry.reference,
            "title": s.entry.title,
            "kind": s.entry.kind,
            "discipline": s.entry.discipline,
            "published": s.entry.published.isoformat() if s.entry.published else None,
            "target": s.entry.target,
            "state": s.state,
            "local_reference": s.local_reference,
            "local_published": (s.local_published.isoformat()
                                if s.local_published else None),
        } for s in report.entries],
    }


@app.get("/sources")
def list_sources():
    """Upstream status per pack, from the last check.

    Reads cached state only -- it never makes a request of its own, so the
    page stays instant and an offline machine sees the last known answer
    rather than a hang.
    """
    rows = []
    for name in sorted(PACKS):
        report = SOURCE_REPORTS.get(name)
        if report is None:
            # No cached report: the pack is either unconfigured, or its check
            # has not finished. Say which. This used to return a report with
            # configured=true and error=null, which reads as "checked, nothing
            # to report" -- and that is exactly how a total failure to reach
            # the site looked for the feature's entire first release.
            configured = bool(read_source_config(
                RULES_ROOT / name).get("index_url"))
            report = SyncReport(
                pack=name, configured=configured,
                error=("The upstream check has not completed yet. If this "
                       "persists, it failed -- see the server log."
                       if configured else None))
        rows.append(_report_json(report))
    return rows


@app.post("/sources/fetch")
def fetch_sources(pack: str = Form(...),
                  _guard: None = Depends(guard_state_change)):
    """Settle unverified entries, then download whatever is genuinely newer.

    Verification comes first and is the reason this is one button rather than
    two: on a fresh install every document reads 'unverified', and without
    resolving those the fetch would have nothing to do.
    """
    if pack not in PACKS:
        raise HTTPException(404, f"Unknown pack: {pack}")
    ruleset_dir = RULES_ROOT / pack
    report = source_check(ruleset_dir)
    if not report.configured:
        # Not a 200 with staged=[]: that is exactly what an up-to-date pack
        # returns, so an unconfigured one was indistinguishable from "nothing
        # newer upstream".
        raise HTTPException(
            409, f"{pack} has no publication page configured "
                 f"(no source.index_url in its pack.yaml), so there is "
                 f"nothing to check or download.")
    if report.error:
        SOURCE_REPORTS[pack] = report
        raise HTTPException(502, report.error)

    unverified = [s.entry for s in report.entries if s.state == "unverified"]
    verify_targets(ruleset_dir, unverified)

    report = source_check(ruleset_dir)
    SOURCE_REPORTS[pack] = report
    staged = fetch_targets(ruleset_dir, [s.entry for s in report.updates])
    return {"pack": pack, "staged": staged}


@app.post("/sources/apply")
def apply_sources(pack: str = Form(...),
                  _guard: None = Depends(guard_state_change)):
    """Promote staged files into the live tree and reload the pack.

    Deliberately reads no network and no cached report: what is applicable
    is whatever is sitting in .incoming/ with a manifest record describing
    it (see sources/sync.py's `staged_entries`), full stop. Staging exists
    so a human can review before promoting -- an arbitrary amount of time,
    and an app restart, can pass in between -- so making this depend on
    SOURCE_REPORTS (empty until the first background check lands, and
    empty forever offline) defeated the point of staging: a file fetched
    while online used to become unapplicable, indistinguishable from
    nothing having been staged at all, the moment the app restarted
    offline.
    """
    if pack not in PACKS:
        raise HTTPException(404, f"Unknown pack: {pack}")
    ruleset_dir = RULES_ROOT / pack
    entries = staged_entries(ruleset_dir)
    applied = apply_targets(ruleset_dir, entries)
    # Staged files with no manifest record (an older build, or a lost/
    # corrupted manifest) are never applied blind -- see staged_entries's
    # docstring for why -- but must not vanish silently either, so they are
    # surfaced here rather than left indistinguishable from "not staged".
    unrecorded = orphaned_staged_files(ruleset_dir)
    # A hand-converted stand-in (e.g. a .md standing in for a newly-applied
    # .pdf) is deliberately never retired just because a same-url document
    # landed under a different suffix -- see _retire_superseded's suffix
    # guard. It is not deleted, so it is not an error, but it IS something
    # an operator should know is still sitting there so they can remove it
    # once satisfied the new file is good.
    held_stand_ins = superseded_stand_ins(ruleset_dir, entries)
    if applied:
        # Rebuild this pack so the new documents are live without a restart.
        PACKS[pack] = build_ruleset_pack(ruleset_dir)
        SOURCE_REPORTS[pack] = source_check(ruleset_dir)
    return {"pack": pack, "applied": applied, "unrecorded": unrecorded,
           "held_stand_ins": held_stand_ins}


@app.get("/drafts", response_class=HTMLResponse)
def drafts_page(request: Request, skipped: int = 0):
    drafts = draft_store.list_all_drafts(RULES_ROOT)
    active_ids = {r.id for p in PACKS.values() for r in p.rules}
    for d in drafts:
        d["_replaces_active"] = d.get("id") in active_ids
        # What approving this would change about the live rule. `dropped` is
        # the set that matters: parameters added by hand after the last
        # derivation, which the draft cannot know about and would silently
        # discard. Five were lost that way on 2026-09-01.
        d["_delta"] = draft_store.rule_delta(
            draft_store.active_rule(Path(d["_draft_file"]), d["id"]), d)
    return templates.TemplateResponse(request=request, name="drafts.html",
                                       context={"drafts": drafts,
                                                "skipped": skipped,
                                                "csrf_token": CSRF_TOKEN})


@app.post("/drafts/approve")
def approve_draft_route(draft_file: str = Form(...), rule_id: str = Form(...),
                        confirm_loss: Optional[str] = Form(None),
                        _guard: None = Depends(guard_state_change)):
    try:
        draft_store.approve_draft(Path(draft_file), rule_id,
                                  rules_root=RULES_ROOT,
                                  allow_loss=bool(confirm_loss))
    except draft_store.RefinementLoss as e:
        # 409, not 400: the request is well-formed, the state is the problem.
        # Reached only if the page's own guard was bypassed, so say what would
        # have been lost rather than failing blankly.
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except KeyError as e:
        raise HTTPException(404, str(e))
    discover_packs()
    # A plain <form> POST: answering with JSON navigates the reviewer to a
    # blank page showing a dict. 303 sends them back to the queue.
    return RedirectResponse(url="/drafts", status_code=303)


@app.post("/drafts/approve_all")
def approve_all_drafts_route(_guard: None = Depends(guard_state_change)):
    # Never allow_loss here. Approve-all is the path where nobody is reading
    # individual rules, so lossy drafts are skipped and left in the queue to
    # be approved deliberately, one at a time, with the delta on screen.
    _approved, skipped = draft_store.approve_all_drafts(RULES_ROOT)
    discover_packs()
    # Clean URL when nothing was held back; the counter is a notice, not state.
    target = f"/drafts?skipped={len(skipped)}" if skipped else "/drafts"
    return RedirectResponse(url=target, status_code=303)


@app.post("/drafts/reject_all")
def reject_all_drafts_route(_guard: None = Depends(guard_state_change)):
    # No skip list, unlike approve_all: rejecting writes to no active rule
    # file, so there is no refinement to lose, and the drafts come back from
    # the Data Dictionaries on the next ingestion run.
    draft_store.reject_all_drafts(RULES_ROOT)
    return RedirectResponse(url="/drafts", status_code=303)


@app.post("/drafts/reject")
def reject_draft_route(draft_file: str = Form(...), rule_id: str = Form(...),
                       _guard: None = Depends(guard_state_change)):
    try:
        draft_store.reject_draft(Path(draft_file), rule_id,
                                 rules_root=RULES_ROOT)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except KeyError as e:
        raise HTTPException(404, str(e))
    return RedirectResponse(url="/drafts", status_code=303)


@app.post("/validate/batch")
def validate_batch(pack: str = Form(...),
                   files: List[UploadFile] = File(...)):
    if pack not in PACKS:
        raise HTTPException(404, f"Unknown pack: {pack}")
    p = PACKS[pack]
    pipeline = Pipeline()
    ctx = ValidationContext()           # shared context enables cross-message rules
    batch = BatchResult()
    budget = MAX_UPLOAD_BYTES           # cumulative expanded bytes for this request
    for f in files:
        display_name = f.filename or "(unnamed)"
        data = f.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                413, f"{display_name} is larger than the "
                     f"{MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit.")
        if f.filename and f.filename.lower().endswith(".zip"):
            # Everything zipfile can raise while reading a member -- not just
            # the constructor -- is a malformed-input problem, not a server
            # bug: a smashed local-header magic number, an understated
            # file_size (bad CRC on read), a password-protected member
            # (RuntimeError), or an unsupported compression method
            # (NotImplementedError). All four are routine operator mistakes,
            # not attacks, so they get a 400. pipeline.run() is deliberately
            # called *outside* this try so a genuine internal error there
            # isn't mislabelled as a bad archive. HTTPException (413s raised
            # below for size/count limits) doesn't subclass any of these and
            # propagates through untouched -- see test_an_oversized_member_
            # still_returns_413_not_400.
            members = []
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    names = [n for n in z.namelist() if n.lower().endswith(".xml")]
                    if not names:
                        raise HTTPException(
                            400, _nothing_to_validate(display_name, z.namelist()))
                    if len(names) > MAX_ZIP_MEMBERS:
                        raise HTTPException(
                            413, f"{display_name} holds {len(names)} messages; the "
                                 f"limit is {MAX_ZIP_MEMBERS}.")
                    for name in names:
                        # The declared expanded size (central-directory
                        # file_size) is a cheap first gate. It cannot lie in
                        # a way that matters here: CPython's ZipExtFile
                        # truncates its output to the declared file_size
                        # (ZipExtFile._read1 does `data = data[:self._left]`,
                        # with _left seeded from file_size), so the capped
                        # read below can never produce more bytes than were
                        # declared. A member whose header *understates* the
                        # true size doesn't over-decompress past the
                        # declared bound -- zipfile raises BadZipFile (bad
                        # CRC-32) partway through the read instead, which is
                        # a malformed-archive error handled by the except
                        # clause below, not a size-limit bypass.
                        declared = z.getinfo(name).file_size
                        if declared > MAX_UPLOAD_BYTES:
                            raise HTTPException(
                                413, f"{display_name} expands beyond the "
                                     f"{MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit.")
                        with z.open(name) as member:
                            member_data = member.read(MAX_UPLOAD_BYTES + 1)
                        actual = len(member_data)
                        budget -= actual
                        if actual > MAX_UPLOAD_BYTES or budget < 0:
                            raise HTTPException(
                                413, f"{display_name} expands beyond the "
                                     f"{MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit.")
                        members.append((name, member_data))
            except (zipfile.BadZipFile, RuntimeError,
                    NotImplementedError, EOFError) as e:
                raise HTTPException(
                    400, f"{display_name} is not a readable zip archive.") from e
            for name, member_data in members:
                batch.results[_unique_key(batch.results, name)] = \
                    pipeline.run(member_data, p, ctx)
        else:
            # Loose (non-zip) files are charged to the same cumulative
            # budget as zip members, so N large loose files can't bypass it.
            budget -= len(data)
            if budget < 0:
                raise HTTPException(
                    413, f"This batch exceeds the cumulative "
                         f"{MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit.")
            batch.results[_unique_key(batch.results, display_name)] = \
                pipeline.run(data, p, ctx)
    return batch.to_dict()
