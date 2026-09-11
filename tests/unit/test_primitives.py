from lxml import etree
from odf_validator.rules.primitives import PRIMITIVES
from odf_validator.rules.defs_model import RuleDef, AppliesTo
from odf_validator.model import Severity, Scope


def rule(primitive, target, attribute, params):
    return RuleDef("R", AppliesTo([], [], []), primitive, target, attribute,
                   params, Severity.ERROR, Scope.MESSAGE, "src")


def test_value_format_forbids_dash():
    root = etree.fromstring('<OdfBody><Result IFRANK="1-2"/></OdfBody>')
    r = rule("value_format", ".//Result", "IFRANK", {"forbid_substring": "-"})
    assert len(PRIMITIVES["value_format"](root, r, None, None)) == 1


def test_value_format_regex_ok():
    root = etree.fromstring('<OdfBody><X ItemNum="12"/></OdfBody>')
    r = rule("value_format", ".//X", "ItemNum", {"regex": "^[0-9]+$"})
    assert PRIMITIVES["value_format"](root, r, None, None) == []


def test_value_domain_positive_int():
    root = etree.fromstring('<OdfBody><Session Medal="0"/></OdfBody>')
    r = rule("value_domain", ".//Session", "Medal", {"min": 1, "integer": True})
    assert len(PRIMITIVES["value_domain"](root, r, None, None)) == 1


def test_value_domain_non_integer():
    root = etree.fromstring('<OdfBody><Session Medal="x"/></OdfBody>')
    r = rule("value_domain", ".//Session", "Medal", {"min": 1, "integer": True})
    assert len(PRIMITIVES["value_domain"](root, r, None, None)) == 1


def test_set_filter():
    root = etree.fromstring('<OdfBody><Unit PhaseType="9"/></OdfBody>')
    r = rule("set_filter", ".//Unit", "PhaseType", {"allowed": ["0", "1", "3"]})
    assert len(PRIMITIVES["set_filter"](root, r, None, None)) == 1


def test_conditional_presence_forbid():
    root = etree.fromstring('<OdfBody><Result IRM="DNS" AVG_SPEED="40"/></OdfBody>')
    r = rule("conditional_presence", ".//Result", None,
             {"when_attr": "IRM", "when_equals": "*", "forbid": "AVG_SPEED"})
    assert len(PRIMITIVES["conditional_presence"](root, r, None, None)) == 1


def test_code_membership_correct_field():
    from odf_validator.codes.tables import CodeRegistry, CodeTable, CodeRow
    reg = CodeRegistry()
    t = CodeTable("VENUE"); t.add_row(CodeRow("V1", {"ENG_Description": "Main Arena"}))
    reg.add_table(t, "t")
    bad = etree.fromstring('<OdfBody><S Venue="V1" VenueName="Wrong"/></OdfBody>')
    r = rule("code_membership", ".//S", "VenueName",
             {"codeset": "VENUE", "field": "ENG_Description", "code_attr": "Venue"})
    assert len(PRIMITIVES["code_membership"](bad, r, reg, None)) == 1
    good = etree.fromstring('<OdfBody><S Venue="V1" VenueName="Main Arena"/></OdfBody>')
    assert PRIMITIVES["code_membership"](good, r, reg, None) == []


