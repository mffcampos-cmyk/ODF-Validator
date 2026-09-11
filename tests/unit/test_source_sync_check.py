from __future__ import annotations
import os
from datetime import date
from pathlib import Path

import httpx
import pytest

from odf_validator.sources.provenance import (SOURCES_FILE_NAME, Provenance,
                                               SourceRecord)
from odf_validator.sources.sync import check

FIXTURE = Path(__file__).resolve().parents[1] / "corpus" / "dakar_2026_YOG.html"
INDEX_URL = "https://odf.olympictech.org/2026-Dakar/dakar_2026_YOG.html"


def index_client():
    def handler(request):
        return httpx.Response(200, text=FIXTURE.read_text(encoding="utf-8"),
                              headers={"content-type": "text/html"})
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def ruleset(tmp_path):
    """A ruleset laid out like Rules/SYOG26/, with the same mix of already
    converted .md general documents and a versioned codes filename."""
    root = tmp_path / "SYOG26"
    (root / "codes").mkdir(parents=True)
    (root / "xsd").mkdir()
    (root / "Disciplines" / "SWM").mkdir(parents=True)
    (root / "pack.yaml").write_text(
        f'version: "test"\nsource:\n  index_url: {INDEX_URL}\n', encoding="utf-8")
    (root / "codes" / "SYOG2026_ODF_Common_Codes_v_2_1.xlsx").write_bytes(b"codes")
    (root / "Disciplines" / "SWM" / "ODF_SWM_Data_Dictionary.pdf").write_bytes(b"swm")
    (root / "ODF_GEN_R-OWG2026-GEN.md").write_text("gen", encoding="utf-8")
    (root / "ODF_Foundation_Principles_R-SOG-2024-FND.md").write_text(
        "fnd", encoding="utf-8")
    (root / "ODF_GEN_R-OWG2026-NAME-Language_Guidelines.md").write_text(
        "names", encoding="utf-8")
    return root


def test_pack_without_a_source_block_is_not_configured(tmp_path):
    root = tmp_path / "SOLG28"
    root.mkdir()
    (root / "pack.yaml").write_text('version: ""\n', encoding="utf-8")

    report = check(root)          # no client: must make no request at all
    assert report.configured is False
    assert report.entries == []
    assert report.error is None


def test_adoption_matches_existing_files_and_never_claims_current(ruleset):
    with index_client() as c:
        report = check(ruleset, client=c)

    by_target = {s.entry.target: s for s in report.entries if s.entry.target}
    assert by_target["Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf"].state == "unverified"
    assert by_target["codes/"].state == "unverified"

    # The reported state alone does not pin this: _status_for short-circuits
    # on record.adopted before it ever looks at record.reference, so a bug
    # that stamped the entry's reference/published onto an adopted record
    # would still report "unverified" here and slip through. Check the
    # persisted record directly -- adoption must record what it holds, not
    # what upstream claims to be, precisely so a later real fetch is not
    # fooled into thinking this bytes-only guess was already verified.
    prov = Provenance.load(ruleset / SOURCES_FILE_NAME)
    swm_record = prov.get("Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf")
    assert swm_record is not None
    assert swm_record.reference is None
    assert swm_record.published is None


def test_adoption_accepts_a_converted_md_for_a_pdf_entry(ruleset):
    with index_client() as c:
        report = check(ruleset, client=c)

    gen = next(s for s in report.entries
               if s.entry.target == "ODF_GEN_R-OWG2026-GEN.pdf")
    assert gen.state == "unverified", (
        "the hand-converted .md must satisfy its .pdf entry, otherwise the "
        "first check reports every general document as new and applying it "
        "drops PDFs beside the Markdown for the scanner to ingest twice")


