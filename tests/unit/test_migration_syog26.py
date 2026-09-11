from pathlib import Path

import pytest

from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.ingestion.convert import dd_to_markdown
from odf_validator.ingestion.dd_parser import extract_draft_rules
from tests.conftest import needs_populated_ruleset

RULES_ROOT = Path("Rules/SYOG26")

# The GEN document, in the order the application would encounter it. The
# published repository ships no IOC documents: the first-launch import
# downloads ODF_GEN_R-OWG2026-GEN.pdf and dd_to_markdown() converts it with
# pdf-inspector, falling back to markitdown. A development tree may instead
# still hold a .md conversion, which dd_to_markdown() passes through unchanged.
#
# .pdf is tried first on purpose. It is the file the shipped path actually
# produces, so a test reading the .md in preference would keep passing while
# the converted-from-PDF text -- the only text the application ever sees --
# had stopped yielding the draft.
GEN_SOURCE_NAMES = ("ODF_GEN_R-OWG2026-GEN.pdf", "ODF_GEN_R-OWG2026-GEN.md")


def gen_markdown() -> str:
    """GEN's text, obtained through the same converter the builder uses.

    Skips rather than fails when neither source is present: that is the normal
    state of a freshly cloned public checkout, not a defect. Deliberately not
    the @needs_populated_ruleset marker, which probes Rules/SYOG26/xsd/ -- this
    test needs one specific document, so it checks for that document.
    """
    for name in GEN_SOURCE_NAMES:
        path = RULES_ROOT / name
        if path.exists():
            return dd_to_markdown(path)[0]
    pytest.skip("needs the GEN document; run the first-launch import "
                "(Rulesets -> check and download updates -> apply)")


def test_migrated_pack_has_the_same_active_rule_ids_as_before():
    pack = build_ruleset_pack(RULES_ROOT)
    ids = {r.id for r in pack.rules}
    # Every hand-authored rule id from the pre-migration pack must still be
    # active after grandfathering (odf_validator/rules/defs/gen/common.yaml +
    # arc/{config,result,schedule,teams}.yaml).
    expected = {
        "GEN_VENUE_CODE",
        "ARC_EXTCONFIG_CODE",
        # ARC_VENUENAME_DESC/ARC_AVGSPEED/ARC_TBD_COMPETITOR/ARC_PHASETYPE
        # were removed by the 2026-07-02 audit (no doc basis / doc misread);
        # ARC_TBD_NO_COMPOSITION is the doc-correct replacement.
        "ARC_TBD_NO_COMPOSITION", "ARC_MEDAL_INT",
        "ARC_TEAMTYPE_VALID",
    }
    assert expected <= ids


@needs_populated_ruleset
def test_migrated_pack_schema_and_codes_load_cleanly():
    pack = build_ruleset_pack(RULES_ROOT)
    assert pack.report.errors == []
    assert pack.schema is not None
    assert pack.codes.table("COUNTRY") is not None
    # ARC is the discipline grandfathered at migration time and must always
    # be present; other disciplines (e.g. ATH) may legitimately be added
    # later via the watch-folder workflow, so this isn't an exact-match
    # check against Rules/SYOG26's live discipline list.
    assert "ARC" in pack.disciplines


def test_real_gen_doc_extracts_the_same_venue_pattern_as_the_hand_rule():
    # Regression check called out in the design spec: the heuristic parser,
    # run against the real GEN doc in Rules/SYOG26/, should surface a
    # code_membership Venue/VENUE draft — the same real-world pattern
    # GEN_VENUE_CODE already encodes by hand.
    text = gen_markdown()
    drafts = extract_draft_rules(text, discipline=None, source_name="ODF_GEN.md")
    venue_drafts = [d for d in drafts if d.id == "GEN_VENUE_CODE"]
    assert venue_drafts and venue_drafts[0].params == {"codeset": "VENUE"}


def test_generic_rules_moved_to_core():
    pack = build_ruleset_pack(RULES_ROOT)
    pack_ids = {r.id for r in pack.rules}
    assert not {"GEN_ITEMNUM_INT", "GEN_IFRANK_NODASH", "GEN_NO_EMPTY_ATTRS",
                "GEN_VERSION_POSINT"} & pack_ids


def test_moved_checks_still_fire_from_core():
    from odf_validator.pipeline.orchestrator import Pipeline
    pack = build_ruleset_pack(RULES_ROOT)
    xml = (b'<OdfBody CompetitionCode="SYOG2026" DocumentCode="ARC" '
           b'DocumentType="DT_RESULT" Version="1" Date="d" Time="t" '
           b'LogicalDate="d" FeedFlag="P" Source="S" Organisation="">'
           b'<Competition><Discipline Code="ARC"/></Competition></OdfBody>')
    res = Pipeline().run(xml, pack)
    assert any(f.rule_id == "CORE_NO_EMPTY_ATTRS" for f in res.findings)
