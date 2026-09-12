from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import yaml
from ..model import Severity, Scope, Layer
from .defs_model import RuleDef, AppliesTo

_SEV = {s.value: s for s in Severity}
_SCOPE = {s.value: s for s in Scope}


def _to_rule(d: dict) -> RuleDef:
    a = d.get("applies_to", {}) or {}
    return RuleDef(
        id=d["id"],
        applies_to=AppliesTo(doc_types=list(a.get("doc_types", [])),
                             subtypes=list(a.get("subtypes", [])),
                             disciplines=list(a.get("disciplines", [])),
                             exclude_doc_types=list(
                                 a.get("exclude_doc_types", []))),
        primitive=d["primitive"],
        target=d["target"],
        attribute=d.get("attribute"),
        params=dict(d.get("params", {}) or {}),
        severity=_SEV[d.get("severity", "error")],
        scope=_SCOPE[d.get("scope", "message")],
        source_ref=d.get("source_ref", ""),
        layer=Layer.CODE if d["primitive"] == "code_membership" else Layer.SEMANTIC,
    )


def _freeze(v):
    """Hashable, order-preserving snapshot of a params value. List order is kept
    rather than sorted: two rules whose lists differ only in order are then
    treated as distinct and both survive, which is the safe direction (an extra
    rule runs) versus silently dropping a check."""
    if isinstance(v, dict):
        return tuple(sorted((k, _freeze(x)) for k, x in v.items()))
    if isinstance(v, (list, tuple, set)):
        return tuple(_freeze(x) for x in v)
    return v


def _semantic_key(r: RuleDef) -> tuple:
    """Everything that determines the finding a rule produces, EXCEPT its id and
    which messages it applies to. Two rules with the same key run the identical
    check and emit the identical finding on any node they both see.

    The key must cover EVERY param any primitive reads, not just the
    code_membership ones this dedup was originally written for -- otherwise two
    rules that differ only in, say, `regex` or `when_equals` collide and one is
    silently dropped, disabling a documented check with no error. Freezing the
    whole params dict keeps the key correct as new primitives and params are
    added, at the cost of only deduplicating byte-identical params (which is
    what the discipline-vs-GEN duplicates are)."""
    return (r.primitive, r.target, r.attribute, r.severity, r.scope,
            _freeze(r.params or {}))


def _subsumes(a: AppliesTo, b: AppliesTo,
              ignore_disciplines: bool = False) -> bool:
    """True if scope `a` covers every message scope `b` covers (a is as broad or
    broader). An empty dimension means 'any'. So a global rule ({} everywhere)
    subsumes any discipline-scoped rule with the same semantics.

    `ignore_disciplines` skips the discipline dimension, answering "would `a`
    cover everything `b` covers, for a discipline they both apply to?" -- the
    question _specialise_by_discipline needs."""
    dims = [(a.doc_types, b.doc_types), (a.subtypes, b.subtypes)]
    if not ignore_disciplines:
        dims.append((a.disciplines, b.disciplines))
    for a_dim, b_dim in dims:
        if not a_dim:                 # a matches all values of this dimension
            continue
        if not b_dim:                 # a is limited but b matches all -> no
            return False
        if not set(b_dim) <= set(a_dim):
            return False
    # Anything `a` carves out is a message `a` does not check. If `b` still
    # checks it, `a` cannot stand in for `b` and dropping `b` would lose a
    # check -- the one outcome this dedup must never produce.
    if a.exclude_doc_types:
        excluded = set(a.exclude_doc_types)
        if b.doc_types:
            if excluded & set(b.doc_types):
                return False
        elif not excluded <= set(b.exclude_doc_types):
            return False
    return True


