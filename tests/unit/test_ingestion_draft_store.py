import yaml
from pathlib import Path
from odf_validator.ingestion import draft_store

RULE_A = {"id": "ARC_VENUE_CODE", "applies_to": {"disciplines": ["ARC"]},
          "primitive": "code_membership", "target": ".//*[@Venue]",
          "attribute": "Venue", "params": {"codeset": "VENUE"},
          "severity": "warning", "scope": "message", "source_ref": "x", "status": "draft"}
RULE_B = {"id": "ARC_VERSION_POSINT", "applies_to": {"disciplines": ["ARC"]},
          "primitive": "value_format", "target": ".//*[@Version]",
          "attribute": "Version", "params": {"regex": "^[0-9]+$"},
          "severity": "error", "scope": "message", "source_ref": "y", "status": "draft"}


def _dd_path(tmp_path) -> Path:
    disc = tmp_path / "Disciplines" / "ARC"
    disc.mkdir(parents=True)
    dd = disc / "ARC_DD.md"
    dd.write_text("stub")
    return dd


def test_write_and_list_drafts(tmp_path):
    dd = _dd_path(tmp_path)
    draft_store.write_drafts(dd, [RULE_A, RULE_B])

    drafts = draft_store.list_all_drafts(tmp_path)
    ids = {d["id"] for d in drafts}
    assert ids == {"ARC_VENUE_CODE", "ARC_VERSION_POSINT"}
    assert all("_draft_file" in d for d in drafts)


def test_write_drafts_location(tmp_path):
    dd = _dd_path(tmp_path)
    path = draft_store.write_drafts(dd, [RULE_A])
    assert path == dd.parent / ".drafts" / "ARC_DD.md.draft.yaml"
    assert path.exists()


def test_approve_moves_rule_to_active_file_and_removes_from_draft(tmp_path):
    dd = _dd_path(tmp_path)
    draft_file = draft_store.write_drafts(dd, [RULE_A, RULE_B])

    draft_store.approve_draft(draft_file, "ARC_VENUE_CODE")

    active_file = dd.parent / "rules" / "ARC_DD.md.yaml"
    active = yaml.safe_load(active_file.read_text(encoding="utf-8"))
    assert [r["id"] for r in active] == ["ARC_VENUE_CODE"]
    assert active[0]["status"] == "active"

    remaining = yaml.safe_load(draft_file.read_text(encoding="utf-8"))
    assert [r["id"] for r in remaining] == ["ARC_VERSION_POSINT"]


def test_approve_last_draft_removes_the_draft_file(tmp_path):
    dd = _dd_path(tmp_path)
    draft_file = draft_store.write_drafts(dd, [RULE_A])
    draft_store.approve_draft(draft_file, "ARC_VENUE_CODE")
    assert not draft_file.exists()


def test_approve_replaces_same_id_in_active_file(tmp_path):
    dd = _dd_path(tmp_path)
    draft_file = draft_store.write_drafts(dd, [RULE_A])
    draft_store.approve_draft(draft_file, "ARC_VENUE_CODE")

    # Re-extraction of a changed source produces a new draft with the same id;
    # approving it must replace, not duplicate, the active entry.
    updated = dict(RULE_A)
    updated["params"] = {"codeset": "VENUE_V2"}
    draft_file2 = draft_store.write_drafts(dd, [updated])
    draft_store.approve_draft(draft_file2, "ARC_VENUE_CODE")

    active_file = dd.parent / "rules" / "ARC_DD.md.yaml"
    active = yaml.safe_load(active_file.read_text(encoding="utf-8"))
    assert len(active) == 1
    assert active[0]["params"] == {"codeset": "VENUE_V2"}


def test_reject_removes_only_that_rule(tmp_path):
    dd = _dd_path(tmp_path)
    draft_file = draft_store.write_drafts(dd, [RULE_A, RULE_B])
    draft_store.reject_draft(draft_file, "ARC_VENUE_CODE")

    remaining = yaml.safe_load(draft_file.read_text(encoding="utf-8"))
    assert [r["id"] for r in remaining] == ["ARC_VERSION_POSINT"]
    assert not (dd.parent / "rules").exists()


def test_reject_last_draft_removes_the_draft_file(tmp_path):
    dd = _dd_path(tmp_path)
    draft_file = draft_store.write_drafts(dd, [RULE_A])
    draft_store.reject_draft(draft_file, "ARC_VENUE_CODE")
    assert not draft_file.exists()


