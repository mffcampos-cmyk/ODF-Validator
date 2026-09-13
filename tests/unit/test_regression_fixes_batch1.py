"""Regressions found while reviewing the rule set against its source
documents. Each test pins a specific misfire that reached a real run.

Covers:
- Unknown codesets must be loud (pack-load error), and every shipped rule
  must resolve against the pack's code tables.
- *Name description attributes validated as ENG descriptions, not codes.
- TBD competitors are legal; Composition under a TBD competitor is not.
- The DocumentSubcode positive-integer check is scoped to the two doc types
  that define it (GEN 9176, 13433).
- Medal is 0..3 (SC@UnitMedalType@GEN) or a planned-medal count (#0).
- Fabricated/unbacked rules removed (GEN_O_CODE, ARC_AVGSPEED,
  ARC_PHASETYPE); IFRANK re-attributed to the observed defect that backs it,
  because it appears nowhere in the ODF GEN document it used to cite.
- The envelope rule checks the full required header; Version must be >= 1;
  ResultStatus is validated against CC@RESULTSTATUS.
"""
from pathlib import Path
from lxml import etree

from odf_validator.rules.primitives import PRIMITIVES
from odf_validator.rules.defs_model import RuleDef, AppliesTo
from odf_validator.rules.core import load_core_rules
from odf_validator.codes.tables import CodeRegistry, CodeTable, CodeRow
from odf_validator.model import Severity, Scope
from odf_validator.ingestion.builder import build_ruleset_pack
from tests.conftest import needs_populated_ruleset

PACK = build_ruleset_pack(Path("Rules/SYOG26"))
RULES = {r.id: r for r in PACK.rules}
CORE = {r.id: r for r in load_core_rules()}


def rule(primitive, target, attribute, params, severity=Severity.ERROR):
    return RuleDef("R", AppliesTo([], [], []), primitive, target, attribute,
                   params, severity, Scope.MESSAGE, "src")


def run(r, xml, registry=None):
    root = etree.fromstring(xml)
    return PRIMITIVES[r.primitive](root, r, registry, None)


def _venue_registry():
    reg = CodeRegistry()
    t = CodeTable("VENUE")
    t.add_row(CodeRow(id="PDP", fields={"ENG_Description": "Parc des Princes"}))
    t.add_row(CodeRow(id="STA", fields={"ENG_Description": "Stadium"}))
    reg.add_table(t, "test")
    return reg


# ---- unknown codesets are loud -------------------------------------------

def test_unknown_codeset_is_a_pack_load_error(tmp_path):
    """A rule naming a codeset the pack's tables do not provide: one rule
    wrong among many right, so it is named and dropped.

    The pack needs a code table for this to be the case under test. Without
    one, "unknown codeset" and "no tables to judge any codeset against" are
    the same state, and the second is the ordinary condition of a ruleset
    before its first import -- every code_membership rule inert, one cause,
    one remedy, reported as a single counted note rather than one line per
    rule (see test_codes_unavailable_channel.py). This fixture had no
    `codes/` at all and was pinning that case by accident; both messages
    read the same, so nothing showed it.
    """
    root = tmp_path / "PACKX"
    (root / "rules").mkdir(parents=True)
    (root / "codes").mkdir()
    (root / "codes" / "codes.xml").write_text(
        '<?xml version="1.0"?>\n'
        '<CommonCodes><Codeset name="VENUE">'
        '<Code id="PDP" ENG_Description="Parc des Princes"/>'
        '</Codeset></CommonCodes>', encoding="utf-8")
    (root / "rules" / "r.yaml").write_text(
        "- id: GEN_BAD\n"
        "  applies_to: {}\n"
        "  primitive: code_membership\n"
        "  target: './/*[@Venue]'\n"
        "  attribute: Venue\n"
        "  params: {codeset: NO_SUCH_SHEET}\n"
        "  severity: warning\n"
        "  scope: message\n"
        "  source_ref: 'x'\n")
    pack = build_ruleset_pack(root)
    assert any("GEN_BAD" in e and "NO_SUCH_SHEET" in e
               for e in pack.report.errors), pack.report.errors


@needs_populated_ruleset
def test_all_shipped_codesets_resolve():
    known = set(PACK.codes.names())
    bad = [(r.id, r.params.get("codeset")) for r in PACK.rules
           if r.params.get("codeset") and r.params["codeset"] not in known]
    assert bad == [], bad
    assert not any("codeset" in e for e in PACK.report.errors), \
        [e for e in PACK.report.errors if "codeset" in e]


# ---- description attributes ----------------------------------------------

def test_field_membership_accepts_valid_description():
    r = rule("code_membership", ".//*[@VenueName]", "VenueName",
             {"codeset": "VENUE", "field": "ENG_Description"})
    out = run(r, '<OdfBody><V VenueName="Parc des Princes"/></OdfBody>',
              _venue_registry())
    assert out == []


def test_field_membership_flags_code_sent_as_description():
    r = rule("code_membership", ".//*[@VenueName]", "VenueName",
             {"codeset": "VENUE", "field": "ENG_Description"})
    out = run(r, '<OdfBody><V VenueName="PDP"/></OdfBody>', _venue_registry())
    assert len(out) == 1


