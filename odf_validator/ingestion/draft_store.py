from __future__ import annotations
from pathlib import Path
import yaml


def draft_path_for(dd_path: Path) -> Path:
    # Use the full filename (dd_path.name), not just the stem: two DDs that
    # differ only by extension (e.g. a re-supplied ARC_DD.pdf replacing an
    # ARC_DD.md) must not collide on the same draft/active file.
    return dd_path.parent / ".drafts" / f"{dd_path.name}.draft.yaml"


def active_path_for(dd_path: Path) -> Path:
    return dd_path.parent / "rules" / f"{dd_path.name}.yaml"


class RefinementLoss(Exception):
    """Approving this draft would silently discard hand-made rule refinements.

    Drafts are re-derived from the Data Dictionary every time the DD changes,
    and approving one overwrites the active rule of the same id wholesale. Any
    parameter added by hand after the last derivation is therefore dropped
    without a word.

    That is not hypothetical. Refreshing the WST DD on 2026-09-01 regenerated
    its drafts, and approving them reverted every fix made that month:

        WST_UNIT_CODE      exclude_tags [Precipitation, Pressure, Temperature, Wind]
        WST_STATUS_CODE    exclude_tags [Protest]
        WST_FUNCTION_CODE  exclude_tags [Presenter]
        WST_VENUE_CODE     allow [TBD]
        WST_LOCATION_CODE  allow [TBD]

    Nothing reported it. The five rules stopped matching their GEN
    counterparts, stopped being deduped, and the active count rose from 88 to
    93 -- the only visible trace, and only to someone who happened to look.

    Carries the delta so the caller can say exactly what would go.
    """

    def __init__(self, rule_id: str, delta: dict):
        self.rule_id = rule_id
        self.delta = delta
        lost = ", ".join(f"{k}={v!r}" for k, v in delta["dropped"].items())
        super().__init__(
            f"Approving '{rule_id}' would drop parameters set by hand on the "
            f"active rule: {lost}. Approve with confirmation to proceed.")


# Fields compared when deciding whether a draft changes an active rule. `params`
# is treated key-by-key (see rule_delta); the rest are compared whole.
_COMPARED_FIELDS = ("primitive", "target", "attribute", "severity", "scope",
                    "applies_to")


def rule_delta(active: dict | None, draft: dict) -> dict:
    """What approving `draft` would change about `active`.

    `dropped` is the dangerous set: parameters the active rule carries that the
    draft does not mention at all. Those are almost always deliberate
    refinements, because the derivation that produced the draft cannot invent
    them -- it only ever emits what the DD literally states.
    """
    if active is None:
        return {"new": True, "dropped": {}, "changed": {}, "added": {}, "fields": {}}

    a_params = active.get("params") or {}
    d_params = draft.get("params") or {}
    return {
        "new": False,
        "dropped": {k: v for k, v in a_params.items() if k not in d_params},
        "changed": {k: (a_params[k], d_params[k]) for k in a_params
                    if k in d_params and a_params[k] != d_params[k]},
        "added": {k: v for k, v in d_params.items() if k not in a_params},
        "fields": {f: (active.get(f), draft.get(f)) for f in _COMPARED_FIELDS
                   if active.get(f) != draft.get(f)},
    }


def active_rule(draft_file: Path, rule_id: str) -> dict | None:
    """The live rule this draft would replace, or None if it is new."""
    active_file = active_path_for(_dd_path_from_draft_file(draft_file))
    if not active_file.exists():
        return None
    for entry in yaml.safe_load(active_file.read_text(encoding="utf-8")) or []:
        if entry.get("id") == rule_id:
            return entry
    return None


def _dd_path_from_draft_file(draft_file: Path) -> Path:
    """Reverse draft_path_for: recover the original DD source path from its
    .drafts/<name>.draft.yaml file, so active_path_for can be reused as the
    single source of truth for the draft <-> active naming convention."""
    dd_name = draft_file.name.removesuffix(".draft.yaml")
    return draft_file.parent.parent / dd_name


