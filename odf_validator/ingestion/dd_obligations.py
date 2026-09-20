"""Read M/O obligations out of a converted Data Dictionary.

The sport Data Dictionary is the final authority on whether an attribute is
mandatory. This matters because the shared `odf2-structure.xsd` declares ONE
`competitionType` used by every message, so `use="required"` on
`Competition/@Gen` necessarily applies to DT_ENTRIES and DT_RESULT alike. The
DD does not: all 25 SYOG26 discipline DDs mark `Gen` and `Codes` mandatory for
DT_ENTRIES and optional everywhere else. The XSD cannot express that; only the
DD can, so the DD wins (survey 2026-08-14).

Obligations are keyed on `(doc_type, element, attribute)`. Attribute name alone
is never sufficient -- `Code` is required on 83 complexTypes in the schema, and
a DD marking `Result/@Rank` optional says nothing about `MedalLine/@Rank`.
Keying on the name alone would silently disable dozens of valid checks: the
same overbroad-target mistake that produced 19,103 false positives in the
2026-08-12 corpus, only inverted.

Input is the Markdown produced by `dd_to_markdown()` (pdf-inspector for PDFs,
passthrough for .md), so the shapes handled here are the shapes that converter
emits. The regexes below are why dd_to_markdown() reports which backend it
used: a PDF converted by the markitdown fallback has a different Markdown
shape, and obligations parsed out of it may be incomplete rather than absent.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re

# `|DocumentType|DT_RESULT|...`, but also BS5's `||DocumentType||DT_ENTRIES|`
# and headers listing several messages: `|DocumentType|DT_PARTIC / DT_PARTIC_UPDATE|`.
# The padding tolerance is not cosmetic: missing it makes the rows that follow
# get attributed to the PREVIOUS message, which during the 2026-08-14 survey
# invented a "BS5 marks Gen mandatory for DT_PARTIC_TEAMS" finding that is not
# in the document.
# A message-section header row. Two spellings occur:
#   |DocumentType|DT_ENTRIES|List of entries by event message|
#   |D oc ume ntTy p e|DT_R ES ULT|Event Unit Start List and Results message|
# The second is the GEN DD's PDF letter-spacing surviving conversion, and it is
# the common case: 50 of the GEN DD's 51 message sections look like that. A
# parser that only matches the clean spelling attributes all 602 GEN
# obligations to the single message that happens to be written cleanly.
# Matching is therefore done on the cells with whitespace removed, not by regex
# over the raw line.
_DOC_CELL = "documenttype"

# Split a run of concatenated names: whitespace removal turns
# "DT_SCHEDULE DT_SCHEDULE_UPDATE" into "DT_SCHEDULEDT_SCHEDULE_UPDATE", so
# each name runs up to the next "DT_" rather than to the next underscore --
# DT_SCHEDULE_UPDATE must not be truncated to its DT_SCHEDULE prefix.
_DT_RUN = re.compile(r'DT_(?:(?!DT_).)*')


def _doc_types(line: str) -> list[str] | None:
    """Message names if `line` is a section header, else None."""
    if not line.lstrip().startswith("|"):
        return None
    cells = line.split("|")
    if len(cells) < 3:
        return None
    for i in range(1, len(cells) - 1):
        if re.sub(r"\s+", "", cells[i]).lower() != _DOC_CELL:
            continue
        # BS5 pads with empty cells (`||DocumentType||DT_ENTRIES|`), so the
        # value is the next cell with anything in it.
        value = ""
        for cell in cells[i + 1:]:
            # Drop everything that cannot be part of a name: the letter-spacing
            # above, and the "/" in `DT_PARTIC / DT_PARTIC_UPDATE`.
            cleaned = re.sub(r"[^A-Za-z0-9_]", "", cell)
            if cleaned:
                value = cleaned
                break
        # `|D oc ume ntTy p e|M|S(30)|...|` is an attribute definition whose
        # name happens to be DocumentType, not the start of a new section.
        if not value.startswith("DT_"):
            return None
        return [m.group(0) for m in _DT_RUN.finditer(value)]
    return None


# A numbered heading, and the number itself: `## 2.3.3 List of teams`,
# `#### 2.1.37.2 Header Values`, `## <u>1.5</u> Related Documents`. The
# markdown depth is NOT usable as the section level -- ARC writes its message
# sections as h2 and GEN writes its as h3 -- so the numbering the documents
# carry is what tells one level from another.
# At least two components, deliberately: a single number is not a section
# number in these documents, it is page furniture. GEN stamps every other page
# with `##### 10 December 2025`, which as a bare `\d+` reads as heading "10"
# and leaves whatever section is open -- discarding 2,531 of its facts.
_HEADING_NUM = re.compile(r'^\s{0,3}#{1,6}\s+(?:<u>\s*)?(\d+(?:\.\d+)+)')


def _leaves_section(number: str, prefix: str) -> bool:
    """True when a heading numbered `number` is outside section `prefix`.

    `2.3.2.4` is inside `2.3.2`; `2.3.3` and `2.4` are not. Used to end a
    message at its section boundary: the parser keys rows on the last
    DocumentType row it saw, and a section that never emits one would
    otherwise inherit the previous message.

    SYOG2026's ARC DD has exactly that. Section 2.3.3, "List of teams",
    carries its structure table under a heading reading "Header Values" and is
    missing the three subsections that normally follow, so it never states its
    DocumentType. The team structure was recorded as "DT_PARTIC requires
    Competition/Team (1,N)" -- a rule the other thirteen DDs state under
    DT_PARTIC_TEAMS, and one the GEN document contradicts. GEN has the same
    shape in its Team Biography section, which was inheriting DT_PDF.

    A table nobody can attribute is dropped rather than attached to whatever
    came before: a guessed key is worse than a missing one.
    """
    return number != prefix and not number.startswith(prefix + ".")


# A message named in a section's own prose, used ONLY to fill the gap a missing
# DocumentType row leaves. Scanning stops at the section's first table row, and
# a real DocumentType row always replaces whatever was recovered -- prose names
# other messages freely (the DT_PARTIC section's description mentions
# DT_PARTIC_UPDATE in passing), so this must never compete with the document
# stating its message itself.
_PROSE_DT = re.compile(r'\bDT_[A-Z0-9_]+')


# `|Element: Competition /Result (1,N)||||`, sometimes bold-wrapped by the
# converter: `**Element: Competition /Result /Composition (0,N)**`.
_ELEMENT = re.compile(r'Element:\s*\**\s*([A-Za-z0-9 /]+?)\s*(?:\(|\||\*|$)')

# `|SortOrder|M|Positive Integer|Used to sort...|`. The third group is the
# Value cell that follows the obligation: `S(21)`, `Positive Integer`,
# `CC@VENUE`, `Numeric #0.00`. Only an S(n) in it states a width.
_ATTR = re.compile(r'^\|?\s*([A-Za-z][A-Za-z0-9_]{1,30})\s*\|\s*([MO])\s*\|([^|]*)')

# `S(21)`, and the `S( 40 )` that PDF conversion also produces.
_WIDTH = re.compile(r'\bS\s*\(\s*(\d+)\s*\)')

# The bound after an element path: `(1,N)`, `(0,1)`, and the `(01,N)` and
# `( 0 , 3 )` spellings that survive conversion. N means unbounded.
_CARD = re.compile(r'\(\s*(\d+)\s*,\s*(\d+|N)\s*\)')

# Extension-style elements do not have one attribute table; they have one per
# @Code. The DD introduces them with a `Type|Code|...` header and then a row
# per code, and the attribute table that follows belongs to the code above it:
#
#   ||Type|Code|Pos|Description|
#   |ER||A B DEDUCTION|N/A|Element Expected: Always, ...|
#   ||Attribute|M/O|Value|Description|
#   ||Value|M|Numeric #0.00#|Send judges value for category A, B, ...|
#   |ER||B_JUDGE|Numeric #0|Pos Description: send judges position ...|
#   |Attribute|M/O|Value|Description|
#   |Value|M|Numeric #0.00|Send judges score for @Pos|
#   |Value2|M|Numeric #0|0 (no) and 1(yes), if the score is counting|
#
# Read flat, that says "@Value2 is mandatory on every ExtendedResult". Read as
# written, it says "@Value2 is mandatory when @Code is B_JUDGE". The flat
# reading produced 567 of the 778 findings in the real WST run of 2026-08-31 --
# 73% of the report, all false. This shape occurs 256 times across the 24
# discipline DDs, so it is the rule, not a WST quirk.
_TYPECODE_HEADER = re.compile(r'^\|+\s*Type\s*\|\s*Code\s*\|', re.IGNORECASE)

# `|ER||A B DEDUCTION|N/A|...` -- a short upper-case Type in the first cell, an
# EMPTY second cell, then the code(s). The empty cell is what separates these
# from attribute rows (`|Value|M|...`), whose second cell is always M or O.
_CODE_ROW = re.compile(r'^\|\s*([A-Z][A-Z0-9_]{0,15})\s*\|\s*\|\s*([A-Z0-9_][A-Z0-9_ ]*?)\s*\|')

# Separates the obligation from the @Code values it is conditional on, in the
# stored value: "M" (unconditional) vs "M@B_JUDGE" / "M@A B DEDUCTION".
# Encoded in the VALUE rather than the key so the committed cache
# (.dd_obligations.json, 4-element rows) keeps its format and needs no
# regeneration -- see ObligationStore._encode.
COND = "@"


def split_condition(value: str) -> tuple[str, frozenset[str]]:
    """`"M@B_JUDGE"` -> `("M", {"B_JUDGE"})`; `"M"` -> `("M", frozenset())`."""
    mo, sep, codes = value.partition(COND)
    return mo, frozenset(codes.split()) if sep else frozenset()


@dataclass
class DDFacts:
    """What one Data Dictionary states, keyed the way obligations are.

    obligations   (doc_type, element, attribute) -> "M" / "O" / "M@CODE"
    widths        (doc_type, element, attribute) -> n, from an S(n) Value cell
    cardinalities (doc_type, parent, child)      -> (min, max), max None for N
    """
    obligations: dict[tuple[str, str, str], str] = field(default_factory=dict)
    widths: dict[tuple[str, str, str], int] = field(default_factory=dict)
    cardinalities: dict[tuple[str, str, str], tuple[int, int | None]] = field(default_factory=dict)


def parse_obligations(markdown: str) -> dict[tuple[str, str, str], str]:
    """Map (doc_type, element, attribute) -> "M" or "O". See parse_dd()."""
    return parse_dd(markdown).obligations


def parse_dd(markdown: str) -> DDFacts:
    """Obligations, widths and cardinalities of one Data Dictionary.

    Rows appearing before any message header, or before any `Element:` line,
    are skipped: without both we cannot say which message or element an
    obligation belongs to, and a guessed key is worse than a missing one.

    When a DD states an obligation twice for the same key, the first wins;
    message-structure summaries repeat attribute names later in looser tables
    and re-reading them would overwrite the real value.
    """
    facts = DDFacts()
    out = facts.obligations
    doc_types: list[str] = []
    element: str | None = None
    # The @Code values governing the attribute table currently being read, or
    # None when the element states its attributes unconditionally. Reset at
    # every element and message boundary: a code block never spans them.
    codes: list[str] | None = None
    seen_typecode_header = False
    # The number of the most recent numbered heading, and the section the
    # current message belongs to (that heading's parent, recorded when the
    # DocumentType row was read). See _leaves_section.
    heading: str | None = None
    section: str | None = None
    # True from a section boundary until that section's first table row: the
    # window in which a message named in prose may stand in for a missing
    # DocumentType row.
    recovering = False
    for line in markdown.splitlines():
        numbered = _HEADING_NUM.match(line)
        if numbered:
            heading = numbered.group(1)
            if section is not None and _leaves_section(heading, section):
                doc_types, element, codes = [], None, None
                seen_typecode_header = False
                section = None
                recovering = True
            continue
        if recovering:
            if line.lstrip().startswith("|"):
                recovering = False
            else:
                # Accumulate across the whole window, not only the first line
                # that names something: a section covering a bulk message and
                # its update introduces them a paragraph apart.
                for name in _PROSE_DT.findall(line):
                    if name not in doc_types:
                        doc_types.append(name)
        found = _doc_types(line)
        if found:
            doc_types, element, codes = found, None, None
            seen_typecode_header = False
            recovering = False
            # The DocumentType row sits in a subsection of the message's own
            # section (`2.3.2.2 Header Values` under `2.3.2`), so the section
            # is that heading's parent.
            section = heading.rpartition(".")[0] if heading and "." in heading else None
            continue
        m = _ELEMENT.search(line)
        if m:
            # "Competition /Result /Composition" -> "Composition": the leaf is
            # the element the attribute actually hangs off.
            parts = [x.strip() for x in m.group(1).split('/') if x.strip()]
            element = parts[-1] if parts else None
            codes = None
            seen_typecode_header = False
            # `Competition /Entry (1,N)`: the bound belongs to the pair
            # (parent, child). A single-segment path is the document root's
            # child, which has no parent to key on and is fixed by the schema.
            bound = _CARD.search(line[m.end() - 1:])
            if bound and len(parts) >= 2 and doc_types:
                lo = int(bound.group(1))
                hi = None if bound.group(2) == "N" else int(bound.group(2))
                for dt in doc_types:
                    facts.cardinalities.setdefault((dt, parts[-2], element), (lo, hi))
            continue
        if _TYPECODE_HEADER.match(line):
            seen_typecode_header = True
            continue
        # Only trust a code row once this element has announced a Type|Code
        # table. Without that guard an ordinary row of capitalised prose could
        # silently turn a real obligation into a conditional one.
        if seen_typecode_header:
            m = _CODE_ROW.match(line)
            if m:
                codes = m.group(2).split()
                continue
        m = _ATTR.match(line)
        if m and doc_types and element:
            attr, mo = m.group(1), m.group(2)
            if attr in ("Attribute", "Element"):     # table header, not data
                continue
            value = mo if not codes else f"{mo}{COND}{' '.join(codes)}"
            width = _WIDTH.search(m.group(3) or "")
            for dt in doc_types:
                out.setdefault((dt, element, attr), value)
                if width:
                    facts.widths.setdefault((dt, element, attr), int(width.group(1)))
    return facts
