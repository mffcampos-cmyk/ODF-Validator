"""Rules derived from defects observed in production ODF message traffic.

Each rule below traces to a failure pattern seen repeatedly in feeds that had
already passed schema validation. Where that evidence contradicts the previous
rule set, the observed behaviour wins.

The patterns, stated as technical conditions:
- RankEqual absent on a tie, or present when there is no tie. It must be Y on
  a tie and otherwise omitted.
- SortOrder zero, duplicated within a result list, or not following Rank.
- DocumentCode carrying a 33-character RSC where the format requires 34.
- Empty container elements, e.g. a DT_RESULT_STARTLIST carrying an
  EXTENDEDRESULTS node with no children, which fails schema validation.
- Empty attributes treated as errors rather than advice on cumulative-result
  and participant-update messages.
"""
from pathlib import Path
from lxml import etree

from odf_validator.rules.primitives import PRIMITIVES
from odf_validator.rules.defs_model import RuleDef, AppliesTo
from odf_validator.rules.core import load_core_rules
from odf_validator.model import Severity, Scope
from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.pipeline.orchestrator import Pipeline

PACK = build_ruleset_pack(Path("Rules/SYOG26"))
RSC = "ARC" + "-" * 31  # valid 34-char RSC document code


def rule(primitive, target, attribute, params):
    return RuleDef("R", AppliesTo([], [], []), primitive, target, attribute,
                   params, Severity.ERROR, Scope.MESSAGE, "src")


def ids(result):
    return {f.rule_id for f in result.findings}


def run(xml):
    return Pipeline().run(xml.encode("utf-8"), PACK)


def result_msg(body):
    return (f'<OdfBody DocumentType="DT_RESULT" DocumentCode="{RSC}" '
            f'CompetitionCode="SYOG2026" Version="1">'
            f'<Competition><Discipline Code="ARC"/>{body}</Competition></OdfBody>')


# ---------------- primitive: sibling_duplicates ----------------

def test_sibling_duplicates_forbid_flags_both_nodes():
    root = etree.fromstring(
        '<OdfBody><Competition>'
        '<Result SortOrder="1"/><Result SortOrder="1"/><Result SortOrder="2"/>'
        '</Competition></OdfBody>')
    r = rule("sibling_duplicates", ".//*[@SortOrder]", "SortOrder",
             {"mode": "forbid"})
    out = PRIMITIVES["sibling_duplicates"](root, r, None, None)
    assert len(out) == 2


def test_sibling_duplicates_different_parents_not_grouped():
    root = etree.fromstring(
        '<OdfBody><Unit><Result SortOrder="1"/></Unit>'
        '<Unit><Result SortOrder="1"/></Unit></OdfBody>')
    r = rule("sibling_duplicates", ".//*[@SortOrder]", "SortOrder",
             {"mode": "forbid"})
    assert PRIMITIVES["sibling_duplicates"](root, r, None, None) == []


def test_sibling_duplicates_require_attr_on_ties():
    tied = etree.fromstring(
        '<OdfBody><Competition>'
        '<Result Rank="1"/><Result Rank="1"/><Result Rank="3"/>'
        '</Competition></OdfBody>')
    r = rule("sibling_duplicates", ".//*[@Rank]", "Rank",
             {"mode": "require_attr", "require_attr": "RankEqual",
              "require_value": "Y"})
    out = PRIMITIVES["sibling_duplicates"](tied, r, None, None)
    assert len(out) == 2  # both tied Results lack RankEqual="Y"
    ok = etree.fromstring(
        '<OdfBody><Competition>'
        '<Result Rank="1" RankEqual="Y"/><Result Rank="1" RankEqual="Y"/>'
        '</Competition></OdfBody>')
    assert PRIMITIVES["sibling_duplicates"](ok, r, None, None) == []


# ---------------- primitive: no_empty_elements ----------------