def test_field_membership_exact_match_when_code_attr_present():
    r = rule("code_membership", ".//*[@VenueName]", "VenueName",
             {"codeset": "VENUE", "field": "ENG_Description",
              "code_attr": "Venue"})
    # Wrong pairing: description of another venue.
    out = run(r, '<OdfBody><V Venue="PDP" VenueName="Stadium"/></OdfBody>',
              _venue_registry())
    assert len(out) == 1
    # Right pairing passes.
    out = run(r, '<OdfBody><V Venue="PDP" VenueName="Parc des Princes"/></OdfBody>',
              _venue_registry())
    assert out == []
    # code_attr absent on the node -> falls back to set membership.
    out = run(r, '<OdfBody><V VenueName="Stadium"/></OdfBody>', _venue_registry())
    assert out == []
    out = run(r, '<OdfBody><V VenueName="PDP"/></OdfBody>', _venue_registry())
    assert len(out) == 1


def test_gen_description_rules_use_field_mode():
    for rid, field in [("GEN_VENUENAME_CODE", "ENG_Description"),
                       ("GEN_LOCATIONNAME_CODE", "ENG_Description"),
                       ("GEN_DISCIPLINENAME_CODE", "ENG_Description"),
                       ("GEN_EVENTNAME_CODE", "ENG_Description"),
                       ("GEN_SUBEVENTNAME_CODE", "ENG_shortDescription"),
                       ("GEN_ORGANISATIONNAME_CODE", "ENG_longDescription"),
                       ("GEN_CLUSTERNAME_CODE", "ENG_Description"),
                       ("GEN_REPORTTYPENAME_CODE", "ENG_Description"),
                       ("GEN_CATEGORYNAME_CODE", "ENG_Description")]:
        assert rid in RULES, rid
        assert RULES[rid].params.get("field") == field, \
            (rid, RULES[rid].params)


# ---- TBD competitors ------------------------------------------------------

def test_tbd_competitor_rule_removed():
    assert "ARC_TBD_COMPETITOR" not in RULES


def test_tbd_competitor_with_composition_flagged():
    r = RULES["ARC_TBD_NO_COMPOSITION"]
    bad = ('<OdfBody><Competitor Code="TBD" Type="T">'
           '<Composition><Athlete Code="1"/></Composition>'
           '</Competitor></OdfBody>')
    assert len(run(r, bad)) == 1
    ok = '<OdfBody><Competitor Code="TBD" Type="T"/></OdfBody>'
    assert run(r, ok) == []
    ok2 = ('<OdfBody><Competitor Code="1234" Type="T">'
           '<Composition><Athlete Code="1"/></Composition>'
           '</Competitor></OdfBody>')
    assert run(r, ok2) == []


# ---- DocumentSubcode scoping / Medal range ---------------------------------

def test_documentsubcode_posint_scoped_to_defining_doc_types():
    r = RULES["GEN_DOCUMENTSUBCODE_POSINT"]
    assert set(r.applies_to.doc_types) == {"DT_PRESSPHOTOFINISH_LK",
                                           "DT_COMMUNICATION"}


def test_arc_documentsubcode_must_be_absent():
    r = RULES["ARC_DOCSUBCODE_ABSENT"]
    assert r.applies_to.disciplines == ["ARC"]
    bad = '<OdfBody DocumentCode="X" DocumentSubcode="1"/>'
    assert len(run(r, bad)) == 1
    ok = '<OdfBody DocumentCode="X"/>'
    assert run(r, ok) == []


def test_medal_accepts_zero_and_rejects_negative():
    r = RULES["ARC_MEDAL_INT"]
    assert run(r, '<OdfBody><Unit Medal="0"/></OdfBody>') == []
    assert run(r, '<OdfBody><Unit Medal="3"/></OdfBody>') == []
    assert len(run(r, '<OdfBody><Unit Medal="-1"/></OdfBody>')) == 1


# ---- unbacked rules removed / re-attributed --------------------------------

def test_fabricated_and_unbacked_rules_removed():
    for rid in ("GEN_O_CODE", "ARC_AVGSPEED", "ARC_PHASETYPE"):
        assert rid not in RULES, rid


def test_ifrank_source_cites_an_observed_defect_not_gen():
    r = CORE["CORE_IFRANK_NODASH"]
    # Must cite an observed defect, and must not claim ODF GEN as its source
    # (IFRANK appears nowhere in the GEN doc).
    assert "defect" in r.source_ref.lower() or "bug" in r.source_ref.lower()
    assert not r.source_ref.startswith("ODF GEN")


# ---- envelope, version, resultstatus ---------------------------------------

def test_envelope_requires_full_required_header():
    r = CORE["CORE_ENVELOPE_REQUIRED"]
    xml = ('<OdfBody CompetitionCode="SYOG2026" DocumentCode="%s" '
           'DocumentType="DT_RESULT" Version="1"/>' % ("ARC" + "-" * 31))
    missing = {f.message.split("@")[1].split(" ")[0] for f in run(r, xml)}
    assert {"FeedFlag", "Date", "Time", "LogicalDate", "Source"} <= missing


def test_version_zero_rejected():
    r = CORE["CORE_VERSION_POSINT"]
    xml = '<OdfBody Version="0"/>'
    assert len(run(r, xml)) == 1
    assert run(r, '<OdfBody Version="1"/>') == []


def test_resultstatus_membership_rule_exists():
    r = RULES["GEN_RESULTSTATUS_CODE"]
    assert r.params.get("codeset") == "RESULTSTATUS"
