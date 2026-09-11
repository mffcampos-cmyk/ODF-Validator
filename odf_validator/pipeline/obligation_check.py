"""Enforce attributes a Data Dictionary marks mandatory that the XSD does not.

The mirror of obligation_filter.py. If the sport Data Dictionary is the
authority on whether an attribute is mandatory -- which is why an XSD "required
but missing" error is dropped where a DD says optional -- then it is equally the
authority where the DD says mandatory and the schema is silent. 65
(element, attribute) pairs across the SYOG26 DDs are in that position.

Only pairs the schema proves unambiguous are enforced. The two directions carry
very different risk: a wrong suppression hides one finding, whereas a wrong
mandatory attribute fires on every matching element in every file. Measured on
the real 2026-06-05 corpus, the unrestricted set produced 5,924 findings of
which 5,902 were a single ambiguous element name (<Description>, 13
complexTypes, so a Competitor-only @TeamName was demanded of every athlete);
two mis-attributed rows in an earlier converter build would have produced
38,648. The restricted set produces 523, matching the surviving XSD errors
exactly and adding no false positives.
"""
from __future__ import annotations
from ..model import Finding, Location, Layer, Severity

RULE_ID = "CORE_DD_MANDATORY_ATTR"


def missing_mandatory_attrs(root, info, obligations) -> list:
    """Findings for DD-mandatory attributes absent from the message.

    No obligations, or no schema to prove a pair unambiguous, means no findings:
    the check fails closed rather than guessing.
    """
    if obligations is None or root is None:
        return []
    pairs = obligations.mandatory_attrs(info.discipline, info.doc_type,
                                        enforceable_only=True)
    # Extension-style elements carry one attribute table per @Code, so some
    # obligations hold only for particular @Code values. Enforcing those on
    # every node of the element is exactly what produced 567 of the 778
    # findings in the real WST run of 2026-08-31 -- @Value2 is mandatory on an
    # <ExtendedResult> whose @Code is B_JUDGE, and on no other.
    conditional = obligations.conditional_mandatory_attrs(
        info.discipline, info.doc_type, enforceable_only=True)
    if not pairs and not conditional:
        return []
    tree = root.getroottree()
    out = []

    def report(element: str, attribute: str, node, detail: str = "") -> None:
        out.append(Finding(
            Severity.ERROR, Layer.SEMANTIC, RULE_ID,
            f"<{element}> is missing @{attribute}, which the "
            f"{info.discipline or 'GEN'} Data Dictionary marks mandatory "
            f"for {info.doc_type}{detail}.",
            Location(line=node.sourceline, path=tree.getpath(node)),
            "Data Dictionary M/O obligation (DD overrides XSD; "
            "see rules/obligations.py)"))

    for element, attribute in sorted(pairs):
        for node in root.iter(element):
            if node.get(attribute) is None:
                report(element, attribute, node)

    for (element, attribute), codes in sorted(conditional.items()):
        for node in root.iter(element):
            # A node whose @Code the DD does not name is governed by a
            # different attribute table, or by none. Say nothing about it.
            if node.get("Code") not in codes:
                continue
            if node.get(attribute) is None:
                report(element, attribute, node,
                       f" when @Code is {node.get('Code')}")
    return out