def _dedupe_semantic(rules: list[RuleDef]) -> tuple[list[RuleDef], list[str]]:
    """Drop rules whose check is identical to, and whose scope is fully covered
    by, another loaded rule. Keeps the broadest rule in each semantic group
    (e.g. a global GEN rule over a per-discipline copy). Rules that only overlap
    partially, or differ in any finding-affecting field, are all kept."""
    dropped_ids: set[str] = set()
    notes: list[str] = []
    groups: dict[tuple, list[RuleDef]] = {}
    for r in rules:
        groups.setdefault(_semantic_key(r), []).append(r)
    for grp in groups.values():
        if len(grp) < 2:
            continue
        kept: list[RuleDef] = []
        for r in grp:
            if any(_subsumes(k.applies_to, r.applies_to) for k in kept):
                # some already-kept rule is as-broad-or-broader: r is redundant
                dominator = next(k for k in kept
                                 if _subsumes(k.applies_to, r.applies_to))
                dropped_ids.add(r.id)
                notes.append(
                    f"Rule '{r.id}' is a semantic duplicate of '{dominator.id}' "
                    f"(identical check; '{dominator.id}' covers an equal-or-"
                    f"broader scope) -- dropped so it cannot double-fire.")
                continue
            # r is not dominated; it may itself dominate earlier-kept rules
            survivors: list[RuleDef] = []
            for k in kept:
                if _subsumes(r.applies_to, k.applies_to):
                    dropped_ids.add(k.id)
                    notes.append(
                        f"Rule '{k.id}' is a semantic duplicate of '{r.id}' "
                        f"(identical check; '{r.id}' covers an equal-or-broader "
                        f"scope) -- dropped so it cannot double-fire.")
                else:
                    survivors.append(k)
            survivors.append(r)
            kept = survivors
    if not dropped_ids:
        return rules, notes
    return [r for r in rules if r.id not in dropped_ids], notes


def _specialisation_key(r: RuleDef) -> tuple:
    """What makes two rules "the same check in the same place", ignoring how
    they judge it. Deliberately excludes params: rules that agree on params are
    handled by _dedupe_semantic, and it is precisely the params disagreement
    (ENG_shortDescription vs ENG_Description) that specialisation resolves."""
    return (r.primitive, r.target, r.attribute)


def _specialise_by_discipline(
        rules: list[RuleDef]) -> tuple[list[RuleDef], list[str]]:
    """Where a discipline rule specialises a generic one, stand the generic
    rule down for that discipline.

    A discipline Data Dictionary that redefines how an attribute is validated
    is the authority for its own discipline; the GEN rule remains authoritative
    everywhere else. Without this the two both fire and the generic one is
    wrong by construction -- GEN_SUBEVENTNAME_CODE produced 370 of 375 warnings
    in a swimming run review, every one of them a value the SWM DD blesses.

    The generic rule is only stood down where the discipline rule genuinely
    stands in for it: the specialist must cover every document type and subtype
    the generic covers. GEN_DOCUMENTSUBCODE_POSINT (DT_PRESSPHOTOFINISH_LK,
    DT_COMMUNICATION) and ATH_DOCUMENTSUBCODE_POSINT (DT_IMAGE) share a
    primitive, target and attribute but are disjoint in doc_types, so the ATH
    rule does not displace the generic one and both keep running."""
    groups: dict[tuple, list[RuleDef]] = {}
    for r in rules:
        groups.setdefault(_specialisation_key(r), []).append(r)
    notes: list[str] = []
    carved: dict[str, list[str]] = {}
    for grp in groups.values():
        generics = [r for r in grp if not r.applies_to.disciplines]
        specials = [r for r in grp if r.applies_to.disciplines]
        if not generics or not specials:
            continue
        for g in generics:
            for s in specials:
                if not _subsumes(s.applies_to, g.applies_to,
                                 ignore_disciplines=True):
                    continue
                added = [d for d in s.applies_to.disciplines
                         if d not in carved.get(g.id, [])]
                if not added:
                    continue
                carved.setdefault(g.id, []).extend(added)
                notes.append(
                    f"Rule '{g.id}' stands down for {', '.join(added)}: "
                    f"'{s.id}' specialises the same check there "
                    f"(discipline Data Dictionary wins over GEN).")
    if not carved:
        return rules, notes
    out: list[RuleDef] = []
    for r in rules:
        if r.id in carved:
            r = replace(r, applies_to=replace(
                r.applies_to,
                exclude_disciplines=list(r.applies_to.exclude_disciplines)
                + carved[r.id]))
        out.append(r)
    return out, notes


