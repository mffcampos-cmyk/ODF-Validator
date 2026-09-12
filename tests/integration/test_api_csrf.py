"""The /drafts mutating routes must not be reachable from another origin.

A security review, findings F-01 and F-02. /drafts/approve, /approve_all and /reject
change which rules are live. They had no authentication, no token, and no
Origin or Host check, so any page the operator browsed while the validator was
running could flip the whole draft queue to active -- and approve_all needs no
parameters, so the attacker needed to know nothing about the install.

Each test below states the attack it forecloses, because a bare
'assert r.status_code == 403' tells a future reader nothing about why the
guard has to stay.
"""
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import api.app as app_module
from api.app import app, CSRF_TOKEN

client = TestClient(app)

EVIL = "https://attacker.example"


def _pending_draft(tmp_path, monkeypatch):
    """A real draft waiting for review, so a successful attack would be visible."""
    rules_root = tmp_path / "Rules"
    disc = rules_root / "TESTSET" / "Disciplines" / "ARC"
    disc.mkdir(parents=True)
    dd = disc / "ARC_DD.md"
    dd.write_text("Venue M CC@VENUE Venue where the session takes place\n")

    monkeypatch.setattr(app_module, "RULES_ROOT", rules_root)
    monkeypatch.setattr(app_module, "PACKS", {})
    app_module.discover_packs()
    return dd


def _active_rule_ids():
    return {r.id for p in app_module.PACKS.values() for r in p.rules}


# --------------------------------------------------------------------------- #
# The form token
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("route", ["/drafts/approve", "/drafts/reject"])
def test_a_state_change_without_the_token_is_refused(route, tmp_path, monkeypatch):
    """The token is the load-bearing control: it is per-process and only ever
    rendered into this app's own pages, so an off-origin page cannot read it."""
    dd = _pending_draft(tmp_path, monkeypatch)
    draft_file = dd.parent / ".drafts" / "ARC_DD.md.draft.yaml"

    r = client.post(route, data={"draft_file": str(draft_file),
                                 "rule_id": "ARC_VENUE_CODE"})

    assert r.status_code == 422          # the token field is required
    assert draft_file.exists()
    assert "ARC_VENUE_CODE" not in _active_rule_ids()


def test_approve_all_without_the_token_is_refused(tmp_path, monkeypatch):
    """approve_all took no parameters at all, which made it the cheapest
    possible target -- a single parameterless POST emptied the review queue."""
    _pending_draft(tmp_path, monkeypatch)

    r = client.post("/drafts/approve_all")

    assert r.status_code == 422
    assert "ARC_VENUE_CODE" not in _active_rule_ids()


def test_a_wrong_token_is_refused(tmp_path, monkeypatch):
    dd = _pending_draft(tmp_path, monkeypatch)
    draft_file = dd.parent / ".drafts" / "ARC_DD.md.draft.yaml"

    r = client.post("/drafts/approve",
                    data={"draft_file": str(draft_file),
                          "rule_id": "ARC_VENUE_CODE",
                          "csrf_token": "not-the-token"})

    assert r.status_code == 403
    assert draft_file.exists()
    assert "ARC_VENUE_CODE" not in _active_rule_ids()


def test_a_non_ascii_token_is_refused_rather_than_crashing(tmp_path, monkeypatch):
    """compare_digest raises TypeError on non-ASCII str, which would surface as
    a 500 and leak a traceback. The comparison is done on bytes for this reason."""
    dd = _pending_draft(tmp_path, monkeypatch)
    draft_file = dd.parent / ".drafts" / "ARC_DD.md.draft.yaml"

    r = client.post("/drafts/approve",
                    data={"draft_file": str(draft_file),
                          "rule_id": "ARC_VENUE_CODE",
                          "csrf_token": "tökén-ünicode"})

    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Origin / Sec-Fetch-Site, defence in depth in front of the token
# --------------------------------------------------------------------------- #

def test_a_cross_origin_post_is_refused_even_holding_a_valid_token(tmp_path, monkeypatch):
    """Belt and braces: if the token ever leaked, the origin check still holds."""
    dd = _pending_draft(tmp_path, monkeypatch)
    draft_file = dd.parent / ".drafts" / "ARC_DD.md.draft.yaml"

    r = client.post("/drafts/approve",
                    data={"draft_file": str(draft_file),
                          "rule_id": "ARC_VENUE_CODE",
                          "csrf_token": CSRF_TOKEN},
                    headers={"origin": EVIL, "sec-fetch-site": "cross-site"})

    assert r.status_code == 403
    assert draft_file.exists()
    assert "ARC_VENUE_CODE" not in _active_rule_ids()


