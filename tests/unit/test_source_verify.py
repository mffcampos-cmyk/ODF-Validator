from __future__ import annotations
from pathlib import Path

import httpx

from odf_validator.sources.catalogue import CatalogueEntry
from odf_validator.sources.provenance import (Provenance, SourceRecord,
                                              hash_bytes)
from odf_validator.sources.sync import _status_for, verify_targets

URL = ("https://odf.olympictech.org/2026-Dakar/YOG/"
       "ODF_SWM_Data_Dictionary.pdf")
DD = CatalogueEntry(reference="YOG-2026-SWM", title="ODF Swimming Data Dictionary",
                    published=None, kind="dd", url=URL,
                    target="Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf",
                    discipline="SWM")


def client_returning(body: bytes):
    def handler(request):
        return httpx.Response(200, content=body,
                              headers={"content-type": "application/pdf",
                                       "etag": '"e9"'})
    return httpx.Client(transport=httpx.MockTransport(handler))


def adopted_ruleset(tmp_path, body: bytes) -> Path:
    root = tmp_path / "SYOG26"
    (root / "Disciplines" / "SWM").mkdir(parents=True)
    (root / DD.target).write_bytes(body)
    prov = Provenance.load(root / ".sources.json")
    prov.put(DD.target, SourceRecord(url=URL, reference=None, published=None,
                                     sha256=hash_bytes(body), adopted=True))
    prov.save()
    return root


def test_matching_bytes_promote_an_adopted_entry_to_current(tmp_path):
    root = adopted_ruleset(tmp_path, b"%PDF-same")

    with client_returning(b"%PDF-same") as c:
        states = verify_targets(root, [DD], client=c)

    assert states == {DD.target: "current"}
    record = Provenance.load(root / ".sources.json").get(DD.target)
    assert record.adopted is False
    assert record.stale is False
    assert record.reference == "YOG-2026-SWM"
    assert record.etag == '"e9"'
    assert _status_for(root, DD, Provenance.load(root / ".sources.json")).state == "current"


def test_differing_bytes_mark_it_stale_even_when_the_reference_is_unchanged(tmp_path):
    """Every Swimming DD is YOG-2026-SWM whatever its date. If verification
    stamped the catalogue reference on a mismatch, the entry would read
    'current' forever and the stale local copy would stay invisible."""
    root = adopted_ruleset(tmp_path, b"%PDF-old")

    with client_returning(b"%PDF-new") as c:
        states = verify_targets(root, [DD], client=c)

    assert states == {DD.target: "update"}
    record = Provenance.load(root / ".sources.json").get(DD.target)
    assert record.stale is True
    # The assertion this test is named for. Without it the test passes even
    # if the mismatch branch stamps entry.reference, because _status_for
    # checks `stale` before it looks at the reference -- so the bug would be
    # masked here and only surface once someone reordered those checks.
    assert record.reference is None
    assert record.published is None
    assert _status_for(root, DD, Provenance.load(root / ".sources.json")).state == "update"