def load_rule_defs(
    paths: list[Path], allow_core: bool = False, resolve_codeset=None,
    drop_unresolvable_codesets: bool = False
) -> tuple[list[RuleDef], list[str], list[str], list[str]]:
    """Returns (rules, errors, conflicts, deduped, specialised).

    `resolve_codeset`, when given, maps a codeset name as the Data Dictionary
    cites it to the name the pack's code tables actually use (see
    CodeRegistry.resolve). It is applied HERE, before the dedup below, and not
    by the caller afterwards: _semantic_key freezes the whole params dict, so
    a GEN rule reading WIND_DIRECTION and its discipline copy reading
    WINDDIRECTION are two different checks to the dedup and both survive --
    two warnings for one bad value, which is the double-firing the dedup
    exists to prevent.

    `drop_unresolvable_codesets` removes rules whose codeset does not resolve
    at all, and it has to happen here too, for a second ordering reason:
    _specialisation_key is (primitive, target, attribute) with params
    EXCLUDED, so a discipline rule with a dead codeset still counts as
    specialising the GEN rule and stands it down for that discipline. Drop it
    in the caller afterwards and the discipline is left with no check at all
    -- neither the dropped rule nor the GEN rule it displaced. That is what
    13 SHEDULESTATUS rules did to @SessionStatus across 13 disciplines.
    Pass it only when the pack actually has code tables to judge against; a
    pack with none cannot tell a dead codeset from an unloaded workbook.

    `conflicts` are collisions a human must resolve (two files claiming
    one rule id). `deduped` is routine, lossless housekeeping: a rule
    dropped because another loaded rule performs the identical check over
    an equal-or-broader scope. The two are kept apart deliberately --
    merging them made a clean pack report "405 rule conflict(s)", since
    discipline rulesets legitimately re-declare the global GEN checks."""
    rules: list[RuleDef] = []
    errors: list[str] = []
    conflicts: list[str] = []
    seen: dict[str, str] = {}  # rule id -> name of the file that first defined it
    for p in paths:
        try:
            data = yaml.safe_load(Path(p).read_text(encoding="utf-8")) or []
            if not isinstance(data, list):
                errors.append(f"Rule file {Path(p).name}: expected a list of rules.")
                continue
            for i, d in enumerate(data):
                try:
                    rule = _to_rule(d)
                except Exception as e:
                    errors.append(f"Rule file {Path(p).name} entry {i}: {e}")
                    continue
                if not allow_core and rule.id.startswith("CORE_"):
                    errors.append(
                        f"Rule file {Path(p).name}: id '{rule.id}' uses the "
                        f"reserved CORE_ prefix (engine core rules only); "
                        f"rule dropped.")
                    continue
                if rule.id in seen:
                    # First occurrence wins deterministically; the duplicate is
                    # dropped (not appended) so it can never double-fire in the
                    # runner, and the collision is surfaced for a human to
                    # resolve (e.g. a hand-authored rule now duplicated by an
                    # approved draft extracted from the same field).
                    conflicts.append(
                        f"Rule id '{rule.id}' defined in both {seen[rule.id]} and "
                        f"{Path(p).name} (first-wins) -- kept the one from {seen[rule.id]}."
                    )
                    continue
                if resolve_codeset is not None:
                    cs = rule.params.get("codeset")
                    if cs:
                        real = resolve_codeset(cs)
                        if real:
                            rule.params["codeset"] = real
                seen[rule.id] = Path(p).name
                rules.append(rule)
        except Exception as e:
            errors.append(f"Failed to read rule file {Path(p).name}: {e}")
    # Dead rules go first, before either dedup or specialisation can treat one
    # as standing in for a rule that works. See the docstring.
    if resolve_codeset is not None and drop_unresolvable_codesets:
        alive: list[RuleDef] = []
        for rule in rules:
            cs = rule.params.get("codeset")
            if cs and resolve_codeset(cs) is None:
                errors.append(
                    f"Rule {rule.id}: codeset '{cs}' is not provided by this "
                    f"pack's code tables under any spelling; the rule was "
                    f"dropped rather than left active and permanently silent.")
                continue
            alive.append(rule)
        rules = alive
    # Cross-pack deduplication: discipline rulesets re-declare the global GEN
    # code-membership checks almost verbatim (a rules review found 408 of 457
    # discipline rules were exact GEN duplicates). Both copies load with
    # distinct ids, so id-dedup above cannot catch them; drop the redundant
    # ones by semantics + scope subsumption here.
    rules, dedupe_notes = _dedupe_semantic(rules)
    # Specialisation runs after dedup: identical checks are already collapsed,
    # so anything still colliding here differs in params -- the case where the
    # discipline rule must win locally rather than one copy being dropped.
    rules, spec_notes = _specialise_by_discipline(rules)
    return rules, errors, conflicts, dedupe_notes, spec_notes
