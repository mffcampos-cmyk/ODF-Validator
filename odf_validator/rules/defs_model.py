from __future__ import annotations
from dataclasses import dataclass, field
from ..model import Severity, Scope, Layer


@dataclass
class AppliesTo:
    doc_types: list[str] = field(default_factory=list)   # empty = any
    subtypes: list[str] = field(default_factory=list)    # empty = any
    disciplines: list[str] = field(default_factory=list)  # empty = any
    # Carve-outs from an otherwise universal rule. Prefer this over listing
    # every included DocumentType: an exclusion list fails closed, so a
    # DocumentType added to the schema later inherits the check instead of
    # silently escaping it. Applied after the include lists above.
    exclude_doc_types: list[str] = field(default_factory=list)
    # Disciplines carved out because a discipline-specific rule specialises
    # this one there (see loader._specialise_by_discipline). Populated by the
    # loader, not by rule YAML.
    exclude_disciplines: list[str] = field(default_factory=list)


@dataclass
class RuleDef:
    id: str
    applies_to: AppliesTo
    primitive: str
    target: str
    attribute: str | None
    params: dict
    severity: Severity
    scope: Scope
    source_ref: str
    layer: Layer = Layer.SEMANTIC