def test_code_membership_column_matches_named_column_not_row_key():
    # Real DISCIPLINE-shape defect (item 2, 2026-08-30): the sheet has both a
    # 'Code' column (the 34-char RSC, which codes/excel.py._pick_id_index
    # picks as the row key because it appears before 'Id' in the sheet) and an
    # 'Id' column (the short 3-char business code, e.g. 'ATH' for Athletics --
    # real value from SYOG2026_ODF_Common_Codes_v_1_9_1.xlsx). The GEN DD says
    # @Category is char(3): it must be checked against 'Id', not the RSC key.
    from odf_validator.codes.tables import CodeRegistry, CodeTable, CodeRow
    reg = CodeRegistry()
    t = CodeTable("DISCIPLINE")
    t.add_row(CodeRow("ATH-------------------------------",
                       {"Id": "ATH", "ENG_Description": "Athletics"}))
    reg.add_table(t, "t")
    r = rule("code_membership", ".//*", "Category",
             {"codeset": "DISCIPLINE", "column": "Id"})
    good = etree.fromstring('<OdfBody><X Category="ATH"/></OdfBody>')
    assert PRIMITIVES["code_membership"](good, r, reg, None) == []
    bad = etree.fromstring('<OdfBody><X Category="ATX"/></OdfBody>')
    assert len(PRIMITIVES["code_membership"](bad, r, reg, None)) == 1
    # Without `column`, the short code can never match the RSC row key -- this
    # is the pre-fix behaviour and must still 100%-false-positive so the two
    # code paths stay distinguishable.
    r_no_column = rule("code_membership", ".//*", "Category",
                        {"codeset": "DISCIPLINE"})
    assert len(PRIMITIVES["code_membership"](good, r_no_column, reg, None)) == 1


def test_code_membership_column_phase():
    # Real PHASE-shape defect: table keyed by RSC, 'Phase' column holds the
    # short code ('DRAW', 'FNL-', ... -- real values from the same workbook).
    from odf_validator.codes.tables import CodeRegistry, CodeTable, CodeRow
    reg = CodeRegistry()
    t = CodeTable("PHASE")
    t.add_row(CodeRow("ARCGGEN---------------DRAW--------", {"Phase": "DRAW"}))
    reg.add_table(t, "t")
    r = rule("code_membership", ".//*", "Phase",
             {"codeset": "PHASE", "column": "Phase"})
    good = etree.fromstring('<OdfBody><X Phase="DRAW"/></OdfBody>')
    assert PRIMITIVES["code_membership"](good, r, reg, None) == []
    bad = etree.fromstring('<OdfBody><X Phase="ZZZZ"/></OdfBody>')
    assert len(PRIMITIVES["code_membership"](bad, r, reg, None)) == 1


def test_code_membership_column_case_insensitive():
    # The DD writes 'Eventunit'; a rule author might spell it 'EventUnit'.
    # CodeTable.resolve_field must match case/separator-insensitively, the
    # same idiom codes/excel.py already uses to pick a sheet's id column.
    from odf_validator.codes.tables import CodeRegistry, CodeTable, CodeRow
    reg = CodeRegistry()
    t = CodeTable("EVENT_UNIT")
    t.add_row(CodeRow("ARCGGEN---------------DRAW--------",
                       {"Eventunit": "--------"}))
    reg.add_table(t, "t")
    r = rule("code_membership", ".//*", "EventUnit",
             {"codeset": "EVENT_UNIT", "column": "EventUnit"})  # differs in case
    good = etree.fromstring('<OdfBody><X EventUnit="--------"/></OdfBody>')
    assert PRIMITIVES["code_membership"](good, r, reg, None) == []
    bad = etree.fromstring('<OdfBody><X EventUnit="000100--"/></OdfBody>')
    assert len(PRIMITIVES["code_membership"](bad, r, reg, None)) == 1


