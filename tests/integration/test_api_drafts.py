from pathlib import Path
import shutil
from fastapi.testclient import TestClient
import api.app as app_module
from api.app import app, CSRF_TOKEN

client = TestClient(app)


def _setup_pending_draft(tmp_path, monkeypatch):
    rules_root = tmp_path / "Rules"
    ruleset = rules_root / "TESTSET"
    disc = ruleset / "Disciplines" / "ARC"
    disc.mkdir(parents=True)
    dd = disc / "ARC_DD.md"
    dd.write_text("Venue M CC@VENUE Venue where the session takes place\n")

    monkeypatch.setattr(app_module, "RULES_ROOT", rules_root)
    monkeypatch.setattr(app_module, "PACKS", {})
    app_module.discover_packs()
    return dd


def test_drafts_page_lists_pending_drafts(tmp_path, monkeypatch):
    _setup_pending_draft(tmp_path, monkeypatch)

    r = client.get("/drafts")
    assert r.status_code == 200
    assert "ARC_VENUE_CODE" in r.text


def test_approve_draft_promotes_it_and_refreshes_packs(tmp_path, monkeypatch):
    dd = _setup_pending_draft(tmp_path, monkeypatch)
    draft_file = dd.parent / ".drafts" / "ARC_DD.md.draft.yaml"

    r = client.post("/drafts/approve",
                     data={"draft_file": str(draft_file), "rule_id": "ARC_VENUE_CODE",
                           "csrf_token": CSRF_TOKEN},
                     follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/drafts"

    active_file = dd.parent / "rules" / "ARC_DD.md.yaml"
    assert active_file.exists()
    assert "ARC_VENUE_CODE" in {r.id for r in app_module.PACKS["TESTSET"].rules}


def test_reject_draft_removes_it_without_activating(tmp_path, monkeypatch):
    dd = _setup_pending_draft(tmp_path, monkeypatch)
    draft_file = dd.parent / ".drafts" / "ARC_DD.md.draft.yaml"

    r = client.post("/drafts/reject",
                     data={"draft_file": str(draft_file), "rule_id": "ARC_VENUE_CODE",
                           "csrf_token": CSRF_TOKEN},
                     follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/drafts"
    assert not draft_file.exists()
    assert not (dd.parent / "rules").exists()


def test_approve_all_promotes_every_pending_draft_and_refreshes_packs(tmp_path, monkeypatch):
    dd = _setup_pending_draft(tmp_path, monkeypatch)
    disc2 = dd.parent.parent / "GEN"
    disc2.mkdir(parents=True)
    dd2 = disc2 / "GEN_DD.md"
    dd2.write_text("Venue M CC@VENUE Venue where the session takes place\n")
    app_module.discover_packs()

    r = client.post("/drafts/approve_all", data={"csrf_token": CSRF_TOKEN},
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/drafts"

    # approve_draft only unlinks the .draft.yaml file, not the (now-empty)
    # .drafts directory -- matches the existing contract asserted by
    # test_reject_draft_removes_it_without_activating and
    # test_approve_last_draft_removes_the_draft_file in the unit suite.
    assert not (dd.parent / ".drafts" / "ARC_DD.md.draft.yaml").exists()
    assert not (dd2.parent / ".drafts" / "GEN_DD.md.draft.yaml").exists()
    active_ids = {rule.id for p in app_module.PACKS.values() for rule in p.rules}
    assert {"ARC_VENUE_CODE", "GEN_VENUE_CODE"} <= active_ids


def test_approve_and_reject_return_the_reviewer_to_the_drafts_page(tmp_path, monkeypatch):
    """A form POST that answers with JSON strands the browser on a blank page.

    Reviewing a queue of drafts one at a time made that a Back-button round
    trip per decision. Raised as U-C4.
    """
    import yaml
    import api.app as app_module

    rules_root = tmp_path / "Rules"
    drafts = rules_root / "TESTSET" / "Disciplines" / "ARC" / ".drafts"
    drafts.mkdir(parents=True)
    draft = drafts / "ARC_DD.md.draft.yaml"
    draft.write_text(
        yaml.safe_dump([{"id": "R1", "primitive": "set_filter", "target": ".//Unit",
                         "attribute": "PhaseType", "params": {}, "severity": "error",
                         "scope": "message", "source_ref": ""},
                        {"id": "R2", "primitive": "set_filter", "target": ".//Unit",
                         "attribute": "PhaseType", "params": {}, "severity": "error",
                         "scope": "message", "source_ref": ""}]),
        encoding="utf-8")
    monkeypatch.setattr(app_module, "RULES_ROOT", rules_root)

    r = client.post("/drafts/reject",
                    data={"draft_file": str(draft), "rule_id": "R1",
                          "csrf_token": CSRF_TOKEN},
                    follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/drafts"


def test_reject_route_refuses_a_path_outside_the_rules_folder(tmp_path):
    """The path comes from a form field; a stray page must not weaponise it."""
    import yaml
    outsider = tmp_path / "secrets.yaml"
    outsider.write_text(yaml.safe_dump([{"id": "R1"}]), encoding="utf-8")

    r = client.post("/drafts/reject",
                    data={"draft_file": str(outsider), "rule_id": "R1",
                          "csrf_token": CSRF_TOKEN})

    assert r.status_code == 400
    assert outsider.exists()


# --------------------------------------------------- the refinement guard ---
#
# A draft regenerated from a refreshed Data Dictionary replaces the active rule
# of the same id wholesale. On 2026-09-01 that silently reverted five WST
# refinements. The page must show what a draft would remove, and the route must
# refuse a lossy approval that was not explicitly confirmed.

import yaml


def _setup_refined_rule(tmp_path, monkeypatch):
    """An active rule carrying a hand-set param, and a draft that lacks it."""
    rules_root = tmp_path / "Rules"
    disc = rules_root / "TESTSET" / "Disciplines" / "ARC"
    (disc / "rules").mkdir(parents=True)
    (disc / ".drafts").mkdir()
    (disc / "ARC_DD.md").write_text("stub\n", encoding="utf-8")

    refined = {"id": "ARC_UNIT_CODE", "primitive": "code_membership",
               "target": ".//*[@Unit]", "attribute": "Unit",
               "params": {"codeset": "EVENT_UNIT",
                          "exclude_tags": ["Precipitation", "Wind"]},
               "severity": "warning", "scope": "message",
               "source_ref": "x", "status": "active"}
    regenerated = dict(refined, params={"codeset": "EVENT_UNIT"}, status="draft")

    (disc / "rules" / "ARC_DD.md.yaml").write_text(
        yaml.safe_dump([refined], sort_keys=False), encoding="utf-8")
    draft_file = disc / ".drafts" / "ARC_DD.md.draft.yaml"
    draft_file.write_text(yaml.safe_dump([regenerated], sort_keys=False),
                          encoding="utf-8")

    monkeypatch.setattr(app_module, "RULES_ROOT", rules_root)
    monkeypatch.setattr(app_module, "PACKS", {})
    return draft_file


def test_drafts_page_shows_what_would_be_removed(tmp_path, monkeypatch):
    _setup_refined_rule(tmp_path, monkeypatch)

    r = client.get("/drafts")

    assert r.status_code == 200
    assert "exclude_tags" in r.text, "the page must name the parameter at risk"
    assert "Would discard" in r.text


def test_lossy_approval_without_confirmation_is_refused(tmp_path, monkeypatch):
    draft_file = _setup_refined_rule(tmp_path, monkeypatch)

    r = client.post("/drafts/approve",
                    data={"draft_file": str(draft_file),
                          "rule_id": "ARC_UNIT_CODE",
                          "csrf_token": CSRF_TOKEN},
                    follow_redirects=False)

    assert r.status_code == 409
    assert "exclude_tags" in r.text
    live = yaml.safe_load(
        (draft_file.parent.parent / "rules" / "ARC_DD.md.yaml").read_text())
    assert live[0]["params"]["exclude_tags"] == ["Precipitation", "Wind"]


def test_lossy_approval_proceeds_when_confirmed(tmp_path, monkeypatch):
    draft_file = _setup_refined_rule(tmp_path, monkeypatch)

    r = client.post("/drafts/approve",
                    data={"draft_file": str(draft_file),
                          "rule_id": "ARC_UNIT_CODE", "confirm_loss": "1",
                          "csrf_token": CSRF_TOKEN},
                    follow_redirects=False)

    assert r.status_code == 303
    live = yaml.safe_load(
        (draft_file.parent.parent / "rules" / "ARC_DD.md.yaml").read_text())
    assert "exclude_tags" not in live[0]["params"]


def test_approve_all_skips_the_lossy_draft_and_says_so(tmp_path, monkeypatch):
    draft_file = _setup_refined_rule(tmp_path, monkeypatch)

    r = client.post("/drafts/approve_all", data={"csrf_token": CSRF_TOKEN},
                    follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/drafts?skipped=1"
    live = yaml.safe_load(
        (draft_file.parent.parent / "rules" / "ARC_DD.md.yaml").read_text())
    assert live[0]["params"]["exclude_tags"] == ["Precipitation", "Wind"], \
        "approve-all must not discard a refinement"
    assert draft_file.exists(), "the skipped draft stays in the queue"


# --------------------------------------------------------------- reject all ---

def test_reject_all_empties_the_queue_without_activating_anything(tmp_path, monkeypatch):
    dd = _setup_pending_draft(tmp_path, monkeypatch)
    draft_file = dd.parent / ".drafts" / "ARC_DD.md.draft.yaml"
    assert draft_file.exists()          # fixture sanity

    r = client.post("/drafts/reject_all", data={"csrf_token": CSRF_TOKEN},
                    follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/drafts"
    assert not draft_file.exists()
    assert not (dd.parent / "rules" / "ARC_DD.md.yaml").exists(), (
        "rejecting must never write an active rule file")


def test_the_drafts_page_offers_reject_all_with_the_pending_count(tmp_path, monkeypatch):
    _setup_pending_draft(tmp_path, monkeypatch)

    page = client.get("/drafts").text

    assert 'action="/drafts/reject_all"' in page
    assert "Reject all 1" in page


def test_reject_all_is_not_offered_when_the_queue_is_empty(tmp_path, monkeypatch):
    rules_root = tmp_path / "Rules"
    (rules_root / "TESTSET").mkdir(parents=True)
    monkeypatch.setattr(app_module, "RULES_ROOT", rules_root)
    monkeypatch.setattr(app_module, "PACKS", {})
    app_module.discover_packs()

    page = client.get("/drafts").text

    assert 'action="/drafts/reject_all"' not in page