def test_approve_unknown_id_raises(tmp_path):
    dd = _dd_path(tmp_path)
    draft_file = draft_store.write_drafts(dd, [RULE_A])
    try:
        draft_store.approve_draft(draft_file, "NOPE")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_approve_active_path_matches_active_path_for(tmp_path):
    # The active file approve_draft writes to must be exactly what
    # active_path_for(dd_path) would compute - single source of truth,
    # not two independently-derived paths that merely happen to agree.
    dd = _dd_path(tmp_path)
    draft_file = draft_store.write_drafts(dd, [RULE_A])
    draft_store.approve_draft(draft_file, "ARC_VENUE_CODE")
    assert draft_store.active_path_for(dd).exists()


def test_approve_all_promotes_every_pending_draft_across_multiple_dds(tmp_path):
    dd1 = _dd_path(tmp_path)
    disc2 = tmp_path / "Disciplines" / "GEN"
    disc2.mkdir(parents=True)
    dd2 = disc2 / "GEN_DD.md"
    dd2.write_text("stub")

    draft_store.write_drafts(dd1, [RULE_A, RULE_B])
    rule_c = {**RULE_A, "id": "GEN_VENUE_CODE"}
    draft_store.write_drafts(dd2, [rule_c])

    # Returns (approved, skipped) since 2026-09-01: a draft that would drop a
    # hand-set parameter is held back rather than applied. None of these do.
    approved_ids, skipped = draft_store.approve_all_drafts(tmp_path)

    assert skipped == []
    assert set(approved_ids) == {"ARC_VENUE_CODE", "ARC_VERSION_POSINT", "GEN_VENUE_CODE"}
    assert draft_store.list_all_drafts(tmp_path) == []
    active1 = yaml.safe_load(draft_store.active_path_for(dd1).read_text(encoding="utf-8"))
    assert {r["id"] for r in active1} == {"ARC_VENUE_CODE", "ARC_VERSION_POSINT"}
    active2 = yaml.safe_load(draft_store.active_path_for(dd2).read_text(encoding="utf-8"))
    assert {r["id"] for r in active2} == {"GEN_VENUE_CODE"}


def test_approve_all_with_no_pending_drafts_returns_empty_lists(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    assert draft_store.approve_all_drafts(tmp_path) == ([], [])


# --------------------------------------------------------------- reject all ---
#
# The counterpart to approve_all: empty the queue. Unlike approve_all this
# cannot lose a hand-made refinement, because rejecting never touches an
# active rule file -- and a rejected draft is re-derived from its Data
# Dictionary on the next ingestion run, so nothing is permanently destroyed.

def test_reject_all_empties_the_queue_across_multiple_dds(tmp_path):
    dd_arc = _dd_path(tmp_path)
    draft_store.write_drafts(dd_arc, [RULE_A, RULE_B])
    disc_swm = tmp_path / "Disciplines" / "SWM"
    disc_swm.mkdir(parents=True)
    dd_swm = disc_swm / "SWM_DD.md"
    dd_swm.write_text("stub")
    draft_store.write_drafts(dd_swm, [dict(RULE_A, id="SWM_VENUE_CODE")])

    rejected = draft_store.reject_all_drafts(tmp_path)

    assert sorted(rejected) == ["ARC_VENUE_CODE", "ARC_VERSION_POSINT",
                                "SWM_VENUE_CODE"]
    assert draft_store.list_all_drafts(tmp_path) == []
    assert not (dd_arc.parent / ".drafts" / "ARC_DD.md.draft.yaml").exists()
    assert not (dd_swm.parent / ".drafts" / "SWM_DD.md.draft.yaml").exists()


def test_reject_all_leaves_active_rules_untouched(tmp_path):
    dd = _dd_path(tmp_path)
    active_file = draft_store.active_path_for(dd)
    active_file.parent.mkdir(parents=True, exist_ok=True)
    active_file.write_text(yaml.safe_dump([dict(RULE_A, status="active")]),
                           encoding="utf-8")
    draft_store.write_drafts(dd, [dict(RULE_A, params={"codeset": "OTHER"})])

    draft_store.reject_all_drafts(tmp_path)

    live = yaml.safe_load(active_file.read_text(encoding="utf-8"))
    assert live == [dict(RULE_A, status="active")]


def test_reject_all_with_no_pending_drafts_returns_an_empty_list(tmp_path):
    _dd_path(tmp_path)
    assert draft_store.reject_all_drafts(tmp_path) == []