def test_a_cross_site_form_post_without_sec_fetch_is_refused_on_origin(tmp_path, monkeypatch):
    """Older browsers omit Sec-Fetch-Site but still send Origin on a form POST."""
    dd = _pending_draft(tmp_path, monkeypatch)
    draft_file = dd.parent / ".drafts" / "ARC_DD.md.draft.yaml"

    r = client.post("/drafts/approve",
                    data={"draft_file": str(draft_file),
                          "rule_id": "ARC_VENUE_CODE",
                          "csrf_token": CSRF_TOKEN},
                    headers={"origin": EVIL})

    assert r.status_code == 403
    assert "ARC_VENUE_CODE" not in _active_rule_ids()


def test_the_apps_own_form_still_works(tmp_path, monkeypatch):
    """The guard is worthless if it also blocks the reviewer. Same-origin
    submission with the rendered token must still promote the draft."""
    dd = _pending_draft(tmp_path, monkeypatch)
    draft_file = dd.parent / ".drafts" / "ARC_DD.md.draft.yaml"

    r = client.post("/drafts/approve",
                    data={"draft_file": str(draft_file),
                          "rule_id": "ARC_VENUE_CODE",
                          "csrf_token": CSRF_TOKEN},
                    headers={"origin": "http://127.0.0.1:8000",
                             "sec-fetch-site": "same-origin"},
                    follow_redirects=False)

    assert r.status_code == 303
    assert "ARC_VENUE_CODE" in _active_rule_ids()


def test_the_drafts_page_renders_the_token_into_every_form(tmp_path, monkeypatch):
    """A form that renders without the token would 422 for the operator on
    click. Counted against the number of <form> elements actually on the page
    rather than a literal, so adding a button cannot make this test wrong
    while it still passes -- or, as happened with reject_all, fail for the
    bookkeeping rather than for a missing token."""
    _pending_draft(tmp_path, monkeypatch)

    body = client.get("/drafts").text

    forms = body.count("<form ")
    assert forms >= 4, (
        f"expected at least approve, reject, approve_all and reject_all; "
        f"found {forms} forms")
    assert body.count(f'name="csrf_token" value="{CSRF_TOKEN}"') == forms


# --------------------------------------------------------------------------- #
# Host header, closing the DNS-rebinding read path
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("path", ["/", "/packs", "/drafts"])
def test_a_rebound_hostname_is_refused_on_every_route(path):
    """An attacker-controlled name whose A record flips to 127.0.0.1 makes the
    browser treat this server as same-origin. The Host header still carries the
    attacker's name, and /packs and /validate quote submitted XML back."""
    r = client.get(path, headers={"host": "rebind.attacker.example"})

    assert r.status_code == 400
    assert "localhost" in r.text


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.1:8000",
                                  "localhost", "localhost:8000",
                                  "[::1]", "[::1]:8000"])
def test_every_loopback_spelling_is_accepted(host):
    """Including the bracketed IPv6 form, where a naive rsplit(':') would yield
    '[::1' and lock the operator out of their own tool."""
    r = client.get("/packs", headers={"host": host})

    assert r.status_code == 200


def test_reject_all_without_the_token_is_refused(tmp_path, monkeypatch):
    """reject_all takes no parameters either, so it is as cheap a target as
    approve_all: one parameterless POST would wipe the review queue."""
    dd = _pending_draft(tmp_path, monkeypatch)
    draft_file = dd.parent / ".drafts" / "ARC_DD.md.draft.yaml"

    r = client.post("/drafts/reject_all")

    assert r.status_code == 422
    assert draft_file.exists()


def test_reject_all_with_a_wrong_token_is_refused(tmp_path, monkeypatch):
    dd = _pending_draft(tmp_path, monkeypatch)
    draft_file = dd.parent / ".drafts" / "ARC_DD.md.draft.yaml"

    r = client.post("/drafts/reject_all", data={"csrf_token": "nope"})

    assert r.status_code == 403
    assert draft_file.exists()


def test_reject_all_from_a_foreign_origin_is_refused(tmp_path, monkeypatch):
    """The token alone is the control, but an off-origin POST that somehow
    carried it must still be refused -- same belt-and-braces as approve_all."""
    dd = _pending_draft(tmp_path, monkeypatch)
    draft_file = dd.parent / ".drafts" / "ARC_DD.md.draft.yaml"

    r = client.post("/drafts/reject_all", data={"csrf_token": CSRF_TOKEN},
                    headers={"Origin": EVIL})

    assert r.status_code == 403
    assert draft_file.exists()
