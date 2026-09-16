"""Enforce the child cardinalities the Data Dictionaries state and the schema
cannot.

odf2-structure.xsd declares ONE competitionType for every message and puts
Result, Entry, Team and the rest in a single xs:choice with optional
alternatives, so the choice is emptiable and `<Competition/>` is schema-valid
in a DT_ENTRIES. The DD says `Competition /Entry (1,N)`: a DT_ENTRIES with no
Entry is not merely wrong, it reads as "this event has no entries".

Restricted set only: ObligationRegistry.child_bounds(enforceable_only=True)
keeps pairs whose parent name is one complexType (<Description> is thirteen)
and drops what the schema already reports -- a minimum it requires outright,
a maximum it caps at one -- so one defect yields one finding.
"""
from __future__ import annotations
from ..model import Finding, Location, Layer, Severity

CARD_RULE = "CORE_DD_CARDINALITY"


def _bounds(lo, hi) -> str:
    return f"({lo},{'N' if hi is None else hi})"


def child_count_violations(root, info, obligations) -> list:
    """Findings for parents whose child count is outside the DD's (min,max)."""
    if obligations is None or root is None:
        return []
    bounds = obligations.child_bounds(info.discipline, info.doc_type,
                                      enforceable_only=True)
    if not bounds:
        return []
    tree = root.getroottree()
    out = []
    for (parent, child), (lo, hi) in sorted(bounds.items()):
        for node in root.iter(parent):
            n = sum(1 for c in node if c.tag == child)
            if n < lo or (hi is not None and n > hi):
                out.append(Finding(
                    Severity.ERROR, Layer.SEMANTIC, CARD_RULE,
                    f"<{parent}> has {n} <{child}> child(ren); the "
                    f"{info.discipline or 'GEN'} Data Dictionary declares "
                    f"{parent} /{child} {_bounds(lo, hi)} for {info.doc_type}.",
                    Location(line=node.sourceline, path=tree.getpath(node)),
                    "Data Dictionary element cardinality (DD overrides XSD; "
                    "see rules/obligations.py)"))
    return out