def test_no_empty_elements_flags_childless_attrless_container():
    root = etree.fromstring(
        '<OdfBody><Competition><Result Rank="1"><ExtendedResults/></Result>'
        '</Competition></OdfBody>')
    r = rule("no_empty_elements", ".//*", None, {})
    out = PRIMITIVES["no_empty_elements"](root, r, None, None)
    assert len(out) == 1 and "ExtendedResults" in out[0].message


def test_no_empty_elements_ignores_attrs_text_children():
    root = etree.fromstring(
        '<OdfBody><Competition><Discipline Code="ARC"/>'
        '<Note>text</Note><Wrap><Child A="1"/></Wrap></Competition></OdfBody>')
    r = rule("no_empty_elements", ".//*", None, {})
    assert PRIMITIVES["no_empty_elements"](root, r, None, None) == []


# ---------------- core rules wired into the pipeline ----------------

def test_new_core_rules_registered():
    got = {r.id for r in load_core_rules()}
    assert {"CORE_RANK_TIES_RANKEQUAL", "CORE_RANKEQUAL_VALUE",
            "CORE_SORTORDER_POSINT", "CORE_SORTORDER_UNIQUE",
            "CORE_DOCCODE_RSC_FORMAT", "CORE_NO_EMPTY_ELEMENTS"} <= got


def test_tied_ranks_without_rankequal_flagged():
    msg = result_msg('<Result Rank="1" SortOrder="1"/>'
                     '<Result Rank="1" SortOrder="2"/>')
    assert "CORE_RANK_TIES_RANKEQUAL" in ids(run(msg))


def test_tied_ranks_with_rankequal_ok():
    msg = result_msg('<Result Rank="1" RankEqual="Y" SortOrder="1"/>'
                     '<Result Rank="1" RankEqual="Y" SortOrder="2"/>')
    got = ids(run(msg))
    assert "CORE_RANK_TIES_RANKEQUAL" not in got


def test_rankequal_must_be_Y():
    # Observed defect: "RankEqual should be Y or not be present" (had a number)
    msg = result_msg('<Result Rank="1" RankEqual="2" SortOrder="1"/>')
    assert "CORE_RANKEQUAL_VALUE" in ids(run(msg))


def test_sortorder_zero_flagged():
    # Observed defect: DT_CURRENT Result SortOrder="0" for all competitors
    msg = result_msg('<Result Rank="1" SortOrder="0"/>')
    assert "CORE_SORTORDER_POSINT" in ids(run(msg))


def test_sortorder_duplicate_flagged():
    msg = result_msg('<Result Rank="1" SortOrder="3"/>'
                     '<Result Rank="2" SortOrder="3"/>')
    assert "CORE_SORTORDER_UNIQUE" in ids(run(msg))


def test_doccode_not_full_rsc_flagged():
    # Observed defect: 33 chars instead of 34 -> the official validator
    # rejected the message
    short = result_msg("").replace(f'DocumentCode="{RSC}"',
                                   'DocumentCode="ARC"')
    assert "CORE_DOCCODE_RSC_FORMAT" in ids(run(short))
    ok = result_msg('<Result Rank="1" SortOrder="1"/>')
    assert "CORE_DOCCODE_RSC_FORMAT" not in ids(run(ok))


def test_empty_container_element_flagged_as_error():
    msg = result_msg('<Result Rank="1" SortOrder="1"><ExtendedResults/></Result>')
    hits = [f for f in run(msg).findings if f.rule_id == "CORE_NO_EMPTY_ELEMENTS"]
    assert hits and all(f.severity.value == "error" for f in hits)


def test_empty_attrs_are_reported_as_warning():
    # Unsuppressed empty attributes are reported as defects in the field, so
    # this is still surfaced -- but as a warning, not an error: FND 3.1
    # explicitly permits the empty form and 6.7 only prefers omission.
    msg = result_msg('<Result Rank="1" SortOrder="1" IRM=""/>')
    hits = [f for f in run(msg).findings if f.rule_id == "CORE_NO_EMPTY_ATTRS"]
    assert hits and all(f.severity.value == "warning" for f in hits)
