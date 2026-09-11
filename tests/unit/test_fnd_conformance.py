"""Regressions found while checking the rule set against the Foundation
Principles. Each test pins a place where a rule contradicted the spec.

Source of truth: ODF R-SOG-2024 FND V2.3 APP.

Covers:
- DocumentCode is only an RSC for RSC-bearing message types. FND 3.3.2:
  "DocumentCode can have different values depending on the nature of the
  message ... the ID of an athlete (for biographies), sequential numbers
  (for background imports)". OWG2026-GEN defines the four DT_BIO_*_IMP
  messages as S(20) with no leading zeros (lines 16508/17457/17985/18248)
  and DT_NEWS_IMP as a free S(34) identifier (line 19364).
- FND 10.3 allows the dot inside an RSC: "Allow characters are A ... Z,
  0...9 and the special characters of dot and dash."
- FND 3.1 *requires* a valueless mandatory attribute to be sent empty;
  6.7 only makes omission a SHOULD. Empty attributes are therefore a
  warning, never an error.
- FND 3.3.2 / 3.4.2 -- header @Time is hhmmssfff.
- The five *_DOCUMENTSUBCODE_POSINT rules targeted `.//*[@DocumentSubcode]`,
  which lxml's findall never matches because DocumentSubcode exists only on
  the root OdfBody. They must target `.` and carry the doc_types their
  source document actually scopes them to.
- FND 10.3 -- the 34-char RSC is five right-padded components and the dash
  "is used as a filler"; no data may follow a filler inside a component.
"""
from pathlib import Path

from lxml import etree

from odf_validator.ingestion.builder import build_ruleset_pack
from odf_validator.pipeline.orchestrator import Pipeline
from odf_validator.rules.core import load_core_rules
from odf_validator.rules.primitives import PRIMITIVES
from odf_validator.rules.defs_model import RuleDef, AppliesTo
from odf_validator.model import Severity, Scope
from tests.conftest import needs_populated_ruleset

PACK = build_ruleset_pack(Path("Rules/SYOG26"))
CORE = {r.id: r for r in load_core_rules()}
RULES = {r.id: r for r in PACK.rules}
PIPE = Pipeline()

RSC = "ATHM100M--------------FNL-0001----"


def _msg(doc_type="DT_RESULT", doc_code=RSC, subcode=None, time="120000000",
         body='<Result SortOrder="1"><Competitor Code="1" Type="A" '
              'Organisation="SUI"/></Result>'):
    sub = f'DocumentSubcode="{subcode}" ' if subcode is not None else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<OdfBody CompetitionCode="SYOG2026" DocumentCode="{doc_code}" {sub}'
        f'DocumentType="{doc_type}" Version="1" FeedFlag="P" Date="2026-01-10" '
        f'Time="{time}" LogicalDate="2026-01-10" Source="ATHOLY1">\n'
        f' <Competition Gen="1" Codes="1">{body}</Competition>\n'
        '</OdfBody>'
    ).encode("utf-8")


def _ids(xml, severity=None):
    findings = PIPE.run(xml, PACK).findings
    if severity is not None:
        findings = [f for f in findings if f.severity == severity]
    return [f.rule_id for f in findings]


def _run_primitive(rule, xml, registry=None):
    return PRIMITIVES[rule.primitive](etree.fromstring(xml), rule, registry, None)


# --------------------------------------------------------------------------
# baseline
# --------------------------------------------------------------------------

@needs_populated_ruleset
def test_valid_result_message_is_clean():
    """Guard: the fixture used by every other test must produce no findings."""
    assert _ids(_msg()) == []


# --------------------------------------------------------------------------
# DocumentCode is not always an RSC
# --------------------------------------------------------------------------

def test_biography_import_external_id_is_accepted():
    """FND 3.3.2 / GEN 16508: DT_BIO_PAR_IMP DocumentCode is the participant's
    S(20) external ID (prefixed A/C/O), not a 34-character RSC."""
    for dt in ("DT_BIO_PAR_IMP", "DT_BIO_TEA_IMP",
               "DT_BIO_NOC_IMP", "DT_BIO_HOR_IMP"):
        ids = _ids(_msg(doc_type=dt, doc_code="A1234567", body=""))
        assert "CORE_DOCCODE_RSC_FORMAT" not in ids, dt


def test_biography_import_rejects_leading_zero_and_overlong_id():
    """GEN 16508: 'S(20) with no leading zeros'."""
    assert "CORE_DOCCODE_EXTERNAL_ID" in _ids(
        _msg(doc_type="DT_BIO_PAR_IMP", doc_code="0123456", body=""))
    assert "CORE_DOCCODE_EXTERNAL_ID" in _ids(
        _msg(doc_type="DT_BIO_PAR_IMP", doc_code="A" * 21, body=""))


