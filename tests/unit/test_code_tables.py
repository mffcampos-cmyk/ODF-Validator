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