def _require_inside(path: Path, rules_root: Path | None) -> Path:
    """Resolve `path` and refuse anything outside `rules_root`.

    approve/reject take their path from a form field. Without this, reject
    deletes any file that parses as a YAML list of mappings with `id` keys --
    the shape of the app's own rule files -- and approve writes into any
    directory, creating parents (a security review, finding S-H1).

    `rules_root=None` keeps the unchecked behaviour for internal callers that
    built the path themselves.
    """
    resolved = path.resolve()
    if rules_root is None:
        return resolved
    root = rules_root.resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"Draft path is outside the rules folder: {path}")
    if not resolved.name.endswith(".draft.yaml") or resolved.parent.name != ".drafts":
        raise ValueError(f"Not a draft file: {path}")
    return resolved


def write_drafts(dd_path: Path, draft_dicts: list[dict]) -> Path:
    path = draft_path_for(dd_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(draft_dicts, sort_keys=False), encoding="utf-8")
    return path


def list_all_drafts(rules_root: Path) -> list[dict]:
    out: list[dict] = []
    for draft_file in sorted(rules_root.rglob(".drafts/*.draft.yaml")):
        entries = yaml.safe_load(draft_file.read_text(encoding="utf-8")) or []
        for entry in entries:
            entry = dict(entry)
            entry["_draft_file"] = str(draft_file)
            out.append(entry)
    return out


def approve_draft(draft_file: Path, rule_id: str, *,
                  rules_root: Path | None = None,
                  allow_loss: bool = False) -> dict:
    """Promote a draft to an active rule. Returns the delta that was applied.

    Refuses with RefinementLoss when the draft would drop a parameter the
    active rule carries, unless `allow_loss` says the caller has seen the
    delta and accepts it. See RefinementLoss for why.
    """
    draft_file = _require_inside(draft_file, rules_root)
    entries = yaml.safe_load(draft_file.read_text(encoding="utf-8")) or []
    keep, approved = [], None
    for entry in entries:
        if entry["id"] == rule_id:
            approved = dict(entry)
        else:
            keep.append(entry)
    if approved is None:
        raise KeyError(f"No draft rule '{rule_id}' in {draft_file}")
    approved["status"] = "active"

    delta = rule_delta(active_rule(draft_file, rule_id), approved)
    if delta["dropped"] and not allow_loss:
        raise RefinementLoss(rule_id, delta)

    dd_path = _dd_path_from_draft_file(draft_file)
    active_file = active_path_for(dd_path)
    active_file.parent.mkdir(parents=True, exist_ok=True)
    active_entries = (yaml.safe_load(active_file.read_text(encoding="utf-8"))
                       if active_file.exists() else None) or []
    active_entries = [e for e in active_entries if e["id"] != rule_id]
    active_entries.append(approved)
    active_file.write_text(yaml.safe_dump(active_entries, sort_keys=False), encoding="utf-8")

    if keep:
        draft_file.write_text(yaml.safe_dump(keep, sort_keys=False), encoding="utf-8")
    else:
        draft_file.unlink()
    return delta


def approve_all_drafts(rules_root: Path, *,
                       allow_loss: bool = False) -> tuple[list[str], list[dict]]:
    """Approve every draft, returning `(approved_ids, skipped)`.

    Drafts that would discard hand-made refinements are SKIPPED rather than
    applied, and reported in `skipped`. Approve-all is the operation that lost
    five WST refinements on 2026-09-01 -- it is exactly the path where nobody
    is looking at individual rules, so it must be the one that fails safe.
    Pass `allow_loss=True` only when the caller has shown the deltas.
    """
    approved_ids: list[str] = []
    skipped: list[dict] = []
    for entry in list_all_drafts(rules_root):
        try:
            approve_draft(Path(entry["_draft_file"]), entry["id"],
                          allow_loss=allow_loss)
        except RefinementLoss as loss:
            skipped.append({"rule_id": loss.rule_id, "delta": loss.delta,
                            "draft_file": entry["_draft_file"]})
            continue
        approved_ids.append(entry["id"])
    return approved_ids, skipped


def reject_draft(draft_file: Path, rule_id: str, *,
                 rules_root: Path | None = None) -> None:
    draft_file = _require_inside(draft_file, rules_root)
    entries = yaml.safe_load(draft_file.read_text(encoding="utf-8")) or []
    keep = [entry for entry in entries if entry["id"] != rule_id]
    if len(keep) == len(entries):
        raise KeyError(f"No draft rule '{rule_id}' in {draft_file}")
    if keep:
        draft_file.write_text(yaml.safe_dump(keep, sort_keys=False), encoding="utf-8")
    else:
        draft_file.unlink()
