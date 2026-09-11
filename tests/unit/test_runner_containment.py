from lxml import etree
from odf_validator.rules.runner import run_rules
from odf_validator.rules.defs_model import RuleDef, AppliesTo
from odf_validator.model import Severity, Scope, Layer
from odf_validator.dispatch import dispatch

BAD_REGEX_RULE = RuleDef(
    id="PACK_BAD", applies_to=AppliesTo(), primitive="value_format",
    target=".", attribute="X", params={"regex": "("},  # invalid regex -> re.error
    severity=Severity.ERROR, scope=Scope.MESSAGE, source_ref="src")

GOOD_RULE = RuleDef(
    id="PACK_GOOD", applies_to=AppliesTo(), primitive="value_format",
    target=".", attribute="X", params={"regex": "^a$"},
    severity=Severity.ERROR, scope=Scope.MESSAGE, source_ref="src")


def test_crashing_rule_is_contained_and_run_continues():
    root = etree.fromstring(b'<OdfBody X="zzz"/>')
    findings = run_rules([BAD_REGEX_RULE, GOOD_RULE], root, None,
                         dispatch(root), None)
    crash = [f for f in findings if f.rule_id == "RULE_CRASH"]
    normal = [f for f in findings if f.rule_id == "PACK_GOOD"]
    assert len(crash) == 1
    assert crash[0].severity == Severity.WARNING
    assert "PACK_BAD" in crash[0].message
    assert len(normal) == 1, "later rules still ran"


def test_applies_to_filter_respected():
    root = etree.fromstring(b'<OdfBody X="zzz" DocumentType="DT_OTHER"/>')
    scoped = RuleDef(id="R", applies_to=AppliesTo(doc_types=["DT_RESULT"]),
                     primitive="value_format", target=".", attribute="X",
                     params={"regex": "^a$"}, severity=Severity.ERROR,
                     scope=Scope.MESSAGE, source_ref="")
    assert run_rules([scoped], root, None, dispatch(root), None) == []
