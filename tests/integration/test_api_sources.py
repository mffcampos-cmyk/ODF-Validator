from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

import api.app as app_module
from api.app import CSRF_TOKEN, app
from odf_validator.sources.catalogue import CatalogueEntry
from odf_validator.sources.provenance import Provenance, SourceRecord
from odf_validator.sources.sync import fetch_targets

client = TestClient(app)


def test_sources_endpoint_lists_every_pack():
    response = client.get("/sources")
    assert response.status_code == 200
    body = response.json()
    names = {row["pack"] for row in body}
    assert "SYOG26" in names
    assert "SOLG28" in names


def test_solg28_reports_as_not_configured():
    row = next(r for r in client.get("/sources").json() if r["pack"] == "SOLG28")
    assert row["configured"] is False
    assert row["entries"] == []


def test_fetch_without_a_csrf_token_is_refused():
    response = client.post("/sources/fetch", data={"pack": "SYOG26"})
    assert response.status_code == 422        # missing required form field


def test_fetch_with_a_wrong_csrf_token_is_refused():
    response = client.post("/sources/fetch",
                           data={"pack": "SYOG26", "csrf_token": "nope"})
    assert response.status_code == 403


def test_apply_with_a_wrong_csrf_token_is_refused():
    response = client.post("/sources/apply",
                           data={"pack": "SYOG26", "csrf_token": "nope"})
    assert response.status_code == 403


def test_fetch_for_an_unknown_pack_is_404():
    response = client.post("/sources/fetch",
                           data={"pack": "NOPE", "csrf_token": CSRF_TOKEN})
    assert response.status_code == 404


# ------------------------------------------------- staged-but-offline apply ---
#
# apply_targets' ground truth is what is sitting in .incoming/, not what a
# live network check says right now. A file staged while online must still
# be applicable after a restart with no network -- that is the whole point
# of staging for later human review. See odf_validator/sources/sync.py's
# fetch_targets/apply_targets docstrings.

TESTSET_DD = CatalogueEntry(
    reference="YOG-2026-ARC", title="ODF Archery Data Dictionary",
    published=None, kind="dd",
    url="https://odf.olympictech.org/2026-Dakar/YOG/ODF_ARC_Data_Dictionary.pdf",
    target="Disciplines/ARC/ODF_ARC_Data_Dictionary.pdf", discipline="ARC")


def _client_serving_pdf():
    def handler(request):
        return httpx.Response(200, content=b"%PDF-new",
                              headers={"content-type": "application/pdf"})
    return httpx.Client(transport=httpx.MockTransport(handler))


def _setup_testset_with_a_staged_document(tmp_path, monkeypatch):
    rules_root = tmp_path / "Rules"
    ruleset = rules_root / "TESTSET"
    (ruleset / "Disciplines" / "ARC").mkdir(parents=True)
    (ruleset / "pack.yaml").write_text(
        'version: "test"\n'
        'source:\n'
        '  index_url: https://odf.olympictech.org/2026-Dakar/dakar_2026_YOG.html\n',
        encoding="utf-8")

    with _client_serving_pdf() as c:
        staged = fetch_targets(ruleset, [TESTSET_DD], client=c)
    assert staged == [".incoming/" + TESTSET_DD.target]  # sanity: fixture staged

    monkeypatch.setattr(app_module, "RULES_ROOT", rules_root)
    monkeypatch.setattr(app_module, "PACKS", {})
    app_module.discover_packs()
    return ruleset


def test_a_staged_file_is_still_applied_when_the_network_is_down(tmp_path, monkeypatch):
    """Reproduces the reported flaw: fetch while online, clear the in-memory
    report cache (as happens on every restart), then apply while the network
    check itself fails (as happens when genuinely offline). The staged file
    must still be promoted -- apply must not depend on a live network call.
    """
    ruleset = _setup_testset_with_a_staged_document(tmp_path, monkeypatch)

    # Empty forever, exactly as documented at SOURCE_REPORTS' definition for
    # a fresh start or an offline machine.
    monkeypatch.setattr(app_module, "SOURCE_REPORTS", {})

    def offline(*a, **kw):
        raise httpx.ConnectError("simulated: the network is down")
    import odf_validator.sources.sync as sync_module
    monkeypatch.setattr(sync_module, "get", offline)

    response = client.post("/sources/apply",
                           data={"pack": "TESTSET", "csrf_token": CSRF_TOKEN})

    assert response.status_code == 200
    body = response.json()
    assert body["applied"] == [TESTSET_DD.target], (
        "a genuinely staged file must be applied even though the live "
        "network check that would normally supply its catalogue entry "
        "fails while offline")
    assert (ruleset / TESTSET_DD.target).read_bytes() == b"%PDF-new"
    assert not (ruleset / ".incoming" / TESTSET_DD.target).exists()


