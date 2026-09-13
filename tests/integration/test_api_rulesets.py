from pathlib import Path
from fastapi.testclient import TestClient
import api.app as app_module
from api.app import app

client = TestClient(app)


def _setup_ruleset_with_discipline(tmp_path, monkeypatch):
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


def test_rulesets_page_lists_ruleset_name_and_discipline(tmp_path, monkeypatch):
    _setup_ruleset_with_discipline(tmp_path, monkeypatch)

    r = client.get("/rulesets")

    assert r.status_code == 200
    assert "TESTSET" in r.text
    assert "ARC" in r.text


def test_rulesets_page_shows_message_when_no_rulesets(tmp_path, monkeypatch):
    rules_root = tmp_path / "Rules"
    rules_root.mkdir()
    monkeypatch.setattr(app_module, "RULES_ROOT", rules_root)
    monkeypatch.setattr(app_module, "PACKS", {})
    app_module.discover_packs()

    r = client.get("/rulesets")

    assert r.status_code == 200
    # Assert on the structural marker first: prose is redesign-volatile and
    # this assertion silently rotted for three weeks after commit 606d271.
    assert 'class="empty"' in r.text
    assert "No rulesets loaded" in r.text


def test_index_links_to_rulesets_page():
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/rulesets"' in r.text


def test_healthy_syog26_pack_is_quiet_about_the_cache_on_both_surfaces(monkeypatch):
    # Final whole-branch review: a cache-integrity alarm must never fire for
    # a healthy, committed obligation cache. Re-point at the real Rules/
    # folder (the committed .dd_obligations.json has all 28 entries current)
    # and check both consumers of the load report: the /packs JSON that
    # drives the pack-report alarm strip, and the /rulesets HTML page.
    monkeypatch.setattr(app_module, "RULES_ROOT", app_module.PROJECT_ROOT / "Rules")
    monkeypatch.setattr(app_module, "PACKS", {})
    app_module.discover_packs()

    packs = client.get("/packs").json()
    syog26 = next(p for p in packs if p["name"] == "SYOG26")
    assert syog26["cache_warnings"] == [], syog26["cache_warnings"]
    # The fallback-conversion channel has to reach the page, not just the
    # dataclass: app.js reads this key off /packs to draw its warning.
    assert "converted_by_fallback" in syog26, sorted(syog26)
    assert not any("cache" in e.lower() for e in syog26["errors"]), syog26["errors"]

    r = client.get("/rulesets")
    assert r.status_code == 200
    assert "cache warning" not in r.text.lower(), r.text


def test_packs_json_carries_the_schema_channel(tmp_path, monkeypatch):
    """app.js reads `schema_unavailable` off /packs to draw its note, so the
    key has to reach the wire, not just the dataclass -- the same wiring gap
    `converted_by_fallback` is pinned against above.

    TESTSET has no XSD at all, which is exactly a fresh clone of the public
    repository: the tree ships the authored rules and the IOC documents are
    fetched on first launch.
    """
    _setup_ruleset_with_discipline(tmp_path, monkeypatch)

    testset = next(p for p in client.get("/packs").json()
                   if p["name"] == "TESTSET")

    assert testset["schema_unavailable"], sorted(testset)
    assert testset["errors"] == [], (
        "a ruleset awaiting its first import has no failed rule loads")


def test_packs_json_carries_the_codes_channel(tmp_path, monkeypatch):
    """Companion to the schema channel above: app.js reads
    `codes_unavailable` off /packs, so the key has to reach the wire."""
    _setup_ruleset_with_discipline(tmp_path, monkeypatch)

    testset = next(p for p in client.get("/packs").json()
                   if p["name"] == "TESTSET")

    assert "codes_unavailable" in testset, sorted(testset)