def test_a_document_with_no_local_file_is_new(ruleset):
    with index_client() as c:
        report = check(ruleset, client=c)

    arc = next(s for s in report.entries if s.entry.discipline == "ARC")
    assert arc.state == "new"
    # Common Codes Definition has no local .md in this repo either.
    ccdefn = next(s for s in report.entries
                  if s.entry.reference == "OWG-2026_CCDEFN")
    assert ccdefn.state == "new"


def test_adoption_is_persisted_so_the_second_check_is_cheap(ruleset):
    with index_client() as c:
        check(ruleset, client=c)
    saved = (ruleset / ".sources.json").read_text(encoding="utf-8")
    assert '"adopted": true' in saved
    assert '"reference": null' in saved


def test_last_checked_is_stamped(ruleset):
    with index_client() as c:
        report = check(ruleset, client=c)
    assert report.last_checked is not None
    assert report.last_checked.endswith("Z")


def test_unknown_kind_entry_is_reported_not_fetched(ruleset):
    with index_client() as c:
        report = check(ruleset, client=c)
    hv = next(s for s in report.entries if s.entry.reference == "YOG-2026-HV")
    assert hv.state == "unknown"


def test_network_failure_is_reported_not_raised(ruleset):
    def handler(request):
        raise httpx.ConnectError("offline")

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        report = check(ruleset, client=c)
    assert report.error is not None
    assert report.entries == []


