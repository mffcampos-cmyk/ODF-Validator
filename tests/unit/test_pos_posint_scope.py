"""A rules review -- PROVISIONAL, conservative narrowing only.

ATH_POS_POSINT and GAR_POS_POSINT (both severity error, regex ^[0-9]+$)
targeted .//*[@Pos] wholesale. Two prior reviewers disagreed on whether that
was ever wrong: one read the DD's "N/A" @Pos cells as per-Code metadata that
real conforming messages never send (so the broad target was harmless); the
other found @Pos typed xs:string in most XSD declarations and pointed at
concrete non-numeric values the DDs document for the very same tag, e.g. ATH
ExtendedResult/Extension@Code=FALSE_START has @Pos "G, 2"
(ODF_ATH_Data_Dictionary.md line 885) -- not purely numeric.

This was NOT settled (it needs the real message corpus). The conservative
fix narrows each rule to only the @Code values its own DD states as numeric,
via a new value_format `context_attr`/`context_values` filter, leaving every
other @Pos occurrence -- including FALSE_START -- unchecked by this rule.
Under-enforcing is deliberate for an error-severity rule on disputed
grounds; these tests assert exactly that: the narrowed rule still catches
real corruption in a named-numeric context, while a documented non-numeric
value in a NOT-named context is no longer wrongly flagged.
"""
from pathlib import Path
from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.pipeline.orchestrator import Pipeline

PACK = build_ruleset_pack(Path("Rules/SYOG26"))


def ids(result):
    return {f.rule_id for f in result.findings}


def run(xml):
    return Pipeline().run(xml.encode("utf-8"), PACK)


ATH_DISC = "ATH" + "-" * 31
GAR_DISC = "GAR" + "-" * 31

ATH_EXTENDED_RESULT = (
    '<OdfBody DocumentType="DT_RESULT" DocumentCode="ATH">'
    '<Competition><Discipline Code="{disc}"/>'
    '<Result><ExtendedResults>'
    '<ExtendedResult Type="ER" Code="{code}" Pos="{pos}" Value="x"/>'
    '</ExtendedResults></Result></Competition></OdfBody>'
).format(disc=ATH_DISC, code="{code}", pos="{pos}")

ATH_FALSE_START = (
    '<OdfBody DocumentType="DT_RESULT" DocumentCode="ATH">'
    '<Competition><Discipline Code="{disc}"/>'
    '<Result><ExtendedResults>'
    '<ExtendedResult Type="ER" Code="FALSE_START" Pos="G" Value="F1"/>'
    '</ExtendedResults></Result></Competition></OdfBody>'
).format(disc=ATH_DISC)

ATH_IMAGE = (
    '<OdfBody DocumentType="DT_IMAGE" DocumentCode="ATH">'
    '<Competition><Discipline Code="{disc}"/>'
    '<Image Pos="{pos}" Version="1" Revision="1" ImageType="jpg"/>'
    '</Competition></OdfBody>'
)

GAR_EXTENDED_RESULT = (
    '<OdfBody DocumentType="DT_RESULT" DocumentCode="GAR">'
    '<Competition><Discipline Code="{disc}"/>'
    '<Result><ExtendedResults>'
    '<ExtendedResult Type="ER" Code="STAGE" Pos="{pos}" Value="LAST"/>'
    '</ExtendedResults></Result></Competition></OdfBody>'
).format(disc=GAR_DISC, pos="{pos}")

GAR_UNDOCUMENTED_EXTENSION = (
    '<OdfBody DocumentType="DT_GENERAL" DocumentCode="GAR">'
    '<Competition><Discipline Code="{disc}"/>'
    '<ExtendedInfos><ExtendedInfo Type="UI" Code="PHASE" Value="x">'
    '<Extension Code="SOMETHING_ELSE" Pos="Q" Value="y"/>'
    '</ExtendedInfo></ExtendedInfos></Competition></OdfBody>'
).format(disc=GAR_DISC)


# ---- ATH_POS_POSINT --------------------------------------------------------

def test_ath_pos_posint_flags_bad_value_in_named_numeric_context():
    xml = ATH_EXTENDED_RESULT.format(code="INTERMEDIATE", pos="abc")
    assert "ATH_POS_POSINT" in ids(run(xml))


def test_ath_pos_posint_accepts_good_value_in_named_numeric_context():
    xml = ATH_EXTENDED_RESULT.format(code="INTERMEDIATE", pos="3")
    assert "ATH_POS_POSINT" not in ids(run(xml))


def test_ath_pos_posint_does_not_flag_documented_false_start_letter():
    # FALSE_START's own DD entry allows @Pos="G" (guide) -- not a Code named
    # numeric by this rule, so it must be left unchecked.
    assert "ATH_POS_POSINT" not in ids(run(ATH_FALSE_START))


def test_ath_pos_posint_image_flags_and_accepts():
    assert "ATH_POS_POSINT_IMAGE" in ids(run(ATH_IMAGE.format(disc=ATH_DISC, pos="x")))
    assert "ATH_POS_POSINT_IMAGE" not in ids(run(ATH_IMAGE.format(disc=ATH_DISC, pos="1")))


# ---- GAR_POS_POSINT ---------------------------------------------------------

def test_gar_pos_posint_flags_bad_value_in_named_numeric_context():
    xml = GAR_EXTENDED_RESULT.format(pos="abc")
    assert "GAR_POS_POSINT" in ids(run(xml))


def test_gar_pos_posint_accepts_good_value_in_named_numeric_context():
    xml = GAR_EXTENDED_RESULT.format(pos="1")
    assert "GAR_POS_POSINT" not in ids(run(xml))


def test_gar_pos_posint_does_not_flag_undocumented_extension_code():
    # Code="SOMETHING_ELSE" is not one the GAR DD names as numeric for @Pos
    # (GAR's own numeric statements are Code-specific -- STAGE, SCORE, NEED,
    # apparatus codes, etc.); a generic ExtendedInfo/Extension the GAR DD
    # never speaks to at all must not be asserted numeric by this rule.
    assert "GAR_POS_POSINT" not in ids(run(GAR_UNDOCUMENTED_EXTENSION))
