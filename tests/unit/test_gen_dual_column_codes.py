"""Regression tests from a codes review: several Common Codes
tables carry TWO code-shaped columns -- a short business code plus a 34-char
RSC -- and codes/excel.py._pick_id_index always keys the table by whichever
column is literally named 'Code' (the RSC), because 'Code' appears before
'Id'/the short-code column in the sheet's own column order. Attributes the DD
documents against the SHORT column (GEN DD: '@Category' is char(3);
'@Phase'/'@EventUnit' reference the 'Phase'/'Eventunit' columns explicitly)
were being checked against the RSC key instead, so:

  * GEN_CATEGORY_CODE / GEN_PHASE_CODE / GEN_EVENTUNIT_CODE could never match
    a conforming value (100% false positive on every DT_NEWS/DT_BCK message
    carrying @Category, and on any @Phase/@EventUnit).
  * GEN_CATEGORYNAME_CODE's code_attr lookup (Category -> DISCIPLINE row ->
    ENG_Description) always missed too, so the primitive's "no paired code"
    guard never tripped and the rule silently never fired at all -- a false
    negative dressed as a passing check.

Fixed by adding a `column:` param to code_membership (mirrors the DD's own
'CC@TABLE Column' notation) and pointing the four rules at it in
Rules/SYOG26/rules/ODF_GEN_R-OWG2026-GEN.md.yaml. See also
tests/unit/test_primitives.py for the primitive-level column: tests and
tests/unit/test_ingestion_builder.py for the general pack-load-error pattern
this file's unknown-column test follows.
"""
from pathlib import Path
import shutil

import pytest

from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.pipeline.orchestrator import Pipeline
from tests.conftest import needs_populated_ruleset

pytestmark = needs_populated_ruleset


@pytest.fixture(scope="module")
def pack():
    """The real pack, built on first use rather than at import, so that
    collecting this module cannot fail when the schema and the codes
    workbook are absent."""
    return build_ruleset_pack(Path("Rules/SYOG26"))


def _codes_xlsx() -> Path:
    """The pack's Common Codes workbook, whatever version is installed.

    Pinning the filename broke every test here when the pack moved from
    v1.9.1 to v2.1 (2026-09-01). The version is the pack's business, not the
    test's.
    """
    found = sorted(Path("Rules/SYOG26/codes").glob("*.xlsx"))
    assert len(found) == 1, f"expected exactly one codes workbook, found {found}"
    return found[0]


def rsc(disc):
    return disc + "-" * (34 - len(disc))


def run(pack, xml):
    return Pipeline().run(xml.encode("utf-8"), pack)


def ids(result):
    return {f.rule_id for f in result.findings}


def envelope(disc, body):
    return (
        '<OdfBody DocumentType="DT_NEWS" DocumentCode="{disc_rsc}" '
        'CompetitionCode="SYOG2026" Version="1">'
        '<Competition Gen="SYOG2026-1.0" Sport="SYOG2026-1.0" '
        'Codes="SYOG2026-1.9.1"><Discipline Code="{disc_rsc}"/>'
        '{body}'
        '</Competition></OdfBody>'
    ).format(disc_rsc=rsc(disc), body=body)


# Real values from Rules/SYOG26/codes/SYOG2026_ODF_Common_Codes_v_1_9_1.xlsx,
# not invented (confirmed via odf_validator.codes.excel.load_excel_codes):
#   DISCIPLINE: row keyed 'ATH-------------------------------' has
#     fields Id='ATH', ENG_Description='Athletics'.
#   PHASE: row keyed 'ARCGGEN---------------DRAW--------' has fields
#     Phase='DRAW'.
#   EVENT_UNIT: the SAME row key has fields Eventunit='--------'.
GOOD_CATEGORY = "ATH"
GOOD_CATEGORY_NAME = "Athletics"
GOOD_PHASE = "DRAW"
GOOD_EVENT_UNIT = "--------"
BOGUS = "NOT_A_REAL_CODE"


def test_gen_category_code_accepts_real_discipline_id(pack):
    res = run(pack, envelope("ATH", f'<Result Category="{GOOD_CATEGORY}"/>'))
    assert "GEN_CATEGORY_CODE" not in ids(res), [
        f.message for f in res.findings if f.rule_id == "GEN_CATEGORY_CODE"]


def test_gen_category_code_still_flags_bogus_category(pack):
    res = run(pack, envelope("ATH", f'<Result Category="{BOGUS}"/>'))
    hits = [f for f in res.findings if f.rule_id == "GEN_CATEGORY_CODE"]
    assert len(hits) == 1


