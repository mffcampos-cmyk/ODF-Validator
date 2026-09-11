from lxml import etree
from odf_validator.rules.registry import python_rule, PYTHON_RULES
from odf_validator.rules.runner import evaluate_rule
from odf_validator.rules.defs_model import RuleDef, AppliesTo
from odf_validator.model import Severity, Scope, Finding, Location, Layer


def _rule():
    return RuleDef("DEMO_PY", AppliesTo([], [], []), "python", ".", None,
                   {"fn": "demo"}, Severity.ERROR, Scope.MESSAGE, "")


def test_python_rule_is_pack_namespaced():
    @python_rule("SYOG26:demo")
    def _demo(root, rule, registry, ctx):
        return [Finding(Severity.ERROR, Layer.SEMANTIC, rule.id, "fired",
                        Location(), rule.source_ref)]
    assert "SYOG26:demo" in PYTHON_RULES
    out = evaluate_rule(_rule(), etree.fromstring(b"<OdfBody/>"), None, None,
                        pack_name="SYOG26")
    assert len(out) == 1 and out[0].message == "fired"


def test_other_pack_cannot_reach_the_function():
    out = evaluate_rule(_rule(), etree.fromstring(b"<OdfBody/>"), None, None,
                        pack_name="SOLG28")
    assert out == []


def test_unnamespaced_registration_rejected():
    try:
        python_rule("no_colon")(lambda *a: [])
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for un-namespaced key")
