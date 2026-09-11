"""Regression tests from a rules review: @Unit carries an
EVENT_UNIT RSC on competition elements (Competitor, Config, ...) but is also
the plain measurement-unit attribute on the weather blocks --
Competition/Weather/Conditions/{Precipitation, Pressure, Temperature, Wind}
and Venue/DateTime/Conditions/{same four} (GEN DD lines 8919/8925/8932/8940
and 12986/12992/13001/13009: SCGEN@PrecipitationUnit / @PressureUnit /
@TemperatureUnit / @WindUnit Code -- none of which are EVENT_UNIT codes).

GEN_UNIT_CODE and the 23 discipline `*_UNIT_CODE` rules used the broad target
`.//*[@Unit]` against codeset EVENT_UNIT, so every weather message (sent every
30 minutes during a session per several discipline DDs) was flagged, four
attributes at a time. Fixed by adding `exclude_tags:
[Precipitation, Pressure, Temperature, Wind]` to code_membership's params
(odf_validator/rules/primitives.py) and to every affected rule.

Also pins the interaction with the 2026-08-29 GAR/SKB narrowing: once
GAR_UNIT_CODE / SKB_UNIT_CODE were narrowed to `.//Configs/Config[@Unit]`,
GEN_UNIT_CODE (still `.//*[@Unit]`) resumed covering Competitor/@Unit -- and
weather Unit -- for GAR and SKB messages too. SKB sends DT_WEATHER, so SKB
weather blocks were flagged by the generic rule even though SKB_UNIT_CODE
itself no longer matched. See tests/unit/test_gar_skb_unit_code_scope.py.
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


def weather_msg(disc):
    # Element hierarchy per Rules/SYOG26/xsd/odf2-structure.xsd
    # (weatherType/conditionsType) and GEN DD Sec 2.1.24 (DT_WEATHER):
    # Competition/Weather/Conditions/{Precipitation, Pressure, Temperature,
    # Wind}, each carrying @Unit as a measurement unit, not an RSC.
    return (
        '<OdfBody DocumentType="DT_WEATHER" DocumentCode="{disc_rsc}" '
        'CompetitionCode="SYOG2026" Version="1">'
        '<Competition Gen="SYOG2026-1.0" Sport="SYOG2026-1.0" '
        'Codes="SYOG2026-1.9.1"><Discipline Code="{disc_rsc}"/>'
        '<Weather Date="2026-08-30T12:00:00">'
        '<Conditions>'
        '<Precipitation Unit="M" Value="0"/>'
        '<Pressure Unit="hPa" Value="1013"/>'
        '<Temperature Unit="C" Value="20"/>'
        '<Wind Unit="KMH" Value="10"/>'
        '</Conditions>'
        '</Weather>'
        '</Competition></OdfBody>'
    ).format(disc_rsc=rsc(disc))


def venue_conditions_msg(disc):
    # Second documented shape (GEN DD DT_VEN_COND): Venue/DateTime/Conditions/
    # {Precipitation, Pressure, Temperature, Wind}, same four tag names, same
    # SCGEN@*Unit codesets -- confirms the tag-name exclusion also covers this
    # context, not just the Weather/Conditions one.
    return (
        '<OdfBody DocumentType="DT_VEN_COND" DocumentCode="{disc_rsc}" '
        'CompetitionCode="SYOG2026" Version="1">'
        '<Competition Gen="SYOG2026-1.0" Sport="SYOG2026-1.0" '
        'Codes="SYOG2026-1.9.1"><Discipline Code="{disc_rsc}"/>'
        '<Venue Code="AAW">'
        '<DateTime>'
        '<Conditions>'
        '<Condition Code="1"/>'
        '<Precipitation Unit="M" Value="0"/>'
        '<Pressure Unit="hPa" Value="1013"/>'
        '<Temperature Unit="C" Value="20"/>'
        '<Wind Unit="KMH" Value="10"/>'
        '</Conditions>'
        '</DateTime>'
        '</Venue>'
        '</Competition></OdfBody>'
    ).format(disc_rsc=rsc(disc))


def bad_competitor_msg(disc, bad_unit):
    return (
        '<OdfBody DocumentType="DT_RESULT" DocumentCode="{disc_rsc}" '
        'CompetitionCode="SYOG2026" Version="1">'
        '<Competition Gen="SYOG2026-1.0" Sport="SYOG2026-1.0" '
        'Codes="SYOG2026-1.9.1"><Discipline Code="{disc_rsc}"/>'
        '<Result><Competitor Unit="{bad_unit}"/></Result>'
        '</Competition></OdfBody>'
    ).format(disc_rsc=rsc(disc), bad_unit=bad_unit)


# Real 34-char EVENT_UNIT RSCs, from
# Rules/SYOG26/codes/SYOG2026_ODF_Common_Codes_v_1_9_1.xlsx, not invented.
ATH_EVENT_UNIT = "ATHM100M--------------FNL-000100--"
BKG_EVENT_UNIT = "BKGMINDIVID-----------QUAL000100--"
SKB_EVENT_UNIT = "SKBMSTREET------------QUAL000100--"


def test_ath_weather_block_clean():
    res = run(weather_msg("ATH"))
    got = ids(res)
    assert "ATH_UNIT_CODE" not in got, [
        f.message for f in res.findings if f.rule_id == "ATH_UNIT_CODE"]
    assert "GEN_UNIT_CODE" not in got, [
        f.message for f in res.findings if f.rule_id == "GEN_UNIT_CODE"]


def test_bkg_weather_block_clean():
    res = run(weather_msg("BKG"))
    got = ids(res)
    assert "BKG_UNIT_CODE" not in got
    assert "GEN_UNIT_CODE" not in got


def test_bkg_venue_conditions_block_clean():
    res = run(venue_conditions_msg("BKG"))
    got = ids(res)
    assert "BKG_UNIT_CODE" not in got
    assert "GEN_UNIT_CODE" not in got


def test_skb_weather_block_clean():
    # Pins the GAR/SKB narrowing interaction: SKB_UNIT_CODE no longer matches
    # .//*[@Unit] at all (it targets Configs/Config), so GEN_UNIT_CODE
    # (.//*[@Unit], codeset EVENT_UNIT) is the one that resumed covering SKB's
    # Competitor/@Unit -- and, before this fix, SKB's weather @Unit too, since
    # SKB sends DT_WEATHER.
    res = run(weather_msg("SKB"))
    got = ids(res)
    assert "SKB_UNIT_CODE" not in got
    assert "GEN_UNIT_CODE" not in got, [
        f.message for f in res.findings if f.rule_id == "GEN_UNIT_CODE"]


def test_ath_competitor_valid_event_unit_is_clean():
    res = run(bad_competitor_msg("ATH", ATH_EVENT_UNIT))
    assert "ATH_UNIT_CODE" not in ids(res)
    assert "GEN_UNIT_CODE" not in ids(res)


@needs_populated_ruleset
def test_bkg_competitor_bad_unit_still_flagged():
    # The fix must not silence the rule's real purpose: a genuinely bad
    # @Unit on a competition element (Competitor, not a weather element)
    # still must not pass. BKG_UNIT_CODE itself never appears in a loaded
    # pack's findings -- it is byte-identical in primitive/target/attribute/
    # params to GEN_UNIT_CODE (applies_to: {}), so loader._dedupe_semantic
    # drops it at load time in favour of the broader GEN rule (confirmed via
    # build_ruleset_pack: 'BKG_UNIT_CODE' not in {r.id for r in PACK.rules}).
    # GEN_UNIT_CODE is therefore the rule that must still fire here.
    res = run(bad_competitor_msg("BKG", "NOTANEVENTUNIT"))
    hits = [f for f in res.findings if f.rule_id == "GEN_UNIT_CODE"]
    assert len(hits) == 1


@needs_populated_ruleset
def test_skb_competitor_bad_unit_still_flagged_via_gen():
    # SKB_UNIT_CODE itself no longer targets Competitor/@Unit (narrowed to
    # Configs/Config); GEN_UNIT_CODE is the one that must still catch a bad
    # Competitor/@Unit for SKB.
    res = run(bad_competitor_msg("SKB", "NOTANEVENTUNIT"))
    assert "GEN_UNIT_CODE" in ids(res), [f.rule_id for f in res.findings]


def test_bkg_competitor_valid_event_unit_is_clean_sanity():
    res = run(bad_competitor_msg("BKG", BKG_EVENT_UNIT))
    assert "BKG_UNIT_CODE" not in ids(res)


def test_skb_competitor_valid_event_unit_is_clean_sanity():
    res = run(bad_competitor_msg("SKB", SKB_EVENT_UNIT))
    assert "GEN_UNIT_CODE" not in ids(res)