def test_apply_surfaces_a_held_stand_in_via_the_api(tmp_path, monkeypatch):
    """IMPORTANT 3: the /sources/apply response must tell an operator about
    a hand-converted stand-in that survives a same-url, different-suffix
    promotion, not just quietly keep it on disk."""
    rules_root = tmp_path / "Rules"
    ruleset = rules_root / "TESTSET"
    (ruleset / "Disciplines" / "ARC").mkdir(parents=True)
    (ruleset / "pack.yaml").write_text(
        'version: "test"\n'
        'source:\n'
        '  index_url: https://odf.olympictech.org/2026-Dakar/dakar_2026_YOG.html\n',
        encoding="utf-8")

    stand_in = ruleset / "Disciplines" / "ARC" / "ODF_ARC_Data_Dictionary.md"
    stand_in.write_bytes(b"# hand-converted")
    prov = Provenance.load(ruleset / ".sources.json")
    prov.put("Disciplines/ARC/ODF_ARC_Data_Dictionary.md",
             SourceRecord(url=TESTSET_DD.url, reference=None, published=None,
                          sha256="x", adopted=True))
    prov.save()

    with _client_serving_pdf() as c:
        fetch_targets(ruleset, [TESTSET_DD], client=c)

    monkeypatch.setattr(app_module, "RULES_ROOT", rules_root)
    monkeypatch.setattr(app_module, "PACKS", {})
    app_module.discover_packs()

    response = client.post("/sources/apply",
                           data={"pack": "TESTSET", "csrf_token": CSRF_TOKEN})

    assert response.status_code == 200
    body = response.json()
    assert body["applied"] == [TESTSET_DD.target]
    assert body["held_stand_ins"] == [
        "Disciplines/ARC/ODF_ARC_Data_Dictionary.md"]
    assert stand_in.exists(), "the stand-in must not have been deleted"


def test_an_unchecked_pack_does_not_look_healthy():
    """A configured pack with no cached report must say the check has not
    completed, not return error=null.

    This is how a total outage presented for the feature's whole first
    release: /sources answered configured=true, error=null, entries=[], which
    is indistinguishable from a successful check that found nothing, while in
    fact every request to the site was being reset.
    """
    from api.app import SOURCE_REPORTS
    saved = dict(SOURCE_REPORTS)
    SOURCE_REPORTS.clear()
    try:
        row = next(r for r in client.get("/sources").json()
                   if r["pack"] == "SYOG26")
        assert row["configured"] is True
        assert row["error"], (
            "a configured pack with no report must not report error=null -- "
            "that reads as 'checked, all well'")
        assert "not completed" in row["error"]
    finally:
        SOURCE_REPORTS.clear()
        SOURCE_REPORTS.update(saved)


def test_an_unconfigured_pack_reports_no_error():
    """SOLG28 has no index_url on purpose; 'not checked' is correct for it and
    must not be dressed up as a failure."""
    from api.app import SOURCE_REPORTS
    saved = dict(SOURCE_REPORTS)
    SOURCE_REPORTS.clear()
    try:
        row = next(r for r in client.get("/sources").json()
                   if r["pack"] == "SOLG28")
        assert row["configured"] is False
        assert row["error"] is None
    finally:
        SOURCE_REPORTS.clear()
        SOURCE_REPORTS.update(saved)


def test_a_crashed_check_is_recorded_rather_than_left_silent(monkeypatch, tmp_path):
    """refresh_source_reports must store the failure, not only log it --
    otherwise the UI cannot tell a crash from 'not run yet'."""
    from api import app as app_module

    root = tmp_path / "Rules"
    (root / "SYOG26").mkdir(parents=True)
    (root / "SYOG26" / "pack.yaml").write_text(
        'version: "t"\nsource:\n  index_url: https://odf.olympictech.org/x.html\n',
        encoding="utf-8")

    def boom(ruleset_dir, **kwargs):
        raise RuntimeError("network is on fire")

    monkeypatch.setattr(app_module, "source_check", boom)
    saved = dict(app_module.SOURCE_REPORTS)
    app_module.SOURCE_REPORTS.clear()
    try:
        app_module.refresh_source_reports(root)
        report = app_module.SOURCE_REPORTS.get("SYOG26")
        assert report is not None, "a crashed check must still be recorded"
        assert "network is on fire" in report.error
    finally:
        app_module.SOURCE_REPORTS.clear()
        app_module.SOURCE_REPORTS.update(saved)


