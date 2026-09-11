"""Draft paths arrive from a form field and must stay inside Rules/.

Confirmed before the fix: reject_draft() deletes any file that parses as a
YAML list of mappings with `id` keys -- the exact shape of the app's own
active rule files -- and approve_draft() writes into any directory, creating
parents. Raised as S-H1.
"""
from pathlib import Path

import pytest
import yaml

from odf_validator.ingestion import draft_store


def _drafts_dir(rules_root: Path) -> Path:
    d = rules_root / "TESTSET" / "Disciplines" / "ARC" / ".drafts"
    d.mkdir(parents=True)
    return d


def _write_draft(rules_root: Path) -> Path:
    path = _drafts_dir(rules_root) / "ARC_DD.md.draft.yaml"
    path.write_text(yaml.safe_dump([{"id": "R1", "primitive": "set_filter"}]),
                    encoding="utf-8")
    return path


def test_reject_refuses_a_path_outside_the_rules_root(tmp_path):
    rules_root = tmp_path / "Rules"
    rules_root.mkdir()
    outsider = tmp_path / "secrets.yaml"
    outsider.write_text(yaml.safe_dump([{"id": "R1"}]), encoding="utf-8")

    with pytest.raises(ValueError):
        draft_store.reject_draft(outsider, "R1", rules_root=rules_root)

    assert outsider.exists(), "a file outside Rules/ must never be deleted"


def test_approve_refuses_a_path_outside_the_rules_root(tmp_path):
    rules_root = tmp_path / "Rules"
    rules_root.mkdir()
    outsider = tmp_path / "elsewhere" / ".drafts" / "x.draft.yaml"
    outsider.parent.mkdir(parents=True)
    outsider.write_text(yaml.safe_dump([{"id": "R1"}]), encoding="utf-8")

    with pytest.raises(ValueError):
        draft_store.approve_draft(outsider, "R1", rules_root=rules_root)

    assert not (tmp_path / "elsewhere" / "rules").exists(), \
        "nothing may be written outside Rules/"


def test_traversal_out_of_the_rules_root_is_refused(tmp_path):
    rules_root = tmp_path / "Rules"
    rules_root.mkdir()
    outsider = tmp_path / "secrets.yaml"
    outsider.write_text(yaml.safe_dump([{"id": "R1"}]), encoding="utf-8")
    traversal = rules_root / ".." / "secrets.yaml"

    with pytest.raises(ValueError):
        draft_store.reject_draft(traversal, "R1", rules_root=rules_root)

    assert outsider.exists()


def test_a_legitimate_draft_inside_the_rules_root_still_works(tmp_path):
    rules_root = tmp_path / "Rules"
    rules_root.mkdir()
    draft = _write_draft(rules_root)

    draft_store.reject_draft(draft, "R1", rules_root=rules_root)

    assert not draft.exists(), "the last entry removed deletes the draft file"


def test_no_rules_root_given_keeps_the_old_permissive_behaviour(tmp_path):
    """Internal callers that already control the path are unaffected."""
    rules_root = tmp_path / "Rules"
    rules_root.mkdir()
    draft = _write_draft(rules_root)

    draft_store.reject_draft(draft, "R1")

    assert not draft.exists()
