"""Enforce attributes a Data Dictionary marks mandatory that the XSD does not.

65 (element, attribute) pairs across the SYOG26 DDs are mandatory per the DD
and optional per the schema, so nothing checks them today. If the DD is the
authority on obligation -- which is why XSD errors are suppressed where a DD
says optional -- it is the authority in the other direction too.

Enforcement is restricted to pairs the schema proves unambiguous
(ObligationRegistry.mandatory_attrs(enforceable_only=True)). Measured on the
real 2026-06-05 corpus that restriction is what separates 523 correct findings
from 38,648 false ones.
"""
from pathlib import Path

from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.pipeline.orchestrator import Pipeline
from tests.conftest import needs_populated_ruleset

PACK = build_ruleset_pack(Path("Rules/SYOG26"))
RSC = "SWM" + "-" * 31
RULE = "CORE_DD_MANDATORY_ATTR"


def result_msg(sub_event_name=True):
    """DT_RESULT carrying a SportDescription.

    SWM marks SportDescription/@SubEventName mandatory and the schema leaves it
    optional, so this is one of the 18 pairs enforcement exists for -- unlike
    Competition/@Gen, which the schema already reports and which enforcement
    therefore skips to avoid double-counting.
    """
    sen = ' SubEventName="Men\'s 50m Backstroke - Heat 1"' if sub_event_name else ''
    return ('<OdfBody DocumentType="DT_RESULT" DocumentCode="{}" '
            'CompetitionCode="SYOG2026" Version="1" FeedFlag="P" '
            'Date="2026-06-05" Time="120000000" LogicalDate="2026-06-05" '
            'Source="SWM"><Competition Gen="G" Sport="S" Codes="C">'
            '<Discipline Code="{}"/><ExtendedInfos><SportDescription '
            'DisciplineName="Swimming" EventName="50m Backstroke"{}/>'
            '</ExtendedInfos></Competition></OdfBody>'
            ).format(RSC, RSC, sen).encode()


def ids(res, rule=RULE):
    return [f for f in res.findings if f.rule_id == rule]


@needs_populated_ruleset
def test_missing_dd_mandatory_attribute_is_reported():
    assert ids(Pipeline().run(result_msg(sub_event_name=False), PACK))


def test_present_attribute_is_not_reported():
    assert not ids(Pipeline().run(result_msg(sub_event_name=True), PACK))


@needs_populated_ruleset
def test_what_the_xsd_already_reports_is_not_duplicated():
    """Competition/@Gen is mandatory for DT_ENTRIES per the SWM DD AND required
    by the schema. Only XSD_INVALID should fire; enforcing it too would give
    two errors for one defect."""
    xml = ('<OdfBody DocumentType="DT_ENTRIES" DocumentCode="{}" '
           'CompetitionCode="SYOG2026" Version="1" FeedFlag="P" '
           'Date="2026-06-05" Time="1" LogicalDate="2026-06-05" Source="SWM">'
           '<Competition Sport="S" Codes="C"><Discipline Code="{}"/>'
           '</Competition></OdfBody>').format(RSC, RSC).encode()
    res = Pipeline().run(xml, PACK)
    assert [f for f in res.findings
            if f.rule_id == "XSD_INVALID" and "'Gen'" in f.message]
    assert not [f for f in ids(res) if "Gen" in f.message]


@needs_populated_ruleset
def test_finding_names_the_element_the_attribute_and_the_authority():
    f = ids(Pipeline().run(result_msg(sub_event_name=False), PACK))[0]
    assert "SubEventName" in f.message and "SportDescription" in f.message
    assert f.source_ref


def test_ambiguous_pairs_never_fire():
    """Description/@TeamName is mandatory only for a Competitor's description,
    but <Description> is 13 complexTypes. Enforcing it by element name flagged
    5,419 athlete descriptions on the real corpus. It must stay excluded."""
    body = ('<Result SortOrder="1"><Competitor Code="1" Type="A"><Composition>'
            '<Athlete Code="1" Order="1"><Description GivenName="A" '
            'FamilyName="B" Gender="M"/></Athlete></Composition>'
            '</Competitor></Result>')
    xml = ('<OdfBody DocumentType="DT_RESULT" DocumentCode="{}" '
           'CompetitionCode="SYOG2026" Version="1" FeedFlag="P" '
           'Date="2026-06-05" Time="1" LogicalDate="2026-06-05" Source="SWM">'
           '<Competition Gen="G" Sport="S" Codes="C"><Discipline Code="{}"/>'
           '{}</Competition></OdfBody>').format(RSC, RSC, body).encode()
    bad = [f for f in ids(Pipeline().run(xml, PACK)) if "TeamName" in f.message]
    assert bad == [], bad
