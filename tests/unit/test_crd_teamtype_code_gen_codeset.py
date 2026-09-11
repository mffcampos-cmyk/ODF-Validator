"""Regression test from a rule-content review.

CRD_TEAMTYPE_CODE checked @TeamType against the DISCIPLINE_GENDER codeset
(34-char RSCs), transcribing a documentation error -- the DD names
DISCIPLINE_GENDER but its own instruction is "Use ORG", which is not a
gender RSC. SC@TeamType@CRD does not exist in the Common Codes SPORT_CODES
sheet; SC@TeamType@GEN does, and contains ORG (plus CPLM/CPLP/CPLW/CUSTOM),
matching the DD's own example. Same class of documented DD typo as
SHEDULESTATUS; same pattern as the correct
sibling ARC_TEAMTYPE_VALID (SC@TeamType@ARC).

See Rules/SYOG26/Disciplines/CRD/rules/ODF_CRD_Data_Dictionary.pdf.yaml.
"""
from pathlib import Path

from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.pipeline.orchestrator import Pipeline
from tests.conftest import needs_populated_ruleset

PACK = build_ruleset_pack(Path("Rules/SYOG26"))


def rsc(disc):
    return disc + "-" * (34 - len(disc))


def run(xml):
    return Pipeline().run(xml.encode("utf-8"), PACK)


def ids(result):
    return {f.rule_id for f in result.findings}


def msg(disc, body, doc_type="DT_RESULT", extra=""):
    return ('<OdfBody DocumentType="{}" DocumentCode="{}" '
            'CompetitionCode="SYOG2026" Version="1"{}>'
            '<Competition Gen="SYOG2026-1.0" Sport="SYOG2026-1.0" '
            'Codes="SYOG2026-1.9.1"><Discipline Code="{}"/>{}'
            '</Competition></OdfBody>').format(
                doc_type, rsc(disc), extra, disc, body)


def test_crd_teamtype_code_does_not_fire_on_org():
    res = run(msg("CRD", '<Team TeamType="ORG"/>'))
    assert "CRD_TEAMTYPE_CODE" not in ids(res), [
        f.message for f in res.findings if f.rule_id == "CRD_TEAMTYPE_CODE"]


@needs_populated_ruleset
def test_crd_teamtype_code_fires_on_bogus_value():
    res = run(msg("CRD", '<Team TeamType="NOTATEAMTYPE"/>'))
    hits = [f for f in res.findings if f.rule_id == "CRD_TEAMTYPE_CODE"]
    assert len(hits) == 1