def test_news_import_free_identifier_is_accepted():
    """GEN 19364: DT_NEWS_IMP DocumentCode is a free S(34) news identifier."""
    ids = _ids(_msg(doc_type="DT_NEWS_IMP", doc_code="FQ-2026-000123", body=""))
    assert "CORE_DOCCODE_RSC_FORMAT" not in ids


def test_rsc_still_enforced_on_results_messages():
    """The exemption must not punch a hole in the normal case."""
    assert "CORE_DOCCODE_RSC_FORMAT" in _ids(_msg(doc_code="TOO-SHORT"))
    assert "CORE_DOCCODE_RSC_FORMAT" in _ids(_msg(doc_code=RSC.lower()))


def test_rsc_rule_excludes_only_documented_import_types():
    """Fail-closed: a newly added DocumentType must inherit the RSC check."""
    excluded = set(CORE["CORE_DOCCODE_RSC_FORMAT"].applies_to.exclude_doc_types)
    assert excluded == {"DT_BIO_PAR_IMP", "DT_BIO_TEA_IMP", "DT_BIO_NOC_IMP",
                        "DT_BIO_HOR_IMP", "DT_NEWS_IMP"}


# --------------------------------------------------------------------------
# the dot is a legal RSC character
# --------------------------------------------------------------------------

@needs_populated_ruleset
def test_dot_is_allowed_inside_an_rsc():
    """FND 10.3: 'Allow characters are A ... Z, 0...9 and the special
    characters of dot and dash.'"""
    assert _ids(_msg(doc_code="SWMM100.5M------------FNL-0001----")) == []


def test_characters_outside_the_documented_set_are_still_rejected():
    assert "CORE_DOCCODE_RSC_FORMAT" in _ids(
        _msg(doc_code="ATHM100M_-------------FNL-0001----"))


# --------------------------------------------------------------------------
# empty attributes are a warning, not an error
# --------------------------------------------------------------------------

def test_empty_attribute_is_a_warning_not_an_error():
    """FND 3.1: 'Mandatory attributes must always be sent. If they do not have
    any value then they must be sent empty (Attribute="")'."""
    rule = CORE["CORE_NO_EMPTY_ATTRS"]
    assert rule.severity is Severity.WARNING

    xml = _msg(body='<Result SortOrder="1" IRM=""><Competitor Code="1" '
                    'Type="A" Organisation="SUI"/></Result>')
    errors = _ids(xml, severity=Severity.ERROR)
    assert "CORE_NO_EMPTY_ATTRS" not in errors
    assert "CORE_NO_EMPTY_ATTRS" in _ids(xml, severity=Severity.WARNING)


def test_required_envelope_attributes_are_still_errors_when_empty():
    """3.1 permits empty values, but CORE_ENVELOPE_REQUIRED covers the case
    where a *required* attribute carries no value -- that stays an error."""
    assert "CORE_ENVELOPE_REQUIRED" in _ids(_msg(time=""), severity=Severity.ERROR)


# --------------------------------------------------------------------------
# header @Time is hhmmssfff
# --------------------------------------------------------------------------

@needs_populated_ruleset
def test_header_time_must_be_hhmmssfff():
    """FND 3.4.2: Time = hhmmssfff, 'All formatted with leading and trailing
    zeros'. Previously bodyType/@Time used an unrestricted string alias."""
    assert _ids(_msg(time="120000000")) == []
    for bad in ("12:00:00", "abc", "12000000"):
        assert "XSD_INVALID" in _ids(_msg(time=bad)), bad


# --------------------------------------------------------------------------
# the DocumentSubcode rules must actually fire
# --------------------------------------------------------------------------

def test_documentsubcode_rules_target_the_root_element():
    """DocumentSubcode exists only on OdfBody, and findall('.//*') excludes the
    context node, so './/*[@DocumentSubcode]' could never match."""
    subcode_rules = [r for r in PACK.rules if "DOCUMENTSUBCODE" in r.id]
    assert subcode_rules, "the DocumentSubcode rules disappeared"
    for r in subcode_rules:
        assert r.target == ".", r.id
        assert r.applies_to.doc_types, f"{r.id} must be scoped to a DocumentType"