def test_an_empty_200_body_leaves_the_entry_unverified(tmp_path):
    """A 200 carrying no body is a transport failure, not evidence that the
    local copy is out of date. Hashing b"" would never match what we
    recorded, so a falsy-body check that only tested `is None` reported a
    truncated response as 'stale' -- telling the operator their file was
    superseded when nothing of the sort had happened."""
    root = adopted_ruleset(tmp_path, b"%PDF-old")

    def handler(request):
        return httpx.Response(200, content=b"",
                              headers={"content-type": "application/pdf"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert verify_targets(root, [DD], client=c) == {}

    record = Provenance.load(root / ".sources.json").get(DD.target)
    assert record.adopted is True
    assert record.stale is False
    assert _status_for(root, DD,
                       Provenance.load(root / ".sources.json")).state == "unverified"


def test_verification_does_not_overwrite_the_local_file(tmp_path):
    root = adopted_ruleset(tmp_path, b"%PDF-old")
    with client_returning(b"%PDF-new") as c:
        verify_targets(root, [DD], client=c)
    assert (root / DD.target).read_bytes() == b"%PDF-old"


def test_an_entry_with_no_record_is_skipped(tmp_path):
    root = tmp_path / "SYOG26"
    root.mkdir()
    with client_returning(b"%PDF-new") as c:
        assert verify_targets(root, [DD], client=c) == {}


def test_a_network_failure_leaves_the_entry_unverified(tmp_path):
    root = adopted_ruleset(tmp_path, b"%PDF-old")

    def handler(request):
        raise httpx.ConnectError("offline")

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert verify_targets(root, [DD], client=c) == {}

    record = Provenance.load(root / ".sources.json").get(DD.target)
    assert record.adopted is True


# --- archive entries --------------------------------------------------------
#
# Reproduced from the live Rules/SYOG26/.sources.json on 2026-09-13:
#
#   "xsd/odf2-structure.xsd": {"adopted": false, "reference": null,
#                              "published": null, "stale": true,
#                              "sha256": "d2b0702e...",
#                              "url": ".../odf-schema.zip"}
#
# stale, forever, with no reference. The record was adopted against ONE
# EXTRACTED MEMBER's bytes, and verify_targets then compared it against the
# bytes of the ARCHIVE. Those two can never be equal, so the entry was
# condemned on its first verification and has read "update" on every startup
# since -- urging a download that (until the nested-member fix) extracted
# nothing at all. The four .md stand-in records in that same file are stale
# for the mirror-image reason: an .md we made by hand is not the .pdf the
# entry names.

import io
import zipfile

from odf_validator.sources.sync import fetch_targets  # noqa: E402  (grouped here)

SCHEMA_URL = "https://odf.olympictech.org/2026-MiCo/schema/odf-schema.zip"
SCHEMA = CatalogueEntry(reference="OWG-2026", title="ODF Schema",
                        published=None, kind="schema", url=SCHEMA_URL,
                        target="xsd/", discipline=None)


def schema_zip(body: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("odf2-schema-30112025-DRAFT/odf2.xsd", body)
    return buf.getvalue()


def client_returning_zip(archive: bytes):
    def handler(request):
        return httpx.Response(200, content=archive,
                              headers={"content-type": "application/zip",
                                       "etag": '"z1"'})
    return httpx.Client(transport=httpx.MockTransport(handler))


def adopted_archive_ruleset(tmp_path, member_body: bytes) -> Path:
    """A ruleset holding an extracted schema, recorded the way
    `_adopt_existing` records one: keyed by a member's path, hashed over
    that member's bytes, no reference."""
    root = tmp_path / "SYOG26"
    (root / "xsd").mkdir(parents=True)
    (root / "xsd" / "odf2.xsd").write_bytes(member_body)
    prov = Provenance.load(root / ".sources.json")
    prov.put("xsd/odf2.xsd",
             SourceRecord(url=SCHEMA_URL, reference=None, published=None,
                          sha256=hash_bytes(member_body), adopted=True))
    prov.save()
    return root


def test_an_archive_entry_is_settled_from_the_card_without_a_download(tmp_path):
    """The bug: a member's hash compared against the archive's bytes.

    There is nothing here that byte comparison can settle. What sits on disk
    are the archive's extracted MEMBERS; what the url serves is the ARCHIVE.
    Hashing one against the other is guaranteed to differ, so the entry was
    condemned on its first verification and has read "update" on every
    startup since -- urging a download that (until the nested-member fix)
    extracted nothing at all.

    An archive's version identity lives on the index card, not in its bytes,
    so that is where it is settled from: we hold the version the card names.
    No download is made, because none would prove anything.
    """
    root = adopted_archive_ruleset(tmp_path, b"<xs:schema>locally corrected</xs:schema>")

    def refuse(request):
        raise AssertionError("an archive entry must not be downloaded to be "
                             "settled -- the bytes cannot answer the question")

    with httpx.Client(transport=httpx.MockTransport(refuse)) as c:
        states = verify_targets(root, [SCHEMA], client=c)

    assert states == {"xsd/": "current"}, states
    record = Provenance.load(root / ".sources.json").get("xsd/odf2.xsd")
    assert record.stale is False
    assert record.adopted is False
    assert record.reference == "OWG-2026"
    assert _status_for(root, SCHEMA,
                       Provenance.load(root / ".sources.json")).state == "current"


def test_a_locally_modified_member_does_not_make_the_archive_stale(tmp_path):
    """odf2.xsd and odf2-structure.xsd both carry deliberate local
    corrections -- the IOC's published schema references RecordBrokenType
    and never defines it, so theirs does not compile. Byte-equality with
    upstream can therefore never hold for our copy, and condemning the entry
    for it is a permanent false alarm, not a finding."""
    root = adopted_archive_ruleset(tmp_path, b"<xs:schema>locally corrected</xs:schema>")

    with client_returning_zip(schema_zip(b"<xs:schema>as published</xs:schema>")) as c:
        verify_targets(root, [SCHEMA], client=c)

    record = Provenance.load(root / ".sources.json").get("xsd/odf2.xsd")
    assert record.stale is False
    assert (root / "xsd" / "odf2.xsd").read_bytes() == \
        b"<xs:schema>locally corrected</xs:schema>", "verification never writes"


def test_a_republished_archive_reads_as_an_update(tmp_path):
    """The other half of what makes 'current' safe to record: once the card
    names a different version, the entry is an update -- to be downloaded
    and applied as-is, local corrections and all."""
    root = adopted_archive_ruleset(tmp_path, b"<xs:schema>v1</xs:schema>")
    with httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(404))) as c:
        verify_targets(root, [SCHEMA], client=c)

    republished = CatalogueEntry(reference="OWG-2030", title=SCHEMA.title,
                                 published=SCHEMA.published, kind="schema",
                                 url=SCHEMA_URL, target="xsd/", discipline=None)
    state = _status_for(root, republished,
                        Provenance.load(root / ".sources.json"))

    assert state.state == "update"
    assert state.local_reference == "OWG-2026"


def test_a_settled_archive_is_not_re_settled_on_every_check(tmp_path):
    """Once an archive entry carries the card's reference it is no longer
    adopted, so verify_targets has nothing left to do with it -- the same
    contract single documents have. Without this it would keep rewriting
    .sources.json on every startup."""
    root = adopted_archive_ruleset(tmp_path, b"<xs:schema>v1</xs:schema>")
    with httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(404))) as c:
        assert verify_targets(root, [SCHEMA], client=c) == {"xsd/": "current"}
        assert verify_targets(root, [SCHEMA], client=c) == {}