def test_code_membership_column_with_code_attr_description_path():
    # GEN_CATEGORYNAME_CODE-shape: code_attr points at the short code
    # ('Category'), field is the description to validate ('CategoryName').
    # Without `column`, table.get(code, field) looks the code up by row key
    # (the RSC) and always misses -- the rule silently never fires. With
    # `column: Id`, the code is resolved against the 'Id' column instead.
    from odf_validator.codes.tables import CodeRegistry, CodeTable, CodeRow
    reg = CodeRegistry()
    t = CodeTable("DISCIPLINE")
    t.add_row(CodeRow("ATH-------------------------------",
                       {"Id": "ATH", "ENG_Description": "Athletics"}))
    reg.add_table(t, "t")
    r = rule("code_membership", ".//*", "CategoryName",
             {"codeset": "DISCIPLINE", "field": "ENG_Description",
              "code_attr": "Category", "column": "Id"})
    bad = etree.fromstring(
        '<OdfBody><X Category="ATH" CategoryName="Wrong Name"/></OdfBody>')
    out = PRIMITIVES["code_membership"](bad, r, reg, None)
    assert len(out) == 1 and "Athletics" in out[0].message
    good = etree.fromstring(
        '<OdfBody><X Category="ATH" CategoryName="Athletics"/></OdfBody>')
    assert PRIMITIVES["code_membership"](good, r, reg, None) == []
    # Pre-fix behaviour: without `column` the code_attr lookup always misses
    # (row key is the RSC, not 'ATH'), so even a wrong name never fires --
    # a false negative dressed as a passing check.
    r_no_column = rule("code_membership", ".//*", "CategoryName",
                        {"codeset": "DISCIPLINE", "field": "ENG_Description",
                         "code_attr": "Category"})
    assert PRIMITIVES["code_membership"](bad, r_no_column, reg, None) == []


def test_code_membership_unknown_column_skips_silently_at_runtime():
    # The pack loader (ingestion/builder.py) is responsible for surfacing this
    # as an authoring error; the primitive itself must not crash or fall back
    # to RSC-key matching (which would reintroduce the false positives).
    from odf_validator.codes.tables import CodeRegistry, CodeTable, CodeRow
    reg = CodeRegistry()
    t = CodeTable("PHASE")
    t.add_row(CodeRow("ARCGGEN---------------DRAW--------", {"Phase": "DRAW"}))
    reg.add_table(t, "t")
    r = rule("code_membership", ".//*", "Phase",
             {"codeset": "PHASE", "column": "NoSuchColumn"})
    node = etree.fromstring('<OdfBody><X Phase="DRAW"/></OdfBody>')
    assert PRIMITIVES["code_membership"](node, r, reg, None) == []


def test_no_empty_attributes_flags_empty():
    root = etree.fromstring('<OdfBody><Team TeamType="" Organisation="ASA"/>'
                            '<Result IRM=""/></OdfBody>')
    r = rule("no_empty_attributes", ".//*", None, {})
    out = PRIMITIVES["no_empty_attributes"](root, r, None, None)
    msgs = " ".join(f.message for f in out)
    assert len(out) == 2 and "TeamType" in msgs and "IRM" in msgs


def test_no_empty_attributes_exempt():
    root = etree.fromstring('<OdfBody><X A=""/></OdfBody>')
    r = rule("no_empty_attributes", ".//*", None, {"exempt": ["A"]})
    assert PRIMITIVES["no_empty_attributes"](root, r, None, None) == []


def test_forbidden_value():
    root = etree.fromstring('<OdfBody><Competitor Code="TBD"/><Competitor Code="9001"/></OdfBody>')
    r = rule("forbidden_value", ".//Competitor", "Code", {"values": ["TBD"]})
    out = PRIMITIVES["forbidden_value"](root, r, None, None)
    assert len(out) == 1 and "TBD" in out[0].message


def test_required_attributes_flags_missing_and_empty():
    r = rule("required_attributes", ".", None,
             {"attrs": ["DocumentCode", "Version"]})
    root = etree.fromstring(b'<OdfBody DocumentCode="" NotIt="x"/>')
    out = PRIMITIVES["required_attributes"](root, r, None, None)
    msgs = " | ".join(f.message for f in out)
    assert len(out) == 2                      # empty DocumentCode + missing Version
    assert "DocumentCode" in msgs and "Version" in msgs


def test_required_attributes_passes_when_present():
    r = rule("required_attributes", ".", None,
             {"attrs": ["DocumentCode"]})
    root = etree.fromstring(b'<OdfBody DocumentCode="ARC"/>')
    assert PRIMITIVES["required_attributes"](root, r, None, None) == []


def test_findall_dot_returns_root():
    root = etree.fromstring(b"<OdfBody/>")
    assert root.findall(".") == [root]
