"""Discipline scoping must work on real ODF messages.

In a conforming message Competition/Discipline/@Code is a full 34-character
RSC ("ARC" followed by 31 dashes). Rule YAML — and the DocumentCode fallback
in dispatch() — use the bare three letters. Before 2026-08-28 dispatch()
reported the RSC verbatim and rule_applies() compared it literally, so every
discipline-scoped rule was skipped on exactly the input the validator exists
to check, and every generic-rule stand-down was inert. Findings C1/C2.
"""
from lxml import etree

from odf_validator.dispatch import dispatch
from odf_validator.model import Scope, Severity
from odf_validator.rules.defs_model import AppliesTo, RuleDef
from odf_validator.rules.runner import rule_applies
from tests.conftest import needs_populated_ruleset

RSC = "ARC-------------------------------"          # 3 letters + 31 dashes = 34

RSC_XML = f"""<OdfBody CompetitionCode="SYOG2026" DocumentCode="ARCMTEAM-------"
 DocumentType="DT_RESULT" DocumentSubtype="START_LIST" Version="3"
 Date="2026-01-10" Time="100000000" LogicalDate="2026-01-10"
 FeedFlag="P" Source="ODF">
 <Competition><Discipline Code="{RSC}"/></Competition></OdfBody>""".encode()

SHORT_XML = RSC_XML.replace(RSC.encode(), b"ARC")

NO_DISCIPLINE_XML = b"""<OdfBody CompetitionCode="SYOG2026" DocumentCode="ARCMTEAM-------"
 DocumentType="DT_RESULT" Version="3" Date="2026-01-10" Time="100000000"
 LogicalDate="2026-01-10" FeedFlag="P" Source="ODF"><Competition/></OdfBody>"""


def _rule(rule_id, disciplines=(), exclude_disciplines=()):
    return RuleDef(rule_id,
                   AppliesTo([], [], list(disciplines), [],
                             list(exclude_disciplines)),
                   "set_filter", ".//Unit", "PhaseType", {},
                   Severity.ERROR, Scope.MESSAGE, "")


def test_rsc_is_normalised_to_three_letters():
    assert len(RSC) == 34
    assert dispatch(etree.fromstring(RSC_XML)).discipline == "ARC"


def test_all_three_spellings_agree():
    """RSC, short code and the DocumentCode fallback resolve identically."""
    assert (dispatch(etree.fromstring(RSC_XML)).discipline
            == dispatch(etree.fromstring(SHORT_XML)).discipline
            == dispatch(etree.fromstring(NO_DISCIPLINE_XML)).discipline
            == "ARC")


def test_discipline_scoped_rule_fires_on_an_rsc_message():
    info = dispatch(etree.fromstring(RSC_XML))
    assert rule_applies(_rule("ARC_ONLY", disciplines=["ARC"]), info)


def test_other_disciplines_rule_still_does_not_fire():
    info = dispatch(etree.fromstring(RSC_XML))
    assert not rule_applies(_rule("SWM_ONLY", disciplines=["SWM"]), info)


def test_generic_rule_stands_down_on_an_rsc_message():
    """exclude_disciplines is written by loader._specialise_by_discipline in
    three-letter form; it must carve out an RSC message too."""
    info = dispatch(etree.fromstring(RSC_XML))
    assert not rule_applies(_rule("GEN_X", exclude_disciplines=["ARC"]), info)


def test_missing_discipline_and_documentcode_yields_none():
    xml = b'<OdfBody DocumentType="DT_RESULT"><Competition/></OdfBody>'
    assert dispatch(etree.fromstring(xml)).discipline is None


def test_corpus_messages_use_canonical_rscs():
    """The corpus must look like production input.

    Every corpus message once used Code="ARC", which is not a member of the
    pack's DISCIPLINE codeset (all 33 entries are 34-char RSCs). That is why
    the suite could not see the scoping defect this module tests.
    """
    from pathlib import Path
    corpus = Path(__file__).resolve().parent.parent / "corpus"
    files = sorted(corpus.rglob("*.xml"))
    assert files, f"no corpus messages found under {corpus}"
    for xml_file in files:
        root = etree.fromstring(xml_file.read_bytes())
        for disc in root.findall("./Competition/Discipline"):
            code = disc.get("Code") or ""
            assert len(code) == 34, (
                f"{xml_file.name}: Discipline @Code is {len(code)} chars "
                f"({code!r}); corpus messages must carry a full RSC")


@needs_populated_ruleset
def test_a_short_discipline_code_is_still_invalid_content():
    """Scoping treats both spellings alike; content validation must not.

    dispatch() truncates the discipline for rule scoping. CORE_DISCIPLINE_CODE
    reads Competition/Discipline/@Code from the XML instead, so a short code is
    still a finding. If that rule were ever repointed at info.discipline, short
    codes would silently become valid input -- this test fails if that happens.
    """
    from pathlib import Path
    from odf_validator.ingestion.builder import build_ruleset_pack
    from odf_validator.pipeline.orchestrator import Pipeline

    repo_root = Path(__file__).resolve().parent.parent.parent
    pack = build_ruleset_pack(repo_root / "Rules" / "SYOG26")

    def ids(xml):
        return {f.rule_id for f in Pipeline().run(xml, pack).findings}

    assert "CORE_DISCIPLINE_CODE" in ids(SHORT_XML)
    assert "CORE_DISCIPLINE_CODE" not in ids(RSC_XML)
