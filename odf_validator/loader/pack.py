from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from ..codes.tables import CodeRegistry


@dataclass
class LoadReport:
    loaded_files: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # Rules dropped as redundant duplicates of a broader rule. Informational:
    # nothing is lost, so this must never be presented as a fault.
    deduped: list[str] = field(default_factory=list)
    # Generic rules stood down for a discipline that specialises them. Like
    # `deduped` this is informational, not a fault: the check still runs, the
    # discipline's own version of it does. Kept separate from `deduped`
    # because nothing was merged and nothing was lost.
    specialised: list[str] = field(default_factory=list)
    # Data Dictionaries that could not be converted to Markdown. Not a rule
    # failure: the ruleset loads intact and only this DD's obligations and
    # draft suggestions are unavailable. Kept off `errors` because the UI
    # renders that list as "N rule(s) failed to load", which was untrue and
    # alarming when a missing PDF converter produced 24 of them.
    dd_unconvertible: list[str] = field(default_factory=list)
    # Data Dictionaries converted by the fallback backend. Not a failure: the
    # DD converted and its rules loaded. But dd_parser's regexes are tuned to
    # pdf-inspector's Markdown shape, so obligations parsed from markitdown
    # output deserve a second look. Kept off `errors`, which the UI renders
    # as "N rule(s) failed to load".
    converted_by_fallback: list[str] = field(default_factory=list)
    # Obligation-cache integrity problems: e.g. a scan that could not account
    # for a cached DD, so the cache was left intact rather than pruned. This
    # is neither a rule-load failure nor cosmetic bookkeeping -- no rule
    # failed to load, but DD-over-XSD authority may be running on stale
    # data. Kept off `errors` for the same reason as `dd_unconvertible`: the
    # UI renders `errors` as "N rule(s) failed to load", which is untrue here
    # and (for a cache whose keys can never again match, e.g. after a DD
    # filename migration) would alarm on every single load with a remedy
    # that can never resolve it.
    cache_warnings: list[str] = field(default_factory=list)
    # Data Dictionary lines that asked for a codeset the Common Codes do not
    # provide under any spelling, so no draft rule was offered for them. Not
    # a rule failure -- no rule exists to fail -- and not silent either: the
    # document said something the workbook cannot support, and only a human
    # can decide whether the document, the workbook or the attribute is at
    # fault. Before this, such lines became drafts, were approved, and were
    # then dropped at load on every start, with every import putting them
    # back (17 of them after the 2026-09-11 import).
    unmatched_codesets: list[str] = field(default_factory=list)
    # Why this ruleset has no compiled schema underneath its rules: no XSD in
    # the tree at all (the normal state of a fresh clone of the public
    # repository, which ships the authored rules but not the IOC documents),
    # a pack.yaml root_xsd naming a file that is not there, or an XSD that
    # would not compile. Every rule still loads and runs; they just run
    # without a schema beneath them.
    #
    # Off `errors` for the fourth time now, and for the same reason as
    # dd_unconvertible, cache_warnings and unmatched_codesets: the UI renders
    # that list as "N rule(s) failed to load", and here no rule failed, none
    # had even been read yet. The counterpart mistake is silence -- a pack
    # that validates nothing while saying nothing is how "@Class is validated
    # by nothing" survived for months -- so this is reported, just truthfully.
    schema_unavailable: list[str] = field(default_factory=list)
    # The Common Codes workbook is not in this ruleset, so every
    # code_membership rule is inert. Same first-launch state as
    # schema_unavailable and the same reason it is not on `errors`: the
    # rules loaded, all of them, and the rule count says so in the same
    # breath. ONE note, not one per rule: with no tables at all every
    # code_membership rule is affected without exception, so the set is
    # derivable and the count is the useful part -- the 52 lines this
    # replaced differed only by rule id and shared one cause and one
    # remedy. Per-rule naming stays on `errors` for the case that earns
    # it: tables present, one rule naming a codeset they do not provide.
    codes_unavailable: list[str] = field(default_factory=list)


@dataclass
class RulePack:
    name: str
    version: str
    xsd_paths: list[Path]
    root_xsd: Path | None
    schema: object  # compiled lxml XMLSchema, or None if it failed to compile
    codes: CodeRegistry
    rules: list
    disciplines: list[str]
    report: LoadReport
    # Attribute obligations from the Data Dictionaries, with the DD-over-XSD
    # authority chain applied. See odf_validator/rules/obligations.py.
    obligations: object = None
    # (element, attribute) pairs the pack exempts from DD width enforcement:
    # rows whose DD entry states both an S(n) and a Common Codes description
    # (pack.yaml `length_exempt`, e.g. "ItemName/@Value"). See
    # pipeline/width_check.py.
    length_exempt: frozenset = frozenset()


def ruleset_summary(packs: dict) -> list[dict]:
    """Turn the app's PACKS dict into template-ready summaries for a
    'current rulesets and disciplines' overview page. Sorted by name so the
    page has a stable order regardless of dict insertion order."""
    return [{
        "name": pack.name,
        "version": pack.version,
        "disciplines": pack.disciplines,
        "rule_count": len(pack.rules),
        "error_count": len(pack.report.errors),
        "cache_warning_count": len(pack.report.cache_warnings),
    } for pack in sorted(packs.values(), key=lambda p: p.name)]
