"""A DD obligation stated under one @Code must not be enforced on every node.

Extension-style elements do not have one attribute table; they have one per
@Code. The WST DD says @Value2 is mandatory on an <ExtendedResult> whose @Code
is B_JUDGE -- and says nothing about it for @Code A, B or DEDUCTION. Read flat,
that becomes "every ExtendedResult needs @Value2", which produced 567 of the
778 findings in the real 82-file WST run of 2026-08-31: 73% of the report, all
false. The shape occurs 256 times across the 24 discipline DDs.
"""
from pathlib import Path

import pytest
from lxml import etree

from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.ingestion.dd_obligations import parse_obligations, split_condition
from odf_validator.ingestion.obligation_store import PARSER_VERSION, ObligationStore
from odf_validator.pipeline.orchestrator import Pipeline
from tests.conftest import needs_populated_ruleset

PACK_DIR = Path(__file__).resolve().parents[2] / "Rules" / "SYOG26"
WST_RSC = "WST-------------------------------"

# The WST DD verbatim, including the page-break header that separates the
# B_JUDGE code row from the attribute table it governs.
WST_EXTRESULT_DD = """
|DocumentType|DT_RESULT|Event Unit Start List and Results message|

|||Element: Competition /Result /ExtendedResults /ExtendedResult (1,N)|||
|---|---|---|---|---|
||Type|Code|Pos|Description|
|ER||A B DEDUCTION|N/A|Element Expected: Always, if the information is available|
||Attribute|M/O|Value|Description|
||Value|M|Numeric #0.00#|Send judges value for category A, B, C, T, BONUS|
|ER||B_JUDGE|Numeric #0|Pos Description: send judges position|

#### SYOG-2026-WST-1.0 SFR

|Attribute|M/O|Value|Description|
|---|---|---|---|
|Value|M|Numeric #0.00|Send judges score for @Pos|
|Value2|M|Numeric #0|0 (no) and 1(yes), if the score of the judge is counting|

|Element: Competition /Result /Competitor (1,1)||||
|---|---|---|---|
|Attribute|M/O|Value|Description|
|Code|M|S(20)|Competitor's ID|
"""


def test_attribute_under_a_code_block_is_recorded_as_conditional():
    ob = parse_obligations(WST_EXTRESULT_DD)

    assert ob[("DT_RESULT", "ExtendedResult", "Value2")] == "M@B_JUDGE"
    mo, codes = split_condition(ob[("DT_RESULT", "ExtendedResult", "Value2")])
    assert (mo, codes) == ("M", frozenset({"B_JUDGE"}))


def test_attributes_outside_a_code_block_stay_unconditional():
    """The next Element: heading ends the code context."""
    ob = parse_obligations(WST_EXTRESULT_DD)

    assert ob[("DT_RESULT", "Competitor", "Code")] == "M"
    assert split_condition("M") == ("M", frozenset())


def test_the_real_wst_dd_qualifies_value2_by_b_judge():
    dd = PACK_DIR / "Disciplines" / "WST" / "ODF_WST_Data_Dictionary.pdf"
    md_dd = PACK_DIR / "Disciplines" / "WST" / "ODF_WST_Data_Dictionary.md"
    source = dd if dd.exists() else md_dd
    if not source.exists():
        pytest.skip("WST Data Dictionary not present")
    from odf_validator.ingestion.convert import dd_to_markdown
    try:
        markdown, backend = dd_to_markdown(source)
    except Exception as exc:                                  # pragma: no cover
        pytest.skip(f"WST DD not convertible here: {exc}")
    if backend == "markitdown":
        # Not a pass and not a failure: the fallback converter's Markdown
        # shape is not what parse_obligations' line regexes match, so it
        # yields no obligations at all from this DD. Asserting on it would
        # pin the fallback's output as if it were the real thing. This is
        # precisely why dd_to_markdown reports its backend.
        pytest.skip("WST DD converted by the markitdown fallback, whose "
                    "Markdown shape the obligation regexes are not tuned to")

    ob = parse_obligations(markdown)

    assert ob.get(("DT_RESULT", "ExtendedResult", "Value2")) == "M@B_JUDGE"


class _Store(ObligationStore):
    pass


