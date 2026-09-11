from __future__ import annotations

from odf_validator.ingestion.scanner import scan_ruleset


def test_staged_downloads_are_invisible_to_the_scanner(tmp_path):
    """A half-downloaded document must never reach the validator."""
    root = tmp_path / "SYOG26"
    (root / ".incoming" / "Disciplines" / "SWM").mkdir(parents=True)
    (root / ".incoming" / "Disciplines" / "SWM"
     / "ODF_SWM_Data_Dictionary.pdf").write_bytes(b"partial")
    (root / ".incoming" / "codes").mkdir(parents=True)
    (root / ".incoming" / "codes" / "new.xlsx").write_bytes(b"partial")

    scan = scan_ruleset(root)
    assert scan.dd_files == []
    assert scan.code_files == []
    assert scan.unknown_files == []
