"""Enforce the field widths the Data Dictionaries state and the schema cannot.

Across the three SYOG26 XSDs there is not one xs:maxLength; the only widths
the schema pins are exact (`xs:length` 34 for the RSC, 1 for flags). The DDs
state S(n) for 3,967 (message, element, attribute) rows, and until this check
a 27-character Team/@TVTeamName in a 21-character field validated clean -- a
consumer sizing a TV lower-third to the published width truncates it.

Restricted set only: ObligationRegistry.max_widths(enforceable_only=True)
keeps the pairs whose attribute the schema declares under one element name.
A width fires on every node carrying the attribute, so a Data Dictionary row
attributed to the wrong element (converted-PDF tables interrupt each other)
would otherwise report valid data across a whole corpus. The precedence is
the DD authority chain: the CRD DD's S(40) for TVTeamName beats the GEN DD's
S(21) for curling, and only for curling.

`exempt` is the pack's ruling on attributes whose DD row states both a width
and a Common Codes description (GEN: Unit/ItemName/@Value is S(40) AND the
EVENT_UNIT ENG description, 150 of which are longer than 40). The two halves
of that row cannot both hold; the description governs, as it already does for
VenueName and LocationName, which carry no S(n) at all.
"""
from __future__ import annotations
from ..model import Finding, Location, Layer, Severity

WIDTH_RULE = "CORE_DD_MAX_LENGTH"


def over_width_attrs(root, info, obligations, exempt=frozenset()) -> list:
    """Findings for attribute values longer than the DD's S(n)."""
    if obligations is None or root is None:
        return []
    widths = obligations.max_widths(info.discipline, info.doc_type,
                                    enforceable_only=True)
    if not widths:
        return []
    tree = root.getroottree()
    out = []
    for (element, attribute), limit in sorted(widths.items()):
        if (element, attribute) in exempt:
            continue
        for node in root.iter(element):
            value = node.get(attribute)
            if value is None or len(value) <= limit:
                continue
            out.append(Finding(
                Severity.ERROR, Layer.SEMANTIC, WIDTH_RULE,
                f"<{element}> @{attribute} is {len(value)} characters; the "
                f"{info.discipline or 'GEN'} Data Dictionary declares it "
                f"S({limit}) for {info.doc_type}.",
                Location(line=node.sourceline, path=tree.getpath(node)),
                "Data Dictionary field width (DD overrides XSD; "
                "see rules/obligations.py)"))
    return out
