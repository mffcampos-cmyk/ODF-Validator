"""ExtendedResult siblings are split points of ONE competitor, not competitors.

A manual review of a 2,637-file swimming run: 19,103 of 19,551
reported errors (97.9%) came from CORE_SORTORDER_UNIQUE and
CORE_RANK_TIES_RANKEQUAL firing on
/OdfBody/Competition/Result[]/ExtendedResults/ExtendedResult[]. Both rules use
a wildcard target (".//*[@SortOrder]", ".//*[@Rank]") and the
sibling_duplicates primitive, which groups by (parent, tag, value).

That axis is correct for <Result>, <Entry>, <StatsItem> and friends, where
siblings are distinct competitors in one ranked list:

  SWM DD line 944  "Used to sort all results in a phase"
  SWM DD line 1271 "Unique sort order for all results"

It is wrong for <ExtendedResult Type="PROGRESS" Code="INTERMEDIATE">, where
siblings are the SAME competitor at successive split points (@Pos = 1,2,3,F):

  SWM DD line 706 SortOrder  "Index based on whole list ... Sorted by the
                              intermediate passed most recently"
  SWM DD line ~705 Rank      "Cumulative rank of the competitor for THIS
                              SPECIFIC ExtendedResult"
  SWM DD line ~705 RankEqual "Send Y where Rank AT THIS SPECIFIC
                              ExtendResult is equalled"

A repeated SortOrder across those siblings means the swimmer held position
between two splits; a repeated Rank is not a tie at all (a tie is two
competitors sharing a rank at the same @Pos, i.e. across <Result> siblings).

The canonical proof is that the Data Dictionary's own published sample fails
both rules. That sample is the fixture below.
"""
from pathlib import Path

from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.pipeline.orchestrator import Pipeline

PACK = build_ruleset_pack(Path("Rules/SYOG26"))
RSC = "SWM" + "-" * 31

# VERBATIM from ODF_SWM_Data_Dictionary.md line 726, "Sample (Individual)".
# Pos=3 and Pos=F share Rank="1" and SortOrder="1"; both are documented-valid.
DD_SAMPLE_EXTENDED_RESULTS = (
    '<ExtendedResults>'
    '<ExtendedResult Type="ER" Code="REACT_TIME" Value="0.76"/>'
    '<ExtendedResult Type="PROGRESS" Code="INTERMEDIATE" Pos="1" Value="25.30"'
    ' Rank="5" Diff="0.39" SortOrder="5"/>'
    '<ExtendedResult Type="PROGRESS" Code="INTERMEDIATE" Pos="2" Value="52.26"'
    ' Value2="26.96" Rank="2" Diff="0.24" SortOrder="2" Move="3"/>'
    '<ExtendedResult Type="PROGRESS" Code="INTERMEDIATE" Pos="3" Value="1:19.54"'
    ' Value2="27.28" Rank="1" SortOrder="1" Move="1"/>'
    '<ExtendedResult Type="PROGRESS" Code="INTERMEDIATE" Pos="F" Value="1:46.10"'
    ' Value2="26.56" Rank="1" SortOrder="1" Move="0"/>'
    '</ExtendedResults>'
)


def result_msg(body):
    return ('<OdfBody DocumentType="DT_RESULT" DocumentCode="{}" '
            'CompetitionCode="SYOG2026" Version="1">'
            '<Competition Gen="SYOG2026-1.0" Sport="SYOG2026-SWM-1.2" '
            'Codes="SYOG2026-1.9.1"><Discipline Code="SWM"/>{}'
            '</Competition></OdfBody>').format(RSC, body)


def run(xml):
    return Pipeline().run(xml.encode("utf-8"), PACK)


def ids(result):
    return {f.rule_id for f in result.findings}


def test_dd_sample_extendedresult_does_not_trigger_sortorder_unique():
    """The DD's own published sample must not be reported as a defect."""
    res = run(result_msg(
        '<Result SortOrder="1" Rank="1" ResultType="TIME" Result="1:46.10"'
        ' StartOrder="4" StartSortOrder="4">'
        + DD_SAMPLE_EXTENDED_RESULTS +
        '</Result>'))
    assert "CORE_SORTORDER_UNIQUE" not in ids(res), [
        f.message for f in res.findings if f.rule_id == "CORE_SORTORDER_UNIQUE"]


def test_dd_sample_extendedresult_does_not_trigger_rank_ties_rankequal():
    """Same competitor at two splits is not a tie between competitors."""
    res = run(result_msg(
        '<Result SortOrder="1" Rank="1" ResultType="TIME" Result="1:46.10"'
        ' StartOrder="4" StartSortOrder="4">'
        + DD_SAMPLE_EXTENDED_RESULTS +
        '</Result>'))
    assert "CORE_RANK_TIES_RANKEQUAL" not in ids(res), [
        f.message for f in res.findings
        if f.rule_id == "CORE_RANK_TIES_RANKEQUAL"]


def test_duplicate_sortorder_across_result_siblings_still_flagged():
    """Two competitors in one ranked list sharing a SortOrder is the observed
    defect this rule exists for -- it must keep firing."""
    res = run(result_msg(
        '<Result SortOrder="1" Rank="1"/><Result SortOrder="1" Rank="2"/>'))
    assert "CORE_SORTORDER_UNIQUE" in ids(res)


def test_tied_rank_across_result_siblings_still_flagged():
    """A genuine tie between competitors with no RankEqual is the observed
    defect this rule exists for -- it must keep firing."""
    res = run(result_msg(
        '<Result SortOrder="1" Rank="1"/><Result SortOrder="2" Rank="1"/>'))
    assert "CORE_RANK_TIES_RANKEQUAL" in ids(res)


def test_tied_rank_across_result_siblings_accepted_with_rankequal():
    res = run(result_msg(
        '<Result SortOrder="1" Rank="1" RankEqual="Y"/>'
        '<Result SortOrder="2" Rank="1" RankEqual="Y"/>'))
    assert "CORE_RANK_TIES_RANKEQUAL" not in ids(res)


def test_entry_sortorder_uniqueness_still_enforced():
    """Excluding ExtendedResult must not weaken other elements (Entry)."""
    res = run(result_msg(
        '<ExtendedInfos><Entry SortOrder="1"/><Entry SortOrder="1"/>'
        '</ExtendedInfos>'))
    assert "CORE_SORTORDER_UNIQUE" in ids(res)
