"""A rule whose codeset cannot be found must not stay active.

Before this, builder.py reported "codeset 'X' is not provided by this pack's
code tables; the rule will never fire" and then kept the rule in the pack.
29 rules were in that state after the 2026-09-11 import. An active rule that
can never fire is worse than a load error: code_membership skips silently
when the table is missing, so every message it touches is reported as
conforming on that attribute.

Two outcomes are wanted, and they are different:
  * the DD's spelling differs from the workbook's only in separators or case
    (WINDDIRECTION vs WIND_DIRECTION, DISCIPLINEFUNCTION vs
    DISCIPLINE_FUNCTION) -- resolve it and let the rule run;
  * the codeset does not exist under any spelling -- drop the rule and say
    so. That covers DISCIPLINECLASS and WEATHER_REGION, which have no sheet
    at all, AND SHEDULESTATUS, which is a MISSPELLING of SCHEDULESTATUS
    rather than a separator difference. Normalisation must not paper over a
    missing letter: that would be guessing which codes a rule enforces. The
    hand-curated GEN rule already spells it correctly and covers
    @SessionStatus globally, so dropping the discipline copies costs no
    coverage.
"""
from __future__ import annotations
from pathlib import Path

from odf_validator.ingestion.builder import build_ruleset_pack

CODES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Codesets>
  <Codeset name="WIND_DIRECTION">
    <Code id="N" ENG_Description="North"/>
    <Code id="S" ENG_Description="South"/>
  </Codeset>
  <Codeset name="SCHEDULESTATUS">
    <Code id="SCHEDULED" ENG_Description="Scheduled"/>
  </Codeset>
  <Codeset name="DISCIPLINE_FUNCTION">
    <Code id="COACH" ENG_Description="Coach"/>
  </Codeset>
</Codesets>
"""

RULES_YAML = """\
- id: ATH_WIND_DIRECTION_CODE
  applies_to: {}
  primitive: code_membership
  target: './/*[@Wind_Direction]'
  attribute: Wind_Direction
  params: {codeset: WINDDIRECTION}
  severity: warning
  scope: message
  source_ref: 'ODF_ATH_Data_Dictionary.pdf line 2663: Wind direction'
  status: active
- id: ATH_SESSIONSTATUS_CODE
  applies_to: {}
  primitive: code_membership
  target: './/*[@SessionStatus]'
  attribute: SessionStatus
  params: {codeset: SHEDULESTATUS}
  severity: warning
  scope: message
  source_ref: 'ODF_ATH_Data_Dictionary.pdf line 379: session status'
  status: active
- id: ATH_MAINFUNCTIONID_CODE
  applies_to: {}
  primitive: code_membership
  target: './/*[@MainFunctionId]'
  attribute: MainFunctionId
  params: {codeset: DISCIPLINEFUNCTION}
  severity: warning
  scope: message
  source_ref: 'ODF_ATH_Data_Dictionary.pdf line 625: Main function'
  status: active
- id: ATH_CLASS_CODE
  applies_to: {}
  primitive: code_membership
  target: './/*[@Class]'
  attribute: Class
  params: {codeset: DISCIPLINECLASS}
  severity: warning
  scope: message
  source_ref: 'ODF_ATH_Data_Dictionary.pdf line 580: sport class'
  status: active
