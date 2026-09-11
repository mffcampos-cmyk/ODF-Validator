"""Drop XSD "attribute required but missing" errors the Data Dictionary excuses.

`odf2-structure.xsd` declares a single `competitionType` used by every message
type, so `use="required"` on `Competition/@Gen` is asserted for DT_ENTRIES and
DT_RESULT simultaneously. All 25 SYOG26 discipline Data Dictionaries mark @Gen
mandatory for DT_ENTRIES and optional for every other message. The schema has
no way to say that, so it is not the authority on obligation -- the DD is
(survey 2026-08-14).

Only that one error shape is filtered, and only on an explicit "O" from a DD.
An attribute no DD mentions resolves to None and is left alone: unknown is not
permission.
"""
from __future__ import annotations
import re

# libxml2: "Element 'Competition': The attribute 'Gen' is required but missing."
_REQUIRED_MISSING = re.compile(
    r"Element '([^']+)':\s*The attribute '([^']+)' is required but missing")


def drop_dd_optional_attrs(findings, info, obligations):
    """Return `findings` without the required-but-missing errors a DD excuses.

    No obligations (a pack with no DDs, or an XSD that did not compile) means no
    filtering: the findings pass through untouched rather than being trusted
    away.
    """
    if obligations is None:
        return findings
    kept = []
    for f in findings:
        m = _REQUIRED_MISSING.search(f.message or "")
        if m and obligations.resolve(info.discipline, info.doc_type,
                                     m.group(1), m.group(2)) == "O":
            continue
        kept.append(f)
    return kept