# ------------------------------------------ which pack the buttons target ---
#
# The /rulesets page used to post every fetch/apply to sorted(PACKS)[0]. With
# SOLG28 (no index_url) and SYOG26 (configured) side by side, "SOLG28" sorts
# first, so "Check and download updates" answered {"pack": "SOLG28",
# "staged": []} and the configured pack could not be reached from the UI at
# all. The pack names below are chosen so the unconfigured one sorts first,
# exactly like the real pair.

def _two_packs_unconfigured_sorting_first(tmp_path, monkeypatch):
    rules_root = tmp_path / "Rules"
    (rules_root / "AAA_UNCONFIGURED").mkdir(parents=True)
    (rules_root / "AAA_UNCONFIGURED" / "pack.yaml").write_text(
        'version: ""\n', encoding="utf-8")
    (rules_root / "ZZZ_CONFIGURED").mkdir(parents=True)
    (rules_root / "ZZZ_CONFIGURED" / "pack.yaml").write_text(
        'version: "test"\n'
        'source:\n'
        '  index_url: https://odf.olympictech.org/2026-Dakar/dakar_2026_YOG.html\n',
        encoding="utf-8")
    monkeypatch.setattr(app_module, "RULES_ROOT", rules_root)
    monkeypatch.setattr(app_module, "PACKS", {})
    app_module.discover_packs()


def test_rulesets_page_offers_fetch_for_the_configured_pack(tmp_path, monkeypatch):
    _two_packs_unconfigured_sorting_first(tmp_path, monkeypatch)

    page = client.get("/rulesets").text

    assert 'name="pack" value="ZZZ_CONFIGURED"' in page, (
        "the only pack with a publication page must be reachable from the "
        "fetch button, whatever its position in sort order")
    assert 'name="pack" value="AAA_UNCONFIGURED"' not in page, (
        "a pack with no index_url has nothing to fetch; offering a button "
        "for it is what produced the silent staged=[]")


def test_fetch_for_an_unconfigured_pack_says_so(tmp_path, monkeypatch):
    _two_packs_unconfigured_sorting_first(tmp_path, monkeypatch)

    response = client.post("/sources/fetch",
                           data={"pack": "AAA_UNCONFIGURED",
                                 "csrf_token": CSRF_TOKEN})

    assert response.status_code == 409, (
        "200 with staged=[] reads as 'checked, nothing newer' -- the same "
        "answer a healthy, up-to-date pack gives")
    assert "index_url" in response.json()["detail"]


# ------------------------------------------------ the page keeps the operator ---
#
# Clicking either button used to replace the Rulesets page with the endpoint's
# raw JSON. The forms stay real <form> POSTs so the page still works without
# JavaScript; sources.js upgrades them to fetch() + a popup.

def test_the_rulesets_page_wires_the_source_forms_for_a_popup(tmp_path, monkeypatch):
    _two_packs_unconfigured_sorting_first(tmp_path, monkeypatch)

    page = client.get("/rulesets").text

    assert 'src="/static/sources.js"' in page, "the popup script must be loaded"
    assert "defer" in page, (
        "sources.js wires the forms on load, so it must not run before the "
        "forms are parsed")
    assert 'id="source-popup"' in page, "the popup needs a host element"
    assert page.count("data-async-source") == 2, (
        "both the fetch and the apply form must be upgraded")
    assert 'data-action-label="Check and download updates"' in page
    assert 'data-action-label="Apply downloaded"' in page
    assert "refreshSourceRows" in page, (
        "the status rows must be refreshable in place, since the operator "
        "no longer leaves the page")


def test_the_source_buttons_are_styled_like_every_other_button(tmp_path, monkeypatch):
    """These two rendered as bare browser buttons, the only unstyled controls
    in the app. `btn` is the shared control class; `btn-run` marks the primary
    action, and its [aria-busy] rule is what greys the button out while
    sources.js has the request in flight."""
    _two_packs_unconfigured_sorting_first(tmp_path, monkeypatch)

    page = client.get("/rulesets").text

    assert 'class="btn btn-run"' in page, "the fetch button is the primary action"
    assert page.count('class="btn') == 2, (
        "both the fetch and the apply button must carry the control class")


def test_the_source_buttons_sit_in_an_action_bar(tmp_path, monkeypatch):
    """`row-actions` is the wrapper class (see drafts.html) -- it was on the
    forms themselves here, so the two buttons stacked with no spacing. The
    page-level equivalent is `bar-actions`, which is what the Approve all bar
    on /drafts uses."""
    _two_packs_unconfigured_sorting_first(tmp_path, monkeypatch)

    page = client.get("/rulesets").text

    assert 'class="bar-actions"' in page
    assert 'class="row-actions"' not in page, (
        "row-actions on a <form> makes the form the flex container, not the "
        "row")
