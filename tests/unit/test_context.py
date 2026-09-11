from lxml import etree
from odf_validator.context import ValidationContext
from odf_validator.rules.primitives import PRIMITIVES
from odf_validator.rules.defs_model import RuleDef, AppliesTo
from odf_validator.model import Severity, Scope


def xrule():
    return RuleDef("ARC_SO", AppliesTo([], [], []), "cross_message", ".//Result",
                   "StartSortOrder", {"key_attr": "Code"}, Severity.ERROR,
                   Scope.CONTEXT, "src")


def msg(order):
    return etree.fromstring(f'<OdfBody><Result Code="A1" StartSortOrder="{order}"/></OdfBody>')


def test_cross_message_consistent():
    ctx = ValidationContext()
    r = xrule()
    assert PRIMITIVES["cross_message"](msg(5), r, None, ctx) == []   # first records
    assert PRIMITIVES["cross_message"](msg(5), r, None, ctx) == []   # same -> ok


def test_cross_message_inconsistent():
    ctx = ValidationContext()
    r = xrule()
    PRIMITIVES["cross_message"](msg(5), r, None, ctx)
    out = PRIMITIVES["cross_message"](msg(9), r, None, ctx)          # differs -> error
    assert len(out) == 1 and out[0].severity.value == "error"


def test_cross_message_no_context_silent():
    # No batch context -> cross-message check is skipped silently (no noise).
    assert PRIMITIVES["cross_message"](msg(5), xrule(), None, None) == []
