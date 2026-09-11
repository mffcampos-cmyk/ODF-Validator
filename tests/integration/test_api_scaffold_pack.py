"""A pack with no schema and no rules must not masquerade as a ruleset.

SOLG28 sorts before SYOG26, so the dropdown defaulted to an empty scaffold:
validating against it returned CORE_XSD_INACTIVE and envelope noise, with
nothing on the validate page saying why. Raised as F-M8.
"""
from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)


def test_packs_reports_whether_each_pack_is_usable():
    packs = client.get("/packs").json()

    assert packs, "no packs discovered"
    for p in packs:
        assert "usable" in p, f"{p['name']} has no usable flag"


def test_the_scaffold_is_marked_unusable_and_the_real_pack_is_not():
    by_name = {p["name"]: p for p in client.get("/packs").json()}

    if "SOLG28" in by_name:
        assert by_name["SOLG28"]["usable"] is False
    assert by_name["SYOG26"]["usable"] is True
