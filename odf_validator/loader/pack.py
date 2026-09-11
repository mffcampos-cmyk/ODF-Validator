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
