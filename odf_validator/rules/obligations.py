"""Who decides whether an attribute is mandatory.

Authority order, highest first:

  1. the discipline Data Dictionary
  2. the GEN Data Dictionary
  3. the XSD

This lives in the engine rather than in a pack because it is not a SYOG26
policy -- it follows from what each source can express. A sport DD states an
obligation for one discipline and one message: the most specific statement
available. The GEN DD covers messages a sport DD does not define. The XSD comes
last because it is message-blind: `odf2-structure.xsd` declares a single
`competitionType` used by every message, so `use="required"` on
`Competition/@Gen` is asserted for DT_ENTRIES and DT_RESULT simultaneously.
All 25 SYOG26 discipline DDs say `Gen` is mandatory for DT_ENTRIES and optional
elsewhere; the schema has no way to say that, so it cannot be the authority
(survey 2026-08-14).

Everything is keyed on `(doc_type, element, attribute)`. Attribute name alone is
never enough -- `Code` is required on 83 complexTypes, so an obligation recorded
for one element must never answer for another.
"""
from __future__ import annotations

Key = tuple[str, str, str]        # (doc_type, element, attribute)
Pair = tuple[str, str]            # (element, attribute)


def _disc(value: str | None) -> str:
    """Normalise a discipline to its three-letter code.

    `dispatch()` reports whatever `Competition/Discipline/@Code` holds, and in
    ODF that is a full 34-character RSC ("SWM" followed by 31 dashes); only
    messages without a Discipline element fall back to the bare three letters.
    Both spellings must resolve to the same obligations.
    """
    return (value or "")[:3]


