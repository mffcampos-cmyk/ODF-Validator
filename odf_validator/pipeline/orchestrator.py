from __future__ import annotations
from ..model import RunResult
from ..dispatch import dispatch
from ..rules.core import load_core_rules
from ..rules.runner import run_rules
from .structural import validate_structural
from .obligation_filter import drop_dd_optional_attrs
from .obligation_check import missing_mandatory_attrs
from .width_check import over_width_attrs
from .cardinality_check import child_count_violations


class Pipeline:
    """Runs the two-layer validation for one message:

    1. Immutable core: well-formedness -> XSD -> engine-bundled CORE_ rules.
       Malformed XML short-circuits; a missing schema yields the
       CORE_XSD_INACTIVE hard-gate ERROR (see structural.py).
    2. Pack rules: the selected game ruleset's rules, run after core.

    Between well-formedness and the rules, XSD findings are filtered against
    the pack's Data Dictionary obligations: the shared schema cannot express a
    per-message rule, so where a DD marks an attribute optional its "required
    but missing" error is dropped (see pipeline/obligation_filter.py).

    Core rules ship with the engine (odf_validator/core_rules/) and cannot be
    overridden by packs (loader rejects CORE_-prefixed pack rules).
    """

    def __init__(self, core_rules=None):
        self._core_rules = core_rules if core_rules is not None else load_core_rules()

    def run(self, xml, pack, ctx=None):
        root, findings = validate_structural(xml, pack.schema)
        if root is None:
            return RunResult(None, None, None, None, pack.name, findings)
        info = dispatch(root)
        findings = drop_dd_optional_attrs(list(findings), info,
                                          getattr(pack, "obligations", None))
        findings += missing_mandatory_attrs(root, info,
                                            getattr(pack, "obligations", None))
        # Field widths and child cardinalities: DD-stated, schema-blind, same
        # authority chain and the same restricted-set discipline.
        findings += over_width_attrs(root, info, getattr(pack, "obligations", None),
                                     exempt=getattr(pack, "length_exempt", frozenset()))
        findings += child_count_violations(root, info,
                                           getattr(pack, "obligations", None))
        findings += run_rules(self._core_rules, root, pack.codes, info, ctx,
                              pack_name="core")
        findings += run_rules(pack.rules, root, pack.codes, info, ctx,
                              pack_name=pack.name)
        return RunResult(info.doc_type, info.discipline, info.document_code,
                         info.version, pack.name, findings)