def test_empty_index_body_is_reported_not_raised(ruleset):
    """An empty (or whitespace-only) body makes lxml_html.fromstring raise
    lxml.etree.ParserError, which is not a SourceFetchError, httpx.HTTPError,
    or ValueError. check() must swallow it like any other ordinary failure --
    a truncated proxy response or a misconfigured server is not exotic --
    rather than let it propagate out of a function that runs on app start."""
    def handler(request):
        return httpx.Response(200, text="   \n",
                              headers={"content-type": "text/html"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        report = check(ruleset, client=c)          # must not raise

    assert report.error is not None
    assert "index page" in report.error
    assert report.entries == []


def test_stem_match_does_not_bind_an_unrelated_record(ruleset):
    """A same-directory, same-stem provenance record from an unrelated
    document must not be adopted for a brand-new catalogue entry just
    because the filenames happen to collide. Reproduces the reviewer's
    Notes.md / Notes.pdf case: a stale record with a different url must not
    make a never-held Notes.pdf report as 'unverified'."""
    html = '''<html><body>
    <div class="doc-card">
      <div class="title">Notes</div>
      <div class="ref">Reference: NEW-NOTES</div>
      <div class="date">2 September 2026</div>
      <div class="links"><a class="pdf" href="new/Notes.pdf">PDF</a></div>
    </div>
    </body></html>'''

    def handler(request):
        return httpx.Response(200, text=html,
                              headers={"content-type": "text/html"})

    # A stale, unrelated record already sits in provenance for a same-stem
    # file that was never adopted for *this* entry -- a different document,
    # fetched from a different url, that just happens to share the stem.
    (ruleset / "Notes.md").write_text("unrelated notes", encoding="utf-8")
    prov = Provenance(path=ruleset / SOURCES_FILE_NAME)
    prov.put("Notes.md", SourceRecord(
        url="https://odf.olympictech.org/old/unrelated-Notes.md",
        reference=None, published=None, sha256="deadbeef", adopted=True))
    prov.save()

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        report = check(ruleset, client=c)

    notes = next(s for s in report.entries if s.entry.target == "Notes.pdf")
    assert notes.state == "new", (
        "the unrelated Notes.md record must not be bound to Notes.pdf just "
        "because the filename stem matches -- that would report a document "
        "as held/unverified when it was never actually fetched or adopted "
        "for this entry")


def test_save_failure_is_reported_not_raised(ruleset, monkeypatch):
    """Everything after the fetch/parse stage -- adoption, the status loop,
    orphan detection, and prov.save() -- previously ran unprotected. A
    reviewer demonstrated that a raising Provenance.save() (e.g. a full disk
    or a permission error, both real failure modes on this project's own
    state files) propagated straight out of check() and crashed it exactly
    like the original bug this module was built to prevent.

    The diff itself succeeded here -- only persisting it failed -- so the
    report must still come back usable rather than empty, and its error
    message must be distinguishable from a fetch/parse failure so an
    operator (or a test) can tell which stage actually broke."""
    from odf_validator.sources.provenance import Provenance

    def broken_save(self):
        raise OSError("Disk full or permission denied")

    monkeypatch.setattr(Provenance, "save", broken_save)

    with index_client() as c:
        report = check(ruleset, client=c)          # must not raise

    assert report.error is not None
    assert "index page" not in report.error
    assert "persist" in report.error.lower() or "save" in report.error.lower()
    # The diff itself succeeded -- only persisting it failed -- so the
    # caller still gets a usable report with its computed entries rather
    # than an empty one indistinguishable from "nothing could be read".
    assert report.entries != []
    arc = next(s for s in report.entries if s.entry.discipline == "ARC")
    assert arc.state == "new"


def test_a_logic_bug_in_the_diff_stage_still_propagates(ruleset, monkeypatch):
    """Pin against a future well-meaning 'just wrap the whole function in
    try/except' change. The fetch/parse stage is environmental I/O and is
    allowed to be swallowed -- the diffing logic is this module's own code,
    and a real defect there (e.g. a typo causing an AttributeError) must
    stay loud and crash check(), not get silently relabelled as 'could not
    read the index page'."""
    import odf_validator.sources.sync as sync_module

    def broken_status_for(ruleset_dir, entry, prov):
        raise AttributeError("boom: simulated typo in _status_for")

    monkeypatch.setattr(sync_module, "_status_for", broken_status_for)

    with index_client() as c:
        with pytest.raises(AttributeError, match="boom"):
            check(ruleset, client=c)


def test_second_check_does_not_re_adopt_and_downgrade_verified_records(ruleset):
    """Regression pin for the `if not prov.records:` guard in check(). If
    that guard is removed, _adopt_existing runs on every check() call and
    unconditionally overwrites any existing record for a locally-present
    file -- including one a later task has already verified against
    upstream (reference/published set, adopted=False) -- back down to an
    adopted, reference=None, published=None record. That would silently
    destroy real verification work on every single startup check."""
    with index_client() as c:
        check(ruleset, client=c)

    # Simulate a later task (not built yet) having verified the SWM Data
    # Dictionary against upstream: a real fetch matched hash and version, so
    # the record now carries the entry's own reference/published and is no
    # longer flagged as adopted.
    swm_target = "Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf"
    prov = Provenance.load(ruleset / SOURCES_FILE_NAME)
    verified = prov.get(swm_target)
    assert verified is not None
    verified.adopted = False
    verified.reference = "YOG-2026-SWM"
    verified.published = date(2026, 5, 19)
    prov.put(swm_target, verified)
    prov.save()

    with index_client() as c:
        report = check(ruleset, client=c)

    by_target = {s.entry.target: s for s in report.entries if s.entry.target}
    assert by_target[swm_target].state == "current", (
        "a second check() must not re-run adoption over an already-"
        "verified record and downgrade it back to 'unverified' -- that is "
        "exactly what the `if not prov.records:` guard in check() exists "
        "to prevent")


def _skip_unless_chmod_can_deny_access():
    """The three tests below provoke EACCES with chmod 000. That only works
    where the OS enforces the mode AND the caller is not exempt from it.

    Root is exempt: the mode is set and root reads the file regardless.

    Windows does not implement POSIX modes at all -- os.chmod() there only
    toggles the read-only bit, so chmod(p, 0o000) leaves the path fully
    readable. check() then takes its SUCCESS path and reports 'unverified'
    (or configured=True), which is correct behaviour for a readable path and
    simply not the situation under test. Without this guard those three read
    as failures on any Windows checkout of the public repository.

    What is being tested -- that an unreadable file, directory, or ruleset
    root is reported rather than raised -- is real and stays covered wherever
    POSIX permissions exist. Only the means of provoking it is missing here.
    """
    if os.name == "nt":
        pytest.skip("chmod 000 does not remove read access on Windows; "
                    "cannot exercise PermissionError on this platform")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("chmod 000 has no effect for root; cannot exercise "
                    "PermissionError as this user")


def test_unreadable_local_file_during_adoption_is_skipped_not_raised(ruleset):
    """Round 3's first repro: local.read_bytes() in _adopt_existing raises
    PermissionError for a file the process cannot read (e.g. chmod 000).
    That must not escape check() -- one unreadable file among many is not
    grounds to crash startup, and it must not be recorded as adopted when
    it was never actually hashed. It should simply report as "new", same
    as if nothing were on disk yet."""
    _skip_unless_chmod_can_deny_access()
    target = ruleset / "Disciplines" / "SWM" / "ODF_SWM_Data_Dictionary.pdf"
    os.chmod(target, 0o000)
    try:
        with index_client() as c:
            report = check(ruleset, client=c)          # must not raise
    finally:
        os.chmod(target, 0o644)

    swm = next(s for s in report.entries if s.entry.discipline == "SWM")
    assert swm.state == "new"


def test_local_file_vanishing_between_scan_and_hash_is_skipped_not_raised(
        ruleset, monkeypatch):
    """Round 3's second repro (TOCTOU): the file _local_file_for finds
    during its directory scan is deleted before _adopt_existing gets to
    local.read_bytes(), raising FileNotFoundError. Same requirement as the
    permission case: check() must not crash, and the entry must not be
    recorded as adopted -- it reports "new" and is retried next check."""
    target = ruleset / "Disciplines" / "SWM" / "ODF_SWM_Data_Dictionary.pdf"
    original_read_bytes = Path.read_bytes

    def vanish_then_read(self):
        if self == target and target.exists():
            target.unlink()
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", vanish_then_read)

    with index_client() as c:
        report = check(ruleset, client=c)               # must not raise

    swm = next(s for s in report.entries if s.entry.discipline == "SWM")
    assert swm.state == "new"


def test_unreadable_directory_during_adoption_is_skipped_not_raised(ruleset):
    """_local_file_for calls directory.iterdir() (and, for an unreadable
    directory, is_dir()/iterdir() can raise PermissionError too -- this is
    filesystem I/O just like read_bytes()). An unreadable discipline
    directory must not crash check(); that one entry reports "new" and
    every other entry is still processed normally."""
    _skip_unless_chmod_can_deny_access()
    directory = ruleset / "Disciplines" / "SWM"
    os.chmod(directory, 0o000)
    try:
        with index_client() as c:
            report = check(ruleset, client=c)            # must not raise
    finally:
        os.chmod(directory, 0o755)

    swm = next(s for s in report.entries if s.entry.discipline == "SWM")
    assert swm.state == "new"
    # Other entries are unaffected by the one bad directory.
    by_target = {s.entry.target: s for s in report.entries if s.entry.target}
    assert by_target["codes/"].state == "unverified"


def test_inaccessible_ruleset_dir_is_reported_not_raised(tmp_path):
    """read_source_config() calls manifest_path.exists() before its own
    try/except -- and exists() only swallows ENOENT/ENOTDIR/EBADF/ELOOP
    internally, not EACCES (verified empirically), so a ruleset directory
    the process cannot traverse (e.g. chmod 000) makes exists() raise
    PermissionError straight out of read_source_config(), before check()
    even reaches its own try blocks. That must not crash the app at
    startup any more than a missing pack.yaml does."""
    _skip_unless_chmod_can_deny_access()
    root = tmp_path / "LOCKED"
    root.mkdir()
    (root / "pack.yaml").write_text(
        'version: "test"\nsource:\n  index_url: https://x\n', encoding="utf-8")
    os.chmod(root, 0o000)
    try:
        report = check(root)                              # must not raise
    finally:
        os.chmod(root, 0o755)

    assert report.configured is False
    assert report.entries == []
    assert report.error is None


def test_provenance_load_failure_is_reported_not_raised(ruleset, monkeypatch):
    """Provenance.load() documents that it never raises, but that promise
    rests on Path.exists() -- which itself can raise PermissionError for a
    directory-level EACCES (verified empirically above; not one of the
    errnos pathlib ignores). sync.py does not own provenance.py, so it
    defends its own call site rather than trusting the docstring: a failure
    here degrades to an empty Provenance (same as a missing/corrupt file)
    so the rest of check() -- including a normal adoption pass -- still
    runs, rather than crashing the app at startup."""
    import odf_validator.sources.sync as sync_module

    def broken_load(path):
        raise PermissionError("Permission denied (simulated)")

    monkeypatch.setattr(sync_module.Provenance, "load", broken_load)

    with index_client() as c:
        report = check(ruleset, client=c)                 # must not raise

    assert report.error is None
    by_target = {s.entry.target: s for s in report.entries if s.entry.target}
    assert by_target["codes/"].state == "unverified"


def test_a_refused_stale_record_does_not_shadow_the_promoted_one(ruleset):
    """FINDING 2: _record_for used to return the FIRST record matching an
    archive entry's url in dict-iteration order -- alphabetical after a
    save/load round-trip -- rather than the one that actually represents
    the entry. A refused-but-retained stale record (see
    _retire_superseded's docstring: a target _confined refuses is KEPT,
    not dropped, precisely so the problem keeps surfacing) must not shadow
    the real one and make check() report a just-fetched archive as
    something other than 'current'.

    The refused record's `fetched_at` is deliberately set LATER than the
    real record's (and its `reference` deliberately different) -- this is
    what makes the test actually pin the `_confined` filter in
    _best_archive_record, not just the fetched_at tiebreak that runs after
    it: changing `candidates = confined or matches` to `matches` (dropping
    the filter entirely) would, with an EARLIER refused fetched_at, still
    happen to pick the real record by the tiebreak alone and pass anyway.
    With a LATER refused fetched_at, dropping the filter picks the refused
    record instead -- its distinct reference then makes _status_for report
    'update', not 'current', and only restoring the confined-only filtering
    makes this pass.
    """
    codes_url = "https://odf.olympictech.org/2026-Dakar/codes/ZIP/YOG2026_XLS_Codes.zip"

    prov = Provenance.load(ruleset / SOURCES_FILE_NAME)
    # Refused by _confined (resolves outside ruleset_dir) -- kept, not
    # dropped -- and its fetched_at sorts AFTER the real record below, so a
    # fetched_at-only tiebreak (with the confined filter removed) would
    # wrongly prefer this one.
    prov.put("codes/../../outside/evil.xlsx",
             SourceRecord(url=codes_url, reference="EVIL-REF", published=None,
                          sha256="bad", fetched_at="2026-09-03T00:00:00Z",
                          adopted=False))
    # The real record: a genuine fetch, matching the fixture's Common
    # Codes card (Reference: YOG-2026-2.2, 2 September 2026) exactly.
    prov.put("codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx",
             SourceRecord(url=codes_url, reference="YOG-2026-2.2",
                          published=date(2026, 9, 2), sha256="good",
                          fetched_at="2026-09-02T00:00:00Z", adopted=False))
    prov.save()
    (ruleset / "codes" / "SYOG2026_ODF_Common_Codes_v_2_2.xlsx").write_bytes(b"v22")

    with index_client() as c:
        report = check(ruleset, client=c)

    by_target = {s.entry.target: s for s in report.entries if s.entry.target}
    assert by_target["codes/"].state == "current", (
        "the refused stale record shadowed the real, freshly-verified "
        "one and made a just-fetched archive report as something other "
        "than 'current'")