"""


def _ruleset(tmp_path: Path) -> Path:
    root = tmp_path / "TESTSET"
    (root / "codes").mkdir(parents=True)
    (root / "codes" / "codes.xml").write_text(CODES_XML, encoding="utf-8")
    (root / "rules").mkdir()
    (root / "rules" / "ath.yaml").write_text(RULES_YAML, encoding="utf-8")
    (root / "pack.yaml").write_text('version: "test"\n', encoding="utf-8")
    return root


def test_a_dd_spelling_of_a_real_codeset_stays_active(tmp_path):
    pack = build_ruleset_pack(_ruleset(tmp_path))

    ids = {r.id for r in pack.rules}
    assert "ATH_WIND_DIRECTION_CODE" in ids, (
        "WINDDIRECTION is the DD's spelling of the workbook's WIND_DIRECTION; "
        "the rule must run, not be dropped")
    assert "ATH_MAINFUNCTIONID_CODE" in ids, (
        "DISCIPLINEFUNCTION is the DD's spelling of DISCIPLINE_FUNCTION")
    assert not [e for e in pack.report.errors
                if "WINDDIRECTION" in e or "DISCIPLINEFUNCTION" in e], (
        f"a resolvable spelling is not an error: {pack.report.errors}")


def test_a_misspelt_codeset_is_dropped_rather_than_guessed(tmp_path):
    """SHEDULESTATUS is one letter short of SCHEDULESTATUS. Matching it would
    mean inferring which table a rule meant from a near-miss; the rule is
    dropped and reported instead, and @SessionStatus stays covered by the
    hand-corrected GEN rule."""
    pack = build_ruleset_pack(_ruleset(tmp_path))

    assert "ATH_SESSIONSTATUS_CODE" not in {r.id for r in pack.rules}
    assert any("ATH_SESSIONSTATUS_CODE" in e and "SHEDULESTATUS" in e
               for e in pack.report.errors), pack.report.errors


def test_the_rule_can_actually_find_its_table_at_runtime(tmp_path):
    """The loader's check and the runtime lookup must agree -- passing the
    load and then finding no table is the exact failure being fixed."""
    pack = build_ruleset_pack(_ruleset(tmp_path))
    rule = next(r for r in pack.rules if r.id == "ATH_WIND_DIRECTION_CODE")

    table = pack.codes.table(rule.params["codeset"])

    assert table is not None and table.name == "WIND_DIRECTION"


def test_a_codeset_that_exists_under_no_spelling_drops_the_rule(tmp_path):
    pack = build_ruleset_pack(_ruleset(tmp_path))

    assert "ATH_CLASS_CODE" not in {r.id for r in pack.rules}, (
        "a rule that can never fire must not be left active, reporting a "
        "pass on an attribute nobody is checking")
    assert any("ATH_CLASS_CODE" in e and "DISCIPLINECLASS" in e
               for e in pack.report.errors), pack.report.errors
    assert any("dropped" in e for e in pack.report.errors), (
        f"the error must say the rule was dropped, not that it 'will never "
        f"fire' -- it no longer exists: {pack.report.errors}")


def test_a_pack_with_no_code_tables_keeps_its_rules(tmp_path):
    """Dropping is for a rule whose codeset is missing from tables the pack
    DOES have. A pack that has loaded no Common Codes at all -- a scaffold,
    or a ruleset mid-setup before the first import -- cannot judge any
    codeset name, and deleting every code_membership rule from the active set
    there would report the operator's authored rules as simply absent."""
    root = tmp_path / "NOCODES"
    (root / "rules").mkdir(parents=True)
    (root / "rules" / "ath.yaml").write_text(RULES_YAML, encoding="utf-8")
    (root / "pack.yaml").write_text('version: "test"\n', encoding="utf-8")

    pack = build_ruleset_pack(root)

    assert {r.id for r in pack.rules} == {"ATH_WIND_DIRECTION_CODE",
                                          "ATH_SESSIONSTATUS_CODE",
                                          "ATH_MAINFUNCTIONID_CODE",
                                          "ATH_CLASS_CODE"}
    assert any("no code tables" in n.lower()
               for n in pack.report.codes_unavailable), (
        f"silence here would look like a healthy pack: "
        f"{pack.report.codes_unavailable}")
    # The other half, and the reason this moved off `errors`: app.js renders
    # that list as "N rule(s) failed to load". Every rule above loaded. A
    # freshly downloaded copy of the public tree is in exactly this state and
    # opened with "54 rule(s) failed to load" beside "89 rules active".
    assert pack.report.errors == [], pack.report.errors


# The dedup key freezes the whole params dict (see rules/loader._semantic_key),
# so two spellings of one codeset are two different checks as far as it is
# concerned. Left alone, the GEN rule and its discipline copy would both fire
# on the same attribute -- the double-firing the dedup channel exists to stop.
# Canonicalising the name therefore has to happen BEFORE the dedup, not after.

