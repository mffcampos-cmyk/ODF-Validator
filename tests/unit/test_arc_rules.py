from pathlib import Path
from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.pipeline.orchestrator import Pipeline
from odf_validator.context import ValidationContext
from tests.conftest import needs_populated_ruleset

PACK = build_ruleset_pack(Path("Rules/SYOG26"))


def ids(result):
    return {f.rule_id for f in result.findings}


def run(xml):
    return Pipeline().run(xml.encode("utf-8"), PACK)


SCHED = ('<OdfBody DocumentType="DT_SCHEDULE" DocumentCode="ARC">'
         '<Competition><Discipline Code="ARC-------------------------------"/>'
         '<Session Medal="{medal}"><Unit PhaseType="{pt}"/></Session>'
         '</Competition></OdfBody>')

RESULT = ('<OdfBody DocumentType="DT_RESULT" DocumentCode="ARC">'
          '<Competition><Discipline Code="ARC-------------------------------"/>{body}</Competition></OdfBody>')


def test_schedule_medal_bad():
    # A rules review found ARC_PHASETYPE ({0,1,3} allowlist) had no basis in the
    # ARC DD (line 549 just says CC@PHASE_TYPE) and was removed. Medal="0" is
    # now legal (planned-gold count #0 / SC@UnitMedalType@GEN code 0); a
    # negative value is still flagged.
    got = ids(run(SCHED.format(medal="-1", pt="3")))
    assert "ARC_MEDAL_INT" in got
    assert "ARC_PHASETYPE" not in got


def test_schedule_good():
    got = ids(run(SCHED.format(medal="0", pt="3")))
    assert "ARC_PHASETYPE" not in got
    assert "ARC_MEDAL_INT" not in got


def test_ifrank_dash_flagged():
    # ARC_AVGSPEED was removed by the 2026-07-02 audit: AVG_SPEED appears
    # nowhere in the ARC Data Dictionary.
    got = ids(run(RESULT.format(body='<Result IFRANK="1-2" IRM="DNS"/>')))
    assert "CORE_IFRANK_NODASH" in got


def test_result_clean():
    got = ids(run(RESULT.format(body='<Result IFRANK="1" StartSortOrder="5" Code="A1"/>')))
    assert "CORE_IFRANK_NODASH" not in got




def test_tbd_competitor_is_legal_but_composition_under_it_is_not():
    # Finding C2: Code='TBD' is explicitly legal (GEN 1281/1408, ARC
    # DD 704); what must not be sent under a TBD competitor is Composition/
    # Athlete (GEN 1325 / ARC DD 722).
    legal = RESULT.format(body='<Result><Competitor Code="TBD" Type="A"/></Result>')
    assert "ARC_TBD_NO_COMPOSITION" not in ids(run(legal))
    bad = RESULT.format(body='<Result><Competitor Code="TBD" Type="T">'
                             '<Composition><Athlete Code="1"/></Composition>'
                             '</Competitor></Result>')
    got = [f for f in run(bad).findings if f.rule_id == "ARC_TBD_NO_COMPOSITION"]
    assert len(got) == 1 and got[0].severity.value == "error"


def test_empty_attribute_is_warning():
    # Raised to error on the strength of observed feed defects, then put
    # back to warning: FND 3.1 states that a mandatory attribute with
    # no value "must be sent empty (Attribute="")" and that an empty optional
    # attribute may be sent either way "without any restriction". Omission is a
    # SHOULD in 6.7, so a conforming producer must not fail validation over it.
    # Still reported -- the condition is real -- just not as an error.
    msg = ('<OdfBody DocumentType="DT_RANKING" DocumentCode="ARC"><Competition>'
           '<Discipline Code="ARC-------------------------------"/><Result Rank="1" IRM="" SortOrder="1"/>'
           '</Competition></OdfBody>')
    hits = [f for f in run(msg).findings if f.rule_id == "CORE_NO_EMPTY_ATTRS"]
    assert hits and all(f.severity.value == "warning" for f in hits)


