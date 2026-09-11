from odf_validator.rules.core import load_core_rules
from odf_validator.model import Layer, Severity


def test_core_rules_load_and_are_namespaced():
    rules = load_core_rules()
    assert rules, "core rules must not be empty"
    assert all(r.id.startswith("CORE_") for r in rules)
    ids = [r.id for r in rules]
    assert len(ids) == len(set(ids)), "no duplicate core rule ids"


def test_core_rules_expected_members():
    ids = {r.id for r in load_core_rules()}
    assert {"CORE_ITEMNUM_INT", "CORE_IFRANK_NODASH", "CORE_NO_EMPTY_ATTRS",
            "CORE_VERSION_POSINT", "CORE_ENVELOPE_REQUIRED",
            "CORE_DOCSUBCODE_NOT_IN_RANKING", "CORE_COMPETITION_CODE",
            "CORE_DISCIPLINE_CODE"} <= ids


def test_code_membership_core_rules_report_code_layer():
    by_id = {r.id: r for r in load_core_rules()}
    assert by_id["CORE_COMPETITION_CODE"].layer == Layer.CODE
    # Warning, not error: FND 3.1 requires a valueless mandatory attribute to be
    # sent empty, and lets an optional one be sent empty "without any
    # restriction"; only 6.7 prefers omission, as a SHOULD. This reverses the
    # earlier promotion to error (a conformance review, finding C4).
    assert by_id["CORE_NO_EMPTY_ATTRS"].severity == Severity.WARNING
