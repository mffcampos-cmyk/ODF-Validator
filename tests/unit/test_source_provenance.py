from __future__ import annotations
from datetime import date
import json

from odf_validator.sources.provenance import (Provenance, SourceRecord,
                                              hash_bytes)


def _record(**over):
    base = dict(url="https://odf.olympictech.org/a.pdf", reference="YOG-2026-SWM",
                published=date(2026, 5, 19), sha256="abc", etag='"e1"',
                last_modified=None, fetched_at="2026-09-02T10:00:00Z",
                adopted=False)
    base.update(over)
    return SourceRecord(**base)


def test_missing_file_loads_empty(tmp_path):
    prov = Provenance.load(tmp_path / ".sources.json")
    assert prov.records == {}
    assert prov.last_checked is None


def test_roundtrip_preserves_every_field(tmp_path):
    path = tmp_path / ".sources.json"
    prov = Provenance.load(path)
    prov.put("Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf", _record())
    prov.last_checked = "2026-09-02T10:05:00Z"
    prov.save()

    again = Provenance.load(path)
    rec = again.get("Disciplines/SWM/ODF_SWM_Data_Dictionary.pdf")
    assert rec == _record()
    assert again.last_checked == "2026-09-02T10:05:00Z"


def test_adopted_record_roundtrips_with_null_reference_and_date(tmp_path):
    path = tmp_path / ".sources.json"
    prov = Provenance.load(path)
    prov.put("codes/x.xlsx", _record(reference=None, published=None,
                                     etag=None, fetched_at=None, adopted=True))
    prov.save()

    rec = Provenance.load(path).get("codes/x.xlsx")
    assert rec.adopted is True
    assert rec.reference is None
    assert rec.published is None


def test_corrupt_file_degrades_to_empty(tmp_path):
    path = tmp_path / ".sources.json"
    path.write_text("{not json at all", encoding="utf-8")
    prov = Provenance.load(path)
    assert prov.records == {}


def test_malformed_published_date_is_skipped_not_raised(tmp_path):
    path = tmp_path / ".sources.json"
    path.write_text(json.dumps({
        "last_checked": "2026-09-02T10:05:00Z",
        "entries": {
            "bad.pdf": {"url": "https://odf.olympictech.org/bad.pdf",
                        "reference": "YOG-2026-SWM",
                        "published": "not-a-date",
                        "sha256": "abc", "etag": None,
                        "last_modified": None, "fetched_at": None,
                        "adopted": False},
        },
    }), encoding="utf-8")

    prov = Provenance.load(path)
    assert prov.get("bad.pdf") is None
    assert prov.records == {}


def test_good_entry_survives_a_bad_sibling(tmp_path):
    path = tmp_path / ".sources.json"
    good = _record().to_json()
    path.write_text(json.dumps({
        "last_checked": "2026-09-02T10:05:00Z",
        "entries": {
            "good.pdf": good,
            "bad.pdf": {"url": "https://odf.olympictech.org/bad.pdf",
                        "reference": "YOG-2026-SWM",
                        "published": "not-a-date",
                        "sha256": "abc", "etag": None,
                        "last_modified": None, "fetched_at": None,
                        "adopted": False},
        },
    }), encoding="utf-8")

    prov = Provenance.load(path)
    assert prov.get("bad.pdf") is None
    assert prov.get("good.pdf") == _record()


def test_drop_removes_a_record(tmp_path):
    prov = Provenance.load(tmp_path / ".sources.json")
    prov.put("codes/old.xlsx", _record())
    prov.drop("codes/old.xlsx")
    assert prov.get("codes/old.xlsx") is None


def test_saved_json_is_stable_and_readable(tmp_path):
    path = tmp_path / ".sources.json"
    prov = Provenance.load(path)
    prov.put("b.pdf", _record())
    prov.put("a.pdf", _record())
    prov.save()
    text = path.read_text(encoding="utf-8")
    assert text.index('"a.pdf"') < text.index('"b.pdf"')   # sort_keys
    assert "\n" in text                                     # indent=2


def test_hash_bytes_is_sha256():
    assert hash_bytes(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
