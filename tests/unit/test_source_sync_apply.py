from __future__ import annotations
import io
import os
import zipfile
from pathlib import Path

import httpx
import pytest

from odf_validator.sources.catalogue import CatalogueEntry
from odf_validator.sources.sync import fetch_targets

DD = CatalogueEntry(reference="YOG-2026-SWM", title="ODF Swimming Data Dictionary",
                    published=None, kind="dd",
                    url="https://odf.olympictech.org/2026-Dakar/YOG/"
                        "ODF_SWM_Data_Dictionary.pdf",
                    target="Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf",
                    discipline="SWM")

CODES = CatalogueEntry(reference="YOG-2026-2.2", title="Common Codes",
                       published=None, kind="codes",
                       url="https://odf.olympictech.org/2026-Dakar/codes/ZIP/"
                           "YOG2026_XLS_Codes.zip",
                       target="codes/", discipline=None)


def zip_bytes(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in names:
            z.writestr(name, b"xlsx-body")
    return buf.getvalue()


def client_serving(bodies):
    def handler(request):
        for suffix, (body, ctype) in bodies.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(200, content=body,
                                      headers={"content-type": ctype})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_document_lands_staged_not_live(tmp_path):
    root = tmp_path / "SYOG26"
    root.mkdir()
    with client_serving({".pdf": (b"%PDF-1.7", "application/pdf")}) as c:
        staged = fetch_targets(root, [DD], client=c)

    assert staged == [".incoming/Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf"]
    assert (root / staged[0]).read_bytes() == b"%PDF-1.7"
    assert not (root / DD.target).exists()


def test_an_archive_is_extracted_into_the_staging_layout(tmp_path):
    root = tmp_path / "SYOG26"
    root.mkdir()
    body = zip_bytes(["SYOG2026_ODF_Common_Codes_v_2_2.xlsx", "readme.txt"])
    with client_serving({".zip": (body, "application/zip")}) as c:
        staged = fetch_targets(root, [CODES], client=c)

    # Only the .xlsx members are kept; the archive itself is never stored.
    assert staged == [".incoming/codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx"]
    assert not list(root.glob("**/*.zip"))


def test_archive_member_paths_cannot_escape_the_staging_folder(tmp_path):
    """A zip member named ../../evil.xlsx must not write outside .incoming."""
    root = tmp_path / "SYOG26"
    root.mkdir()
    body = zip_bytes(["../../evil.xlsx"])
    with client_serving({".zip": (body, "application/zip")}) as c:
        staged = fetch_targets(root, [CODES], client=c)

    assert staged == []
    assert not (tmp_path.parent / "evil.xlsx").exists()


def test_an_empty_200_body_stages_nothing(tmp_path):
    """MINOR 5 (final whole-branch review): commit b3f0949 fixed the falsy-
    body check at BOTH call sites (verify_targets and fetch_targets), but
    only verify_targets' half was ever pinned by a test
    (test_an_empty_200_body_leaves_the_entry_unverified in
    test_source_verify.py) -- this module's own copy at line ~701
    (`not result.body`, not `is None`) could be reverted to `is None`
    without failing anything. A 200 with an empty body is a transport
    failure, not a legitimate zero-byte document; staging it would let a
    later apply overwrite a good local file with nothing.
    """
    root = tmp_path / "SYOG26"
    root.mkdir()

    def handler(request):
        return httpx.Response(200, content=b"",
                              headers={"content-type": "application/pdf"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        staged = fetch_targets(root, [DD], client=c)

    assert staged == []
    assert not (root / ".incoming").exists() or not list(
        (root / ".incoming").rglob("*"))


def test_a_failed_document_does_not_abort_the_others(tmp_path):
    root = tmp_path / "SYOG26"
    root.mkdir()
    missing = CatalogueEntry(reference="X", title="Gone", published=None,
                             kind="dd",
                             url="https://odf.olympictech.org/gone.pdf",
                             target="Disciplines/XXX/gone.pdf", discipline="XXX")
    with client_serving({"ODF_SWM_Data_Dictionary.pdf":
                         (b"%PDF-1.7", "application/pdf")}) as c:
        staged = fetch_targets(root, [missing, DD], client=c)

    assert staged == [".incoming/Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf"]


def zip_bytes_with_corrupt_member(good_names, bad_name):
    """A zip whose central directory is intact and openable, but one
    member's stored bytes have been flipped after writing so its CRC-32
    no longer matches -- data-level corruption on a single member, as
    opposed to a truncated/corrupt central directory (which fails at
    zipfile.ZipFile() itself, before any member can be read)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name in good_names:
            z.writestr(name, b"good-body")
        z.writestr(bad_name, b"bad-body-xxxx")
    data = bytearray(buf.getvalue())
    idx = data.find(b"bad-body-xxxx")
    assert idx != -1, "fixture bug: could not locate the bad member's bytes"
    data[idx] ^= 0xFF
    return bytes(data)


@pytest.mark.parametrize("evil_name", [
    "..\\..\\evil.xlsx",
    "C:\\evil.xlsx",
])
def test_archive_member_paths_with_windows_separators_are_refused(tmp_path, evil_name):
    """The traversal guard must not depend on the host OS's own path
    separator semantics. On POSIX, backslash is an ordinary filename
    character, so a member literally named '..\\..\\evil.xlsx' or
    'C:\\evil.xlsx' has no '/' in it and used to slip past a guard built
    from bare pathlib.Path. Refused here means: not written anywhere
    under the staging folder, and not reported as staged."""
    root = tmp_path / "SYOG26"
    root.mkdir()
    body = zip_bytes([evil_name])
    with client_serving({".zip": (body, "application/zip")}) as c:
        staged = fetch_targets(root, [CODES], client=c)

    assert staged == []
    # Independent of what the host OS would do with this name: nothing
    # new should exist anywhere under tmp_path.
    before_and_after = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert not any("evil" in p.name for p in before_and_after)


@pytest.mark.parametrize("evil_name", [
    "../../evil.xlsx",
    "nested/x.xlsx",
    "/etc/passwd.xlsx",
])
def test_archive_member_paths_with_posix_separators_are_refused(tmp_path, evil_name):
    """Companion cases to the Windows-separator test above -- POSIX-style
    traversal, a nested member, and an absolute path must all still be
    refused after the guard is rewritten to be host-OS-independent."""
    root = tmp_path / "SYOG26"
    root.mkdir()
    body = zip_bytes([evil_name])
    with client_serving({".zip": (body, "application/zip")}) as c:
        staged = fetch_targets(root, [CODES], client=c)

    assert staged == []
    files = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert not any(("evil" in p.name or "passwd" in p.name) for p in files)


def test_archive_member_disguised_as_a_symlink_is_still_refused(tmp_path):
    """A member flagged in its external_attr as a symlink (as a real IOC
    zip would never contain, but a hostile one could) combines the
    symlink trick with a traversal name. It must still be caught by the
    plain name check -- this code never interprets external_attr, it
    only ever writes the member's raw bytes as an ordinary file, so the
    name-based guard is the only, and sufficient, defence."""
    import stat
    root = tmp_path / "SYOG26"
    root.mkdir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("../evil.xlsx")
        info.create_system = 3  # unix
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(info, b"/etc/passwd")
    with client_serving({".zip": (buf.getvalue(), "application/zip")}) as c:
        staged = fetch_targets(root, [CODES], client=c)

    assert staged == []
    files = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert not any("evil" in p.name for p in files)


def test_a_bad_crc_on_one_member_does_not_cost_the_others(tmp_path):
    """The behaviour the corrected docstring actually describes: a
    single member with a bad CRC-32 is skipped, the archive stays open,
    and the other members that decompress fine are still staged."""
    root = tmp_path / "SYOG26"
    root.mkdir()
    body = zip_bytes_with_corrupt_member(
        good_names=["SYOG2026_ODF_Common_Codes_v_2_2.xlsx"],
        bad_name="Corrupt_Codes.xlsx",
    )
    with client_serving({".zip": (body, "application/zip")}) as c:
        staged = fetch_targets(root, [CODES], client=c)

    assert staged == [".incoming/codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx"]
    assert not (root / ".incoming/codes/Corrupt_Codes.xlsx").exists()


def test_a_truncated_central_directory_loses_every_member(tmp_path):
    """Contrast case for finding 2: corrupting the central directory
    itself (rather than one member's data) fails at the ZipFile()
    constructor, so nothing at all is staged -- this is NOT per-member
    isolation, it costs the whole archive."""
    root = tmp_path / "SYOG26"
    root.mkdir()
    good = zip_bytes(["SYOG2026_ODF_Common_Codes_v_2_2.xlsx"])
    truncated = good[: len(good) - 10]  # chop off the end of the central directory
    with client_serving({".zip": (truncated, "application/zip")}) as c:
        staged = fetch_targets(root, [CODES], client=c)

    assert staged == []
    assert not list((root / ".incoming").rglob("*")) if (root / ".incoming").exists() else True


def test_duplicate_target_paths_are_not_double_reported(tmp_path):
    """Finding 3: two members that extract to the same destination path
    (a duplicate member name inside one archive, which the ZIP format
    permits) must not appear twice in the returned staged list -- only
    the second write survives on disk, and apply_targets (a later task)
    consumes `staged` to promote files, so a duplicate entry there would
    promote the same file twice."""
    root = tmp_path / "SYOG26"
    root.mkdir()
    body = zip_bytes(["SYOG2026_ODF_Common_Codes_v_2_2.xlsx",
                      "SYOG2026_ODF_Common_Codes_v_2_2.xlsx"])
    with client_serving({".zip": (body, "application/zip")}) as c:
        staged = fetch_targets(root, [CODES], client=c)

    assert staged == [".incoming/codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx"]
    assert len(staged) == len(set(staged))


def test_fetch_targets_refuses_a_hostile_general_target_even_bypassing_catalogue(tmp_path):
    """CRITICAL 2 (final whole-branch review), defence in depth. The primary
    fix lives in catalogue._classify, which now refuses to hand back a
    'general' target carrying a directory component under either path
    syntax -- so parse_catalogue can never produce this. But a
    CatalogueEntry can also be built directly (as this test does, standing
    in for any future code path that might), and fetch_targets must not
    trust entry.target on the strength of that alone: it is the thing
    joined onto `incoming` and written to disk.

    '..\\..\\..\\..\\Startup\\evil.pdf' is not itself a traversal on THIS
    test's POSIX host -- backslash is an ordinary filename character there,
    so the pre-fix code wrote it as one oddly-named file safely inside
    .incoming/. On the Windows host this app actually runs in production,
    the exact same string walks four directories up and out. The fix must
    refuse the target outright, on every host, rather than depend on
    whether resolve() happens to treat backslash as a separator -- so what
    this test pins is host-independent by construction: nothing is staged,
    and no file carrying any trace of the hostile name is written ANYWHERE
    under tmp_path, not even harmlessly inside .incoming/. (The escape onto
    a real Windows machine cannot be reproduced on this host at all -- that
    is exactly why the assertion is refusal-and-no-write, not "check where
    it landed".)
    """
    root = tmp_path / "SYOG26"
    root.mkdir()
    hostile = CatalogueEntry(
        reference="EVIL", title="Evil", published=None, kind="general",
        url="https://odf.olympictech.org/2026-Dakar/general/evil.pdf",
        target="..\\..\\..\\..\\Startup\\evil.pdf", discipline=None)

    with client_serving({".pdf": (b"%PDF-evil", "application/pdf")}) as c:
        staged = fetch_targets(root, [hostile], client=c)

    assert staged == []
    files = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert not any("evil" in p.name.lower() or "startup" in p.name.lower()
                  for p in files), (
        "a hostile target must be refused outright -- not written anywhere, "
        "not even harmlessly inside .incoming/ under its literal name")


def test_a_logic_bug_in_stage_archive_still_propagates(tmp_path, monkeypatch):
    """Pin against a future well-meaning 'just wrap the per-member loop in
    try/except Exception' change. The catches around each member's write
    are narrowed to OSError and zipfile.BadZipFile -- a real defect (e.g.
    an AttributeError from a typo) must stay loud."""
    import odf_validator.sources.sync as sync_module

    root = tmp_path / "SYOG26"
    root.mkdir()
    body = zip_bytes(["SYOG2026_ODF_Common_Codes_v_2_2.xlsx"])

    def broken_read(self, member, *a, **kw):
        raise AttributeError("boom: simulated typo")

    monkeypatch.setattr(zipfile.ZipFile, "read", broken_read)

    with client_serving({".zip": (body, "application/zip")}) as c:
        with pytest.raises(AttributeError, match="boom"):
            sync_module.fetch_targets(root, [CODES], client=c)


from odf_validator.sources.provenance import Provenance, SourceRecord
from odf_validator.sources.sync import apply_targets


def stage(root: Path, rel: str, body: bytes) -> None:
    path = root / ".incoming" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def test_staged_file_is_promoted_and_recorded(tmp_path):
    root = tmp_path / "SYOG26"
    (root / "Disciplines" / "SWM").mkdir(parents=True)
    stage(root, "Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf", b"%PDF-new")

    applied = apply_targets(root, [DD])

    assert applied == ["Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf"]
    assert (root / DD.target).read_bytes() == b"%PDF-new"
    assert not (root / ".incoming" / DD.target).exists()

    record = Provenance.load(root / ".sources.json").get(DD.target)
    assert record.reference == "YOG-2026-SWM"
    assert record.adopted is False


def test_a_missing_discipline_folder_is_created(tmp_path):
    root = tmp_path / "SYOG26"
    root.mkdir()
    stage(root, "Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf", b"%PDF-new")

    apply_targets(root, [DD])
    assert (root / "Disciplines" / "SWM" / "ODF_SWM_Data_Dictionary.pdf").exists()


def test_the_superseded_codes_file_is_retired(tmp_path):
    root = tmp_path / "SYOG26"
    (root / "codes").mkdir(parents=True)
    old = root / "codes" / "SYOG2026_ODF_Common_Codes_v_2_1.xlsx"
    old.write_bytes(b"v21")

    prov = Provenance.load(root / ".sources.json")
    prov.put("codes/SYOG2026_ODF_Common_Codes_v_2_1.xlsx",
             SourceRecord(url=CODES.url, reference=None, published=None,
                          sha256="x", adopted=True))
    prov.save()

    stage(root, "codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx", b"v22")
    apply_targets(root, [CODES])

    remaining = sorted(p.name for p in (root / "codes").iterdir())
    assert remaining == ["SYOG2026_ODF_Common_Codes_v_2_2.xlsx"], (
        "leaving 2.1 beside 2.2 means the loader ingests both code tables")


def test_an_unrecorded_file_in_the_same_folder_survives(tmp_path):
    root = tmp_path / "SYOG26"
    (root / "codes").mkdir(parents=True)
    (root / "codes" / "hand_written_notes.xlsx").write_bytes(b"mine")
    stage(root, "codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx", b"v22")

    apply_targets(root, [CODES])

    assert (root / "codes" / "hand_written_notes.xlsx").exists(), (
        "never delete a file the app did not put there")


def test_applying_with_nothing_staged_is_a_no_op(tmp_path):
    root = tmp_path / "SYOG26"
    root.mkdir()
    assert apply_targets(root, [DD]) == []


def test_retire_refuses_a_posix_traversal_target(tmp_path):
    """FINDING 1: a provenance record's `target` is a dict key straight out
    of .sources.json -- plain JSON in the user's own repo, hand-editable or
    corruptible -- and was trusted on nothing but a url match. A record
    naming '../outside/victim.txt' under CODES' own url must not let
    apply_targets delete a file outside ruleset_dir."""
    root = tmp_path / "SYOG26"
    root.mkdir()
    victim_dir = tmp_path / "outside"
    victim_dir.mkdir()
    victim = victim_dir / "victim.txt"
    victim.write_bytes(b"do not delete me")

    prov = Provenance.load(root / ".sources.json")
    prov.put("../outside/victim.txt",
             SourceRecord(url=CODES.url, reference=None, published=None,
                          sha256="x", adopted=True))
    prov.save()

    stage(root, "codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx", b"v22")
    applied = apply_targets(root, [CODES])

    assert victim.exists(), "a '../' traversal target must not be deleted"
    assert applied == ["codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx"], (
        "the legitimate promotion must still succeed")


def test_retire_refuses_a_deep_posix_traversal_target(tmp_path):
    """Companion to the single-level case: a deeper '../../..' climb must
    be refused the same way."""
    root = tmp_path / "SYOG26" / "nested" / "deep"
    root.mkdir(parents=True)
    victim_dir = tmp_path / "outside"
    victim_dir.mkdir()
    victim = victim_dir / "victim.txt"
    victim.write_bytes(b"do not delete me")

    prov = Provenance.load(root / ".sources.json")
    prov.put("../../../outside/victim.txt",
             SourceRecord(url=CODES.url, reference=None, published=None,
                          sha256="x", adopted=True))
    prov.save()

    stage(root, "codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx", b"v22")
    apply_targets(root, [CODES])

    assert victim.exists(), "a deep '../../..' traversal target must not be deleted"


def test_retire_refuses_an_absolute_posix_target(tmp_path):
    """A record naming an absolute path must not be deleted either -- an
    absolute `target` joined with `ruleset_dir` via '/' discards
    ruleset_dir entirely (pathlib's own semantics), so the vulnerable code
    would delete exactly the file the absolute path names."""
    root = tmp_path / "SYOG26"
    root.mkdir()
    victim_dir = tmp_path / "abs_outside"
    victim_dir.mkdir()
    victim = victim_dir / "victim.txt"
    victim.write_bytes(b"do not delete me")

    prov = Provenance.load(root / ".sources.json")
    prov.put(str(victim),
             SourceRecord(url=CODES.url, reference=None, published=None,
                          sha256="x", adopted=True))
    prov.save()

    stage(root, "codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx", b"v22")
    apply_targets(root, [CODES])

    assert victim.exists(), "an absolute target must not be deleted"


def _skip_unless_windows_paths_are_ordinary_filenames():
    """Both tests below need a Windows-absolute string ('C:\\Windows\\x',
    '\\\\server\\share\\x') to be an ORDINARY FILENAME, so that `root / target`
    puts a real file inside root and the assertion can prove apply_targets
    left it alone. That premise holds only off Windows.

    On Windows those strings are genuinely absolute, and pathlib joins an
    absolute path by REPLACING rather than nesting -- `root / 'C:\\Windows\\x'`
    is 'C:\\Windows\\x'. So the fixture escapes tmp_path entirely: the UNC
    case dies with FileNotFoundError at setup, and the drive-letter case, run
    from an elevated shell, silently writes into the real C:\\Windows and then
    'passes' without having tested anything.

    The behaviour under test -- that a target which is absolute under EITHER
    flavour of path semantics is refused unconditionally, not merely when it
    resolves outside the ruleset -- is exactly what matters when a
    .sources.json travels between hosts, and it stays covered on POSIX.
    """
    if os.name == "nt":
        pytest.skip("a Windows-absolute target is not an ordinary filename on "
                    "Windows; `root / target` escapes tmp_path, so this "
                    "fixture cannot be built here")


def test_retire_refuses_a_windows_style_absolute_target_even_on_posix(tmp_path):
    """The confinement guard must be host-independent, the same reasoning
    as `_has_directory_component`'s docstring for archive members.
    'C:\\Windows\\victim.txt' has no leading '/', so on a POSIX host a
    bare pathlib.Path(target).is_absolute() check would say False, and
    `ruleset_dir / target` would treat it as one oddly-named file living
    INSIDE ruleset_dir -- so this places a real file at exactly that
    literal path inside ruleset_dir and asserts it survives regardless:
    this code and the .sources.json it reads travel to Windows too, where
    the same string is a real absolute path, so it must be refused
    unconditionally, not only when it happens to resolve outside."""
    _skip_unless_windows_paths_are_ordinary_filenames()
    root = tmp_path / "SYOG26"
    root.mkdir()
    victim = root / "C:\\Windows\\victim.txt"
    victim.write_bytes(b"do not delete me")

    prov = Provenance.load(root / ".sources.json")
    prov.put("C:\\Windows\\victim.txt",
             SourceRecord(url=CODES.url, reference=None, published=None,
                          sha256="x", adopted=True))
    prov.save()

    stage(root, "codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx", b"v22")
    apply_targets(root, [CODES])

    assert victim.exists(), "a Windows-style absolute target must not be deleted"


def test_retire_refuses_a_unc_style_target_even_on_posix(tmp_path):
    """Companion case: a UNC path ('\\\\server\\share\\x') is absolute
    under PureWindowsPath even though it has no drive letter and no
    leading '/'. Same host-independence reasoning as the Windows-absolute
    case above."""
    _skip_unless_windows_paths_are_ordinary_filenames()
    root = tmp_path / "SYOG26"
    root.mkdir()
    victim = root / "\\\\server\\share\\victim.txt"
    victim.write_bytes(b"do not delete me")

    prov = Provenance.load(root / ".sources.json")
    prov.put("\\\\server\\share\\victim.txt",
             SourceRecord(url=CODES.url, reference=None, published=None,
                          sha256="x", adopted=True))
    prov.save()

    stage(root, "codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx", b"v22")
    apply_targets(root, [CODES])

    assert victim.exists(), "a UNC-style target must not be deleted"


def test_a_file_recorded_under_a_different_entrys_url_survives(tmp_path):
    """FINDING 2: `_retire_superseded`'s `record.url != entry.url` check has
    no test that can distinguish it from a no-op -- both committed tests
    (the superseded-file case and the unrecorded-file case) pass whether or
    not that check exists, because the unrecorded fixture has no provenance
    record at all. This one has a REAL record, for a DIFFERENT entry's url,
    sitting in the same folder as the entry being promoted -- so it fails
    if `record.url != entry.url` is removed from _retire_superseded."""
    root = tmp_path / "SYOG26"
    (root / "codes").mkdir(parents=True)
    other = root / "codes" / "some_other_source.xlsx"
    other.write_bytes(b"not superseded by CODES")

    prov = Provenance.load(root / ".sources.json")
    prov.put("codes/some_other_source.xlsx",
             SourceRecord(url="https://odf.olympictech.org/2026-Dakar/"
                              "codes/ZIP/UnrelatedSource.zip",
                          reference=None, published=None,
                          sha256="y", adopted=True))
    prov.save()

    stage(root, "codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx", b"v22")
    apply_targets(root, [CODES])

    assert other.exists(), (
        "a file recorded under a different entry's url must never be "
        "retired just because it shares a directory with this entry's "
        "target")


def test_retire_refuses_a_target_with_an_embedded_null_byte(tmp_path):
    """FINDING 1: a provenance target containing an embedded NUL byte (e.g.
    from a hand-edited or corrupted .sources.json) makes resolve() raise
    ValueError: embedded null byte inside _confined -- NOT an OSError.
    Before the fix that propagated straight out of _retire_superseded, out
    of apply_targets, and aborted the ENTIRE run: one corrupted record
    blocked promotion for every entry, not just its own. It must be
    refused the same as any other unconfinable target, the legitimate
    promotion must still succeed, and (same "keep it so it is noticed"
    contract as every other unconfinable target) the bad record is kept,
    not silently dropped."""
    root = tmp_path / "SYOG26"
    root.mkdir()

    prov = Provenance.load(root / ".sources.json")
    prov.put("codes/vic\x00tim.txt",
             SourceRecord(url=CODES.url, reference=None, published=None,
                          sha256="x", adopted=True))
    prov.save()

    stage(root, "codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx", b"v22")
    applied = apply_targets(root, [CODES])          # must not raise

    assert applied == ["codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx"]
    assert Provenance.load(root / ".sources.json").get(
        "codes/vic\x00tim.txt") is not None, (
        "an unconfinable target's record must be kept, not dropped, so "
        "the problem keeps surfacing")


def test_a_malformed_record_does_not_block_other_entries_in_the_same_run(tmp_path):
    """The stronger invariant behind Finding 1: one corrupted provenance
    record must not abort promotion of every OTHER, unrelated entry in the
    same apply_targets() call. Not merely 'apply_targets does not raise' --
    every other staged entry must still land."""
    root = tmp_path / "SYOG26"
    (root / "codes").mkdir(parents=True)
    (root / "Disciplines" / "SWM").mkdir(parents=True)

    prov = Provenance.load(root / ".sources.json")
    prov.put("codes/vic\x00tim.txt",
             SourceRecord(url=CODES.url, reference=None, published=None,
                          sha256="x", adopted=True))
    prov.save()

    stage(root, "codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx", b"v22")
    stage(root, "Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf", b"%PDF-new")

    applied = apply_targets(root, [CODES, DD])       # must not raise/abort

    assert set(applied) == {
        "codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx",
        "Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf",
    }, "one malformed record must not block promotion of the other entry"


@pytest.mark.parametrize("target", ["", "."])
def test_confined_refuses_the_ruleset_root_itself(tmp_path, target):
    """FINDING 3 (minor): _confined("") and _confined(".") used to return
    ruleset_dir itself rather than None. Harmless today (is_file() on a
    directory is False) but it silently drops that provenance record from
    consideration -- the opposite of the keep-it-so-it-is-noticed stance
    the rest of this module takes toward unusable targets."""
    import odf_validator.sources.sync as sync_module
    root = tmp_path / "SYOG26"
    root.mkdir()
    assert sync_module._confined(root, target) is None


def test_a_logic_bug_in_confined_still_propagates(tmp_path, monkeypatch):
    """Pin against a future well-meaning 'just wrap it in except Exception'
    widening of _confined's catch tuple. Only OSError, ValueError, and
    RuntimeError are caught -- the enumerated input-validation failures a
    hostile/corrupted target can trigger -- so a real defect in this
    function's own logic (e.g. an AttributeError from a typo) raised
    inside the try block must still propagate loudly."""
    import odf_validator.sources.sync as sync_module

    root = tmp_path / "SYOG26"
    root.mkdir()

    def broken_resolve(self, *a, **kw):
        raise AttributeError("boom: simulated typo")

    monkeypatch.setattr(Path, "resolve", broken_resolve)

    with pytest.raises(AttributeError, match="boom"):
        sync_module._confined(root, "codes/foo.xlsx")


# ------------------------------------------------- the staging manifest ---
#
# apply_targets' ground truth must be what is on disk in .incoming/, not a
# live catalogue -- see api/app.py's /sources/apply route and its docstring.
# fetch_targets now writes a manifest record (StagedEntry) alongside every
# file it stages, and staged_entries() reconstructs CatalogueEntry objects
# from that manifest alone, no network involved.

import os
import json

import odf_validator.sources.sync as sync_module
from odf_validator.sources.sync import (orphaned_staged_files,
                                        staged_entries,
                                        superseded_stand_ins)

ARC_DD = CatalogueEntry(
    reference="YOG-2026-ARC", title="ODF Archery Data Dictionary",
    published=None, kind="dd",
    url="https://odf.olympictech.org/2026-Dakar/YOG/"
        "ODF_ARC_Data_Dictionary.pdf",
    target="Disciplines/ARC/ODF_ARC_Data_Dictionary.pdf", discipline="ARC")


def test_fetch_targets_writes_a_manifest_record_apply_can_use_offline(tmp_path):
    """The core of the fix: fetch_targets stages the bytes AND records what
    the file is, and staged_entries() reconstructs an equivalent entry from
    that record alone -- no catalogue passed in, no network client at all.
    """
    root = tmp_path / "SYOG26"
    root.mkdir()
    with client_serving({".pdf": (b"%PDF-1.7", "application/pdf")}) as c:
        fetch_targets(root, [DD], client=c)

    reconstructed = staged_entries(root)
    assert len(reconstructed) == 1
    entry = reconstructed[0]
    assert entry.url == DD.url
    assert entry.reference == DD.reference
    assert entry.published == DD.published
    assert entry.kind == DD.kind
    assert entry.target == DD.target
    assert entry.discipline == DD.discipline
    assert entry.title == DD.title

    applied = apply_targets(root, reconstructed)
    assert applied == [DD.target]
    assert (root / DD.target).read_bytes() == b"%PDF-1.7"


def test_the_manifest_file_itself_is_never_ingested(tmp_path):
    """.incoming is in scanner.MANAGED_DIR_NAMES; confirm the manifest sitting
    directly inside it is excluded from scan_ruleset the same way any other
    file under .incoming/ already is."""
    from odf_validator.ingestion.scanner import scan_ruleset

    root = tmp_path / "SYOG26"
    root.mkdir()
    with client_serving({".pdf": (b"%PDF-1.7", "application/pdf")}) as c:
        fetch_targets(root, [DD], client=c)

    manifest_path = root / ".incoming" / "manifest.json"
    assert manifest_path.exists(), "fixture bug: no manifest was written"

    scan = scan_ruleset(root)
    all_scanned = (scan.xsd_files + scan.code_files
                  + [p for p, _ in scan.dd_files] + scan.unknown_files)
    assert manifest_path not in all_scanned


def test_a_staged_file_with_no_manifest_record_is_not_applied_but_is_reported(tmp_path):
    """Design decision: a staged file an older build left behind (or one
    whose manifest record was lost) is never applied blind -- doing so
    would write a provenance record (reference/published) this module
    cannot fill in truthfully. But it must not be silently stranded either
    -- indistinguishable from 'nothing staged' is exactly the bug this
    whole manifest exists to fix. So: staged_entries() does not reconstruct
    an entry for it (apply_targets is never even asked about it), and
    orphaned_staged_files() names it so a caller can surface it."""
    root = tmp_path / "SYOG26"
    root.mkdir()
    stage(root, DD.target, b"%PDF-orphan")   # staged with NO manifest at all

    assert staged_entries(root) == []
    assert orphaned_staged_files(root) == [DD.target]

    applied = apply_targets(root, staged_entries(root))
    assert applied == []
    assert (root / ".incoming" / DD.target).exists(), (
        "an unrecorded staged file must be left in place, not deleted")
    assert not (root / DD.target).exists(), (
        "an unrecorded staged file must not be promoted")


def test_a_manifest_record_whose_file_is_gone_is_dropped_not_kept(tmp_path):
    """Design decision: contrast _confined's 'keep it so it is noticed'
    stance toward a provenance record it cannot confirm is safe -- that
    guards against corruption. A manifest record naming a file that simply
    is not there anymore (a user deleted it from .incoming/ by hand) is not
    corruption, just staleness, and self-heals: it is dropped the next time
    the manifest is read, and the drop is persisted."""
    root = tmp_path / "SYOG26"
    root.mkdir()
    with client_serving({".pdf": (b"%PDF-1.7", "application/pdf")}) as c:
        fetch_targets(root, [DD], client=c)

    (root / ".incoming" / DD.target).unlink()   # simulate a hand deletion

    assert staged_entries(root) == []

    manifest_raw = json.loads(
        (root / ".incoming" / "manifest.json").read_text(encoding="utf-8")
    ) if (root / ".incoming" / "manifest.json").exists() else {"entries": {}}
    assert DD.target not in manifest_raw.get("entries", {}), (
        "the dangling record must be dropped from the persisted manifest, "
        "not just from what staged_entries() returns in memory")


def test_a_partial_apply_leaves_the_manifest_describing_what_remains(tmp_path, monkeypatch):
    """Design decision: apply_targets is per-target, not transactional (see
    its own docstring). The manifest must stay coherent with that: after a
    run where one target is promoted and another fails, the manifest must
    still describe the one that is still genuinely staged, and must have
    dropped the one that is now live."""
    root = tmp_path / "SYOG26"
    (root / "Disciplines" / "SWM").mkdir(parents=True)
    (root / "Disciplines" / "ARC").mkdir(parents=True)
    with client_serving({"ODF_SWM_Data_Dictionary.pdf":
                         (b"%PDF-swm", "application/pdf"),
                         "ODF_ARC_Data_Dictionary.pdf":
                         (b"%PDF-arc", "application/pdf")}) as c:
        fetch_targets(root, [DD, ARC_DD], client=c)

    real_write_bytes = Path.write_bytes

    def flaky_write_bytes(self, data, *a, **kw):
        if self.name == "ODF_ARC_Data_Dictionary.pdf" and self.parent.name == "ARC":
            raise OSError("simulated: disk full writing the ARC destination")
        return real_write_bytes(self, data, *a, **kw)

    monkeypatch.setattr(Path, "write_bytes", flaky_write_bytes)
    applied = apply_targets(root, staged_entries(root))

    assert applied == [DD.target], "only the SWM document should have promoted"
    assert (root / DD.target).exists()
    assert not (root / ARC_DD.target).exists()
    assert (root / ".incoming" / ARC_DD.target).exists(), (
        "the failed target's staged file must still be sitting in .incoming/")

    remaining = staged_entries(root)
    assert [e.target for e in remaining] == [ARC_DD.target], (
        "the manifest must still describe exactly the target that is still "
        "staged, having dropped the one that was successfully promoted")


@pytest.mark.parametrize("key_form", ["relative-traversal", "absolute"])
def test_a_hostile_manifest_key_cannot_reach_outside_the_ruleset(tmp_path,
                                                                 key_form):
    """manifest.json is JSON in the user's own repo, so its keys are as
    untrusted as a provenance target -- and they become paths twice over:
    once to locate the staged file under .incoming/, once as the
    destination apply_targets writes and _retire_superseded may delete.

    Before staged_entries() ran them through _confined, a traversal key
    made _staged_for resolve the "staged file" to that outside path, copy
    it onto itself, and then unlink it -- because the staged file is
    deliberately removed last. The net effect was deleting an arbitrary
    file outside the ruleset. Confirmed reachable at the time.

    The key is COMPUTED from tmp_path rather than hardcoded: a fixed
    '../../../../tmp/victim' string resolves somewhere unrelated to the
    victim this test creates, so the test would pass with the guard
    removed -- which is exactly what an earlier draft of it did.
    """
    victim_dir = tmp_path / "outside"
    victim_dir.mkdir()
    victim = victim_dir / "victim.pdf"
    victim.write_bytes(b"ORIGINAL")

    root = tmp_path / "SYOG26"
    incoming = root / ".incoming"
    incoming.mkdir(parents=True)

    if key_form == "absolute":
        hostile_key = str(victim)
    else:
        hostile_key = os.path.relpath(victim, start=incoming)
        # Sanity-check the fixture itself: this must really resolve onto
        # the victim, or the test proves nothing.
        assert (incoming / hostile_key).resolve() == victim.resolve()

    (incoming / "manifest.json").write_text(json.dumps({"entries": {
        hostile_key: {
            "url": "https://odf.olympictech.org/x.pdf",
            "reference": "R", "published": None, "kind": "dd",
            "target": hostile_key, "discipline": None, "title": "t"},
    }}), encoding="utf-8")

    assert staged_entries(root) == []
    assert apply_targets(root, staged_entries(root)) == []
    assert victim.read_bytes() == b"ORIGINAL"


def test_a_hostile_archive_manifest_key_cannot_reach_outside_the_ruleset(tmp_path):
    """Self-review finding while fixing CRITICAL 1: the archive branch of
    _staged_for now selects members by iterating apply_targets' OWN raw
    manifest load (_reconcile_manifest) directly, rather than the
    already-confined entries staged_entries() would have produced --
    apply_targets can be, and is, called directly with hand-built entries
    and no pre-filtering (see its own docstring). Without confining each
    manifest KEY here too, a hostile key sharing the archive entry's
    url/target but resolving OUTSIDE the ruleset would have this function
    treat that outside path as a genuine staged member: apply_targets would
    read it, write its bytes elsewhere, and -- staged files are always
    unlinked LAST -- delete the original. Confirmed reachable before this
    guard existed, the same class as f73d438's own regression.
    """
    victim_dir = tmp_path / "outside"
    victim_dir.mkdir()
    victim = victim_dir / "victim.pdf"
    victim.write_bytes(b"ORIGINAL")

    root = tmp_path / "SYOG26"
    incoming = root / ".incoming"
    incoming.mkdir(parents=True)

    hostile_key = os.path.relpath(victim, start=incoming)
    assert (incoming / hostile_key).resolve() == victim.resolve(), (
        "fixture bug: the key must really resolve onto the victim")

    (incoming / "manifest.json").write_text(json.dumps({"entries": {
        hostile_key: {
            "url": CODES.url, "reference": "R", "published": None,
            "kind": "codes", "target": "codes/", "discipline": None,
            "title": "t"},
    }}), encoding="utf-8")

    # apply_targets called DIRECTLY with a hand-built entry, deliberately
    # bypassing staged_entries()'s own confinement -- exactly the calling
    # convention its docstring promises still works.
    applied = apply_targets(root, [CODES])

    assert applied == []
    assert victim.read_bytes() == b"ORIGINAL"


def test_superseded_stand_ins_surfaces_the_kept_mismatch(tmp_path):
    """The suffix guard in _retire_superseded keeps the file; this is how a
    caller (the /sources/apply route) learns it is there so a human can
    remove it once satisfied."""
    root = tmp_path / "SYOG26"
    (root / "Disciplines" / "GEN").mkdir(parents=True)
    (root / "Disciplines" / "GEN" / "ODF_GEN_R-OWG2026-GEN.md").write_bytes(
        b"# hand-converted")

    prov = Provenance.load(root / ".sources.json")
    prov.put("Disciplines/GEN/ODF_GEN_R-OWG2026-GEN.md",
             SourceRecord(url=DD.url.replace("SWM", "GEN"), reference=None,
                          published=None, sha256="x", adopted=True))
    prov.save()

    gen_entry = CatalogueEntry(
        reference="OWG-2026-GEN", title="ODF General Messages",
        published=None, kind="dd", url=DD.url.replace("SWM", "GEN"),
        target="Disciplines/GEN/ODF_GEN_R-OWG2026-GEN.pdf", discipline="GEN")
    stage(root, gen_entry.target, b"%PDF-real")
    apply_targets(root, [gen_entry])

    assert superseded_stand_ins(root, [gen_entry]) == [
        "Disciplines/GEN/ODF_GEN_R-OWG2026-GEN.md"]


def test_superseded_stand_ins_is_empty_once_nothing_is_held_back(tmp_path):
    """No mismatch, nothing to report -- the ordinary xlsx-to-xlsx case."""
    root = tmp_path / "SYOG26"
    (root / "codes").mkdir(parents=True)
    (root / "codes" / "SYOG2026_ODF_Common_Codes_v_2_1.xlsx").write_bytes(b"v21")

    prov = Provenance.load(root / ".sources.json")
    prov.put("codes/SYOG2026_ODF_Common_Codes_v_2_1.xlsx",
             SourceRecord(url=CODES.url, reference=None, published=None,
                          sha256="x", adopted=True))
    prov.save()

    stage(root, "codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx", b"v22")
    apply_targets(root, [CODES])

    assert superseded_stand_ins(root, [CODES]) == []


def test_a_hostile_manifest_key_with_a_benign_looking_target_is_still_refused(
        tmp_path):
    """MINOR 5 (final whole-branch review): the parametrized test above
    always sets key == target, so it cannot tell staged_entries()'s two
    _confined guards apart -- removing EITHER one alone still passes,
    because the other one, seeing the identical hostile string, refuses the
    record too. This uses an ARCHIVE record (key and target are genuinely
    different fields for one) where the KEY is hostile but the TARGET field
    is a completely ordinary-looking 'codes/' -- so only the key guard
    (`_confined(ruleset_dir, key)`) can catch it; the target guard would
    wave this record straight through.
    """
    victim_dir = tmp_path / "outside"
    victim_dir.mkdir()
    victim = victim_dir / "victim.xlsx"
    victim.write_bytes(b"ORIGINAL")

    root = tmp_path / "SYOG26"
    incoming = root / ".incoming"
    incoming.mkdir(parents=True)

    hostile_key = os.path.relpath(victim, start=incoming)
    assert (incoming / hostile_key).resolve() == victim.resolve()

    (incoming / "manifest.json").write_text(json.dumps({"entries": {
        hostile_key: {
            "url": CODES.url, "reference": "YOG-2026-2.2", "published": None,
            "kind": "codes", "target": "codes/", "discipline": None,
            "title": "Common Codes"},
    }}), encoding="utf-8")

    assert staged_entries(root) == [], (
        "a hostile KEY must be refused even though the record's own "
        "'target' field looks completely ordinary")
    assert apply_targets(root, staged_entries(root)) == []
    assert victim.read_bytes() == b"ORIGINAL"


def test_a_benign_manifest_key_with_a_hostile_target_is_still_refused(tmp_path):
    """Companion to the case above, pinning the OTHER guard: the KEY is
    ordinary (a real file legitimately staged under .incoming/codes/), but
    the record's 'target' FIELD is the hostile string. Only
    `_confined(ruleset_dir, record.target)` can catch this one; the key
    guard sees nothing wrong."""
    root = tmp_path / "SYOG26"
    incoming = root / ".incoming"
    (incoming / "codes").mkdir(parents=True)
    (incoming / "codes" / "legit.xlsx").write_bytes(b"LEGIT")

    hostile_target = "../../../../outside/evil/"

    (incoming / "manifest.json").write_text(json.dumps({"entries": {
        "codes/legit.xlsx": {
            "url": CODES.url, "reference": "YOG-2026-2.2", "published": None,
            "kind": "codes", "target": hostile_target, "discipline": None,
            "title": "Common Codes"},
    }}), encoding="utf-8")

    assert staged_entries(root) == [], (
        "a hostile 'target' field must be refused even though the "
        "manifest KEY it is filed under looks completely ordinary")
    assert apply_targets(root, staged_entries(root)) == []


def test_a_confined_manifest_key_still_applies(tmp_path):
    """The guard above must not refuse ordinary staged files -- including an
    archive entry, whose target ends in '/' and so resolves to a directory
    rather than a file."""
    root = tmp_path / "SYOG26"
    (root / ".incoming" / "codes").mkdir(parents=True)
    (root / ".incoming" / "codes" / "legit.xlsx").write_bytes(b"LEGIT")
    (root / ".incoming" / "manifest.json").write_text(json.dumps({"entries": {
        "codes/legit.xlsx": {
            "url": CODES.url, "reference": "YOG-2026-2.2",
            "published": None, "kind": "codes", "target": "codes/",
            "discipline": None, "title": "Common Codes"},
    }}), encoding="utf-8")

    assert apply_targets(root, staged_entries(root)) == ["codes/legit.xlsx"]
    assert (root / "codes" / "legit.xlsx").read_bytes() == b"LEGIT"


def test_an_untracked_leftover_in_an_archive_directory_is_never_promoted(tmp_path):
    """CRITICAL 1 (final whole-branch review): _staged_for's archive branch
    used to iterdir() the whole .incoming/<dir>/ directory, ignoring the
    manifest entirely -- so a leftover file dropped there by an older build
    (exactly the case orphaned_staged_files() exists for) got promoted
    alongside the real, manifest-tracked member, with a FABRICATED
    provenance record (the archive entry's own reference/published/url)
    describing a document it is not.
    """
    root = tmp_path / "SYOG26"
    root.mkdir()
    body = zip_bytes(["SYOG2026_ODF_Common_Codes_v_2_2.xlsx"])
    with client_serving({".zip": (body, "application/zip")}) as c:
        fetch_targets(root, [CODES], client=c)

    # An untracked leftover: dropped directly into .incoming/codes/ with no
    # manifest record at all -- an older build, or a lost/corrupted manifest.
    leftover = root / ".incoming" / "codes" / "ZZZ_leftover_from_an_old_build.xlsx"
    leftover.write_bytes(b"not part of this release")

    entries = staged_entries(root)
    applied = apply_targets(root, entries)

    assert applied == ["codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx"], (
        "only the manifest-tracked member must be promoted")
    assert not (root / "codes" / "ZZZ_leftover_from_an_old_build.xlsx").exists(), (
        "an untracked leftover must never be promoted with fabricated provenance")
    assert leftover.exists(), (
        "the untracked leftover must be left exactly where it was, not "
        "promoted and not deleted")
    assert "codes/ZZZ_leftover_from_an_old_build.xlsx" in orphaned_staged_files(root), (
        "an unpromoted leftover must be surfaced, not silently stranded")


def test_a_hand_converted_stand_in_is_not_deleted_when_a_pdf_lands(tmp_path):
    """IMPORTANT 3 (final whole-branch review): Rules/SYOG26/ holds
    hand-converted .md files standing in for entries the site publishes as
    .pdf -- a case _local_file_for explicitly documents as supported (a
    hand-converted ODF_GEN_R-OWG2026-GEN.md satisfies the .pdf entry).
    Before this fix, _retire_superseded treated that .md exactly like the
    Common Codes v2.1->v2.2 case and unlinked it the moment the real .pdf
    was promoted -- destroying hand-prepared content with no warning, and
    replacing it with a .pdf this repo cannot always convert (pdf_inspector
    is an optional dependency, absent in some environments). A stand-in
    must be kept, not retired, whenever its suffix differs from the file
    actually being applied.
    """
    root = tmp_path / "SYOG26"
    (root / "Disciplines" / "GEN").mkdir(parents=True)
    GEN = CatalogueEntry(
        reference="OWG-2026-GEN", title="ODF General Messages",
        published=None, kind="dd",
        url="https://odf.olympictech.org/2026-MiCo/general/PDF/"
            "ODF_GEN_R-OWG2026-GEN.pdf",
        target="Disciplines/GEN/ODF_GEN_R-OWG2026-GEN.pdf", discipline="GEN")

    stand_in = root / "Disciplines" / "GEN" / "ODF_GEN_R-OWG2026-GEN.md"
    stand_in.write_bytes(b"# hand-converted, carefully proofread")

    prov = Provenance.load(root / ".sources.json")
    prov.put("Disciplines/GEN/ODF_GEN_R-OWG2026-GEN.md",
             SourceRecord(url=GEN.url, reference=None, published=None,
                          sha256="x", adopted=True))
    prov.save()

    stage(root, GEN.target, b"%PDF-real")
    applied = apply_targets(root, [GEN])

    assert applied == [GEN.target], "the real .pdf must still be promoted"
    assert (root / GEN.target).read_bytes() == b"%PDF-real"
    assert stand_in.exists(), (
        "a hand-converted stand-in with a different suffix must never be "
        "silently deleted -- the operator removes it once satisfied")


def test_the_superseded_codes_file_is_still_retired_despite_the_suffix_guard(tmp_path):
    """Companion/contrast case: the suffix guard above must NOT break the
    case retirement exists for. Both the old and new Common Codes files are
    .xlsx, so the old one must still be deleted -- keeping it beside the new
    one means the loader ingests two conflicting code tables."""
    root = tmp_path / "SYOG26"
    (root / "codes").mkdir(parents=True)
    old = root / "codes" / "SYOG2026_ODF_Common_Codes_v_2_1.xlsx"
    old.write_bytes(b"v21")

    prov = Provenance.load(root / ".sources.json")
    prov.put("codes/SYOG2026_ODF_Common_Codes_v_2_1.xlsx",
             SourceRecord(url=CODES.url, reference=None, published=None,
                          sha256="x", adopted=True))
    prov.save()

    stage(root, "codes/SYOG2026_ODF_Common_Codes_v_2_2.xlsx", b"v22")
    apply_targets(root, [CODES])

    assert not old.exists(), (
        "same-suffix retirement must still happen or the loader ingests "
        "both code tables")
