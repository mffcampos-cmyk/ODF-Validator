"""Item3b audit (2026-08-30): GEN_FUNCTION_CODE / SAL_FUNCTION_CODE asserted
every @Function against DISCIPLINE_FUNCTION, but Presentation/Presenter/
@Function is documented as SCGEN@Presenter (ODF_GEN_R-OWG2026-GEN1.md line
9046: MEDAL_PRESENTER, FLOWER_PRESENTER, ACCOMPANY_PRESENTER, ...), not a
DISCIPLINE_FUNCTION Id -- every conforming Presenters message was flagged.

Verified against the DD: the claim that Decision/SignedBy/@Function is
*generically* a collision does not hold -- ODF_GEN_R-OWG2026-GEN1.md lines
8570 and 8662 document both Decision/SignedBy/@Function and Protest/
SignedBy/@Function as CC@DISCIPLINE_FUNCTION Id identically. The split is
real only for SAL: ODF_SAL_Data_Dictionary.md line 1710 redefines
Decision/SignedBy/@Function as free-text S(30), while line 1828 keeps
Protest/SignedBy/@Function as CC@DISCIPLINE_FUNCTION Id. Since SAL_FUNCTION_
CODE specialises (stands down) GEN_FUNCTION_CODE for SAL entirely, it must
itself cover Presenter and split SignedBy by parent; the tag alone cannot
distinguish Decision/SignedBy from Protest/SignedBy, so the Protest side is
restored by a new, separately-scoped rule, SAL_PROTEST_SIGNEDBY_FUNCTION_CODE
(target .//Protest/SignedBy[@Function]), instead of an exclude_tags entry.
"""
from pathlib import Path
from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.pipeline.orchestrator import Pipeline
from tests.conftest import needs_populated_ruleset

PACK = build_ruleset_pack(Path("Rules/SYOG26"))


def ids(result):
    return {f.rule_id for f in result.findings}


def run(xml):
    return Pipeline().run(xml.encode("utf-8"), PACK)


def _disc(code3):
    return code3 + "-" * 31


PRESENTER = (
    '<OdfBody DocumentType="DT_PRESENTER" DocumentCode="{d3}">'
    '<Competition><Discipline Code="{disc}"/>'
    '<Presentation Event="{disc}">'
    '<Presenter Function="MEDAL_PRESENTER" Order="1">'
    '<Description FamilyName="Smith"/>'
    '<Detail Language="ENG" PresenterName="x" LongPresenterName="x"/>'
    '</Presenter></Presentation></Competition></OdfBody>'
)

COACH_BAD = (
    '<OdfBody DocumentType="DT_PARTIC" DocumentCode="{d3}">'
    '<Competition><Discipline Code="{disc}"/>'
    '<Coach Function="NOT_A_REAL_FUNCTION_ID"/>'
    '</Competition></OdfBody>'
)

DECISION_SIGNEDBY = (
    '<OdfBody DocumentType="DT_COMMUNICATION" DocumentCode="{d3}">'
    '<Competition><Discipline Code="{disc}"/>'
    '<Communication PublishTime="2026-01-01T00:00:00+00:00">'
    '<Decision><SignedBy FamilyName="Smith" Function="Chief Judge" Order="1"/>'
    '</Decision></Communication></Competition></OdfBody>'
)

PROTEST_SIGNEDBY = (
    '<OdfBody DocumentType="DT_COMMUNICATION" DocumentCode="{d3}">'
    '<Competition><Discipline Code="{disc}"/>'
    '<Communication PublishTime="2026-01-01T00:00:00+00:00">'
    '<Protest Status="OPN" Interpreter="N" Rule="R1">'
    '<SignedBy FamilyName="Smith" Function="{fn}"/>'
    '</Protest></Communication></Competition></OdfBody>'
)


# ---- GEN_FUNCTION_CODE (GAR has no independent SignedBy/Presenter text, so
# it exercises GEN's copy directly) -----------------------------------------

def test_gen_function_code_does_not_flag_conforming_presenter():
    xml = PRESENTER.format(d3="GAR", disc=_disc("GAR"))
    assert "GEN_FUNCTION_CODE" not in ids(run(xml))


@needs_populated_ruleset
def test_gen_function_code_still_flags_bad_function_elsewhere():
    xml = COACH_BAD.format(d3="GAR", disc=_disc("GAR"))
    assert "GEN_FUNCTION_CODE" in ids(run(xml))


# ---- SAL_FUNCTION_CODE + SAL_PROTEST_SIGNEDBY_FUNCTION_CODE ---------------

def test_sal_function_code_does_not_flag_conforming_presenter():
    xml = PRESENTER.format(d3="SAL", disc=_disc("SAL"))
    assert "SAL_FUNCTION_CODE" not in ids(run(xml))


def test_sal_function_code_does_not_flag_free_text_decision_signedby():
    # SAL's own DD redefines this as free text S(30); "Chief Judge" is legal.
    xml = DECISION_SIGNEDBY.format(d3="SAL", disc=_disc("SAL"))
    assert "SAL_FUNCTION_CODE" not in ids(run(xml))


@needs_populated_ruleset
def test_sal_function_code_still_flags_bad_function_elsewhere():
    xml = COACH_BAD.format(d3="SAL", disc=_disc("SAL"))
    assert "SAL_FUNCTION_CODE" in ids(run(xml))


@needs_populated_ruleset
def test_sal_protest_signedby_still_checked_against_discipline_function():
    # A real DISCIPLINE_FUNCTION id (any discipline's -- the table is not
    # discipline-filtered on lookup) must not be flagged...
    good = PROTEST_SIGNEDBY.format(d3="SAL", disc=_disc("SAL"), fn="COACH")
    assert "SAL_PROTEST_SIGNEDBY_FUNCTION_CODE" not in ids(run(good))
    # ...while a bogus one still is: this is the real coverage the tag-level
    # exclude_tags on SAL_FUNCTION_CODE would otherwise have silently dropped.
    bad = PROTEST_SIGNEDBY.format(d3="SAL", disc=_disc("SAL"), fn="NOT_REAL")
    assert "SAL_PROTEST_SIGNEDBY_FUNCTION_CODE" in ids(run(bad))
