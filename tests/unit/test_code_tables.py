from odf_validator.codes.tables import CodeRow, CodeTable, CodeRegistry


def test_table_lookup_and_get():
    t = CodeTable("COUNTRY")
    t.add_row(CodeRow(id="AFG", fields={"ENG_Description": "Afghanistan",
                                        "ENG_LongDescription": "Afghanistan"}))
    assert t.lookup("AFG").id == "AFG"
    assert t.lookup("ZZZ") is None
    assert t.get("AFG", "ENG_Description") == "Afghanistan"
    assert t.get("AFG", "MISSING") is None


def test_registry_conflict_last_wins():
    reg = CodeRegistry()
    a = CodeTable("NOC"); a.add_row(CodeRow("USA", {"ENG_Description": "First"}))
    b = CodeTable("NOC"); b.add_row(CodeRow("USA", {"ENG_Description": "Second"}))
    reg.add_table(a, "fileA")
    msgs = reg.add_table(b, "fileB")
    assert reg.table("NOC").get("USA", "ENG_Description") == "Second"
    assert any("NOC" in m for m in msgs)
    assert reg.conflicts


# ------------------------------------------------ codeset name resolution ---
#
# The Data Dictionaries cite codeset names in their own spelling, and the
# workbook does not always agree: the DD writes CC@WINDDIRECTION where the
# workbook sheet is WIND_DIRECTION, CC@DISCIPLINEFUNCTION against
# DISCIPLINE_FUNCTION. 27 derived rules were loaded active and never fired
# because of it (2026-09-12). CodeTable.resolve_field already does exactly
# this for a table's COLUMN names via squash_name; codeset names were left
# matching exactly.

def _reg(*names) -> CodeRegistry:
    reg = CodeRegistry()
    for n in names:
        t = CodeTable(n)
        t.add_row(CodeRow(id="X", fields={"ENG_Description": n}))
        reg.add_table(t, "test")
    return reg


def test_resolve_matches_a_name_ignoring_separators_and_case():
    reg = _reg("WIND_DIRECTION", "SCHEDULESTATUS", "DISCIPLINE_FUNCTION")
    assert reg.resolve("WIND_DIRECTION") == "WIND_DIRECTION"
    assert reg.resolve("WINDDIRECTION") == "WIND_DIRECTION"
    assert reg.resolve("Wind Direction") == "WIND_DIRECTION"
    assert reg.resolve("DISCIPLINEFUNCTION") == "DISCIPLINE_FUNCTION"


def test_resolve_returns_none_for_a_codeset_that_does_not_exist():
    """DISCIPLINECLASS and WEATHER_REGION have no sheet under any spelling;
    those rules must stay broken rather than be matched to something near."""
    reg = _reg("WIND_DIRECTION", "DISCIPLINE")
    assert reg.resolve("DISCIPLINECLASS") is None
    assert reg.resolve("WEATHER_REGION") is None


def test_resolve_refuses_to_guess_between_two_squash_equal_tables():
    """If a workbook ever shipped both spellings, picking one silently would
    be a coin toss over which codes a rule enforces."""
    reg = _reg("RESULT_STATUS", "RESULTSTATUS")
    assert reg.resolve("Resultstatus") is None


def test_table_lookup_accepts_the_dd_spelling():
    """The runtime lookup has to agree with the loader's check, or the rule
    passes validation at load and still finds no table when it runs."""
    reg = _reg("WIND_DIRECTION")
    assert reg.table("WINDDIRECTION") is not None
    assert reg.table("WINDDIRECTION").name == "WIND_DIRECTION"
    assert reg.table("NO_SUCH_TABLE") is None


def test_a_missing_codeset_is_not_matched_to_a_near_neighbour():
    reg = _reg("DISCIPLINE")
    assert reg.table("DISCIPLINECLASS") is None
