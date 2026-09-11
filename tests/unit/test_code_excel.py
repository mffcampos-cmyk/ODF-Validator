from pathlib import Path

import pytest

from odf_validator.codes.excel import load_excel_codes
from tests.conftest import needs_populated_ruleset

pytestmark = needs_populated_ruleset


def _codes_xlsx() -> Path:
    """The pack's Common Codes workbook, whatever version is installed.

    Pinning the filename broke every test here when the pack moved from
    v1.9.1 to v2.1 (2026-09-01). The version is the pack's business, not the
    test's.
    """
    found = sorted(Path("Rules/SYOG26/codes").glob("*.xlsx"))
    assert len(found) == 1, f"expected exactly one codes workbook, found {found}"
    return found[0]


@pytest.fixture(scope="module")
def xlsx() -> Path:
    """Located on first use rather than at import, so that collecting this
    module cannot fail when the workbook has not been downloaded yet."""
    return _codes_xlsx()


def test_loads_real_codesets(xlsx):
    tables = {t.name: t for t in load_excel_codes(xlsx)}
    assert "COUNTRY" in tables and "DISCIPLINE" in tables
    assert "DOCUMENT_CONTROL" not in tables  # control sheet skipped
    country = tables["COUNTRY"]
    assert country.lookup("AFG") is not None
    # header "ENG Description" -> normalized "ENG_Description"
    assert country.get("AFG", "ENG_Description") == "Afghanistan"


def test_sport_codes_expanded_by_entity_and_discipline(xlsx):
    tables = {t.name: t for t in load_excel_codes(xlsx)}
    arc_tt = tables.get("SC@TeamType@ARC")
    assert arc_tt is not None
    assert arc_tt.lookup("ORG") is not None      # ARC teams must be ORG
    assert arc_tt.lookup("CPLM") is None         # discipline-scoped: CPLM is not ARC


def test_record_type_keyed_by_recordtype_not_first_column(xlsx):
    # RECORD_TYPE sheet columns: Discipline | Recordtype | Recordgroup | ...
    # The @RecordType code lives in the *Recordtype* column, not column 0
    # (Discipline). Keying on column 0 made every valid code (e.g. 'WJ',
    # World Junior Record) look invalid -- the source of 44 false-positive
    # findings across GEN_RECORDTYPE_CODE / <DISC>_RECORDTYPE_CODE.
    tables = {t.name: t for t in load_excel_codes(xlsx)}
    rt = tables["RECORD_TYPE"]
    assert rt.lookup("WJ") is not None           # valid code must be found
    assert rt.lookup("SWM") is None              # Discipline value is not a code
    assert rt.get("WJ", "ENG_Description") == "World Junior Record"
