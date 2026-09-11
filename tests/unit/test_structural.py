from odf_validator.pipeline.structural import validate_structural, compile_schema

MINI_XSD = b"""<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="Root">
    <xs:complexType>
      <xs:attribute name="A" type="xs:string" use="required"/>
    </xs:complexType>
  </xs:element>
</xs:schema>"""


def _mini_schema(tmp_path):
    p = tmp_path / "mini.xsd"
    p.write_bytes(MINI_XSD)
    return compile_schema(p)


def test_malformed_xml_short_circuits(tmp_path):
    root, findings = validate_structural(b"<Root><not-closed>", _mini_schema(tmp_path))
    assert root is None
    assert len(findings) == 1 and findings[0].severity.value == "error"


def test_missing_required_attribute_reports(tmp_path):
    root, findings = validate_structural(b'<Root/>', _mini_schema(tmp_path))
    assert root is not None
    assert any(f.layer.value == "structural" and f.severity.value == "error"
               for f in findings)


def test_valid_message_no_findings(tmp_path):
    root, findings = validate_structural(b'<Root A="x"/>', _mini_schema(tmp_path))
    assert root is not None and findings == []


def test_missing_schema_hard_gates_with_error():
    root, findings = validate_structural(b"<OdfBody/>", None)
    assert root is not None
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "CORE_XSD_INACTIVE"
    assert f.severity.value == "error"
