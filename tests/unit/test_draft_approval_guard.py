"""Approving a regenerated draft must not silently discard refinements.

Drafts are re-derived from the Data Dictionary whenever the DD changes, and
approving one overwrites the active rule of the same id wholesale. Any
parameter added by hand after the last derivation is dropped without a word.

Refreshing the WST DD on 2026-09-01 did exactly that, reverting every fix made
that month -- the weather exclusion on WST_UNIT_CODE, the Protest and Presenter
exclusions, and `allow: [TBD]` on the venue and location rules. Nothing
reported it; the only trace was the active rule count moving 88 -> 93, because
the stripped rules stopped matching their GEN counterparts and stopped being
deduped.

The fixtures below use those five rules verbatim.
"""
from pathlib import Path

import pytest
import yaml

from odf_validator.ingestion import draft_store
from odf_validator.ingestion.draft_store import RefinementLoss, rule_delta

# The five WST rules as they stood before the refresh, and as the derivation
# regenerated them.
REFINED = {
    "id": "WST_UNIT_CODE", "primitive": "code_membership",
    "target": ".//*[@Unit]", "attribute": "Unit",
    "params": {"codeset": "EVENT_UNIT",
               "exclude_tags": ["Precipitation", "Pressure", "Temperature", "Wind"]},
    "severity": "warning", "scope": "message", "source_ref": "x", "status": "active",
}
REGENERATED = {
    "id": "WST_UNIT_CODE", "primitive": "code_membership",
    "target": ".//*[@Unit]", "attribute": "Unit",
    "params": {"codeset": "EVENT_UNIT"},
    "severity": "warning", "scope": "message", "source_ref": "x", "status": "draft",
}


def _pack(tmp_path: Path, active: list[dict], drafts: list[dict]) -> Path:
    """A minimal ruleset with one DD, its active rules and its drafts."""
    disc = tmp_path / "Rules" / "SYOG26" / "Disciplines" / "WST"
    (disc / "rules").mkdir(parents=True)
    (disc / ".drafts").mkdir()
    (disc / "ODF_WST_Data_Dictionary.pdf").write_bytes(b"%PDF-1.4 stub")
    (disc / "rules" / "ODF_WST_Data_Dictionary.pdf.yaml").write_text(
        yaml.safe_dump(active, sort_keys=False), encoding="utf-8")
    draft_file = disc / ".drafts" / "ODF_WST_Data_Dictionary.pdf.draft.yaml"
    draft_file.write_text(yaml.safe_dump(drafts, sort_keys=False), encoding="utf-8")
    return draft_file


# ------------------------------------------------------------------ the diff --

def test_delta_names_the_dropped_parameter():
    delta = rule_delta(REFINED, REGENERATED)

    assert delta["dropped"] == {
        "exclude_tags": ["Precipitation", "Pressure", "Temperature", "Wind"]}
    assert delta["changed"] == {}
    assert delta["added"] == {}
    assert delta["new"] is False


def test_delta_reports_a_changed_value_separately_from_a_dropped_one():
    active = {"params": {"codeset": "EVENT_UNIT", "allow": ["TBD"]}}
    draft = {"params": {"codeset": "PHASE", "allow": ["TBD"], "column": "Phase"}}

    delta = rule_delta(active, draft)

    assert delta["dropped"] == {}
    assert delta["changed"] == {"codeset": ("EVENT_UNIT", "PHASE")}
    assert delta["added"] == {"column": "Phase"}


def test_delta_flags_a_brand_new_rule():
    delta = rule_delta(None, REGENERATED)

    assert delta["new"] is True
    assert delta["dropped"] == {}


def test_delta_reports_non_param_field_changes():
    active = dict(REFINED, severity="error")

    delta = rule_delta(active, REFINED)

    assert delta["fields"]["severity"] == ("error", "warning")


# --------------------------------------------------------------- the refusal --

def test_approving_a_lossy_draft_is_refused(tmp_path):
    draft_file = _pack(tmp_path, [REFINED], [REGENERATED])

    with pytest.raises(RefinementLoss) as exc:
        draft_store.approve_draft(draft_file, "WST_UNIT_CODE")

    assert "exclude_tags" in str(exc.value)
    assert exc.value.rule_id == "WST_UNIT_CODE"


