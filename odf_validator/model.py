from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Layer(str, Enum):
    STRUCTURAL = "structural"
    CODE = "code"
    SEMANTIC = "semantic"


class Scope(str, Enum):
    MESSAGE = "message"
    CONTEXT = "context"


@dataclass(frozen=True)
class Location:
    line: int | None = None
    path: str | None = None


@dataclass(frozen=True)
class Finding:
    severity: Severity
    layer: Layer
    rule_id: str
    message: str
    location: Location
    source_ref: str = ""


# Hard caps on how many findings a response can carry. A misbehaving rule (or
# a genuinely huge batch) can otherwise generate hundreds of thousands of
# findings; serializing and rendering all of them is what froze the browser
# on large .zip batch uploads (see ODF Validator freeze investigation). counts()
# always reflects the true, untruncated totals -- only the emitted findings
# list is capped, and the response says how many were left out.
#
# The emitted list is also GROUPED: findings that are identical except for
# their location (same severity/layer/rule_id/message/source_ref) are folded
# into a single entry carrying an `occurrences` count and the full `locations`
# list. This collapses e.g. 18 copies of one "@TeamType='' is invalid" error
# into one line that points at every place it occurs. The cap below applies to
# the number of GROUPS, so grouping also shrinks how often the cap is hit.
MAX_SINGLE_FINDINGS = 5000
MAX_BATCH_FINDINGS = 5000


def _group_key(f: "Finding") -> tuple:
    # Two findings fold together only when everything a reader would see is the
    # same except where it happened. Message is part of the key on purpose:
    # "@TeamType='' invalid" and "@TeamType='X' invalid" stay separate rows.
    return (f.severity.value, f.layer.value, f.rule_id, f.message, f.source_ref)


def group_findings(findings: list["Finding"]) -> list[dict]:
    """Fold identical findings into grouped dicts, preserving first-seen order.

    Each returned dict keeps the original single-finding fields (so existing
    consumers that read `location`/`rule_id`/etc. keep working) and adds:
      - `occurrences`: how many raw findings were folded in (>= 1)
      - `locations`:   every location, in first-seen order (length == occurrences)
    `location` stays as the first occurrence for backward compatibility.
    """
    order: list[tuple] = []
    groups: dict[tuple, dict] = {}
    for f in findings:
        key = _group_key(f)
        loc = {"line": f.location.line, "path": f.location.path}
        g = groups.get(key)
        if g is None:
            groups[key] = {
                "severity": f.severity.value,
                "layer": f.layer.value,
                "rule_id": f.rule_id,
                "message": f.message,
                "location": loc,
                "source_ref": f.source_ref,
                "occurrences": 1,
                "locations": [loc],
            }
            order.append(key)
        else:
            g["occurrences"] += 1
            g["locations"].append(loc)
    return [groups[k] for k in order]


@dataclass
class RunResult:
    doc_type: str | None
    discipline: str | None
    document_code: str | None
    version: int | None
    pack_name: str
    findings: list[Finding] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in Severity}
        for f in self.findings:
            out[f.severity.value] += 1
        return out

    def to_dict(self, max_findings: int | None = None) -> dict:
        # Group first, THEN cap: the cap limits the number of emitted rows, and
        # after grouping a row is a distinct defect rather than a repeat.
        groups = group_findings(self.findings)
        omitted = 0
        if max_findings is not None and len(groups) > max_findings:
            omitted = len(groups) - max_findings
            groups = groups[:max_findings]
        return {
            "doc_type": self.doc_type,
            "discipline": self.discipline,
            "document_code": self.document_code,
            "version": self.version,
            "pack_name": self.pack_name,
            "counts": self.counts(),
            "findings": groups,
            "findings_omitted": omitted,
        }


@dataclass
class BatchResult:
    results: dict[str, RunResult] = field(default_factory=dict)

    def totals(self) -> dict[str, int]:
        out = {s.value: 0 for s in Severity}
        for r in self.results.values():
            for k, v in r.counts().items():
                out[k] += v
        return out

    def to_dict(self) -> dict:
        # Budget is measured in emitted rows (i.e. groups), matching the
        # single-file cap so a huge batch can't blow the row budget.
        budget = MAX_BATCH_FINDINGS
        files = {}
        for name, r in self.results.items():
            d = r.to_dict(max_findings=max(budget, 0))
            files[name] = d
            budget -= len(d["findings"])
        return {
            "totals": self.totals(),
            "files": files,
        }
