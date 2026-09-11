from odf_validator.codes.xml import load_xml_codes

SAMPLE = """<?xml version="1.0"?>
<CommonCodes>
  <Codeset name="NOC">
    <Code id="USA" ENG_Description="United States"/>
    <Code id="FRA" ENG_Description="France"/>
  </Codeset>
</CommonCodes>"""


def test_loads_xml_codeset(tmp_path):
    p = tmp_path / "codes.xml"
    p.write_text(SAMPLE, encoding="utf-8")
    tables = {t.name: t for t in load_xml_codes(p)}
    assert tables["NOC"].get("USA", "ENG_Description") == "United States"
    assert tables["NOC"].lookup("FRA") is not None
