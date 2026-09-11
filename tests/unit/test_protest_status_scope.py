"""Item3a audit (2026-08-30): GEN_STATUS_CODE / SAL_STATUS_CODE asserted
Competition/Communication/Protest/@Status against PARTICIPANT_STATUS
(CNF/ENT/HIS/NPR/LAR/LGL), but the GEN DD documents Protest/@Status as
SCGEN@ProtestStatus (ODF_GEN_R-OWG2026-GEN1.md line 8594: "Status of
protest"), a disjoint codeset -- CLS/OPN/PND/ROPN per
SYOG2026_ODF_Common_Codes_v_1_9_1.md lines 10898-10901. Every conforming
Protest message was flagged. Fixed with code_membership's exclude_tags,
matching the same idiom used for the weather @Unit collision.
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


PROTEST = (
    '<OdfBody DocumentType="DT_COMMUNICATION" DocumentCode="{d3}">'
    '<Competition><Discipline Code="{disc}"/>'
    '<Communication PublishTime="2026-01-01T00:00:00+00:00">'
    '<Protest Status="{status}" Interpreter="N" Rule="R1"/>'
    '</Communication></Competition></OdfBody>'
)

PARTICIPANT = (
    '<OdfBody DocumentType="DT_PARTIC" DocumentCode="{d3}">'
    '<Competition><Discipline Code="{disc}"/>'
    '<Participant Status="{status}"/></Competition></OdfBody>'
)


# ---- GEN_STATUS_CODE (applies to any discipline without its own override;
# GAR has no independent Protest text so it exercises GEN's copy directly) --

def test_gen_status_code_does_not_flag_conforming_protest():
    xml = PROTEST.format(d3="GAR", disc=_disc("GAR"), status="OPN")
    assert "GEN_STATUS_CODE" not in ids(run(xml))


@needs_populated_ruleset
def test_gen_status_code_still_flags_bad_participant_status():
    xml = PARTICIPANT.format(d3="GAR", disc=_disc("GAR"), status="ZZZ")
    assert "GEN_STATUS_CODE" in ids(run(xml))


# ---- SAL_STATUS_CODE (SAL's own DD independently documents Protest/@Status
# as SC@ProtestStatus Code, ODF_SAL_Data_Dictionary.md line 1759) -----------

def test_sal_status_code_does_not_flag_conforming_protest():
    xml = PROTEST.format(d3="SAL", disc=_disc("SAL"), status="OPN")
    assert "SAL_STATUS_CODE" not in ids(run(xml))


@needs_populated_ruleset
def test_sal_status_code_still_flags_bad_participant_status():
    # SAL_STATUS_CODE is byte-identical to GEN_STATUS_CODE after this fix (both
    # assert PARTICIPANT_STATUS and exclude Protest), so the loader's semantic
    # dedup collapses SAL's copy into GEN's broader one -- GEN_STATUS_CODE
    # alone fires for SAL messages, same convention as
    # test_arc_rules.test_schedule_update_phasetype_checked_against_common_codes.
    xml = PARTICIPANT.format(d3="SAL", disc=_disc("SAL"), status="ZZZ")
    got = ids(run(xml))
    assert "SAL_STATUS_CODE" in got or "GEN_STATUS_CODE" in got
