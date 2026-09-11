"""Defense-in-depth: a misnamed child of <ExtendedInfo> (e.g. <ExtensionElem>
instead of the documented <Extension>) must be reported by a pack rule even
when the XSD masks it.

Background (this repo, 2026-07-20 BKG messageset audit): libxml2 validates
extendedInfosType as an ordered sequence. When <ExtendedInfo> appears after
SportDescription/VenueDescription (an ordering defect), libxml2 rejects the
<ExtendedInfo> element itself and never descends into its content, so a
misnamed child like <ExtensionElem> produces NO schema error. The independent
audit caught 8 such files; the validator did not. This rule closes that gap.

Reference: ODF GEN -- Competition/ExtendedInfos/ExtendedInfo/Extension (0,N):
the only permitted child element of <ExtendedInfo> is <Extension>.
"""
from pathlib import Path
from lxml import etree

from odf_validator.rules.primitives import PRIMITIVES
from odf_validator.rules.defs_model import RuleDef, AppliesTo
from odf_validator.model import Severity, Scope
from odf_validator.pipeline.orchestrator import Pipeline
from odf_validator.ingestion.builder import build_ruleset_pack


def _rule():
    return RuleDef("GEN_EXTENDEDINFO_CHILD_TAG", AppliesTo([], [], []),
                   "allowed_child_tags", ".//ExtendedInfo", None,
                   {"allowed": ["Extension"]}, Severity.ERROR, Scope.MESSAGE, "src")


def _run(rule, xml):
    root = etree.fromstring(xml.encode())
    fn = PRIMITIVES.get(rule.primitive)
    assert fn is not None, f"primitive '{rule.primitive}' is not registered"
    return fn(root, rule, None, None)


# ---- unit: the primitive -------------------------------------------------

def test_flags_misnamed_child_extensionelem():
    xml = ('<OdfBody><Competition><ExtendedInfos>'
           '<ExtendedInfo Type="UI" Code="STARTERS" Value="12">'
           '<ExtensionElem Code="COMPLETE" Value="0"/>'
           '</ExtendedInfo>'
           '</ExtendedInfos></Competition></OdfBody>')
    findings = _run(_rule(), xml)
    assert len(findings) == 1, f"expected 1 finding, got {len(findings)}"
    assert "ExtensionElem" in findings[0].message
    assert findings[0].rule_id == "GEN_EXTENDEDINFO_CHILD_TAG"


def test_allows_correct_child_extension():
    xml = ('<OdfBody><Competition><ExtendedInfos>'
           '<ExtendedInfo Type="UI" Code="STARTERS" Value="12">'
           '<Extension Code="COMPLETE" Value="0"/>'
           '</ExtendedInfo>'
           '</ExtendedInfos></Competition></OdfBody>')
    assert _run(_rule(), xml) == []


# ---- integration: fires through the Pipeline despite XSD ordering mask ----

def test_pipeline_reports_child_tag_even_when_xsd_masks_it():
    """Messageset shape: ExtendedInfo placed AFTER SportDescription/Venue
    (so the XSD rejects the ExtendedInfo and never checks its child). The pack
    rule must still surface the misnamed <ExtensionElem>."""
    xml = (
        '<OdfBody CompetitionCode="SYOG2026-ITL" '
        'DocumentCode="BKGWINDIVID-----------QUAL000100--" '
        'DocumentType="DT_RESULT" Version="1" FeedFlag="T" Date="2026-07-20" '
        'Time="1" LogicalDate="2026-07-20" Source="X" ResultStatus="LIVE">'
        '<Competition Gen="G" Codes="C"><ExtendedInfos>'
        '<SportDescription DisciplineName="Breaking"/>'
        '<VenueDescription Venue="CTO" VenueName="X"/>'
        '<ExtendedInfo Type="UI" Code="STARTERS" Value="12">'
        '<ExtensionElem Code="COMPLETE" Value="0"/></ExtendedInfo>'
        '</ExtendedInfos>'
        '<Result StartOrder="1" SortOrder="1" ResultType="POINTS" Rank="1" '
        'Result="1"><Competitor Type="A" Code="1" Organisation="LTU"><Composition>'
        '<Athlete Code="1" Order="1"><Description FamilyName="x" Gender="F" '
        'Organisation="LTU"/></Athlete></Composition></Competitor></Result>'
        '</Competition></OdfBody>')
    pack = build_ruleset_pack(Path("Rules/SYOG26"))
    result = Pipeline().run(xml.encode(), pack)
    ids = [f.rule_id for f in result.findings]
    assert "GEN_EXTENDEDINFO_CHILD_TAG" in ids, (
        "defense-in-depth rule did not fire; ids=" + ", ".join(sorted(set(ids))))


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests)-failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
