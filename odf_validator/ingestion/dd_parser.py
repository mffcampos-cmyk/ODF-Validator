from __future__ import annotations
import re
from dataclasses import dataclass

_WS = re.compile(r"\s+")
_CC_LINE = re.compile(
    r"^(?P<field>[A-Za-z][A-Za-z0-9_]*) [MO] CC@(?P<codeset>[A-Za-z0-9_]+) (?P<comment>.+)$"
)
_POSINT_LINE = re.compile(
    r"^(?P<field>[A-Za-z][A-Za-z0-9_]*) Positive Integer (?P<comment>.+)$"
)

# DD field names whose GENERIC value check is owned by the immutable core layer
# (odf_validator/core_rules/core.yaml). Re-extracting them for a generic (GEN)
# pack would duplicate a CORE_ rule and wrongly plant an engine-wide check in a
# game pack, so the generic parser skips them. e.g. Version -> CORE_VERSION_POSINT.
# Discipline-scoped DDs may still restate the check (that stays as <DISC>_...).
_CORE_OWNED_GENERIC_VALUE_ATTRS = frozenset({"Version"})

# DD "field" names whose meaning (which codeset, whether numeric) depends on the
# element/context they appear in, so an unscoped .//*[@X] rule matches unrelated
# elements and floods the report with false positives:
#   Code, Value  -> generic containers (codeset depends on a sibling Type)
#   Sport        -> a version string on <Competition> ("SOG-2024-BKG-1.1"), a
#                   sport code only elsewhere
#   Gender       -> PERSON_GENDER on a participant but SPORT_GENDER (M/W/O/...) on
#                   an event/SportDescription
# The primitives can't express the context, so these are not turned into rules at
# all (any discipline). Precise checks for them must be hand-authored with a
# context-scoped target.
_UNSCOPED_GENERIC_ATTRS = frozenset({"Code", "Value", "Sport", "Gender"})


@dataclass
class DraftRule:
    id: str
    applies_to: dict
    primitive: str
    target: str
    attribute: str | None
    params: dict
    severity: str
    scope: str
    source_ref: str
    status: str = "draft"

    def to_yaml_dict(self) -> dict:
        return {
            "id": self.id, "applies_to": self.applies_to, "primitive": self.primitive,
            "target": self.target, "attribute": self.attribute, "params": self.params,
            "severity": self.severity, "scope": self.scope,
            "source_ref": self.source_ref, "status": self.status,
        }


def _normalize_line(raw: str) -> str:
    line = raw.strip()
    if line.startswith("|") and line.endswith("|"):
        cells = [c.strip() for c in line.strip("|").split("|")]
        line = " ".join(c for c in cells if c and set(c) != {"-"})
    return _WS.sub(" ", line).strip()


def extract_draft_rules(markdown_text: str, discipline: str | None,
                         source_name: str) -> list[DraftRule]:
    """Scan converted Markdown for the two mechanically-detectable Data
    Dictionary patterns the engine's rule primitives can express faithfully:

    - `<Field> M|O CC@<SET> <comment>` -> code_membership (same shape as the
      hand-authored GEN_VENUE_CODE rule).
    - `<Field> Positive Integer <comment>` -> value_format regex ^[0-9]+$
      (same shape as the hand-authored GEN_ITEMNUM_INT rule).

    The bare M/O flag itself is NOT turned into a rule: unconditional presence
    is the XSD's job, and the engine's conditional_presence primitive requires
    a triggering field (when_attr/when_equals) that a bare M/O flag doesn't
    carry. Anything else (free-form conditional prose, cross-field/cross-
    message logic) is left unextracted rather than guessed.

    DESIGN NOTE on id normalization and attribute casing:
    The rule id is normalized to uppercase (matching this codebase's id convention,
    e.g. GEN_VENUE_CODE) while `attribute`/`target` preserve the DD's exact source
    casing for field_name: XML attribute names are case-sensitive, so `attribute`
    must match the real XML exactly (e.g. "Venue", not "VENUE") or the rule would
    silently never fire. DD source documents are expected to use the correct,
    consistent XML casing already. The codeset is also normalized to uppercase
    before lookup in CodeRegistry, which keys tables by uppercase sheet names
    (e.g. VENUE, COUNTRY) matching Excel sheet titles convention.
    """
    prefix = discipline if discipline else "GEN"
    applies_to = {"disciplines": [discipline]} if discipline else {}
    drafts: list[DraftRule] = []
    seen: set[tuple[str, str]] = set()

    for lineno, raw in enumerate(markdown_text.splitlines(), start=1):
        line = _normalize_line(raw)
        if not line:
            continue

        m = _CC_LINE.match(line)
        if m:
            field_name, codeset, comment = m.group("field", "codeset", "comment")
            # *Name fields hold the ENG description (the DD annotates them
            # "... Description (not code) from Common Codes"), e.g. VenueName=
            # "Tokyo Metropolitan Gym" vs the code Venue="TGY". Checking the
            # description against the code set flags every real value, so skip
            # any field whose name ends in "Name".
            if field_name.endswith("Name"):
                continue
            # Context-dependent attributes can't be validated by an unscoped
            # code_membership rule (see _UNSCOPED_GENERIC_ATTRS): skip them.
            if field_name in _UNSCOPED_GENERIC_ATTRS:
                continue
            codeset = codeset.upper()
            rule_id = f"{prefix}_{field_name}_CODE".upper()
            key = (rule_id, field_name)
            if key not in seen:
                seen.add(key)
                drafts.append(DraftRule(
                    id=rule_id, applies_to=applies_to, primitive="code_membership",
                    target=f".//*[@{field_name}]", attribute=field_name,
                    params={"codeset": codeset}, severity="warning", scope="message",
                    source_ref=f"{source_name} line {lineno}: {comment}",
                ))
            continue

        m = _POSINT_LINE.match(line)
        if m:
            field_name, comment = m.group("field", "comment")
            # Same generic-container guard as the code branch: an unscoped
            # .//*[@Value] positive-integer rule flags every non-numeric @Value.
            if field_name in _UNSCOPED_GENERIC_ATTRS:
                continue
            # Generic value checks that core already owns must not be re-emitted
            # as GEN_ pack rules (they duplicate a CORE_ rule). Discipline DDs
            # may still restate them under their own <DISC>_ id.
            if discipline is None and field_name in _CORE_OWNED_GENERIC_VALUE_ATTRS:
                continue
            rule_id = f"{prefix}_{field_name}_POSINT".upper()
            key = (rule_id, field_name)
            if key not in seen:
                seen.add(key)
                drafts.append(DraftRule(
                    id=rule_id, applies_to=applies_to, primitive="value_format",
                    target=f".//*[@{field_name}]", attribute=field_name,
                    params={"regex": "^[0-9]+$"}, severity="error", scope="message",
                    source_ref=f"{source_name} line {lineno}: {comment}",
                ))

    return drafts
