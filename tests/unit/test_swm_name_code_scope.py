"""A rules review: SWM_NAME_CODE asserted every @Name against the
RECORD table's ENG_Description, but the XSD declares @Name on seven
complexTypes (teamofteamscompositionType, teamType, horseType,
competitorAchievementDataType, teamBIOType, horseBIOType,
brokenRecordDescriptionType) and only the last -- Competition/Record/
Description -- is a record description (ODF_SWM_Data_Dictionary.md line
1097: "Name | M | CC@RECORD ENG Description"). The other six are relay/team
names and biography text, so real team names like "UNITED STATES" were
flagged on essentially every SWM team result. Narrowed target from
.//*[@Name] to .//Record/Description[@Name].
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


SWM_DISC = "SWM" + "-" * 31

TEAM_RESULT = (
    '<OdfBody DocumentType="DT_RESULT" DocumentCode="SWM">'
    '<Competition><Discipline Code="{disc}"/>'
    '<Result><Competitor Code="USA" Type="T" Organisation="USA">'
    '<Composition><Team Code="USA1" Name="UNITED STATES"/></Composition>'
    '</Competitor></Result></Competition></OdfBody>'
).format(disc=SWM_DISC)

RECORD_GOOD = (
    '<OdfBody DocumentType="DT_CODES" DocumentCode="SWM">'
    '<Competition><Discipline Code="{disc}"/>'
    '<Record Code="X"><Description Name="Men\'s 100m Backstroke"/>'
    '</Record></Competition></OdfBody>'
).format(disc=SWM_DISC)

RECORD_BAD = (
    '<OdfBody DocumentType="DT_CODES" DocumentCode="SWM">'
    '<Competition><Discipline Code="{disc}"/>'
    '<Record Code="X"><Description Name="Not A Real Record"/>'
    '</Record></Competition></OdfBody>'
).format(disc=SWM_DISC)


def test_team_name_not_flagged():
    # TeamName lives on Competitor/Description, not Record/Description; the
    # broad .//*[@Name] target used to catch it, the narrowed one does not.
    assert "SWM_NAME_CODE" not in ids(run(TEAM_RESULT))


def test_real_record_description_not_flagged():
    assert "SWM_NAME_CODE" not in ids(run(RECORD_GOOD))


@needs_populated_ruleset
def test_unknown_record_description_still_flagged():
    assert "SWM_NAME_CODE" in ids(run(RECORD_BAD))
