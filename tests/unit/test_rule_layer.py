from pathlib import Path
from lxml import etree
from odf_validator.model import Layer
from odf_validator.rules.loader import load_rule_defs
from odf_validator.rules.defs_model import RuleDef, AppliesTo
from odf_validator.rules.primitives import value_format
from odf_validator.model import Severity, Scope


def test_loader_derives_layer_from_primitive(tmp_path: Path):
    f = tmp_path / "r.yaml"
    f.write_text(
        "- id: A_CODE\n  primitive: code_membership\n  target: '.'\n"
        "  attribute: X\n  params: {codeset: FOO}\n"
        "- id: A_SEM\n  primitive: value_format\n  target: '.'\n"
        "  attribute: X\n  params: {regex: '^a$'}\n",
        encoding="utf-8")
    rules, errors, _, _, _ = load_rule_defs([f])
    assert errors == []
    by_id = {r.id: r for r in rules}
    assert by_id["A_CODE"].layer == Layer.CODE
    assert by_id["A_SEM"].layer == Layer.SEMANTIC


def test_finding_uses_rule_layer():
    rule = RuleDef(id="R1", applies_to=AppliesTo(), primitive="value_format",
                   target=".", attribute="X", params={"regex": "^a$"},
                   severity=Severity.ERROR, scope=Scope.MESSAGE, source_ref="",
                   layer=Layer.CODE)
    root = etree.fromstring(b'<OdfBody X="zzz"/>')
    out = value_format(root, rule, None, None)
    assert len(out) == 1 and out[0].layer == Layer.CODE