def test_gen_phase_code_accepts_real_phase_value(pack):
    res = run(pack, envelope("ARC", f'<Result Phase="{GOOD_PHASE}"/>'))
    assert "GEN_PHASE_CODE" not in ids(res), [
        f.message for f in res.findings if f.rule_id == "GEN_PHASE_CODE"]


def test_gen_phase_code_still_flags_bogus_phase(pack):
    res = run(pack, envelope("ARC", f'<Result Phase="{BOGUS}"/>'))
    hits = [f for f in res.findings if f.rule_id == "GEN_PHASE_CODE"]
    assert len(hits) == 1


def test_gen_eventunit_code_accepts_real_eventunit_value(pack):
    res = run(pack, envelope("ARC", f'<Result EventUnit="{GOOD_EVENT_UNIT}"/>'))
    assert "GEN_EVENTUNIT_CODE" not in ids(res), [
        f.message for f in res.findings if f.rule_id == "GEN_EVENTUNIT_CODE"]


def test_gen_eventunit_code_still_flags_bogus_eventunit(pack):
    res = run(pack, envelope("ARC", f'<Result EventUnit="{BOGUS}"/>'))
    hits = [f for f in res.findings if f.rule_id == "GEN_EVENTUNIT_CODE"]
    assert len(hits) == 1


def test_gen_categoryname_code_now_fires_on_wrong_name(pack):
    # Pre-fix: this rule was silently inert (code_attr lookup always missed),
    # so a mismatched CategoryName never got flagged at all. Proves it is no
    # longer inert -- a real false negative closed, not just quieted noise.
    res = run(pack, envelope(
        "ATH", f'<Result Category="{GOOD_CATEGORY}" CategoryName="Wrong Name"/>'))
    hits = [f for f in res.findings if f.rule_id == "GEN_CATEGORYNAME_CODE"]
    assert len(hits) == 1 and GOOD_CATEGORY_NAME in hits[0].message


def test_gen_categoryname_code_accepts_correct_name(pack):
    res = run(pack, envelope(
        "ATH",
        f'<Result Category="{GOOD_CATEGORY}" CategoryName="{GOOD_CATEGORY_NAME}"/>'))
    assert "GEN_CATEGORYNAME_CODE" not in ids(res), [
        f.message for f in res.findings if f.rule_id == "GEN_CATEGORYNAME_CODE"]


def _make_ruleset_with_bad_column(tmp_path: Path) -> Path:
    """Minimal pack reusing the REAL Common Codes workbook (so 'DISCIPLINE'
    and its real 'Id' column exist) plus one hand-written rule that names a
    column the table does not have. Follows the pattern in
    tests/unit/test_ingestion_builder.py's _make_ruleset."""
    real_codes = _codes_xlsx()
    root = tmp_path / "BADCOL"
    codes_dir = root / "codes"
    codes_dir.mkdir(parents=True)
    shutil.copy(real_codes, codes_dir / real_codes.name)
    (root / "rules").mkdir()
    (root / "rules" / "bad_column.yaml").write_text(
        "- id: TEST_BAD_COLUMN\n"
        "  applies_to: {}\n"
        "  primitive: code_membership\n"
        "  target: './/*[@Category]'\n"
        "  attribute: Category\n"
        "  params: {codeset: DISCIPLINE, column: NoSuchColumn}\n"
        "  severity: warning\n"
        "  scope: message\n"
        "  source_ref: 'test fixture'\n"
    )
    return root


def test_unknown_column_is_a_pack_load_error_not_silent(tmp_path):
    root = _make_ruleset_with_bad_column(tmp_path)
    pack = build_ruleset_pack(root)
    assert any(
        "TEST_BAD_COLUMN" in e and "NoSuchColumn" in e and "DISCIPLINE" in e
        for e in pack.report.errors
    ), pack.report.errors
    # The rule still loads (so it's visible in the pack), it just can never
    # fire and the loader says so -- same contract as an unknown codeset.
    assert "TEST_BAD_COLUMN" in {r.id for r in pack.rules}


def test_column_less_rule_is_unaffected(pack):
    # Regression guard: a rule that never sets `column` must behave exactly
    # as it did before this feature existed. GEN_ITEM_CODE (codeset
    # NEWS_TYPE, no column) is one of the untouched rules in the real pack.
    res = run(pack, envelope("ARC", '<Result Item="NOT_A_REAL_NEWS_ITEM"/>'))
    hits = [f for f in res.findings if f.rule_id == "GEN_ITEM_CODE"]
    assert len(hits) == 1
