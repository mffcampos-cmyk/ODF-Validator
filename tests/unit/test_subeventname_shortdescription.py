"""SubEventName is checked against ENG_shortDescription, not ENG_Description.

Every one of the 24 discipline Data Dictionaries specifies the source column
as `CC@EVENT_UNIT ENG ShortDescription`. The prose in the same row reads
"EventUnit ENG Description (not code)", and the rule derivation followed the
prose, so all 13 discipline `*_SUBEVENTNAME_CODE` rules compared against the
wrong column. GEN_SUBEVENTNAME_CODE was already correct.

Consequences of the old reading: a conforming feed sending the ShortDescription
would be rejected, and the finding text named an expected value the DD does not
ask for. Raised by an external review (46 occurrences in the
2026-08-31 WST run).
"""
from pathlib import Path

import pytest
import yaml
from tests.conftest import needs_populated_ruleset

RULES_ROOT = Path(__file__).resolve().parents[2] / "Rules" / "SYOG26"
DISCIPLINE_RULES = sorted(RULES_ROOT.glob("Disciplines/*/rules/*.yaml"))
GEN_RULES = sorted(RULES_ROOT.glob("rules/*.yaml"))


def _subeventname_rules(paths):
    for path in paths:
        for entry in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            if str(entry.get("id", "")).endswith("_SUBEVENTNAME_CODE"):
                yield path, entry


# SWM is a deliberate exception (owner decision 2026-09-01). Its DD row states
# both columns, like every other discipline's, but the SWM feed sends the
# Description form and the manual audit of 2026-08-12 accepted it; switching
# SWM would reintroduce ~370 warnings on a reading the DD itself contradicts.
# Pinned here so the exception cannot be silently removed OR silently spread.
DESCRIPTION_EXCEPTIONS = {"SWM"}


def test_every_subeventname_rule_uses_shortdescription():
    rules = list(_subeventname_rules(DISCIPLINE_RULES + GEN_RULES))
    assert rules, "no *_SUBEVENTNAME_CODE rules found"

    wrong = [(p.parent.parent.name, e["id"], e["params"].get("field"))
             for p, e in rules
             if p.parent.parent.name not in DESCRIPTION_EXCEPTIONS
             and e.get("params", {}).get("field") != "ENG_shortDescription"]

    assert wrong == [], (
        "these rules compare SubEventName against the wrong column; every "
        f"discipline DD says CC@EVENT_UNIT ENG ShortDescription: {wrong}")


def test_the_swm_exception_is_intact_and_documented():
    """The exception is a decision, not a leftover — it must stay explained.

    If someone later 'tidies' SWM into line with the other twelve, that is a
    reversal of an owner decision and should be a deliberate act, not a drive-by
    consistency fix. The reasoning lives in the rule's own source_ref so it
    travels with the rule.
    """
    swm = [e for p, e in _subeventname_rules(DISCIPLINE_RULES)
           if p.parent.parent.name == "SWM"]

    assert swm, "SWM has no SubEventName rule"
    assert swm[0]["params"]["field"] == "ENG_Description"
    ref = swm[0]["source_ref"]
    assert "SWM EXCEPTION" in ref

    # The regression guarded here is the exception decaying into a bare
    # "SWM EXCEPTION" label with no case behind it. This used to be pinned by
    # asserting the audit's date was still in the string, which was only ever a
    # proxy -- a date can survive while the argument around it is deleted, and
    # the argument can survive a date being dropped. Pin the argument instead:
    # what the feed actually sends, and what reverting would cost.
    assert "sends the Description form" in ref, (
        "the evidence for the exception -- that the SWM feed sends the "
        "Description form -- must survive with the rule")
    assert "~370 warnings" in ref, (
        "the cost of reverting the exception must survive with the rule")


def test_no_other_discipline_quietly_joins_the_exception():
    """Guards the exception from spreading by copy-paste."""
    using_description = {p.parent.parent.name
                         for p, e in _subeventname_rules(DISCIPLINE_RULES)
                         if e.get("params", {}).get("field") == "ENG_Description"}

    assert using_description == DESCRIPTION_EXCEPTIONS, (
        "only SWM may use ENG_Description; adding another needs an owner "
        f"decision recorded the same way. Found: {sorted(using_description)}")


def test_all_thirteen_discipline_rules_are_covered():
    """Guards against a discipline being added later with the old column."""
    disciplines = {p.parent.parent.name
                   for p, _ in _subeventname_rules(DISCIPLINE_RULES)}

    assert len(disciplines) == 13, f"expected 13 discipline rules, got {sorted(disciplines)}"


@needs_populated_ruleset
def test_the_codeset_still_carries_a_shortdescription_column():
    """The fix is only meaningful if the column exists in the shipped tables."""
    import glob
    from odf_validator.codes.excel import load_excel_codes

    tables = {}
    for path in glob.glob(str(RULES_ROOT / "codes" / "*.xlsx")):
        for table in load_excel_codes(Path(path)):
            tables[table.name] = table

    event_unit = tables.get("EVENT_UNIT")
    assert event_unit is not None, "EVENT_UNIT table missing from the pack"
    sample = next(iter(event_unit._rows.values()))
    assert "ENG_shortDescription" in sample.fields

    # And the two columns really do differ, or the fix would be cosmetic.
    differing = [k for k, v in event_unit._rows.items()
                 if v.fields.get("ENG_shortDescription")
                 and v.fields.get("ENG_Description")
                 and v.fields["ENG_shortDescription"] != v.fields["ENG_Description"]]
    assert differing, "ENG_shortDescription never differs from ENG_Description"


# SWM is excluded: it follows the prose, not the column, and its own reasoning
# is pinned by test_the_swm_exception_is_intact_and_documented above.
@pytest.mark.parametrize("discipline", ["WST", "TTE", "TRI"])
def test_source_ref_records_why_the_rule_departs_from_the_dd_prose(discipline):
    """The DD row contradicts itself, so the reason must survive in the rule."""
    paths = sorted((RULES_ROOT / "Disciplines" / discipline / "rules").glob("*.yaml"))
    refs = [e["source_ref"] for _, e in _subeventname_rules(paths)]

    assert refs, f"no SubEventName rule for {discipline}"
    assert "ShortDescription" in refs[0]
    assert "column governs" in refs[0]