def test_a_stale_parser_version_is_a_cache_miss(tmp_path):
    """Entries are keyed on the DD's content hash, which does not change when
    the parser does. Without a version check a parser fix silently no-ops
    against a committed cache -- which is what happened on 2026-08-31."""
    store = ObligationStore(tmp_path / "c.json")
    store.put("Disciplines/WST/dd.pdf", "hash1",
              {("DT_RESULT", "ExtendedResult", "Value2"): "M@B_JUDGE"})

    assert store.get("Disciplines/WST/dd.pdf", "hash1") is not None

    raw = store._data["Disciplines/WST/dd.pdf"]
    assert raw["parser"] == PARSER_VERSION
    raw["parser"] = PARSER_VERSION - 1
    assert store.get("Disciplines/WST/dd.pdf", "hash1") is None


def test_an_entry_without_a_parser_key_is_treated_as_version_1(tmp_path):
    store = ObligationStore(tmp_path / "c.json", {
        "Disciplines/WST/dd.pdf": {"hash": "h", "obligations": []}})

    assert store.get("Disciplines/WST/dd.pdf", "h") is None


# --------------------------------------------------------------- end to end --

def _message(extended_result: str) -> bytes:
    return (
        '<OdfBody CompetitionCode="SYOG2026" DocumentCode="WST" '
        'DocumentType="DT_RESULT" Version="1" Date="d" Time="t" '
        'LogicalDate="d" FeedFlag="P" Source="S">'
        f'<Competition Gen="1" Codes="1"><Discipline Code="{WST_RSC}"/>'
        '<Result Rank="1" SortOrder="1" StartSortOrder="1">'
        f'<ExtendedResults>{extended_result}</ExtendedResults>'
        '</Result></Competition></OdfBody>').encode()


@pytest.fixture(scope="module")
def pack():
    return build_ruleset_pack(PACK_DIR)


def _dd_findings(pack, extended_result: str):
    result = Pipeline().run(_message(extended_result), pack)
    return [f for f in result.findings if f.rule_id == "CORE_DD_MANDATORY_ATTR"]


@pytest.mark.parametrize("code", ["A", "B", "DEDUCTION"])
def test_value2_not_demanded_for_codes_the_dd_does_not_name(pack, code):
    """The 567 false positives. Each of these was reported as an error."""
    findings = _dd_findings(
        pack, f'<ExtendedResult Type="ER" Code="{code}" Value="9.5"/>')

    assert [f.message for f in findings] == []


@needs_populated_ruleset
def test_value2_still_demanded_for_b_judge(pack):
    """The coverage the fix must NOT lose."""
    findings = _dd_findings(
        pack, '<ExtendedResult Type="ER" Code="B_JUDGE" Pos="1" Value="9.5"/>')

    assert len(findings) == 1
    assert "@Value2" in findings[0].message
    assert "B_JUDGE" in findings[0].message


def test_a_conforming_b_judge_node_is_clean(pack):
    findings = _dd_findings(
        pack,
        '<ExtendedResult Type="ER" Code="B_JUDGE" Pos="1" Value="9.5" Value2="1"/>')

    assert [f.message for f in findings] == []


def test_a_node_with_no_code_attribute_is_not_flagged(pack):
    """No @Code means no attribute table applies; say nothing."""
    findings = _dd_findings(pack, '<ExtendedResult Type="ER" Value="9.5"/>')

    assert [f.message for f in findings] == []


@needs_populated_ruleset
def test_unconditional_obligations_are_unaffected(pack):
    """A DD row stated outside any @Code block must still enforce everywhere.

    Guards the fix against over-reaching: it would be easy to make every
    obligation conditional and quietly disable the whole check.
    """
    unconditional = pack.obligations.mandatory_attrs(
        "WST", "DT_RESULT", enforceable_only=True)
    conditional = pack.obligations.conditional_mandatory_attrs(
        "WST", "DT_RESULT", enforceable_only=True)

    assert unconditional, "no unconditional obligations survived the change"
    assert ("ExtendedResult", "Value2") in conditional
    assert ("ExtendedResult", "Value2") not in unconditional
    assert not (set(conditional) & unconditional), "a pair cannot be both"
