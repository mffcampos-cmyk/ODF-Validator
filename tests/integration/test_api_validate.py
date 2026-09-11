from fastapi.testclient import TestClient
from api.app import app

client = TestClient(app)
GOOD = '<OdfBody CompetitionCode="SYOG2026" DocumentCode="ARC" DocumentType="DT_RESULT" Version="1" Date="d" Time="t" LogicalDate="d" FeedFlag="P" Source="S"><Competition><Discipline Code="ARC"/></Competition></OdfBody>'


def test_packs_endpoint_lists_syog():
    r = client.get("/packs")
    assert r.status_code == 200
    assert any(p["name"] == "SYOG26" for p in r.json())


def test_validate_paste():
    r = client.post("/validate", data={"pack": "SYOG26", "xml": GOOD})
    assert r.status_code == 200
    body = r.json()
    assert body["doc_type"] == "DT_RESULT"
    assert "counts" in body


def test_validate_against_broken_xsd_pack_hard_gates(tmp_path, client_factory=None):
    # Build a pack whose XSD does not compile, register it, and validate.
    from fastapi.testclient import TestClient
    from odf_validator.ingestion.builder import build_ruleset_pack
    from api import app as app_module

    d = tmp_path / "BROKEN"
    d.mkdir()
    (d / "odf2.xsd").write_text("<xs:schema", encoding="utf-8")  # malformed
    pack = build_ruleset_pack(d)
    app_module.PACKS["BROKEN"] = pack
    try:
        client = TestClient(app_module.app)
        r = client.post("/validate", data={"pack": "BROKEN",
                                           "xml": "<OdfBody/>"})
        assert r.status_code == 200
        body = r.json()
        assert any(f["rule_id"] == "CORE_XSD_INACTIVE"
                   and f["severity"] == "error"
                   for f in body["findings"])
    finally:
        app_module.PACKS.pop("BROKEN", None)
