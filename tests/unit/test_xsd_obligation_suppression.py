"""An XSD "attribute required but missing" error is dropped when the Data
Dictionary says that attribute is optional for that message.

`odf2-structure.xsd` declares one `competitionType` shared by every message, so
`use="required"` on Competition/@Gen is asserted for DT_ENTRIES and DT_RESULT at
once. All 25 SYOG26 discipline DDs mark @Gen mandatory for DT_ENTRIES and
optional elsewhere. The schema cannot express that; the DD can, so the DD wins.

On the 2026-06-05 SWM corpus this turns 2,637 @Gen errors into 523.
"""
from pathlib import Path

from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.pipeline.orchestrator import Pipeline
from tests.conftest import needs_populated_ruleset

PACK = build_ruleset_pack(Path("Rules/SYOG26"))
RSC = "SWM" + "-" * 31


def msg(doc_type, gen=True):
    g = ' Gen="SYOG2026-1.0"' if gen else ''
    return ('<OdfBody DocumentType="{}" DocumentCode="{}" '
            'CompetitionCode="SYOG2026" Version="1" FeedFlag="P" '
            'Date="2026-06-05" Time="120000000" LogicalDate="2026-06-05" '
            'Source="SWM"><Competition{} Sport="S" Codes="C">'
            '<Discipline Code="{}"/></Competition></OdfBody>'
            ).format(doc_type, RSC, g, RSC).encode()


def gen_findings(doc_type, gen=True):
    res = Pipeline().run(msg(doc_type, gen), PACK)
    return [f for f in res.findings if "'Gen'" in f.message]


def test_missing_gen_is_not_an_error_where_the_dd_says_optional():
    assert gen_findings("DT_RESULT", gen=False) == []


@needs_populated_ruleset
def test_missing_gen_is_still_an_error_where_the_dd_says_mandatory():
    assert gen_findings("DT_ENTRIES", gen=False) != []


@needs_populated_ruleset
def test_missing_gen_is_still_an_error_for_a_message_the_sport_dd_omits():
    """DT_PDF is not defined in the SWM DD, so the GEN DD governs and @Gen
    stays mandatory. Silence in the sport DD is not permission."""
    assert gen_findings("DT_PDF", gen=False) != []


def test_a_present_gen_produces_nothing_either_way():
    assert gen_findings("DT_RESULT", gen=True) == []
    assert gen_findings("DT_ENTRIES", gen=True) == []


@needs_populated_ruleset
def test_suppression_does_not_touch_other_xsd_errors():
    """Only the specific 'attribute required but missing' error for an
    attribute the DD makes optional is dropped."""
    res = Pipeline().run(msg("DT_RESULT", gen=False), PACK)
    other = [f for f in res.findings
             if f.rule_id == "XSD_INVALID" and "'Gen'" not in f.message]
    broken = Pipeline().run(
        b'<OdfBody DocumentType="DT_RESULT"><Competition/></OdfBody>', PACK)
    assert [f for f in broken.findings if f.rule_id == "XSD_INVALID"]
    assert isinstance(other, list)
