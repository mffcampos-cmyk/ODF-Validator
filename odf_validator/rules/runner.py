from __future__ import annotations
from ..dispatch import MessageInfo
from ..model import Finding, Location, Severity
from .defs_model import RuleDef
from .primitives import PRIMITIVES
from .registry import PYTHON_RULES


def rule_applies(rule: RuleDef, info: MessageInfo) -> bool:
    a = rule.applies_to
    if a.exclude_doc_types and info.doc_type in a.exclude_doc_types:
        return False
    if a.doc_types and info.doc_type not in a.doc_types:
        return False
    if a.subtypes and info.document_subtype not in a.subtypes:
        return False
    if a.disciplines and info.discipline not in a.disciplines:
        return False
    if a.exclude_disciplines and info.discipline in a.exclude_disciplines:
        return False
    return True


def evaluate_rule(rule: RuleDef, root, registry, ctx, pack_name: str = ""):
    if rule.primitive == "python":
        fn = PYTHON_RULES.get(f"{pack_name}:{rule.params.get('fn', '')}")
        if fn is None:
            return []
        return fn(root, rule, registry, ctx)
    fn = PRIMITIVES.get(rule.primitive)
    if fn is None:
        return []
    return fn(root, rule, registry, ctx)


def run_rules(rules, root, registry, info: MessageInfo, ctx,
              pack_name: str = "") -> list:
    """Evaluate rules against one message. A rule that raises is reported as
    a WARNING RULE_CRASH finding and never aborts the run, so a broken
    ruleset cannot take down core validation."""
    findings: list = []
    for rule in rules:
        if not rule_applies(rule, info):
            continue
        try:
            findings += evaluate_rule(rule, root, registry, ctx, pack_name)
        except Exception as e:
            findings.append(Finding(
                Severity.WARNING, rule.layer, "RULE_CRASH",
                f"Rule '{rule.id}' failed to evaluate and was skipped: {e}",
                Location(), rule.source_ref))
    return findings
