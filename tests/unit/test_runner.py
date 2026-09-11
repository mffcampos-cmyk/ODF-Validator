from lxml import etree
from odf_validator.dispatch import dispatch
from odf_validator.rules.runner import rule_applies, evaluate_rule
from odf_validator.rules.defs_model import RuleDef, AppliesTo
from odf_validator.model import Severity, Scope

XML = b'<OdfBody DocumentType="DT_SCHEDULE" DocumentCode="ARC"><Competition><Discipline Code="ARC"/></Competition><Unit PhaseType="9"/></OdfBody>'


def test_rule_applies_matrix():
    info = dispatch(etree.fromstring(XML))
    assert rule_applies(RuleDef("a", AppliesTo(["DT_SCHEDULE"], [], ["ARC"]),
                                "set_filter", ".//Unit", "PhaseType", {}, Severity.ERROR,
                                Scope.MESSAGE, ""), info)
    assert not rule_applies(RuleDef("b", AppliesTo(["DT_RESULT"], [], []),
                                    "set_filter", ".//Unit", "PhaseType", {}, Severity.ERROR,
                                    Scope.MESSAGE, ""), info)


def test_evaluate_rule_fires():
    root = etree.fromstring(XML)
    r = RuleDef("c", AppliesTo([], [], []), "set_filter", ".//Unit", "PhaseType",
                {"allowed": ["0", "1", "3"]}, Severity.ERROR, Scope.MESSAGE, "")
    assert len(evaluate_rule(r, root, None, None)) == 1