def test_an_archive_left_stale_by_the_old_comparison_is_not_an_update(tmp_path):
    """The live Rules/SYOG26/.sources.json is carrying this record today:

        "xsd/odf2-structure.xsd": {"adopted": false, "reference": null,
                                   "stale": true, ...}

    `stale` with no reference, written by the member-hash-against-archive-
    bytes comparison that verify_targets no longer makes. Nothing sets
    `stale` on an archive entry any more, so on an archive it can only be
    that bug's residue -- and left reading "update" it is worse than
    cosmetic now that the nested-member fix makes the download work: the
    next check would fetch the published schema and overwrite two
    deliberate local corrections with an IOC copy that does not compile.

    It is treated as what it is: never settled. The entry goes back through
    verification and comes out current.
    """
    root = adopted_archive_ruleset(tmp_path, b"<xs:schema>locally corrected</xs:schema>")
    prov = Provenance.load(root / ".sources.json")
    held = prov.get("xsd/odf2.xsd")
    prov.put("xsd/odf2.xsd", SourceRecord(
        url=held.url, reference=None, published=None, sha256=held.sha256,
        adopted=False, stale=True))
    prov.save()

    assert _status_for(root, SCHEMA,
                       Provenance.load(root / ".sources.json")).state == \
        "unverified"

    with httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(404))) as c:
        assert verify_targets(root, [SCHEMA], client=c) == {"xsd/": "current"}

    assert _status_for(root, SCHEMA,
                       Provenance.load(root / ".sources.json")).state == "current"


def test_a_stale_single_document_is_still_an_update(tmp_path):
    """The narrowness of the rule above. A DD marked stale by a real byte
    mismatch must keep reading as an update -- that is verify_targets' only
    way of saying "your copy is out of date" for a document whose reference
    never changes between revisions."""
    root = adopted_ruleset(tmp_path, b"%PDF-old")

    with client_returning(b"%PDF-new") as c:
        verify_targets(root, [DD], client=c)

    assert _status_for(root, DD,
                       Provenance.load(root / ".sources.json")).state == "update"
