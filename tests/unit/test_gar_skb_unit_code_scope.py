"""Regression tests for the rule-content-fixes audit (2026-08-29):
GAR_UNIT_CODE / SKB_UNIT_CODE checked @Unit against the PHASE codeset
anywhere in the message (target .//*[@Unit]), but the DD's Unit/PHASE row
("Element: Competition /Configs /Config (1,N)") governs only
Competition/Configs/Config/@Unit. The old target also caught
Competitor/@Unit, which GEN DD line 1272 defines as an EVENT_UNIT RSC, not a
PHASE RSC -- so only ~31% (GAR) / ~26% (SKB) of conforming unit codes passed.

Also covers the knock-on effect on loader._specialise_by_discipline:
GEN_UNIT_CODE (codeset EVENT_UNIT, target .//*[@Unit]) previously stood down
for GAR and SKB because their old rules shared its _specialisation_key
(primitive, target, attribute). Narrowing the discipline rules' target
changes that key, so GEN_UNIT_CODE should resume covering Competitor/@Unit
in GAR/SKB messages.

See Rules/SYOG26/Disciplines/GAR/rules/ODF_GAR_Data_Dictionary.pdf.yaml and
Rules/SYOG26/Disciplines/SKB/rules/ODF_SKB_Data_Dictionary.pdf.yaml.
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


# Real 34-char RSCs from SYOG2026_ODF_Common_Codes_v_1_9_1.xlsx (PHASE and
# EVENT_UNIT sheets), not invented.
GAR_EVENT_UNIT = "GARMGEN---------------QUAL000001--"
GAR_PHASE = "GARMGEN---------------QUAL--------"
SKB_EVENT_UNIT = "SKBMSTREET------------QUAL000100--"
SKB_PHASE = "SKBGGEN---------------DRAW--------"


def test_gar_unit_code_does_not_fire_on_competitor_event_unit():
    res = run(msg("GAR", f'<Result><Competitor Unit="{GAR_EVENT_UNIT}"/></Result>'))
    assert "GAR_UNIT_CODE" not in ids(res), [
        f.message for f in res.findings if f.rule_id == "GAR_UNIT_CODE"]


@needs_populated_ruleset
def test_gar_unit_code_fires_on_config_non_phase_value():
    res = run(msg("GAR", '<Configs><Config Unit="NOTAPHASE"/></Configs>'))
    hits = [f for f in res.findings if f.rule_id == "GAR_UNIT_CODE"]
    assert len(hits) == 1


def test_gar_unit_code_does_not_fire_on_config_valid_phase():
    res = run(msg("GAR", f'<Configs><Config Unit="{GAR_PHASE}"/></Configs>'))
    assert "GAR_UNIT_CODE" not in ids(res)


@needs_populated_ruleset
def test_gen_unit_code_resumes_covering_gar_competitor_unit():
    res = run(msg("GAR", '<Result><Competitor Unit="NOTANEVENTUNIT"/></Result>'))
    assert "GEN_UNIT_CODE" in ids(res), [f.rule_id for f in res.findings]


def test_skb_unit_code_does_not_fire_on_competitor_event_unit():
    res = run(msg("SKB", f'<Result><Competitor Unit="{SKB_EVENT_UNIT}"/></Result>'))
    assert "SKB_UNIT_CODE" not in ids(res), [
        f.message for f in res.findings if f.rule_id == "SKB_UNIT_CODE"]


@needs_populated_ruleset
def test_skb_unit_code_fires_on_config_non_phase_value():
    res = run(msg("SKB", '<Configs><Config Unit="NOTAPHASE"/></Configs>'))
    hits = [f for f in res.findings if f.rule_id == "SKB_UNIT_CODE"]
    assert len(hits) == 1


def test_skb_unit_code_does_not_fire_on_config_valid_phase():
    res = run(msg("SKB", f'<Configs><Config Unit="{SKB_PHASE}"/></Configs>'))
    assert "SKB_UNIT_CODE" not in ids(res)


@needs_populated_ruleset
def test_gen_unit_code_resumes_covering_skb_competitor_unit():
    res = run(msg("SKB", '<Result><Competitor Unit="NOTANEVENTUNIT"/></Result>'))
    assert "GEN_UNIT_CODE" in ids(res), [f.rule_id for f in res.findings]