@needs_populated_ruleset
def test_schedule_update_phasetype_checked_against_common_codes():
    # ARC_PHASETYPE (0/1/3 allowlist) was removed by the audit; PhaseType is
    # still validated against CC@PHASE_TYPE by the GEN/ARC membership rules.
    msg = ('<OdfBody DocumentType="DT_SCHEDULE_UPDATE" DocumentCode="ARC"><Competition>'
           '<Discipline Code="ARC-------------------------------"/><Unit Code="ARC" PhaseType="Z"/>'
           '</Competition></OdfBody>')
    got = ids(run(msg))
    assert "ARC_PHASETYPE_CODE" in got or "GEN_PHASETYPE_CODE" in got


CONFIG = ('<OdfBody DocumentType="DT_CONFIG" DocumentCode="ARC"><Competition>'
          '<Discipline Code="ARC-------------------------------"/><Configs><Config Unit="ARC">'
          '<ExtendedConfig Type="EC" Code="QUAL_RULE" Value="x"/>'
          '<ExtendedConfig Type="EC" Code="BRACKET_SIZE" Value="R32"/>'
          '</Config></Configs></Competition></OdfBody>')


def test_extconfig_unknown_code_flagged():
    got = ids(run(CONFIG))
    assert "ARC_EXTCONFIG_CODE" in got          # QUAL_RULE flagged, BRACKET_SIZE not


def test_empty_attribute_flagged():
    # A non-exempt empty attribute (Organisation) is warned about.
    msg = ('<OdfBody DocumentType="DT_RESULT" DocumentCode="ARC">'
           '<Competition><Discipline Code="ARC-------------------------------"/>'
           '<Result><Competitor Code="9001" Organisation=""/></Result>'
           '</Competition></OdfBody>')
    assert "CORE_NO_EMPTY_ATTRS" in ids(run(msg))


@needs_populated_ruleset
def test_teamtype_exempt_from_empty_attr_warning():
    # Empty TeamType is reported by ARC_TEAMTYPE_VALID (error), NOT by the
    # generic empty-attribute warning (avoids double-reporting).
    msg = ('<OdfBody DocumentType="DT_PARTIC_TEAMS_UPDATE" DocumentCode="ARC">'
           '<Competition><Discipline Code="ARC-------------------------------"/>'
           '<Team Code="ARCX-ASA01" Organisation="ASA" TeamType=""/>'
           '</Competition></OdfBody>')
    got = ids(run(msg))
    assert "ARC_TEAMTYPE_VALID" in got
    assert "CORE_NO_EMPTY_ATTRS" not in got


@needs_populated_ruleset
def test_teamtype_must_be_valid():
    bad = ('<OdfBody DocumentType="DT_PARTIC_TEAMS_UPDATE" DocumentCode="ARC">'
           '<Competition><Discipline Code="ARC-------------------------------"/>'
           '<Team Code="X" Organisation="ASA" TeamType=""/></Competition></OdfBody>')
    got = [f for f in run(bad).findings if f.rule_id == "ARC_TEAMTYPE_VALID"]
    assert len(got) == 1 and got[0].severity.value == "error"
    good = bad.replace('TeamType=""', 'TeamType="ORG"')
    assert "ARC_TEAMTYPE_VALID" not in ids(run(good))


@needs_populated_ruleset
def test_unknown_venue_is_warning():
    bad = ('<OdfBody DocumentType="DT_SCHEDULE_UPDATE" DocumentCode="ARC">'
           '<Competition><Discipline Code="ARC-------------------------------"/>'
           '<VenueDescription Venue="AWA" VenueName="x"/></Competition></OdfBody>')
    hits = [f for f in run(bad).findings if f.rule_id == "GEN_VENUE_CODE"]
    assert len(hits) == 1 and hits[0].severity.value == "warning"
    good = bad.replace('Venue="AWA"', 'Venue="AAW"')   # AAW is in the VENUE codeset
    assert "GEN_VENUE_CODE" not in ids(run(good))