def test_a_refused_approval_changes_nothing(tmp_path):
    """The active rule and the draft must both survive intact."""
    draft_file = _pack(tmp_path, [REFINED], [REGENERATED])
    active_file = draft_file.parent.parent / "rules" / "ODF_WST_Data_Dictionary.pdf.yaml"
    before_active = active_file.read_text(encoding="utf-8")
    before_draft = draft_file.read_text(encoding="utf-8")

    with pytest.raises(RefinementLoss):
        draft_store.approve_draft(draft_file, "WST_UNIT_CODE")

    assert active_file.read_text(encoding="utf-8") == before_active
    assert draft_file.read_text(encoding="utf-8") == before_draft


def test_approval_proceeds_when_the_loss_is_accepted(tmp_path):
    draft_file = _pack(tmp_path, [REFINED], [REGENERATED])

    delta = draft_store.approve_draft(draft_file, "WST_UNIT_CODE", allow_loss=True)

    assert "exclude_tags" in delta["dropped"]
    active_file = draft_file.parent.parent / "rules" / "ODF_WST_Data_Dictionary.pdf.yaml"
    live = yaml.safe_load(active_file.read_text(encoding="utf-8"))
    assert live[0]["params"] == {"codeset": "EVENT_UNIT"}
    assert not draft_file.exists()


def test_a_draft_that_adds_a_parameter_is_not_refused(tmp_path):
    """Only losses are guarded. Genuine improvements must stay frictionless."""
    richer = dict(REGENERATED)
    richer["params"] = {"codeset": "EVENT_UNIT", "allow": ["TBD"]}
    draft_file = _pack(tmp_path, [dict(REFINED, params={"codeset": "EVENT_UNIT"})],
                       [richer])

    delta = draft_store.approve_draft(draft_file, "WST_UNIT_CODE")

    assert delta["dropped"] == {}
    assert delta["added"] == {"allow": ["TBD"]}


def test_a_new_rule_is_not_refused(tmp_path):
    draft_file = _pack(tmp_path, [], [REGENERATED])

    delta = draft_store.approve_draft(draft_file, "WST_UNIT_CODE")

    assert delta["new"] is True


# ------------------------------------------------------------- approve-all --

def test_approve_all_skips_lossy_drafts_and_applies_the_rest(tmp_path):
    """The path that lost the five refinements must fail safe.

    Nobody reads individual rules when approving in bulk, so a lossy draft is
    left in the queue rather than applied.
    """
    safe = {"id": "WST_NEW_RULE", "primitive": "value_format",
            "target": ".//*[@Pos]", "attribute": "Pos",
            "params": {"regex": "^[0-9]+$"}, "severity": "error",
            "scope": "message", "source_ref": "y", "status": "draft"}
    draft_file = _pack(tmp_path, [REFINED], [REGENERATED, safe])
    rules_root = tmp_path / "Rules"

    approved, skipped = draft_store.approve_all_drafts(rules_root)

    assert approved == ["WST_NEW_RULE"]
    assert [s["rule_id"] for s in skipped] == ["WST_UNIT_CODE"]
    assert "exclude_tags" in skipped[0]["delta"]["dropped"]

    # The refined rule is untouched and its draft is still waiting.
    live = {r["id"]: r for r in yaml.safe_load(
        (draft_file.parent.parent / "rules" /
         "ODF_WST_Data_Dictionary.pdf.yaml").read_text(encoding="utf-8"))}
    assert live["WST_UNIT_CODE"]["params"]["exclude_tags"]
    remaining = yaml.safe_load(draft_file.read_text(encoding="utf-8"))
    assert [r["id"] for r in remaining] == ["WST_UNIT_CODE"]


def test_approve_all_can_be_told_to_accept_losses(tmp_path):
    draft_file = _pack(tmp_path, [REFINED], [REGENERATED])
    rules_root = tmp_path / "Rules"

    approved, skipped = draft_store.approve_all_drafts(rules_root, allow_loss=True)

    assert approved == ["WST_UNIT_CODE"]
    assert skipped == []


# ------------------------------------------------------------ active lookup --

def test_active_rule_finds_the_live_definition(tmp_path):
    draft_file = _pack(tmp_path, [REFINED], [REGENERATED])

    assert draft_store.active_rule(draft_file, "WST_UNIT_CODE") == REFINED
    assert draft_store.active_rule(draft_file, "NO_SUCH_RULE") is None