class ObligationRegistry:
    """Resolves attribute obligations across the DD/XSD authority chain."""

    def __init__(self, xsd_required: set[Pair] | None = None,
                 xsd_declared: set[Pair] | None = None,
                 xsd_unambiguous: set[Pair] | None = None):
        # (element, attribute) pairs the schema marks use="required". Doc-type
        # blind by construction -- see the module docstring.
        self._xsd: set[Pair] = set(xsd_required or ())
        # Every (element, attribute) the schema declares at all, required or
        # not. Used to discard obligations that cannot be right.
        self._declared: set[Pair] = set(xsd_declared or ())
        # Pairs safe to ENFORCE: the element name maps to exactly one
        # complexType, and the attribute is declared on exactly one element in
        # the schema. See mandatory_attrs(enforceable_only=True).
        self._unambiguous: set[Pair] = set(xsd_unambiguous or ())
        self._disciplines: dict[str, dict[Key, str]] = {}
        self._general: dict[Key, str] = {}

    def _keep(self, obligations: dict[Key, str]) -> dict[Key, str]:
        """Drop rows the schema says are impossible.

        Data Dictionary tables are read from converted PDF text, where a
        nested element's table can interrupt its parent's and make document
        order a poor guide to which element an attribute belongs to. When the
        schema declares no such attribute on that element the row is provably
        mis-attributed (279 rows across the SYOG26 DDs) and is better dropped
        than trusted.

        This is a floor, not a guarantee: `Result` and `ExtendedResult` both
        declare @SortOrder, so a swap between them survives this filter. That
        residual risk is why DD-mandatory *enforcement* is not enabled --
        inventing a mandatory attribute produces findings on every matching
        element in every file, which is the failure mode this project has
        already paid for once.
        """
        if not self._declared:
            return dict(obligations)
        return {(dt, el, at): mo for (dt, el, at), mo in obligations.items()
                if (el, at) in self._declared}

    def add_discipline(self, discipline: str, obligations: dict[Key, str]) -> None:
        self._disciplines.setdefault(_disc(discipline), {}).update(self._keep(obligations))

    def set_general(self, obligations: dict[Key, str]) -> None:
        self._general = self._keep(obligations)

    def disciplines(self) -> list[str]:
        return sorted(self._disciplines)

    def resolve(self, discipline: str | None, doc_type: str | None,
                element: str, attribute: str) -> str | None:
        """"M", "O", or None when no source says anything.

        None is not "optional": it means unknown. Callers that suppress on "O"
        must not also suppress on None, or an attribute no DD happens to mention
        would quietly stop being checked.
        """
        key = (doc_type, element, attribute)
        disc = self._disciplines.get(_disc(discipline), {})
        if key in disc:
            return disc[key]
        if key in self._general:
            return self._general[key]
        if (element, attribute) in self._xsd:
            return "M"
        return None

    def mandatory_attrs(self, discipline: str | None, doc_type: str | None,
                        enforceable_only: bool = False) -> set[Pair]:
        """(element, attribute) pairs this message must carry per the DDs.

        Used to enforce obligations the XSD leaves optional -- 65 such pairs
        across the SYOG26 DDs, including Result/@SortOrder (mandatory in all 25
        discipline DDs, optional in the schema).

        The GEN DD contributes only where the sport DD is silent on that exact
        key, so a sport DD downgrading an attribute to "O" is respected rather
        than being overridden by the more general document.
        """
        # `mo == "M"` deliberately excludes conditional obligations
        # ("M@B_JUDGE"): those are not mandatory on every node of the element,
        # so enforcing them unconditionally is the 2026-08-31 false-positive
        # class. conditional_mandatory_attrs() reports them separately.
        disc = self._disciplines.get(_disc(discipline), {})
        out = {(e, a) for (dt, e, a), mo in disc.items()
               if dt == doc_type and mo == "M"}
        for (dt, e, a), mo in self._general.items():
            if dt != doc_type or mo != "M":
                continue
            if (dt, e, a) in disc:      # sport DD already ruled on this key
                continue
            out.add((e, a))
        if enforceable_only:
            # Enforcing is far less forgiving than suppressing. A wrong
            # suppression hides one finding; a wrong mandatory attribute fires
            # on every matching element in every file -- on the real
            # 2026-06-05 corpus two mis-attributed rows would have produced
            # 38,648 findings, and a single ambiguous element name
            # (<Description>, 13 complexTypes) produced 5,419. So only pairs
            # the schema can prove unambiguous are enforced. Empty schema
            # information means nothing qualifies: fail closed.
            out &= self._unambiguous
            # Anything the schema already requires is the schema's to report.
            # Without this, a missing Competition/@Gen in a DT_ENTRIES message
            # produces both XSD_INVALID and CORE_DD_MANDATORY_ATTR -- on the
            # real corpus that doubled 539 errors to 1,062 with no new
            # information. Enforcement exists for the gap the schema leaves.
            out -= self._xsd
        return out

    def conditional_mandatory_attrs(
            self, discipline: str | None, doc_type: str | None,
            enforceable_only: bool = False) -> dict[Pair, frozenset[str]]:
        """`{(element, attribute): {code, ...}}` for obligations a DD states
        only for particular `@Code` values.

        Extension-style elements carry one attribute table per `@Code`, so
        "mandatory" there means "mandatory on nodes with this @Code" -- see
        ingestion/dd_obligations.py. Enforcing such a row on every node of the
        element is what produced 567 of 778 findings in the real WST run of
        2026-08-31. Precedence and the enforceable_only restrictions match
        mandatory_attrs(); the two sets are disjoint by construction.
        """
        from ..ingestion.dd_obligations import split_condition

        disc = self._disciplines.get(_disc(discipline), {})
        out: dict[Pair, frozenset[str]] = {}

        def add(element: str, attribute: str, codes: frozenset[str]) -> None:
            out[(element, attribute)] = out.get((element, attribute), frozenset()) | codes

        for (dt, e, a), value in disc.items():
            if dt != doc_type:
                continue
            mo, codes = split_condition(value)
            if mo == "M" and codes:
                add(e, a, codes)
        for (dt, e, a), value in self._general.items():
            if dt != doc_type or (dt, e, a) in disc:
                continue
            mo, codes = split_condition(value)
            if mo == "M" and codes:
                add(e, a, codes)

        if enforceable_only:
            out = {pair: codes for pair, codes in out.items()
                   if pair in self._unambiguous and pair not in self._xsd}
        return out
