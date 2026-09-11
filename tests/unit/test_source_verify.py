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