# --- scope is a refinement too -----------------------------------------------
#
# The guard above catches a dropped PARAMETER. It did not catch a dropped
# SCOPE, and `applies_to` is where this rule set does most of its hand
# refinement. Observed on a fresh public clone on 2026-09-13, following the
# documented first-launch flow (download -> check and download updates ->
# apply -> approve drafts):
#
#   ATH_DOCUMENTSUBCODE_POSINT
#     target      '.'                                -> './/*[@DocumentSubcode]'
#     applies_to  {doc_types: [DT_IMAGE], disciplines: [ATH]}
#                                                    -> {disciplines: [ATH]}
#
# The DT_IMAGE confinement is the whole point of that rule -- GEN 9176/13433
# are the document types that define DocumentSubcode as a positive integer,
# and test_documentsubcode_posint_scoped_to_defining_doc_types exists to pin
# it. Approving the draft reverted it in silence, and the active rule count
# moved 89 -> 87 for the same reason the WST refresh moved 88 -> 93: rules
# that stop matching their GEN counterparts stop being deduped.
#
# The reasoning in RefinementLoss applies unchanged: a derivation emits what
# the Data Dictionary literally states, and the DD does not state which
# document types a discipline's attribute is confined to. It cannot invent a
# `doc_types` key, so a `doc_types` key can only have been put there by hand.

SCOPED = {
    "id": "ATH_DOCUMENTSUBCODE_POSINT", "primitive": "value_format",
    "target": ".", "attribute": "DocumentSubcode",
    "params": {"regex": "^[0-9]+$"},
    "applies_to": {"doc_types": ["DT_IMAGE"], "disciplines": ["ATH"]},
    "severity": "error", "scope": "message", "source_ref": "hand-refined",
}
REDERIVED_UNSCOPED = {
    "id": "ATH_DOCUMENTSUBCODE_POSINT", "primitive": "value_format",
    "target": ".//*[@DocumentSubcode]", "attribute": "DocumentSubcode",
    "params": {"regex": "^[0-9]+$"},
    "applies_to": {"disciplines": ["ATH"]},
    "severity": "error", "scope": "message",
    "source_ref": "ODF_ATH_Data_Dictionary.pdf line 411: DocumentSubcode",
}


def test_a_dropped_scope_key_is_reported_as_a_loss():
    delta = rule_delta(SCOPED, REDERIVED_UNSCOPED)
    assert "applies_to.doc_types" in delta["dropped"], delta
    assert delta["dropped"]["applies_to.doc_types"] == ["DT_IMAGE"]


def test_approving_an_unscoped_redraft_is_refused(tmp_path):
    draft_file = _pack(tmp_path, [SCOPED], [REDERIVED_UNSCOPED])
    with pytest.raises(RefinementLoss) as caught:
        draft_store.approve_draft(draft_file, "ATH_DOCUMENTSUBCODE_POSINT")
    assert "doc_types" in str(caught.value)


def test_the_unscoped_redraft_can_still_be_approved_with_confirmation(tmp_path):
    """Refusing is not forbidding. The operator who has read the delta and
    decided the DD is right can still take it -- the same escape the
    parameter guard already offers."""
    draft_file = _pack(tmp_path, [SCOPED], [REDERIVED_UNSCOPED])
    draft_store.approve_draft(draft_file, "ATH_DOCUMENTSUBCODE_POSINT",
                              allow_loss=True)
    active = yaml.safe_load(
        (draft_file.parent.parent / "rules"
         / "ODF_WST_Data_Dictionary.pdf.yaml").read_text(encoding="utf-8"))
    kept = [r for r in active if r["id"] == "ATH_DOCUMENTSUBCODE_POSINT"]
    assert kept and kept[0]["applies_to"] == {"disciplines": ["ATH"]}


def test_a_draft_that_keeps_the_scope_still_approves_cleanly(tmp_path):
    """The narrowness of the rule. A re-derivation that preserves
    `applies_to` is an ordinary update, not a loss."""
    same_scope = dict(REDERIVED_UNSCOPED,
                      applies_to={"doc_types": ["DT_IMAGE"],
                                  "disciplines": ["ATH"]})
    assert rule_delta(SCOPED, same_scope)["dropped"] == {}
    draft_file = _pack(tmp_path, [SCOPED], [same_scope])
    draft_store.approve_draft(draft_file, "ATH_DOCUMENTSUBCODE_POSINT")