def test_documentsubcode_positive_integer_now_fires():
    """GEN 9176 (DT_PRESSPHOTOFINISH_LK) and the ATH/RCB/TRI dictionaries
    (DT_IMAGE) define DocumentSubcode as a positive integer."""
    ids = _ids(_msg(doc_type="DT_PRESSPHOTOFINISH_LK", subcode="abc", body=""))
    assert any("DOCUMENTSUBCODE" in i for i in ids)
    ids = _ids(_msg(doc_type="DT_PRESSPHOTOFINISH_LK", subcode="7", body=""))
    assert not any("DOCUMENTSUBCODE" in i for i in ids)


def test_documentsubcode_not_flagged_where_the_docs_allow_a_code():
    """GEN 20371: DT_SCHED_RES_NOC carries DocumentSubcode = CC@NOC, and
    GEN 16511: DT_BIO_PAR_IMP carries ATH/COA/OFF. Neither is numeric, so the
    positive-integer rule must not reach them."""
    ids = _ids(_msg(doc_type="DT_SCHED_RES_NOC",
                    doc_code="GEN-------------------DAY-01------",
                    subcode="SUI", body=""))
    assert not any("DOCUMENTSUBCODE" in i for i in ids)
    ids = _ids(_msg(doc_type="DT_BIO_PAR_IMP", doc_code="A1234567",
                    subcode="ATH", body=""))
    assert not any("DOCUMENTSUBCODE" in i for i in ids)


# --------------------------------------------------------------------------
# RSC component filler integrity
# --------------------------------------------------------------------------

def _rsc_rule(**params):
    p = {"widths": [3, 1, 8, 10, 4, 8], "filler": "-"}
    p.update(params)
    return RuleDef("R", AppliesTo([], [], []), "rsc_components", ".",
                   "DocumentCode", p, Severity.WARNING, Scope.MESSAGE, "src")


def test_rsc_components_accepts_documented_examples():
    """Real RSCs from the FND and the OWG2026 GEN document."""
    rule = _rsc_rule()
    for good in (
        "ATHM100M--------------FNL-0001----",   # FND 3.3.2 sample
        "GLFWSTROKE------------FNL-000101--",   # GEN 9143
        "ALPGGEN---------------OTHRXYZ-----",   # GEN 15567
        "GEN-------------------DAY-01------",   # GEN 20369, DT_SCHED_RES_NOC
        "ATH-------------------------------",   # discipline-level RSC
        "SWMM100.5M------------FNL-0001----",   # dot is legal
        "ATH-100M--------------FNL-0001----",   # a lone filler fills the gender
    ):
        xml = f'<OdfBody DocumentCode="{good}"/>'
        assert _run_primitive(rule, xml) == [], good


def test_rsc_components_flags_data_after_a_filler():
    """FND 10.3: 'The dash character "-" is used as a filler' and 'Apply right
    padding with the filler character in any part of the RSC'."""
    rule = _rsc_rule()
    for bad in (
        "ATHM---100M-----------FNL-0001----",   # data after filler in EventType
        "A-HM100M--------------FNL-0001----",   # filler inside the DDD triplet
        "ATHM100M--------------FNL--001----",   # filler then data in the Unit
        "ATHM100M----------M---FNL-0001----",   # data after filler in Modifier
        "ATHM100M---------------NL-0001----",   # filler then data in the Phase
    ):
        xml = f'<OdfBody DocumentCode="{bad}"/>'
        assert len(_run_primitive(rule, xml)) >= 1, bad


def test_rsc_components_ignores_wrong_length_values():
    """Length is CORE_DOCCODE_RSC_FORMAT's job; do not double-report."""
    rule = _rsc_rule()
    assert _run_primitive(rule, '<OdfBody DocumentCode="SHORT"/>') == []


def test_rsc_filler_rule_is_wired_in_as_a_core_warning():
    rule = CORE["CORE_RSC_FILLER"]
    assert rule.severity is Severity.WARNING
    assert rule.primitive == "rsc_components"
    ids = _ids(_msg(doc_code="ATHM---100M-----------FNL-0001----"))
    assert "CORE_RSC_FILLER" in ids


def test_rsc_filler_rule_skips_non_rsc_document_types():
    """The exemption list is shared with CORE_DOCCODE_RSC_FORMAT."""
    ids = _ids(_msg(doc_type="DT_BIO_PAR_IMP", doc_code="A1234567", body=""))
    assert "CORE_RSC_FILLER" not in ids


# --------------------------------------------------------------------------
# pack health
# --------------------------------------------------------------------------

@needs_populated_ruleset
def test_pack_still_loads_without_errors():
    assert PACK.report.errors == []
