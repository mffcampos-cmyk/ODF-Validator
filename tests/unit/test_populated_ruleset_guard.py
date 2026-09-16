"""`needs_populated_ruleset` must skip on a fresh public clone.

The published tree ships the authored rules and, since the schema-ship
commit, the SYOG26 XSDs -- but never the Common Codes workbook or the Data
Dictionaries, which are IOC documents fetched on first launch. A guard that
keys on the XSDs therefore stopped skipping the moment the schema shipped,
and 50 pack-dependent tests ran red on the public tree. The guard has to key
on the documents the tree does not carry.
"""
from pathlib import Path

from tests.conftest import ruleset_is_populated


def _tree(root: Path, *, xsd=False, codes=False, dd=False) -> Path:
    pack = root / "Rules" / "SYOG26"
    (pack / "xsd").mkdir(parents=True)
    (pack / "codes").mkdir()
    (pack / "Disciplines" / "SWM").mkdir(parents=True)
    if xsd:
        (pack / "xsd" / "odf2.xsd").write_text("<xs:schema/>")
    if codes:
        (pack / "codes" / "SYOG2026_ODF_Common_Codes_v_2_3.xlsx").write_bytes(b"PK")
    if dd:
        (pack / "Disciplines" / "SWM" / "ODF_SWM_Data_Dictionary.pdf").write_bytes(b"%PDF")
    return root


def test_a_public_clone_with_only_the_schema_is_not_populated(tmp_path):
    assert ruleset_is_populated(_tree(tmp_path, xsd=True)) is False


def test_codes_and_a_data_dictionary_make_it_populated(tmp_path):
    assert ruleset_is_populated(_tree(tmp_path, xsd=True, codes=True, dd=True)) is True


def test_codes_without_any_data_dictionary_is_not_populated(tmp_path):
    assert ruleset_is_populated(_tree(tmp_path, xsd=True, codes=True)) is False


def test_a_missing_pack_is_not_populated(tmp_path):
    assert ruleset_is_populated(tmp_path) is False


def test_the_private_working_tree_is_populated():
    """Sanity check on the real tree this suite runs in: if this fails on a
    developer checkout, every pack-dependent test is silently skipping."""
    root = Path(__file__).resolve().parent.parent.parent
    expected = any((root / "Rules" / "SYOG26" / "codes").glob("*.xlsx"))
    assert ruleset_is_populated(root) is expected
