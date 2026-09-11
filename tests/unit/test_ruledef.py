from odf_validator.rules.defs_model import RuleDef, AppliesTo
from odf_validator.model import Severity, Scope


def test_ruledef_construction():
    r = RuleDef(id="ARC_MEDAL_POS", applies_to=AppliesTo(["DT_SCHEDULE"], [], ["ARC"]),
                primitive="value_domain", target="./Competition/Session",
                attribute="Medal", params={"min": 1, "integer": True},
                severity=Severity.ERROR, scope=Scope.MESSAGE, source_ref="QA")
    assert r.applies_to.doc_types == ["DT_SCHEDULE"]
    assert r.params["min"] == 1