TWO_SPELLINGS_YAML = """\
- id: GEN_WIND_DIRECTION_CODE
  applies_to: {}
  primitive: code_membership
  target: './/*[@Wind_Direction]'
  attribute: Wind_Direction
  params: {codeset: WIND_DIRECTION}
  severity: warning
  scope: message
  source_ref: 'GEN DD: wind direction'
  status: active
- id: ATH_WIND_DIRECTION_CODE
  applies_to: {disciplines: [ATH]}
  primitive: code_membership
  target: './/*[@Wind_Direction]'
  attribute: Wind_Direction
  params: {codeset: WINDDIRECTION}
  severity: warning
  scope: message
  source_ref: 'ATH DD: wind direction'
  status: active
"""


def test_two_spellings_of_one_codeset_do_not_double_fire(tmp_path):
    root = tmp_path / "TESTSET"
    (root / "codes").mkdir(parents=True)
    (root / "codes" / "codes.xml").write_text(CODES_XML, encoding="utf-8")
    (root / "rules").mkdir()
    (root / "rules" / "wind.yaml").write_text(TWO_SPELLINGS_YAML,
                                              encoding="utf-8")
    (root / "pack.yaml").write_text('version: "test"\n', encoding="utf-8")

    pack = build_ruleset_pack(root)

    ids = {r.id for r in pack.rules}
    assert "GEN_WIND_DIRECTION_CODE" in ids, "the broader rule is the keeper"
    assert "ATH_WIND_DIRECTION_CODE" not in ids, (
        "the discipline copy checks the same table under the DD's spelling; "
        "keeping both means two warnings for one bad value")
    assert any("ATH_WIND_DIRECTION_CODE" in n for n in pack.report.deduped), (
        f"the drop belongs in the deduped channel, not errors: "
        f"{pack.report.deduped}")


# A dropped rule must not leave a scar. _specialisation_key is
# (primitive, target, attribute) with params deliberately excluded, so a
# discipline rule whose codeset is unresolvable still counts as specialising
# the GEN rule and stands it down for that discipline -- and is then dropped.
# Net effect: the attribute is checked by nothing at all in that discipline.
# That is how the 13 SHEDULESTATUS rules left @SessionStatus unchecked in 13
# disciplines while GEN_SESSIONSTATUS_CODE, correctly spelt, sat right there.

SHADOW_YAML = """\
- id: GEN_SESSIONSTATUS_CODE
  applies_to: {}
  primitive: code_membership
  target: './/*[@SessionStatus]'
  attribute: SessionStatus
  params: {codeset: SCHEDULESTATUS}
  severity: warning
  scope: message
  source_ref: 'GEN DD: session status (spelling corrected by hand)'
  status: active
- id: ATH_SESSIONSTATUS_CODE
  applies_to: {disciplines: [ATH]}
  primitive: code_membership
  target: './/*[@SessionStatus]'
  attribute: SessionStatus
  params: {codeset: SHEDULESTATUS}
  severity: warning
  scope: message
  source_ref: 'ODF_ATH_Data_Dictionary.pdf line 379: session status'
  status: active
"""


def _shadow_ruleset(tmp_path: Path) -> Path:
    root = tmp_path / "TESTSET"
    (root / "codes").mkdir(parents=True)
    (root / "codes" / "codes.xml").write_text(CODES_XML, encoding="utf-8")
    (root / "rules").mkdir()
    (root / "rules" / "status.yaml").write_text(SHADOW_YAML, encoding="utf-8")
    (root / "pack.yaml").write_text('version: "test"\n', encoding="utf-8")
    return root


def test_a_dropped_rule_does_not_stand_the_generic_rule_down(tmp_path):
    pack = build_ruleset_pack(_shadow_ruleset(tmp_path))

    assert "ATH_SESSIONSTATUS_CODE" not in {r.id for r in pack.rules}
    gen = next(r for r in pack.rules if r.id == "GEN_SESSIONSTATUS_CODE")
    assert "ATH" not in gen.applies_to.exclude_disciplines, (
        "the GEN rule was stood down for ATH by a rule that was then "
        "dropped, so @SessionStatus is now checked by nothing in ATH")
    assert not [n for n in pack.report.specialised
                if "ATH_SESSIONSTATUS_CODE" in n], (
        f"a dropped rule cannot specialise anything: "
        f"{pack.report.specialised}")
