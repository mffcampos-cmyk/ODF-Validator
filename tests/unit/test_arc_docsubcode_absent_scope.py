"""Regression test for the rule-content-fixes audit (2026-08-29):
ARC_DOCSUBCODE_ABSENT forbade @DocumentSubcode on every ARC message with no
doc_types scope. ARC DD line 2030/2031 mandates DocumentSubcode on DT_WEATHER
(CC@LOCATION Id, location code at venue level); the rule now scopes to the
eight doc types the DD actually marks N/A (DT_SCHEDULE(_UPDATE), DT_PARTIC
(_UPDATE), DT_ENTRIES, DT_RESULT, DT_BRACKETS, DT_RANKING -- DD line
304/565/813/986/1546/1810).

See Rules/SYOG26/Disciplines/ARC/rules/result.yaml.
"""
from pathlib import Path

from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.pipeline.orchestrator import Pipeline

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


def test_arc_docsubcode_absent_does_not_fire_on_weather():
    res = run(msg("ARC", "", doc_type="DT_WEATHER", extra=' DocumentSubcode="DKR"'))
    assert "ARC_DOCSUBCODE_ABSENT" not in ids(res), [
        f.message for f in res.findings if f.rule_id == "ARC_DOCSUBCODE_ABSENT"]


def test_arc_docsubcode_absent_still_fires_on_result():
    res = run(msg("ARC", "", doc_type="DT_RESULT", extra=' DocumentSubcode="1"'))
    hits = [f for f in res.findings if f.rule_id == "ARC_DOCSUBCODE_ABSENT"]
    # Warning, not error, since 2026-09-01: the ARC DD contradicts itself
    # (six rows mark DocumentSubcode N/A, line 2030 mandates it for
    # DT_WEATHER, and message type 2.3.3 has no table at all). A forbid
    # rule on documentation that unreliable must not fail a message.
    assert len(hits) == 1 and hits[0].severity.value == "warning"
