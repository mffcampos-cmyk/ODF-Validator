"""A second batch of regressions found while reviewing rule scoping against
the source documents. Each test pins a specific misfire that reached a real
run.

Covers:
- RECORD_TYPE codeset keyed by its 'Recordtype' column (see test_code_excel).
- Semantic dedup of discipline rules that duplicate global GEN rules
  (see test_rule_loader).
- SWM_NAME_CODE validates @Name as a RECORD *description*, not a code id
  (the same description-vs-code confusion as batch 1, missed for @Name).
- TBD is a documented legal placeholder for @Venue / @Location
  (GEN doc lines 20548 / 20551: "Can use TBD if the Venue is not known yet").
  A code_membership `allow` list accepts such sentinels without a lookup.
"""
from pathlib import Path
from lxml import etree

from odf_validator.rules.primitives import PRIMITIVES
from odf_validator.rules.defs_model import RuleDef, AppliesTo
from odf_validator.codes.tables import CodeRegistry, CodeTable, CodeRow
from odf_validator.model import Severity, Scope
from odf_validator.ingestion.builder import build_ruleset_pack
from tests.conftest import needs_populated_ruleset

PACK = build_ruleset_pack(Path("Rules/SYOG26"))
RULES = {r.id: r for r in PACK.rules}


def _rule(primitive, target, attribute, params):
    return RuleDef("R", AppliesTo([], [], []), primitive, target, attribute,
                   params, Severity.WARNING, Scope.MESSAGE, "src")


def _venue_registry():
    reg = CodeRegistry()
    t = CodeTable("VENUE")
    t.add_row(CodeRow(id="CAD", fields={"ENG_Description": "Aquatic Centre"}))
    reg.add_table(t, "test")
    return reg


def _run(r, xml, registry):
    return PRIMITIVES[r.primitive](etree.fromstring(xml), r, registry, None)


# ---- TBD placeholder allow-list ------------------------------------------

def test_code_membership_allow_accepts_listed_placeholder():
    r = _rule("code_membership", ".//*[@Venue]", "Venue",
              {"codeset": "VENUE", "allow": ["TBD"]})
    findings = _run(r, '<OdfBody><Session Venue="TBD"/></OdfBody>',
                    _venue_registry())
    assert findings == []


def test_code_membership_allow_still_flags_other_invalid_codes():
    r = _rule("code_membership", ".//*[@Venue]", "Venue",
              {"codeset": "VENUE", "allow": ["TBD"]})
    findings = _run(r, '<OdfBody><Session Venue="ZZZ"/></OdfBody>',
                    _venue_registry())
    assert len(findings) == 1


def test_code_membership_without_allow_flags_tbd():
    # Regression guard: the allow-list is opt-in; absent it, TBD is still checked.
    r = _rule("code_membership", ".//*[@Venue]", "Venue", {"codeset": "VENUE"})
    findings = _run(r, '<OdfBody><Session Venue="TBD"/></OdfBody>',
                    _venue_registry())
    assert len(findings) == 1


def test_gen_venue_and_location_rules_allow_tbd():
    for rid in ("GEN_VENUE_CODE", "GEN_LOCATION_CODE"):
        assert rid in RULES, f"{rid} missing"
        assert "TBD" in (RULES[rid].params.get("allow") or []), \
            f"{rid} should allow the TBD placeholder"


def test_every_loaded_venue_or_location_rule_allows_tbd():
    # The `allow: [TBD]` fix was applied to the GEN rules only. The 25
    # per-discipline copies kept the un-allowed form, and were invisible because
    # the semantic dedup key ignored `params.allow` and let the GEN rule subsume
    # them. With the key made param-aware they load again -- and would flag a
    # legal TBD venue on every discipline. TBD is legal everywhere it is legal
    # in GEN, so every loaded rule over these codesets must carry the allow-list.
    # Only code-identity rules matter here. The paired description rules
    # (@VenueName against `field`) look the code up first and stay silent when
    # it is absent from the table, so TBD never reaches an assertion there.
    offenders = [r.id for r in PACK.rules
                 if r.primitive == "code_membership"
                 and r.params.get("codeset") in ("VENUE", "LOCATION")
                 and not r.params.get("field")
                 and "TBD" not in (r.params.get("allow") or [])]
    assert offenders == [], (
        f"{len(offenders)} VENUE/LOCATION rules would flag a legal TBD "
        f"placeholder: {offenders[:5]}...")


# ---- SWM_NAME_CODE is a description check --------------------------------

def test_swm_name_rule_uses_description_field_mode():
    assert "SWM_NAME_CODE" in RULES
    assert RULES["SWM_NAME_CODE"].params.get("field") == "ENG_Description"


def test_swm_name_accepts_valid_record_description():
    r = RULES["SWM_NAME_CODE"]
    xml = ("<OdfBody><Record><Description "
           "Name=\"Men's 50m Backstroke\"/></Record></OdfBody>")
    assert _run(r, xml, PACK.codes) == []


@needs_populated_ruleset
def test_swm_name_flags_unknown_record_description():
    r = RULES["SWM_NAME_CODE"]
    xml = ('<OdfBody><Record><Description '
           'Name="Not A Real Record"/></Record></OdfBody>')
    assert len(_run(r, xml, PACK.codes)) == 1
